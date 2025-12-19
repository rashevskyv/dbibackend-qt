"""
USB Handler for DBI Protocol
Handles USB communication with Nintendo Switch
"""

import struct
import time
import traceback
from pathlib import Path
from typing import Dict
from enum import Enum
from datetime import datetime

import usb.core
import usb.util
from PyQt6.QtCore import QThread, pyqtSignal

# FIX: Relative imports
from . import dbi_protocol
from .progress_tracker import ProgressTracker


class ConnectionStatus(Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class USBHandler(QThread):
    """Thread for handling USB communication with Switch"""

    connection_changed = pyqtSignal(ConnectionStatus)
    log_message = pyqtSignal(str, str)
    progress_updated = pyqtSignal(str, object, float, object, int, object, object, object)
    file_progress = pyqtSignal(str, int)
    transfer_complete = pyqtSignal(str)
    file_skipped = pyqtSignal(str, object)
    transfer_reset = pyqtSignal()
    all_transfers_complete = pyqtSignal()

    def __init__(self, file_list: Dict[str, Path]):
        super().__init__()
        self.file_list = file_list
        self.is_running = False
        self.dev = None
        self.in_ep = None
        self.out_ep = None
        self.transfer_start_time = None
        self.progress_tracker = ProgressTracker(file_list)
        self.current_transfer_file = None

    def run(self):
        try:
            self.is_running = True
            self.log_message.emit('info', 'Starting USB handler...')
            if not self.connect_to_switch():
                self.log_message.emit('error', 'Failed to connect to Switch')
                self.is_running = False
                return
            self.poll_commands()
        except Exception as e:
            self.log_message.emit('error', f'Critical error: {e}')

    def stop(self):
        self.is_running = False
        self.quit()
        self.wait()

    def connect_to_switch(self) -> bool:
        self.connection_changed.emit(ConnectionStatus.CONNECTING)
        retry_count = 0
        while self.is_running and retry_count < 30:
            try:
                self.dev = usb.core.find(idVendor=0x057E, idProduct=0x3000)
                if self.dev is None:
                    retry_count += 1
                    time.sleep(1)
                    continue

                self.dev.reset()
                time.sleep(1)
                self.dev.set_configuration()
                cfg = self.dev.get_active_configuration()
                
                is_out = lambda ep: usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT
                is_in = lambda ep: usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
                
                self.out_ep = usb.util.find_descriptor(cfg[(0, 0)], custom_match=is_out)
                self.in_ep = usb.util.find_descriptor(cfg[(0, 0)], custom_match=is_in)

                if self.out_ep and self.in_ep:
                    self.connection_changed.emit(ConnectionStatus.CONNECTED)
                    return True
            except:
                pass
            time.sleep(1)
        
        self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
        return False

    def poll_commands(self):
        self.log_message.emit('info', 'Ready for commands')
        while self.is_running:
            try:
                cmd_header = bytes(self.in_ep.read(16, timeout=0))
                if cmd_header[:4] != b'DBI0': continue

                cmd_id = struct.unpack('<I', cmd_header[8:12])[0]
                data_size = struct.unpack('<I', cmd_header[12:16])[0]

                if cmd_id == dbi_protocol.CMD_ID_EXIT:
                    self.process_exit_command()
                    break
                elif cmd_id == dbi_protocol.CMD_ID_FILE_RANGE:
                    self.process_file_range_command(data_size)
                elif cmd_id == dbi_protocol.CMD_ID_LIST:
                    self.process_list_command()

            except usb.core.USBError:
                if self.is_running:
                    self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
                    if not self.connect_to_switch(): break
            except Exception as e:
                self.log_message.emit('error', f'Loop error: {e}')
                break
        self.is_running = False

    def process_exit_command(self):
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_EXIT, 0))
        self.all_transfers_complete.emit()

    def process_list_command(self):
        nsp_path_list = "\n".join(self.file_list.keys()) + "\n"
        data = nsp_path_list.encode('utf-8')
        
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_LIST, len(data)))
        if len(data) > 0:
            self.in_ep.read(16, timeout=0) # Ack
            self.out_ep.write(data)

    def process_file_range_command(self, data_size):
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_FILE_RANGE, data_size))
        
        header = self.in_ep.read(data_size)
        range_size = struct.unpack('<I', header[:4])[0]
        range_offset = struct.unpack('<Q', header[4:12])[0]
        name = bytes(header[16:]).decode('utf-8')
        
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_FILE_RANGE, range_size))
        self.in_ep.read(16, timeout=0) # Ack

        path = self.file_list.get(name)
        if not path: return # Should not happen

        is_metadata = range_size < dbi_protocol.METADATA_THRESHOLD
        
        # Reset detection logic
        if is_metadata and range_offset == 0 and name in self.progress_tracker.requested_files:
            self.progress_tracker.reset()
            self.transfer_reset.emit()

        if is_metadata:
            self.progress_tracker.register_file_request(name)
        elif not is_metadata:
            if self.transfer_start_time is None: self.transfer_start_time = time.time()
            if self.current_transfer_file != name:
                self.current_transfer_file = name
                # Check for skipped files logic here if needed

        # Send Data
        with open(path, 'rb') as f:
            f.seek(range_offset)
            remaining = range_size
            while remaining > 0:
                chunk = f.read(min(remaining, dbi_protocol.BUFFER_SEGMENT_DATA_SIZE))
                self.out_ep.write(chunk, timeout=0)
                sent = len(chunk)
                remaining -= sent
                
                if not is_metadata:
                    self.progress_tracker.transferred_bytes += sent
                    # Emit progress update (simplified)
                    elapsed = time.time() - self.transfer_start_time
                    speed = (self.progress_tracker.transferred_bytes / elapsed / 1048576) if elapsed > 0 else 0
                    self.progress_updated.emit(name, self.progress_tracker.transferred_bytes, speed, 
                                             self.progress_tracker.total_requested_size, len(self.progress_tracker.requested_files),
                                             0, 0, 0) # simplified args

        if not is_metadata:
             # simplified completion logic
             self.progress_tracker.add_interval(name, range_offset, range_offset + range_size)
             if self.progress_tracker.get_file_size(name) > 0:
                 # Check if complete (logic simplified for brevity)
                 pass