"""
HTTP Handler for DBI Backend
Provides a simple HTTP server to serve files to DBI.
"""

import socket
import threading
import time
from http.server import HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Dict, List, Tuple
from PyQt6.QtCore import QThread, pyqtSignal

from .http_request_handler import DBIRequestHandler

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HTTPHandler(QThread):
    """Thread for running the HTTP Server"""
    
    log_message = pyqtSignal(str, str) 
    server_started = pyqtSignal(str, int) 
    server_stopped = pyqtSignal()
    
    # Progress signals
    progress_updated = pyqtSignal(str, object, float, object, int, object, object, object)
    file_progress = pyqtSignal(str, int)
    transfer_complete = pyqtSignal(str)
    
    def __init__(self, file_list: Dict[str, Path], port: int = 8080):
        super().__init__()
        self.file_list = file_list
        self.port = port
        self.httpd = None
        self.is_running = False
        
        # Build map: Safe_Name.nsp -> {path, orig_name}
        self.file_map = {}
        for name, path in file_list.items():
            safe_name = name.replace(" ", "_")
            self.file_map[safe_name] = {
                'path': path,
                'orig_name': name
            }
        
        self.lock = threading.Lock()
        
        # --- RESTORED LOGIC: Interval Tracking for accurate progress ---
        self.file_intervals: Dict[str, List[Tuple[int, int]]] = {name: [] for name in file_list.keys()}
        self.requested_files = set()
        self.total_requested_size = 0
        self.unique_bytes_transferred = 0
        
        # Helpers for current file tracking
        self.current_file_downloading = None

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 1))
            IP = s.getsockname()[0]
        except: IP = '127.0.0.1'
        finally: s.close()
        return IP

    def register_file_request(self, filename: str, file_size: int):
        """Called when a download starts for a file"""
        with self.lock:
            if filename not in self.requested_files:
                self.requested_files.add(filename)
                self.total_requested_size += file_size

    def update_progress(self, filename: str, start: int, end: int):
        """
        Smart progress update.
        Merges overlapping intervals (e.g., multi-threaded download)
        to calculate actual unique bytes sent.
        """
        with self.lock:
            if filename not in self.file_intervals:
                self.file_intervals[filename] = []

            intervals = self.file_intervals[filename]
            intervals.append((start, end))
            intervals.sort()

            # Merge overlaps
            merged = []
            for s, e in intervals:
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))

            self.file_intervals[filename] = merged

            # Calculate unique bytes for this file
            file_unique_bytes = sum(e - s for s, e in merged)

            # Calculate total unique bytes for session
            self.unique_bytes_transferred = sum(
                sum(e - s for s, e in interval_list)
                for interval_list in self.file_intervals.values()
            )
            
            return file_unique_bytes, self.unique_bytes_transferred, self.total_requested_size, len(self.requested_files)

    def run(self):
        try:
            self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), DBIRequestHandler)
            # Inject data into server instance so RequestHandler can access it
            self.httpd.file_map = self.file_map
            self.httpd.signal_emitter = self
            
            self.is_running = True
            self.server_started.emit(self.get_local_ip(), self.port)
            self.httpd.serve_forever()
            
        except Exception as e:
            self.log_message.emit('error', f'HTTP Server crashed: {e}')
            self.is_running = False

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        self.is_running = False
        self.server_stopped.emit()
        self.wait()