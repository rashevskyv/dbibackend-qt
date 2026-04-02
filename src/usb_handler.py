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

import usb.core
import usb.util
from PyQt6.QtCore import QThread, pyqtSignal

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
    # Signals for UI updates
    progress_updated = pyqtSignal(str, object, float, object, int, object, object, object)
    file_progress = pyqtSignal(str, int)
    transfer_complete = pyqtSignal(str)
    file_skipped = pyqtSignal(str, object)
    transfer_reset = pyqtSignal()
    all_transfers_complete = pyqtSignal()
    installation_begun = pyqtSignal(list) # Sends list of filenames requested via metadata

    def __init__(self, file_list: Dict[str, Path]):
        super().__init__()
        self.file_list = file_list
        self.is_running = False
        self.dev = None
        self.in_ep = None
        self.out_ep = None
        self.transfer_start_time = None
        self.progress_tracker = ProgressTracker(file_list)
        
        # State tracking for UI
        self.current_transfer_file = None
        self.current_file_bytes_sent = 0
        self.current_file_size = 0
        self.installation_started = False
        
        # File handle caching
        self.cached_file_path = None
        self.cached_file_handle = None

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
            self.log_message.emit('error', f'Critical error in USB thread: {e}')

    def stop(self):
        self.is_running = False
        if self.dev:
            try:
                # Reset the device to break any pending blocking I/O
                self.dev.reset()
                usb.util.dispose_resources(self.dev)
            except:
                pass
        
        # Close cached file
        if self.cached_file_handle:
            try:
                self.cached_file_handle.close()
            except:
                pass
            self.cached_file_handle = None
            self.cached_file_path = None

        self.quit()
        if not self.wait(2000): # Wait max 2 seconds for thread to finish
            self.terminate()
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
                    self.log_message.emit('success', 'Connected to Switch via USB')
                    return True
            except Exception as e:
                # self.log_message.emit('debug', f"Connection retry: {e}")
                pass
            time.sleep(1)
        
        self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
        return False

    def poll_commands(self):
        self.log_message.emit('info', 'Waiting for DBI commands...')
        while self.is_running:
            try:
                # Read header
                cmd_header = bytes(self.in_ep.read(16, timeout=1000))
                if cmd_header[:4] != b'DBI0': continue

                cmd_id = struct.unpack('<I', cmd_header[8:12])[0]
                data_size = struct.unpack('<I', cmd_header[12:16])[0]
                # print(f"Received Command ID: {cmd_id}, Size: {data_size}") # Debug

                if cmd_id == dbi_protocol.CMD_ID_EXIT:
                    self.process_exit_command()
                    break
                elif cmd_id == dbi_protocol.CMD_ID_FILE_RANGE:
                    self.process_file_range_command(data_size)
                elif cmd_id == dbi_protocol.CMD_ID_LIST:
                    self.process_list_command()

            except usb.core.USBTimeoutError:
                # Timeout is normal in poll loop
                continue
            except usb.core.USBError as e:
                # On some Windows backends, timeout is a generic USBError with a specific string or errno
                error_str = str(e).lower()
                is_timeout = "timeout" in error_str or e.errno == 10060 or (hasattr(e, 'backend_error_code') and e.backend_error_code == -7)
                is_disconnect = "reaping request failed" in error_str or "aborted" in error_str or e.errno == 22 or e.errno == 10054
                
                if is_timeout:
                    continue
                
                if self.is_running:
                    if is_disconnect:
                        self.log_message.emit('info', 'USB Connection closed by Switch.')
                    else:
                        self.log_message.emit('warning', f'USB connection lost: {e}')
                        print(f"USB Error details: {traceback.format_exc()}") # Print to console
                    
                    self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
                    if not self.connect_to_switch(): break
            except Exception as e:
                self.log_message.emit('error', f'Command loop error: {e}')
                if self.is_running:
                    print(f"Critical error: {traceback.format_exc()}")
                break
        self.is_running = False

    def process_exit_command(self):
        self.log_message.emit('info', 'DBI requested exit.')
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_EXIT, 0))
        self.all_transfers_complete.emit()

    def process_list_command(self):
        self.log_message.emit('info', f'Sending list of {len(self.file_list)} files...')
        nsp_path_list = "\n".join(self.file_list.keys()) + "\n"
        data = nsp_path_list.encode('utf-8')
        
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_LIST, len(data)))
        if len(data) > 0:
            self.in_ep.read(16, timeout=10000) # Use 10s instead of 0
            self.out_ep.write(data, timeout=10000)

    def process_file_range_command(self, data_size):
        # Ack command
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_FILE_RANGE, data_size), timeout=10000)
        
        # Read request details
        header = self.in_ep.read(data_size, timeout=10000)
        range_size = struct.unpack('<I', header[:4])[0]
        range_offset = struct.unpack('<Q', header[4:12])[0]
        name = bytes(header[16:]).decode('utf-8').rstrip('\x00')
        
        # Respond
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_FILE_RANGE, range_size), timeout=10000)
        self.in_ep.read(16, timeout=10000) # Final Ack

        path = self.file_list.get(name)
        if not path: 
            self.log_message.emit('error', f'Requested file not found in list: {name}')
            return

        is_metadata = range_size < dbi_protocol.METADATA_THRESHOLD
        
        # --- Logic for UI State ---
        if is_metadata and range_offset == 0 and name in self.progress_tracker.requested_files:
            # Switch restarted logic
            self.log_message.emit('warning', 'Switch reset file selection.')
            self.progress_tracker.reset()
            self.transfer_reset.emit()

        if is_metadata:
            self.progress_tracker.register_file_request(name)
        elif not is_metadata:
            if not self.installation_started:
                self.installation_started = True
                requested = list(self.progress_tracker.requested_files)
                self.installation_begun.emit(requested)
                self.log_message.emit('info', 'Installation phase started.')

            if self.transfer_start_time is None: 
                self.transfer_start_time = time.time()
            
            # New file started logic
            if self.current_transfer_file != name:
                self.current_transfer_file = name
                self.current_file_size = self.progress_tracker.get_file_size(name)
                self.current_file_bytes_sent = 0
                self.log_message.emit('info', f'Sending: {name}')

        # --- Data Transfer (Optimized with caching) ---
        try:
            # Check if we can reuse the cached handle
            if self.cached_file_path != path:
                if self.cached_file_handle:
                    self.cached_file_handle.close()
                self.cached_file_handle = open(path, 'rb')
                self.cached_file_path = path

            f = self.cached_file_handle
            f.seek(range_offset)
            remaining = range_size
            chunk_size = dbi_protocol.BUFFER_SEGMENT_DATA_SIZE
            
            while remaining > 0:
                if not self.is_running: break # Check for stop during transfer
                read_amount = min(remaining, chunk_size)
                chunk = f.read(read_amount)
                self.out_ep.write(chunk, timeout=10000)
                
                sent = len(chunk)
                remaining -= sent
                
                if not is_metadata:
                    self.progress_tracker.transferred_bytes += sent
                    self.current_file_bytes_sent += sent # Track local file progress
                    
                    # Update UI every chunk
                    elapsed = time.time() - self.transfer_start_time
                    speed = (self.progress_tracker.transferred_bytes / elapsed / 1048576) if elapsed > 0 else 0.0
                    
                    # IMPORTANT: Passing real values here restores the UI
                    self.progress_updated.emit(
                        name,
                        self.progress_tracker.transferred_bytes,
                        speed,
                        self.progress_tracker.total_requested_size,
                        len(self.progress_tracker.requested_files),
                        self.current_file_bytes_sent,  # Current file progress
                        self.current_file_size,        # Current file total
                        self.progress_tracker.unique_bytes_transferred
                    )
        except Exception as e:
            self.log_message.emit('error', f'File error: {e}')
            # Clear cache on error
            if self.cached_file_handle:
                try: self.cached_file_handle.close()
                except: pass
            self.cached_file_handle = None
            self.cached_file_path = None

        # --- Completion Logic ---
        if not is_metadata:
             # Register valid data interval
             total_file_transferred = self.progress_tracker.add_interval(name, range_offset, range_offset + range_size)
             
             # Calculate percentage for file list status
             pct = int((total_file_transferred / self.current_file_size) * 100) if self.current_file_size > 0 else 0
             self.file_progress.emit(name, pct)

             # Check if file is essentially done (>99%)
             if name not in self.progress_tracker.completed_files_set and total_file_transferred >= (self.current_file_size * 0.99):
                 self.progress_tracker.completed_files_set.add(name)
                 self.transfer_complete.emit(name)
                 self.log_message.emit('success', f'Finished: {name}')