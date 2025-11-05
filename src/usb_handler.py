"""
USB Handler for DBI Protocol
Handles USB communication with Nintendo Switch
"""

import struct
import time
import traceback
from pathlib import Path
from typing import Dict, Optional
from enum import Enum
from datetime import datetime

import usb.core
import usb.util
from PyQt6.QtCore import QThread, pyqtSignal


class ConnectionStatus(Enum):
    """USB connection status"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class USBHandler(QThread):
    """Thread for handling USB communication with Switch"""

    # Signals
    connection_changed = pyqtSignal(ConnectionStatus)
    log_message = pyqtSignal(str, str)  # level, message
    progress_updated = pyqtSignal(str, int, float, int, int, int, int, int)  # filename, transferred_bytes, speed_mbps, total_requested_size, num_requested_files, current_file_bytes, current_file_size, unique_bytes_transferred
    file_progress = pyqtSignal(str, int)  # filename, progress% - for updating file list item
    transfer_complete = pyqtSignal(str)  # filename

    # DBI Protocol Commands
    CMD_ID_EXIT = 0
    CMD_ID_LIST_OLD = 1
    CMD_ID_FILE_RANGE = 2
    CMD_ID_LIST = 3

    CMD_TYPE_REQUEST = 0
    CMD_TYPE_RESPONSE = 1
    CMD_TYPE_ACK = 2

    BUFFER_SEGMENT_DATA_SIZE = 0x100000  # 1 MB

    def __init__(self, file_list: Dict[str, Path]):
        super().__init__()
        self.file_list = file_list
        self.is_running = False
        self.dev = None
        self.in_ep = None
        self.out_ep = None
        self.current_file = None
        self.transfer_start_time = None

        # Setup logging to file
        self.log_file = Path("log.txt")
        self._init_log_file()

        # Track progress across all files (sizes calculated lazily when needed)
        self.total_size = 0  # Total size of ALL files (if we knew)
        self.total_requested_size = 0  # Total size of files actually requested by Switch
        self.requested_files = set()  # Files that Switch has requested (metadata phase)
        self.completed_files_set = set()  # Files that have been fully transferred
        self.file_sizes = {}  # Will be populated during metadata phase
        self.transferred_bytes = 0  # Total bytes sent via USB (includes overlaps)
        self.unique_bytes_transferred = 0  # Actual unique bytes transferred (sum of all file intervals)
        self.completed_files = 0
        self.total_files = len(file_list)

        self._log_to_file(f"Total files: {self.total_files}")

        # Speed tracking with smoothing
        self.speed_samples = []
        self.max_speed_samples = 10

        # Track file-specific progress (for current file progress bar)
        # Using interval tracking like torrent clients - track which parts of file were transferred
        self.file_intervals = {name: [] for name in file_list.keys()}  # List of (start, end) tuples
        self.current_file_size = 0  # Size of file currently being transferred
        self.current_file_bytes = 0  # Unique bytes transferred for current file
        self.current_range_offset = 0  # Offset of current range request
        self.current_range_size = 0  # Size of current range request

        # Metadata vs Transfer phase detection
        # Metadata requests are small (<100KB), transfer requests are large (>=1MB)
        self.METADATA_THRESHOLD = 100 * 1024  # 100KB

    def _init_log_file(self):
        """Initialize log file"""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== DBI Backend Qt Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception as e:
            print(f"Cannot create log file: {e}")

    def _log_to_file(self, message: str):
        """Write message to log file"""
        try:
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception as e:
            print(f"Cannot write to log: {e}")

    def _get_file_size(self, filename: str) -> int:
        """Get file size lazily (calculate only when needed)"""
        if filename not in self.file_sizes:
            try:
                file_path = self.file_list[filename]
                size = file_path.stat().st_size if isinstance(file_path, Path) else Path(file_path).stat().st_size
                self.file_sizes[filename] = size
                self.total_size += size
                self._log_to_file(f"File size calculated: {filename} = {size} bytes")
                return size
            except Exception as e:
                error_msg = f"ERROR getting size for {filename}: {e}\n{traceback.format_exc()}"
                self._log_to_file(error_msg)
                print(error_msg)
                self.file_sizes[filename] = 0
                return 0
        return self.file_sizes[filename]

    def _add_interval(self, filename: str, start: int, end: int):
        """Add a transferred interval and merge overlapping intervals (like torrent client)"""
        if filename not in self.file_intervals:
            self.file_intervals[filename] = []

        intervals = self.file_intervals[filename]
        intervals.append((start, end))

        # Sort intervals by start position
        intervals.sort()

        # Merge overlapping intervals
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                # Overlapping or adjacent - merge
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                # Non-overlapping - add as new interval
                merged.append((start, end))

        self.file_intervals[filename] = merged

        # Calculate total unique bytes transferred for this file
        total_bytes = sum(end - start for start, end in merged)

        # Update global unique bytes counter (sum across all files)
        self.unique_bytes_transferred = sum(
            sum(end - start for start, end in intervals)
            for intervals in self.file_intervals.values()
        )

        return total_bytes

    def run(self):
        """Main thread execution"""
        try:
            self.is_running = True
            self._log_to_file("=== USB Handler Started ===")
            self.log_message.emit('info', 'Starting USB handler...')

            if not self.connect_to_switch():
                self._log_to_file("ERROR: Failed to connect to Switch")
                self.log_message.emit('error', 'Failed to connect to Switch')
                self.is_running = False
                return

            self._log_to_file("Connected, entering poll_commands")
            self.poll_commands()
        except Exception as e:
            error_msg = f"CRITICAL ERROR in run(): {e}\n{traceback.format_exc()}"
            self._log_to_file(error_msg)
            print(error_msg)
            self.log_message.emit('error', f'Critical error: {e}')

    def stop(self):
        """Stop the USB handler"""
        self.is_running = False
        self.quit()
        self.wait()

    def connect_to_switch(self) -> bool:
        """Connect to Nintendo Switch via USB"""
        try:
            self._log_to_file("Connecting to Switch...")
            self.connection_changed.emit(ConnectionStatus.CONNECTING)
            self.log_message.emit('info', 'Waiting for Switch...')

            retry_count = 0
            max_retries = 30

            while self.is_running and retry_count < max_retries:
                try:
                    # Find Switch device
                    self._log_to_file(f"Looking for Switch device (attempt {retry_count+1}/{max_retries})")
                    self.dev = usb.core.find(idVendor=0x057E, idProduct=0x3000)

                    if self.dev is None:
                        retry_count += 1
                        time.sleep(1)
                        continue

                    # Reset and configure device
                    self._log_to_file("Switch found! Resetting device...")
                    self.dev.reset()
                    self.log_message.emit('info', 'Switch found, resetting...')
                    time.sleep(1)

                    self._log_to_file("Setting configuration...")
                    self.dev.set_configuration()
                    cfg = self.dev.get_active_configuration()
                    self._log_to_file(f"Active configuration: {cfg}")

                    # Find endpoints
                    is_out_ep = lambda ep: usb.util.endpoint_direction(
                        ep.bEndpointAddress) == usb.util.ENDPOINT_OUT
                    is_in_ep = lambda ep: usb.util.endpoint_direction(
                        ep.bEndpointAddress) == usb.util.ENDPOINT_IN

                    self._log_to_file("Finding endpoints...")
                    self.out_ep = usb.util.find_descriptor(cfg[(0, 0)], custom_match=is_out_ep)
                    self.in_ep = usb.util.find_descriptor(cfg[(0, 0)], custom_match=is_in_ep)

                    if self.out_ep is None or self.in_ep is None:
                        error_msg = f'Failed to find USB endpoints: out={self.out_ep}, in={self.in_ep}'
                        self._log_to_file(error_msg)
                        self.log_message.emit('error', error_msg)
                        return False

                    self._log_to_file(f"Endpoints found: OUT={self.out_ep.bEndpointAddress}, IN={self.in_ep.bEndpointAddress}")
                    self.connection_changed.emit(ConnectionStatus.CONNECTED)
                    self.log_message.emit('success', 'Connected to Switch')
                    return True

                except usb.core.USBError as e:
                    error_msg = f'USB error: {e}'
                    self._log_to_file(error_msg)
                    self.log_message.emit('warning', error_msg)
                    retry_count += 1
                    time.sleep(1)
                except Exception as e:
                    error_msg = f'Unexpected error: {e}\n{traceback.format_exc()}'
                    self._log_to_file(error_msg)
                    self.log_message.emit('error', f'Unexpected error: {e}')
                    return False

            self._log_to_file("Max retries reached, connection failed")
            self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
            return False
        except Exception as e:
            error_msg = f"CRITICAL ERROR in connect_to_switch(): {e}\n{traceback.format_exc()}"
            self._log_to_file(error_msg)
            print(error_msg)
            return False

    def poll_commands(self):
        """Poll for commands from Switch"""
        try:
            self._log_to_file("Entering command loop")
            self.log_message.emit('info', 'Entering command loop')

            while self.is_running:
                try:
                    self._log_to_file("Waiting for command...")
                    cmd_header = bytes(self.in_ep.read(16, timeout=0))
                    magic = cmd_header[:4]
                    self._log_to_file(f"Received header: magic={magic}, len={len(cmd_header)}")

                    if magic != b'DBI0':
                        self._log_to_file(f"WARNING: Invalid magic: {magic}")
                        continue

                    cmd_type = struct.unpack('<I', cmd_header[4:8])[0]
                    cmd_id = struct.unpack('<I', cmd_header[8:12])[0]
                    data_size = struct.unpack('<I', cmd_header[12:16])[0]
                    self._log_to_file(f"Command: type={cmd_type}, id={cmd_id}, data_size={data_size}")

                    if cmd_id == self.CMD_ID_EXIT:
                        self._log_to_file("Processing EXIT command")
                        self.process_exit_command()
                        break
                    elif cmd_id == self.CMD_ID_FILE_RANGE:
                        self._log_to_file(f"Processing FILE_RANGE command (data_size={data_size})")
                        self.process_file_range_command(data_size)
                    elif cmd_id == self.CMD_ID_LIST:
                        self._log_to_file("Processing LIST command")
                        self.process_list_command()
                    else:
                        self._log_to_file(f"WARNING: Unknown command ID: {cmd_id}")

                except usb.core.USBError as e:
                    error_msg = f'USB error in poll_commands: {e}'
                    self._log_to_file(error_msg)
                    if self.is_running:
                        self.log_message.emit('warning', 'Connection lost, reconnecting...')
                        self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
                        if not self.connect_to_switch():
                            break
                except Exception as e:
                    error_msg = f'Command loop error: {e}\n{traceback.format_exc()}'
                    self._log_to_file(error_msg)
                    self.log_message.emit('error', f'Command loop error: {e}')
                    break

            self._log_to_file("Exiting command loop")
            self.is_running = False
            self.connection_changed.emit(ConnectionStatus.DISCONNECTED)
        except Exception as e:
            error_msg = f"CRITICAL ERROR in poll_commands(): {e}\n{traceback.format_exc()}"
            self._log_to_file(error_msg)
            print(error_msg)

    def process_exit_command(self):
        """Handle exit command from Switch"""
        self.log_message.emit('info', 'Received exit command')
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', self.CMD_TYPE_RESPONSE,
                                     self.CMD_ID_EXIT, 0))

    def process_list_command(self):
        """Handle list command - send file list to Switch"""
        self.log_message.emit('info', 'Sending file list to Switch')

        nsp_path_list = ""
        for name in self.file_list.keys():
            nsp_path_list += name + '\n'

        nsp_path_list_bytes = nsp_path_list.encode('utf-8')
        nsp_path_list_len = len(nsp_path_list_bytes)

        # Send response header
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', self.CMD_TYPE_RESPONSE,
                                     self.CMD_ID_LIST, nsp_path_list_len))

        if nsp_path_list_len > 0:
            # Wait for ACK
            ack = bytes(self.in_ep.read(16, timeout=0))
            # Send file list
            self.out_ep.write(nsp_path_list_bytes)

        self.log_message.emit('success', f'Sent list of {len(self.file_list)} files')

    def process_file_range_command(self, data_size: int):
        """Handle file range command - send file data to Switch"""
        self._log_to_file(f"=== FILE_RANGE: data_size={data_size} ===")
        self.log_message.emit('info', 'File range')

        try:
            # IMPORTANT: Send ACK first (like original dbibackend.py)
            self._log_to_file("Sending ACK...")
            self.out_ep.write(struct.pack('<4sIII', b'DBI0', self.CMD_TYPE_ACK,
                                         self.CMD_ID_FILE_RANGE, data_size))
            self._log_to_file("ACK sent")

            # Receive file range header
            self._log_to_file(f"Reading file_range_header ({data_size} bytes)...")
            file_range_header = self.in_ep.read(data_size)
            self._log_to_file(f"Received header: {len(file_range_header)} bytes")

            range_size = struct.unpack('<I', file_range_header[:4])[0]
            range_offset = struct.unpack('<Q', file_range_header[4:12])[0]
            nsp_name_len = struct.unpack('<I', file_range_header[12:16])[0]
            nsp_name = bytes(file_range_header[16:]).decode('utf-8')

            self._log_to_file(f"Range: size={range_size}, offset={range_offset}, name_len={nsp_name_len}, name={nsp_name}")
            self.log_message.emit('info',
                                f'Range Size: {range_size}, Range Offset: {range_offset}, '
                                f'Name len: {nsp_name_len}, Name: {nsp_name}')

            # Send response header
            self._log_to_file("Sending response header...")
            response_bytes = struct.pack('<4sIII', b'DBI0', self.CMD_TYPE_RESPONSE,
                                        self.CMD_ID_FILE_RANGE, range_size)
            self.out_ep.write(response_bytes)
            self._log_to_file("Response header sent")

            # Wait for ACK
            self._log_to_file("Waiting for ACK...")
            ack = bytes(self.in_ep.read(16, timeout=0))
            self._log_to_file(f"ACK received: {len(ack)} bytes")

            # Parse ACK (like original - even though values aren't used)
            magic = ack[:4]
            cmd_type = struct.unpack('<I', ack[4:8])[0]
            cmd_id = struct.unpack('<I', ack[8:12])[0]
            ack_data_size = struct.unpack('<I', ack[12:16])[0]
            self._log_to_file(f"ACK parsed: magic={magic}, type={cmd_type}, id={cmd_id}, size={ack_data_size}")

            # Open and transfer file (like original - no check for file existence)
            file_path = self.file_list[nsp_name]
            self._log_to_file(f"File path: {file_path}")
            self.current_file = nsp_name
            self.transfer_start_time = time.time()

            # Detect metadata vs transfer phase based on range_size
            is_metadata = range_size < self.METADATA_THRESHOLD

            if is_metadata:
                # METADATA PHASE: Small chunks (16, 96, 3072 bytes) - identify which files will be installed
                if nsp_name not in self.requested_files:
                    self.requested_files.add(nsp_name)
                    try:
                        file_size = file_path.stat().st_size
                        self.file_sizes[nsp_name] = file_size
                        self.total_requested_size += file_size
                        self._log_to_file(f"[METADATA] First request for {nsp_name}: size={file_size}, total_requested={self.total_requested_size}")

                        # Emit progress update to notify UI about new file count
                        # During metadata phase: transferred_bytes=0, speed=0, current_file_bytes=0
                        try:
                            num_requested = len(self.requested_files)
                            self._log_to_file(f"[METADATA] Progress emit: {num_requested} files requested so far")
                            self.progress_updated.emit(nsp_name, 0, 0.0, self.total_requested_size, num_requested, 0, 0, 0)
                        except Exception as e:
                            self._log_to_file(f"[METADATA] Progress emit failed (ignored): {e}")
                    except Exception as e:
                        self._log_to_file(f"[METADATA] Cannot get size for {nsp_name}: {e}")
                else:
                    self._log_to_file(f"[METADATA] Additional metadata request for {nsp_name}: range={range_offset}+{range_size}")
            else:
                # TRANSFER PHASE: Large chunks (1MB) - actual file installation
                # Set current file info
                self.current_file_size = self.file_sizes.get(nsp_name, 0)
                self.current_range_offset = range_offset
                self.current_range_size = range_size
                self.current_range_bytes = 0

                self._log_to_file(f"[TRANSFER] Range request for {nsp_name}: offset={range_offset}, size={range_size}, file_size={self.current_file_size}")

            # Open and transfer file data (EXACTLY like original - NO progress for now)
            self._log_to_file(f"Opening file: {file_path}")
            with open(file_path.__str__(), 'rb') as f:
                self._log_to_file(f"Seeking to offset {range_offset}")
                f.seek(range_offset)

                curr_off = 0x0  # Like original
                end_off = range_size
                read_size = self.BUFFER_SEGMENT_DATA_SIZE

                self._log_to_file(f"Starting transfer loop: curr_off={curr_off:#x}, end_off={end_off}, read_size={read_size}")

                chunk_count = 0
                chunk_start_time = time.time()

                while curr_off < end_off:  # Like original - no extra checks
                    chunk_count += 1
                    if curr_off + read_size >= end_off:
                        read_size = end_off - curr_off

                    # Measure chunk transfer time for speed calculation
                    transfer_start = time.time()
                    buf = f.read(read_size)
                    self.out_ep.write(data=buf, timeout=0)
                    transfer_time = time.time() - transfer_start

                    bytes_sent = len(buf)
                    curr_off += bytes_sent
                    self.transferred_bytes += bytes_sent

                    # Track current range progress (only during transfer phase, not metadata)
                    # NOTE: We don't update current_file_bytes here because partial range
                    # might overlap with existing intervals, causing incorrect counts.
                    # Instead, we update it only after range completes (see below)

                    # Note: transferred_bytes may exceed total_requested_size due to:
                    # 1. Overlapping ranges (Switch requests same bytes multiple times)
                    # 2. Verification passes (Switch re-downloads to verify)
                    # This is normal and we'll cap progress display at 99%

                    # Calculate speed for this chunk (only for transfer phase, metadata is too small)
                    if not is_metadata:
                        chunk_speed_mbps = (bytes_sent / transfer_time / (1024 * 1024)) if transfer_time > 0 else 0

                        # Add to speed samples for averaging
                        self.speed_samples.append(chunk_speed_mbps)
                        if len(self.speed_samples) > self.max_speed_samples:
                            self.speed_samples.pop(0)

                        # Average speed
                        avg_speed = sum(self.speed_samples) / len(self.speed_samples) if self.speed_samples else 0
                    else:
                        # Metadata phase - use last known speed or 0
                        avg_speed = sum(self.speed_samples) / len(self.speed_samples) if self.speed_samples else 0

                    # Emit progress every 10 chunks (10 MB) - balance between updates and performance
                    # Only emit during TRANSFER phase (not metadata)
                    # NOTE: We emit current_file_bytes which is updated only after range completes
                    # This means progress updates are slightly delayed but always accurate
                    if not is_metadata and chunk_count % 10 == 0:
                        try:
                            num_requested = len(self.requested_files)
                            self._log_to_file(f"Progress emit: {nsp_name}, overall={self.transferred_bytes}/{self.total_requested_size}, current={self.current_file_bytes}/{self.current_file_size}, files={num_requested}, speed={avg_speed:.1f}MB/s, unique={self.unique_bytes_transferred}")
                            self.progress_updated.emit(nsp_name, self.transferred_bytes, avg_speed, self.total_requested_size, num_requested, self.current_file_bytes, self.current_file_size, self.unique_bytes_transferred)
                        except Exception as e:
                            self._log_to_file(f"Progress emit failed (ignored): {e}")

                    # Log every 10 chunks
                    if chunk_count % 10 == 0:
                        self._log_to_file(f"Chunk {chunk_count}: sent {bytes_sent} bytes, curr_off={curr_off}/{end_off}, speed={avg_speed:.1f}MB/s")

                # Add this range to intervals (only for transfer phase, not metadata)
                if not is_metadata:
                    # Add interval: [range_offset, range_offset + range_size)
                    interval_start = self.current_range_offset
                    interval_end = self.current_range_offset + range_size
                    self.current_file_bytes = self._add_interval(nsp_name, interval_start, interval_end)
                    self._log_to_file(f"Added interval [{interval_start}, {interval_end}) for {nsp_name}, unique_bytes={self.current_file_bytes}/{self.current_file_size}")

                    # Check if file is complete
                    if nsp_name not in self.completed_files_set and self.current_file_bytes >= self.current_file_size:
                        self.completed_files_set.add(nsp_name)
                        self.completed_files = len(self.completed_files_set)

                        # Log file completion with unique bytes info (in MB)
                        file_mb = self.current_file_bytes / (1024 * 1024)
                        total_unique_mb = self.unique_bytes_transferred / (1024 * 1024)
                        self._log_to_file(f"File complete: {nsp_name} ({self.completed_files}/{len(self.requested_files)})")
                        self._log_to_file(f"  File unique bytes: {file_mb:.2f} MB")
                        self._log_to_file(f"  Total unique bytes transferred: {total_unique_mb:.2f} MB")
                        print(f"[FILE COMPLETE] {nsp_name}: {file_mb:.2f} MB | Total: {total_unique_mb:.2f} MB ({self.completed_files}/{len(self.requested_files)} files)")

                        try:
                            self.transfer_complete.emit(nsp_name)
                        except Exception as e:
                            self._log_to_file(f"transfer_complete emit failed (ignored): {e}")

                    # Final emit after transfer completes
                    try:
                        num_requested = len(self.requested_files)
                        self._log_to_file(f"Final progress emit: {nsp_name}, overall={self.transferred_bytes}/{self.total_requested_size}, current={self.current_file_bytes}/{self.current_file_size}, files={num_requested}, speed={avg_speed:.1f}MB/s, unique={self.unique_bytes_transferred}")
                        self.progress_updated.emit(nsp_name, self.transferred_bytes, avg_speed, self.total_requested_size, num_requested, self.current_file_bytes, self.current_file_size, self.unique_bytes_transferred)
                    except Exception as e:
                        self._log_to_file(f"Final progress emit failed (ignored): {e}")

                self._log_to_file(f"Transfer complete: {chunk_count} chunks, total {curr_off} bytes, phase={'METADATA' if is_metadata else 'TRANSFER'}")

        except Exception as e:
            error_msg = f'File transfer error: {e}\n{traceback.format_exc()}'
            self._log_to_file(f"ERROR in file transfer: {error_msg}")
            self.log_message.emit('error', f'File transfer error: {e}')

    @staticmethod
    def format_size(size: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f'{size:.1f} {unit}'
            size /= 1024.0
        return f'{size:.1f} PB'
