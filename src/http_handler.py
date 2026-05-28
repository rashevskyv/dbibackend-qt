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
from .progress_tracker import ProgressTracker

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
    file_skipped = pyqtSignal(str, object)
    all_transfers_complete = pyqtSignal()
    
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
        
        # Centralized Progress Tracker
        self.progress_tracker = ProgressTracker(file_list)
        
        # File handle caching (shared across request handler threads)
        self.cached_file_path = None
        self.cached_file_handle = None
        self.cache_lock = threading.Lock()

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
            self.progress_tracker.register_file_request(filename)

    def mark_file_skipped(self, filename: str):
        """Manually mark a file as skipped (e.g., from UI or reset)"""
        with self.lock:
            self.progress_tracker.mark_file_skipped(filename)
            # Emit for UI update
            path = self.file_list.get(filename)
            size = path.stat().st_size if path else 0
            self.file_skipped.emit(filename, size)

    def update_progress(self, filename: str, start: int, end: int):
        with self.lock:
            file_unique_bytes = self.progress_tracker.add_interval(filename, start, end)
            
            # Update local byte tracking for this specific interval session
            # (Note: progress_tracker handles the interval merging internally)
            
            return (
                file_unique_bytes, 
                self.progress_tracker.unique_bytes_transferred, 
                self.progress_tracker.total_requested_size, 
                len(self.progress_tracker.requested_files)
            )

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
        
        # Close cached file
        with self.cache_lock:
            if self.cached_file_handle:
                try: 
                    self.cached_file_handle.close()
                except Exception: 
                    pass
                self.cached_file_handle = None
                self.cached_file_path = None

        self.is_running = False
        self.server_stopped.emit()
        self.wait()