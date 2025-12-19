"""
HTTP Handler for DBI Backend
Provides a simple HTTP server to serve files to DBI.
"""

import socket
import threading
from http.server import HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Dict
from PyQt6.QtCore import QThread, pyqtSignal

# FIX: Relative import
from .http_request_handler import DBIRequestHandler

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class HTTPHandler(QThread):
    log_message = pyqtSignal(str, str) 
    server_started = pyqtSignal(str, int) 
    server_stopped = pyqtSignal()
    progress_updated = pyqtSignal(str, object, float, object, int, object, object, object)
    file_progress = pyqtSignal(str, int)
    transfer_complete = pyqtSignal(str)
    
    def __init__(self, file_list: Dict[str, Path], port: int = 8080):
        super().__init__()
        self.file_list = file_list
        self.port = port
        self.httpd = None
        self.is_running = False
        
        self.file_map = {}
        for name, path in file_list.items():
            safe_name = name.replace(" ", "_")
            self.file_map[safe_name] = {'path': path, 'orig_name': name}
        
        # Tracking variables
        self.total_bytes_transferred = 0
        self.total_requested_size = 0
        self.requested_files = set()

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 1))
            IP = s.getsockname()[0]
        except: IP = '127.0.0.1'
        finally: s.close()
        return IP

    # Helper methods called by RequestHandler
    def register_file_request(self, filename, size):
        if filename not in self.requested_files:
            self.requested_files.add(filename)
            self.total_requested_size += size

    def update_progress(self, filename, start, end):
        # Simplified interval tracking for HTTP
        chunk = end - start
        self.total_bytes_transferred += chunk
        return chunk, self.total_bytes_transferred, self.total_requested_size, len(self.requested_files)

    def run(self):
        try:
            self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), DBIRequestHandler)
            self.httpd.file_map = self.file_map
            self.httpd.signal_emitter = self # Pass self to handler
            
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
        self.is_running = False
        self.server_stopped.emit()
        self.wait()