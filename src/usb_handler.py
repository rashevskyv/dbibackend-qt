"""
USB Handler for DBI Protocol
Handles USB communication with Nintendo Switch
"""

import struct
import time
import threading
import traceback
from pathlib import Path
from typing import Dict, Optional, Set
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
    package_status_received = pyqtSignal(str, int, int) # filename, status, result_code
    storage_info_received = pyqtSignal(object, object, object, object) # nand_free, nand_total, sd_free, sd_total
    queue_sync_confirmed = pyqtSignal(int)

    @staticmethod
    def _expand_files(file_dict: Dict[str, Path], checked_set: Set[str]):
        supported = {'.nsp', '.nsz', '.xci', '.xcz'}
        raw_items = []
        for name, path in file_dict.items():
            try:
                if path.is_dir():
                    for f in path.rglob('*'):
                        if f.is_file() and f.suffix.lower() in supported:
                            is_chk = name in checked_set or f.name in checked_set
                            raw_items.append((f.name, f.resolve(), is_chk))
                else:
                    if path.suffix.lower() in supported or path.is_file():
                        p_res = path.resolve() if hasattr(path, 'resolve') else path
                        raw_items.append((name, p_res, name in checked_set))
            except Exception:
                continue

        name_to_paths = {}
        for fname, fpath, is_chk in raw_items:
            name_to_paths.setdefault(fname, set()).add(fpath)

        conflicts = {fname for fname, paths in name_to_paths.items() if len(paths) > 1}

        expanded_files = {}
        expanded_checked = set()
        for fname, fpath, is_chk in raw_items:
            if fname in conflicts:
                continue
            expanded_files[fname] = fpath
            if is_chk:
                expanded_checked.add(fname)
        return expanded_files, expanded_checked

    def __init__(self, file_list: Dict[str, Path], initial_checked: Optional[Set[str]] = None, initial_targets: Optional[Dict[str, int]] = None):
        super().__init__()
        self._lock = threading.Lock()
        self._selection_lock = self._lock # Backward compatibility alias

        checked_raw = initial_checked if initial_checked is not None else set(file_list.keys())
        expanded_files, expanded_checked = self._expand_files(file_list, checked_raw)

        with self._lock:
            self.file_list = expanded_files
            self._selected_files = expanded_checked
            self._file_targets: Dict[str, int] = initial_targets.copy() if initial_targets is not None else {}
            self.queue_revision = 1 if self.file_list else 0
            self.last_sent_revision = 0
            self.confirmed_revision = 0
            self._retained_active_files: Dict[str, Path] = {}
            self._session_seen_basenames: Dict[str, Path] = {fname: p for fname, p in self.file_list.items()}

        self.is_running = False
        self.dev = None
        self.in_ep = None
        self.out_ep = None
        self.transfer_start_time = None
        self.progress_tracker = ProgressTracker(self.file_list, initial_checked=self._selected_files)

        # State tracking for UI
        self.current_transfer_file = None
        self.current_file_bytes_sent = 0
        self.current_file_size = 0
        self.installation_started = False

        # progress_updated throttling — emit at most ~20 Hz so the UI thread
        # is not flooded by tens of cross-thread signals per second when the
        # bus is sustaining 30-100 MB/s.
        self._progress_emit_interval = 0.05  # seconds
        self._last_progress_emit = 0.0

        # File handle caching
        self.cached_file_path = None
        self.cached_file_handle = None

        # Inactivity & communication tracking
        self.last_activity_time = time.time()
        self.has_communicated = False

    def record_activity(self):
        """Record timestamp of client communication."""
        self.has_communicated = True
        self.last_activity_time = time.time()

    def get_inactivity_seconds(self) -> Optional[float]:
        """Returns seconds since last client communication, or None if no communication occurred."""
        if not self.has_communicated or self.last_activity_time is None:
            return None
        return max(0.0, time.time() - self.last_activity_time)

    def update_file_registry(self, all_ui_files: Dict[str, Path], checked_names: Set[str], targets: Optional[Dict[str, int]] = None):
        """Update mutable file registry, selected set, and targets from UI thread."""
        expanded_files, expanded_checked = self._expand_files(all_ui_files, checked_names)

        with self._lock:
            if targets is not None:
                self._file_targets.update(targets)

            # Rebuild file_list in exact order of expanded_files, protecting session-locked basenames
            new_file_list: Dict[str, Path] = {}
            for fname, fpath in expanded_files.items():
                if fname in self._session_seen_basenames:
                    known_path = self._session_seen_basenames[fname]
                    if known_path.resolve() != fpath.resolve():
                        self.log_message.emit(
                            'warning',
                            f"Path replacement for active or completed file '{fname}' rejected: "
                            f"cannot replace '{known_path}' with '{fpath}' in active session."
                        )
                        # Never advertise the old bytes under a new UI path.
                        # An active old file stays readable via _retained_active_files.
                        continue
                else:
                    self._session_seen_basenames[fname] = fpath

                new_file_list[fname] = fpath
                self.progress_tracker.file_list[fname] = fpath
                if fname not in self.progress_tracker.file_bytes_sent:
                    self.progress_tracker.file_bytes_sent[fname] = 0

            # Retain active file if removed by user before reaching terminal status
            if self.current_transfer_file and self.current_transfer_file not in new_file_list:
                active_fname = self.current_transfer_file
                active_path = self.file_list.get(active_fname) or self._retained_active_files.get(active_fname)
                if active_path:
                    self._retained_active_files[active_fname] = active_path
                    self.log_message.emit(
                        'warning',
                        f"Active file '{active_fname}' removal deferred until transfer completes."
                    )

            # Clean up removed files (excluding active file currently transferring)
            for fname in set(self.file_list) - set(new_file_list):
                if fname != self.current_transfer_file:
                    self._file_targets.pop(fname, None)
                    self.progress_tracker.file_list.pop(fname, None)

            self.file_list = new_file_list

            new_selected = {name for name in expanded_checked if name in self.file_list}
            new_checked = new_selected - self._selected_files
            new_unchecked = self._selected_files - new_selected
            self._selected_files = new_selected

            for fname in new_checked:
                if fname in self.progress_tracker.skipped_files:
                    self.progress_tracker.skipped_files.remove(fname)
                    bytes_sent = self.progress_tracker.file_bytes_sent.get(fname, 0)
                    fsize = self.progress_tracker.get_file_size(fname)
                    self.progress_tracker.total_requested_size += max(0, fsize - bytes_sent)
                elif fname not in self.progress_tracker.requested_files:
                    self.progress_tracker.register_file_request(fname)

            for fname in new_unchecked:
                if fname not in self.progress_tracker.completed_files_set:
                    self.progress_tracker.mark_file_skipped(fname)

            self.queue_revision += 1

    def update_selected_files(self, checked_filenames, targets: Optional[Dict[str, int]] = None):
        """Update live selection set from UI thread."""
        self.update_file_registry(self.file_list, set(checked_filenames), targets)


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
                    self.record_activity()
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
                if len(cmd_header) < 16 or cmd_header[:4] != b'DBI0':
                    continue
                self.record_activity()

                cmd_type = struct.unpack('<I', cmd_header[4:8])[0]
                cmd_id = struct.unpack('<I', cmd_header[8:12])[0]
                data_size = struct.unpack('<I', cmd_header[12:16])[0]
                # print(f"Received Command ID: {cmd_id}, Size: {data_size}") # Debug

                if cmd_id == dbi_protocol.CMD_ID_EXIT:
                    self.process_exit_command()
                    break
                elif cmd_id == dbi_protocol.CMD_ID_FILE_RANGE:
                    self.process_file_range_command(data_size)
                elif cmd_id in (dbi_protocol.CMD_ID_LIST, dbi_protocol.CMD_ID_LIST_OLD):
                    if cmd_type == dbi_protocol.CMD_TYPE_ACK:
                        self.process_list_ack(data_size)
                    else:
                        self.process_list_command(data_size, cmd_id=cmd_id)
                elif cmd_id == dbi_protocol.CMD_ID_PACKAGE_STATUS:
                    self.process_package_status_command(data_size)
                elif cmd_id == dbi_protocol.CMD_ID_STORAGE_INFO:
                    self.process_storage_info_command(data_size)

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

    def process_list_ack(self, revision: int):
        with self._lock:
            # Reject non-positive, stale, or unsent/future revision
            if revision <= 0:
                self.log_message.emit('warning', f"Ignored list ACK with non-positive revision: {revision}")
                return
            if revision <= self.confirmed_revision:
                self.log_message.emit('warning', f"Ignored stale list ACK (got {revision}, already confirmed {self.confirmed_revision})")
                return
            if revision > self.last_sent_revision:
                self.log_message.emit('warning', f"Ignored future/unsent list ACK (got {revision}, last sent was {self.last_sent_revision})")
                return

            self.confirmed_revision = revision

        self.queue_sync_confirmed.emit(revision)
        self.log_message.emit('info', f'Switch confirmed applied queue revision {revision}')

    def process_package_status_command(self, data_size):
        # 1. Ack the request
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_PACKAGE_STATUS, data_size), timeout=10000)
        # 2. Read payload: [status: u32][result_code: u32][name_len: u32][name: name_len bytes]
        payload = bytes(self.in_ep.read(data_size, timeout=10000))
        if len(payload) < 12:
            raise usb.core.USBError('Truncated package status header')
        status, result_code, name_len = struct.unpack('<III', payload[:12])
        if not name_len or len(payload) < 12 + name_len:
            raise usb.core.USBError('Truncated package status filename')
        name = payload[12:12 + name_len].decode('utf-8', errors='replace')

        # 3. Send response (data_size = 0)
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_PACKAGE_STATUS, 0), timeout=10000)

        # Emit signal to UI thread
        if status == dbi_protocol.STATUS_INSTALLED:
            self.progress_tracker.completed_files_set.add(name)
        self.package_status_received.emit(name, status, result_code)
        with self._lock:
            self._retained_active_files.pop(name, None)
            if self.cached_file_handle:
                try:
                    self.cached_file_handle.close()
                except Exception:
                    pass
                self.cached_file_handle = None
                self.cached_file_path = None
            if self.current_transfer_file == name:
                self.current_transfer_file = None

    def process_storage_info_command(self, data_size):
        # 1. Ack the request
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_STORAGE_INFO, data_size), timeout=10000)
        # 2. Read payload: [nand_free: u64][nand_total: u64][sd_free: u64][sd_total: u64] (32 bytes)
        payload = bytes(self.in_ep.read(data_size, timeout=10000))
        if len(payload) < 32:
            raise usb.core.USBError('Truncated storage info')
        nand_free, nand_total, sd_free, sd_total = struct.unpack('<QQQQ', payload[:32])

        # 3. Send response (data_size = 0)
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_STORAGE_INFO, 0), timeout=10000)

        # Emit signal to UI thread
        self.storage_info_received.emit(nand_free, nand_total, sd_free, sd_total)

    def process_list_command(self, data_size, cmd_id=dbi_protocol.CMD_ID_LIST):
        with self._lock:
            file_list_snapshot = list(self.file_list.items())
            selected_snapshot = set(self._selected_files)
            targets_snapshot = dict(self._file_targets)
            rev = self.queue_revision
            self.last_sent_revision = rev

        self.log_message.emit('info', f'Sending list of {len(file_list_snapshot)} files (rev {rev})...')
        
        data = dbi_protocol.build_list_payload(
            file_list_snapshot, selected_snapshot, targets_snapshot, data_size, rev
        )

        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, cmd_id, len(data)))
        if len(data) > 0:
            self.in_ep.read(16, timeout=10000) # Use 10s instead of 0
            self.out_ep.write(data, timeout=10000)


    def process_file_range_command(self, data_size):
        # Ack command
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_FILE_RANGE, data_size), timeout=10000)
        
        # Read request details
        header = self.in_ep.read(data_size, timeout=10000)
        if len(header) < 16:
            raise usb.core.USBError('Truncated file range header')
        range_size, range_offset, name_len = struct.unpack('<IQI', header[:16])
        if name_len and len(header) < 16 + name_len:
            raise usb.core.USBError('Truncated file range filename')
        # Older DBI clients leave name_len zero and NUL-terminate the trailing name.
        name_bytes = bytes(header[16:16 + name_len] if name_len else header[16:]).rstrip(b'\x00')
        if not name_bytes:
            raise usb.core.USBError('Missing file range filename')
        name = name_bytes.decode('utf-8', errors='replace')
        
        # Respond
        self.out_ep.write(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_RESPONSE, dbi_protocol.CMD_ID_FILE_RANGE, range_size), timeout=10000)
        self.in_ep.read(16, timeout=10000) # Final Ack

        with self._lock:
            path = self.file_list.get(name) or self._retained_active_files.get(name)
        if not path: 
            self.log_message.emit('error', f'Requested file not found in list: {name}')
            raise usb.core.USBError(f'Requested file not found in list: {name}')

        is_metadata = range_size < dbi_protocol.METADATA_THRESHOLD
        
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
                # Force the next progress emit even if the throttle window
                # hasn't elapsed so the UI flips to the new file immediately.
                self._last_progress_emit = 0.0
                self.log_message.emit('info', f'Sending: {name}')

        # --- Data Transfer (Optimized with caching) ---
        range_bytes_sent = 0
        transfer_error = False
        error_exc = None
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
                if not chunk:
                    transfer_error = True
                    break

                written = self.out_ep.write(chunk, timeout=10000)
                if isinstance(written, int) and not isinstance(written, bool) and 0 <= written <= len(chunk):
                    sent = written
                else:
                    transfer_error = True
                    break

                if sent == 0:
                    transfer_error = True
                    break

                range_bytes_sent += sent
                remaining -= sent
                self.last_activity_time = time.time()
                
                if not is_metadata:
                    chunk_offset = range_offset + range_bytes_sent - sent
                    new_file_unique = self.progress_tracker.add_interval(name, chunk_offset, chunk_offset + sent)
                    self.current_file_bytes_sent = new_file_unique

                    # Throttle UI updates: at sustained 100 MB/s this loop
                    # iterates 100x/sec; emitting a cross-thread signal each
                    # iteration overwhelms the event loop and stalls UI input.
                    now = time.time()
                    if now - self._last_progress_emit >= self._progress_emit_interval:
                        self._last_progress_emit = now
                        elapsed = now - self.transfer_start_time
                        speed = (self.progress_tracker.unique_bytes_transferred / elapsed / 1048576) if elapsed > 0 else 0.0

                        self.progress_updated.emit(
                            name,
                            self.progress_tracker.unique_bytes_transferred,
                            speed,
                            self.progress_tracker.total_requested_size,
                            len(self.progress_tracker.requested_files),
                            self.current_file_bytes_sent,  # Current file progress
                            self.current_file_size,        # Current file total
                            self.progress_tracker.unique_bytes_transferred
                        )

                if sent < len(chunk) or len(chunk) < read_amount:
                    transfer_error = True
                    break
        except Exception as e:
            transfer_error = True
            error_exc = e
            self.log_message.emit('error', f'File error: {e}')
            # Clear cache on error
            if self.cached_file_handle:
                try: self.cached_file_handle.close()
                except: pass
            self.cached_file_handle = None
            self.cached_file_path = None

        # --- Completion Logic ---
        if not is_metadata:
             total_file_transferred = self.progress_tracker.file_bytes_sent.get(name, 0)
             
             # Calculate percentage for file list status
             pct = int((total_file_transferred / self.current_file_size) * 100) if self.current_file_size > 0 else 0
             self.file_progress.emit(name, pct)

             # Check if file is essentially done (>99%) and request completed successfully
             is_complete_range = (range_bytes_sent == range_size) and not transfer_error and self.is_running
             if is_complete_range and name not in self.progress_tracker.completed_files_set and total_file_transferred >= (self.current_file_size * 0.99):
                 self.progress_tracker.completed_files_set.add(name)
                 self.transfer_complete.emit(name)
                 self.log_message.emit('success', f'Finished: {name}')

        if self.is_running and (transfer_error or range_bytes_sent < range_size):
            err_msg = f"Incomplete range transfer for {name}: sent {range_bytes_sent}/{range_size} bytes"
            if error_exc and isinstance(error_exc, usb.core.USBError) and not isinstance(error_exc, usb.core.USBTimeoutError) and "timeout" not in str(error_exc).lower():
                raise error_exc
            if error_exc:
                raise usb.core.USBError(err_msg) from error_exc
            raise usb.core.USBError(err_msg)
