"""
Shared network transfer handler logic for HTTP and FTP modes.
"""

import ipaddress
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from . import dbi_protocol
from .progress_tracker import ProgressTracker


class NetworkTransferHandler(QThread):
    """Common progress, file-map, and IP handling for network servers."""

    log_message = pyqtSignal(str, str)
    server_started = pyqtSignal(str, int)
    server_stopped = pyqtSignal()

    progress_updated = pyqtSignal(str, object, float, object, int, object, object, object)
    file_progress = pyqtSignal(str, int)
    transfer_complete = pyqtSignal(str)
    file_skipped = pyqtSignal(str, object)
    all_transfers_complete = pyqtSignal()

    def __init__(self, file_list: Dict[str, Path], port: int, display_ip: Optional[str] = None):
        super().__init__()
        self.file_list = file_list
        self.port = port
        self.display_ip = display_ip or self.get_local_ip()
        self.is_running = False
        self.lock = threading.Lock()
        self.progress_tracker = ProgressTracker(file_list)

        self.file_map = {}
        for name, path in file_list.items():
            safe_name = name.replace(" ", "_")
            self.file_map[safe_name] = {
                "path": path,
                "orig_name": name,
            }

    @staticmethod
    def get_local_ip():
        return NetworkTransferHandler.get_local_ips()[0]

    @staticmethod
    def get_local_ips():
        ips = []

        def add_ip(value: str):
            try:
                addr = ipaddress.ip_address(value.strip())
            except ValueError:
                return

            if (
                addr.version != 4
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_unspecified
            ):
                return

            ip = str(addr)
            if ip not in ips:
                ips.append(ip)

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 1))
            add_ip(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()

        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                add_ip(info[4][0])
        except OSError:
            pass

        if os.name == "nt":
            try:
                output = subprocess.run(
                    ["ipconfig"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=2,
                    check=False,
                ).stdout
                for line in output.splitlines():
                    if "IPv4" in line:
                        for match in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", line):
                            add_ip(match)
            except (OSError, subprocess.SubprocessError):
                pass

        return ips or ["127.0.0.1"]

    def register_file_request(self, filename: str, _file_size: int):
        with self.lock:
            self.progress_tracker.register_file_request(filename)

    def mark_file_skipped(self, filename: str):
        with self.lock:
            self.progress_tracker.mark_file_skipped(filename)
            path = self.file_list.get(filename)
            size = path.stat().st_size if path else 0
            self.file_skipped.emit(filename, size)

    def update_progress(self, filename: str, start: int, end: int):
        with self.lock:
            file_unique_bytes = self.progress_tracker.add_interval(filename, start, end)
            return (
                file_unique_bytes,
                self.progress_tracker.unique_bytes_transferred,
                self.progress_tracker.total_requested_size,
                len(self.progress_tracker.requested_files),
            )

    def begin_file_transfer(self, filename: str, file_size: int, start: int, content_length: int, transport: str):
        self.register_file_request(filename, file_size)
        is_metadata = content_length < dbi_protocol.METADATA_THRESHOLD
        if is_metadata:
            self.log_message.emit("debug", f"{transport} metadata read: {filename}")
        elif start == 0:
            self.log_message.emit("info", f"Starting {transport} transfer: {filename}")
        return is_metadata

    def emit_transfer_progress(self, filename: str, file_size: int, start: int, bytes_sent: int, started_at: float):
        current_pos = start + bytes_sent
        file_unique, total_unique, total_req_size, n_files = self.update_progress(filename, start, current_pos)
        elapsed = time.time() - started_at
        speed_mbps = (bytes_sent / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        self.progress_updated.emit(
            filename,
            total_unique,
            speed_mbps,
            total_req_size,
            n_files,
            file_unique,
            file_size,
            total_unique,
        )

        percent = int((file_unique / file_size) * 100) if file_size else 0
        self.file_progress.emit(filename, percent)
        return file_unique

    def finish_file_transfer(
        self,
        filename: str,
        file_size: int,
        start: int,
        bytes_sent: int,
        started_at: float,
        transport: str,
        is_metadata: bool = False,
    ):
        if is_metadata:
            file_unique, _total_unique, _total_req_size, _n_files = self.update_progress(filename, start, start + bytes_sent)
            percent = int((file_unique / file_size) * 100) if file_size else 0
            self.file_progress.emit(filename, percent)
            return file_unique

        file_unique = self.emit_transfer_progress(filename, file_size, start, bytes_sent, started_at)
        if file_unique >= (file_size * 0.99) and filename not in self.progress_tracker.completed_files_set:
            self.progress_tracker.completed_files_set.add(filename)
            self.transfer_complete.emit(filename)
            self.log_message.emit("success", f"Finished {transport} transfer: {filename}")
        return file_unique

    def get_dbi_flat_file_map(self) -> Dict[str, dict]:
        """
        Returns a flat map of only compatible files for DBI installation.
        If file_list contains directories, it scans them recursively for compatible files.
        """
        flat_map = {}
        supported = {'.nsp', '.nsz', '.xci', '.xcz'}
        for name, path in self.file_list.items():
            try:
                if path.is_dir():
                    for f in path.rglob('*'):
                        if f.is_file() and f.suffix.lower() in supported:
                            safe_name = f.name.replace(" ", "_")
                            flat_map[safe_name] = {
                                "path": f.resolve(),
                                "orig_name": f.name
                            }
                else:
                    if path.suffix.lower() in supported:
                        safe_name = name.replace(" ", "_")
                        flat_map[safe_name] = {
                            "path": path.resolve(),
                            "orig_name": name
                        }
            except Exception:
                pass
        return flat_map

    def resolve_virtual_path(self, clean_path: str):
        """
        Resolves a virtual path (e.g. 'My_Folder/sub/file.txt') to a local disk Path.
        Returns:
            (disk_path, is_dir, original_name) or (None, None, None)
        """
        if not clean_path:
            return None, True, "Root"
            
        parts = clean_path.split('/')
        first_part = parts[0]
        
        entry = self.file_map.get(first_part)
        if not entry:
            return None, None, None
            
        base_path = entry["path"]
        orig_name = entry["orig_name"]
        
        if len(parts) == 1:
            return base_path, base_path.is_dir(), orig_name
            
        if not base_path.is_dir():
            return None, None, None
            
        subpath = "/".join(parts[1:])
        target_path = (base_path / subpath).resolve()
        
        # Security check: prevent directory traversal
        try:
            target_path.relative_to(base_path.resolve())
        except ValueError:
            return None, None, None
            
        if target_path.exists():
            return target_path, target_path.is_dir(), target_path.name
            
        return None, None, None

