"""
HTTP Handler for DBI Backend
Provides a simple HTTP server to serve files to DBI (Install from HTTP)
with Progress Tracking and Chunk Logging.
Implements specific interval tracking logic to match USB Backend behavior.
Replaces spaces with underscores in URLs for better readability.
"""

import os
import socket
import html
import sys
import mimetypes
import urllib.parse
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Dict, Tuple, List, Any
from PyQt6.QtCore import QThread, pyqtSignal

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True

class DBIRequestHandler(BaseHTTPRequestHandler):
    """
    Custom Request Handler for DBI.
    Serves a virtual directory containing selected files.
    Compatible with DBI's 'ApacheHTTP' network source.
    """
    
    def log_message(self, format, *args):
        """Suppress default logging to stderr"""
        pass

    def do_GET(self):
        """Handle GET requests"""
        # Access shared data from the server instance
        # file_map structure: { 'Safe_Name.nsp': {'path': Path(...), 'orig_name': 'Original Name.nsp'} }
        file_map: Dict[str, Any] = self.server.file_map
        handler_thread = self.server.signal_emitter
        
        # Decode path
        path = urllib.parse.unquote(self.path.split('?')[0])
        clean_path = path.strip('/')
        
        try:
            # If path ends with / or is empty, show directory listing
            if self.path.endswith('/') or path == '/index.html':
                self.send_directory_listing(file_map)
                return

            # Check if file exists in our sanitized list
            filename = os.path.basename(clean_path)
            
            if filename in file_map:
                entry = file_map[filename]
                real_path = entry['path']
                # Important: Pass the ORIGINAL name to the thread for UI updates
                original_name = entry['orig_name']
                
                self.send_file_content(original_name, real_path, handler_thread)
            else:
                self.send_error(404, "File not found")
        except Exception as e:
            print(f"Server Error: {e}")
            try:
                self.send_error(500, f"Internal Server Error: {e}")
            except:
                pass

    def send_directory_listing(self, file_map: Dict[str, Any]):
        """
        Generate Apache-style HTML directory listing.
        Uses sanitized names (underscores) for display and links.
        """
        enc = sys.getfilesystemencoding()
        title = "DBI Repository"
        
        r = []
        r.append(f'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">')
        r.append(f'<html><head><meta http-equiv="Content-Type" content="text/html; charset={enc}"><title>{title}</title></head>')
        r.append(f'<body><h1>Index of /</h1>')
        r.append('<hr>')
        r.append('<pre>')
        
        # Sort by the sanitized name (what the user sees on Switch)
        for safe_name in sorted(file_map.keys()):
            entry = file_map[safe_name]
            path = entry['path']
            try:
                size = path.stat().st_size
                # URL encode the sanitized name
                link = urllib.parse.quote(safe_name)
                display_name = html.escape(safe_name)
                # Pad name for alignment
                r.append(f'<a href="{link}">{display_name}</a>{" " * max(1, 50 - len(display_name))} {self.format_size(size)}')
            except Exception:
                pass 
                
        r.append('</pre>')
        r.append('<hr>')
        r.append('</body></html>')
        
        encoded = '\n'.join(r).encode(enc, 'surrogateescape')
        
        self.send_response(200)
        self.send_header("Content-type", f"text/html; charset={enc}")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_file_content(self, original_filename: str, file_path: Path, handler_thread):
        """
        Serve the file content.
        NOTE: 'original_filename' is used for UI updates (contains spaces).
        """
        if not file_path.exists():
            self.send_error(404, "File not found on disk")
            return

        file_size = file_path.stat().st_size
        ctype = 'application/octet-stream'

        # Handle Range Header
        range_header = self.headers.get('Range')
        start, end = 0, file_size - 1
        
        if range_header:
            try:
                _, r = range_header.split('=')
                if '-' in r:
                    s, e = r.split('-')
                    start = int(s) if s else 0
                    end = int(e) if e else file_size - 1
                
                if start >= file_size:
                    self.send_error(416, "Requested Range Not Satisfiable")
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                if end >= file_size:
                    end = file_size - 1
                    
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            except ValueError:
                self.send_error(400, "Invalid Range Header")
                return
        else:
            self.send_response(200)

        content_length = end - start + 1
        
        self.send_header("Content-type", ctype)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        # Update handler state for UI (Dynamic Calculation)
        # Use ORIGINAL NAME for logic so UI matches
        handler_thread.current_file_downloading = original_filename
        handler_thread.register_file_request(original_filename, file_size)
        
        total_requested_size = handler_thread.total_requested_size
        num_files = len(handler_thread.requested_files)

        # Log start
        if start == 0:
            handler_thread.log_message.emit('info', f"Starting transfer: {original_filename}")

        try:
            with open(file_path, 'rb') as f:
                f.seek(start)
                bytes_to_send = content_length
                chunk_size = 128 * 1024 # 128KB chunks
                
                bytes_sent_this_session = 0
                bytes_since_last_log = 0
                log_threshold = 10 * 1024 * 1024  # Log every 10 MB
                
                start_time = time.time()
                last_emit_time = start_time
                
                while bytes_to_send > 0:
                    read_size = min(chunk_size, bytes_to_send)
                    buf = f.read(read_size)
                    if not buf:
                        break
                    
                    self.wfile.write(buf)
                    
                    sent = len(buf)
                    bytes_to_send -= sent
                    bytes_sent_this_session += sent
                    bytes_since_last_log += sent
                    
                    # LOGGING CHUNKS (Activity Log)
                    if bytes_since_last_log >= log_threshold:
                        mb_sent = bytes_sent_this_session / (1024 * 1024)
                        handler_thread.log_message.emit('debug', f"Sending {original_filename}: {mb_sent:.1f} MB session...")
                        bytes_since_last_log = 0

                    # Calculate speed and emit progress periodically
                    current_time = time.time()
                    if current_time - last_emit_time > 0.1:
                        elapsed = current_time - start_time
                        speed_mbps = (bytes_sent_this_session / elapsed) / (1024 * 1024) if elapsed > 0 else 0
                        
                        current_pos = start + bytes_sent_this_session
                        interval_start = start
                        interval_end = current_pos
                        
                        # UPDATE PROGRESS (Using original name for UI)
                        file_unique, total_unique, total_req_size, n_files = handler_thread.update_progress(original_filename, interval_start, interval_end)
                        
                        handler_thread.progress_updated.emit(
                            original_filename,
                            total_unique, 
                            speed_mbps,
                            total_req_size,
                            n_files,
                            file_unique, 
                            file_size,
                            total_unique 
                        )
                        
                        percent = int((file_unique / file_size) * 100)
                        handler_thread.file_progress.emit(original_filename, percent)
                        
                        last_emit_time = current_time

                # === Final Success Check ===
                final_pos = start + bytes_sent_this_session
                file_unique, total_unique, total_req_size, n_files = handler_thread.update_progress(original_filename, start, final_pos)
                
                percent = int((file_unique / file_size) * 100)
                handler_thread.file_progress.emit(original_filename, percent)

                # IMPORTANT: Only mark as COMPLETE if we have transferred > 99% of the unique file content
                if file_unique >= (file_size * 0.99):
                    handler_thread.transfer_complete.emit(original_filename)
                    handler_thread.log_message.emit('success', f"Finished sending: {original_filename}")

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            handler_thread.log_message.emit('error', f"Error serving {original_filename}: {e}")

    @staticmethod
    def format_size(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"


class HTTPHandler(QThread):
    """Thread for running the HTTP Server"""
    
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
        
        # Build the map for sanitized names
        # Structure: { 'Safe_Name.nsp': {'path': Path(...), 'orig_name': 'Original Name.nsp'} }
        self.file_map = {}
        for name, path in file_list.items():
            # Replace spaces with underscores for network transport
            safe_name = name.replace(" ", "_")
            self.file_map[safe_name] = {
                'path': path,
                'orig_name': name
            }
        
        self.lock = threading.Lock()
        # Note: file_intervals uses the ORIGINAL name as key
        self.file_intervals: Dict[str, List[Tuple[int, int]]] = {name: [] for name in file_list.keys()}
        self.requested_files = set()
        self.total_requested_size = 0
        self.unique_bytes_transferred = 0

    @staticmethod
    def get_local_ip():
        """Get local IP address that connects to the internet"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    def register_file_request(self, filename: str, file_size: int):
        with self.lock:
            if filename not in self.requested_files:
                self.requested_files.add(filename)
                self.total_requested_size += file_size

    def update_progress(self, filename: str, start: int, end: int):
        with self.lock:
            if filename not in self.file_intervals:
                self.file_intervals[filename] = []

            intervals = self.file_intervals[filename]
            intervals.append((start, end))
            intervals.sort()

            merged = []
            for s, e in intervals:
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))

            self.file_intervals[filename] = merged

            file_unique_bytes = sum(e - s for s, e in merged)

            self.unique_bytes_transferred = sum(
                sum(e - s for s, e in intervals)
                for intervals in self.file_intervals.values()
            )
            
            return file_unique_bytes, self.unique_bytes_transferred, self.total_requested_size, len(self.requested_files)

    def run(self):
        try:
            try:
                self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), DBIRequestHandler)
                # Inject the map into server instance instead of raw list
                self.httpd.file_map = self.file_map
                self.httpd.signal_emitter = self
            except OSError as e:
                self.log_message.emit('error', f'Could not bind to port {self.port}: {e}')
                return
            
            self.is_running = True
            local_ip = self.get_local_ip()
            self.server_started.emit(local_ip, self.port)
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