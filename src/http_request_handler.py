"""
Request Handler for DBI Backend's HTTP Server
"""

import os
import html
import sys
import socket
import urllib.parse
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any

from .utility_functions import format_size

class DBIRequestHandler(BaseHTTPRequestHandler):
    """
    Custom Request Handler for DBI.
    Serves a virtual directory containing selected files.
    Compatible with DBI's 'ApacheHTTP' network source.
    """
    HTTP_CHUNK_SIZE = 4 * 1024 * 1024

    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
        except OSError:
            pass
    
    def log_message(self, format, *args):
        """Suppress default logging to stderr"""
        pass

    def do_GET(self):
        """Handle GET requests"""
        handler_thread = self.server.signal_emitter
        if hasattr(handler_thread, 'record_activity'):
            handler_thread.record_activity()
        
        # Decode path
        path = urllib.parse.unquote(self.path.split('?')[0])
        clean_path = path.strip('/')
        
        # Determine if client is DBI
        user_agent = self.headers.get('User-Agent', '')
        is_dbi = False
        if user_agent:
            ua_lower = user_agent.lower()
            if 'dbi' in ua_lower or 'libcurl' in ua_lower or 'switch' in ua_lower:
                is_dbi = True
            elif any(b in ua_lower for b in ['mozilla', 'chrome', 'safari', 'firefox', 'edge', 'opera']):
                is_dbi = False
            else:
                is_dbi = True
        else:
            is_dbi = True
            
        try:
            if self.path.endswith('/') or path == '/index.html':
                self.send_directory_listing(clean_path, is_dbi=is_dbi)
                return
                
            disk_path, is_dir, orig_name = handler_thread.resolve_virtual_path(clean_path)
            if disk_path:
                if is_dir:
                    # Redirect to add trailing slash if it didn't have one
                    if not self.path.endswith('/'):
                        self.send_response(301)
                        self.send_header('Location', self.path + '/')
                        self.end_headers()
                    else:
                        self.send_directory_listing(clean_path, is_dbi=is_dbi)
                else:
                    # If DBI, verify compatible extension
                    if is_dbi and disk_path.suffix.lower() not in {'.nsp', '.nsz', '.xci', '.xcz'}:
                        self.send_error(404, "File not found")
                        return
                    self.send_file_content(orig_name, disk_path, handler_thread)
            else:
                self.send_error(404, "File not found")
        except Exception as e:
            print(f"Server Error: {e}")
            try:
                self.send_error(500, f"Internal Server Error: {e}")
            except:
                pass

    def send_directory_listing(self, clean_path: str, is_dbi: bool):
        """
        Generate Apache-style HTML directory listing.
        """
        enc = sys.getfilesystemencoding()
        title = "DBI Repository"
        handler_thread = self.server.signal_emitter
        
        r = []
        r.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">')
        r.append(f'<html><head><meta http-equiv="Content-Type" content="text/html; charset={enc}"><title>{title}</title></head>')
        r.append(f'<body><h1>Index of /{html.escape(clean_path)}</h1>')
        r.append('<hr>')
        r.append('<pre>')
        
        # Parent directory link
        if clean_path:
            r.append('<a href="../">../</a>')
            
        supported = {'.nsp', '.nsz', '.xci', '.xcz'}
        
        if not clean_path:
            # Root level: show items in self.server.file_map
            for safe_name in sorted(self.server.file_map.keys()):
                entry = self.server.file_map[safe_name]
                path = entry['path']
                try:
                    is_dir = path.is_dir()
                    # If DBI, skip non-compatible files
                    if is_dbi and not is_dir and path.suffix.lower() not in supported:
                        continue
                        
                    link = urllib.parse.quote(safe_name) + ('/' if is_dir else '')
                    display_name = html.escape(safe_name) + ('/' if is_dir else '')
                    if is_dir:
                        try:
                            size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
                        except Exception:
                            size = 0
                    else:
                        size = path.stat().st_size
                    r.append(f'<a href="{link}">{display_name}</a>{" " * max(1, 50 - len(display_name))} {format_size(size)}')
                except Exception:
                    pass
        else:
            # Subdirectory level: resolve and show actual files on disk
            disk_path, is_dir, _ = handler_thread.resolve_virtual_path(clean_path)
            if disk_path and is_dir:
                try:
                    for item in sorted(disk_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                        name = item.name
                        is_item_dir = item.is_dir()
                        # If DBI, skip non-compatible files
                        if is_dbi and not is_item_dir and item.suffix.lower() not in supported:
                            continue
                            
                        try:
                            if is_item_dir:
                                size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                            else:
                                size = item.stat().st_size
                        except Exception:
                            size = 0
                        link = urllib.parse.quote(name) + ('/' if is_item_dir else '')
                        display_name = html.escape(name) + ('/' if is_item_dir else '')
                        r.append(f'<a href="{link}">{display_name}</a>{" " * max(1, 50 - len(display_name))} {format_size(size)}')
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

        is_metadata = handler_thread.begin_file_transfer(
            original_filename, file_size, start, content_length, "HTTP"
        )

        try:
            with open(file_path, 'rb') as f:
                f.seek(start)
                bytes_to_send = content_length
                chunk_size = self.HTTP_CHUNK_SIZE
                
                bytes_sent_this_session = 0
                bytes_since_last_log = 0
                log_threshold = 10 * 1024 * 1024  # Log every 10 MB
                
                start_time = time.time()
                last_emit_time = start_time
                
                while bytes_to_send > 0:
                    read_size = min(chunk_size, bytes_to_send)
                    sent = self._send_file_chunk(f, start + bytes_sent_this_session, read_size)
                    if sent <= 0:
                        break
                    
                    bytes_to_send -= sent
                    bytes_sent_this_session += sent
                    bytes_since_last_log += sent
                    
                    # LOGGING CHUNKS (Activity Log)
                    if bytes_since_last_log >= log_threshold:
                        mb_sent = bytes_sent_this_session / (1024 * 1024)
                        handler_thread.log_message.emit('debug', f"Sending {original_filename}: {mb_sent:.1f} MB session...")
                        bytes_since_last_log = 0

                    # Calculate speed and emit progress periodically (Throttled to 0.5s for speed)
                    current_time = time.time()
                    if current_time - last_emit_time > 0.5:
                        if not is_metadata:
                            handler_thread.emit_transfer_progress(
                                original_filename,
                                file_size,
                                start,
                                bytes_sent_this_session,
                                start_time,
                            )
                        last_emit_time = current_time

                # === Final Success Check ===
                handler_thread.finish_file_transfer(
                    original_filename,
                    file_size,
                    start,
                    bytes_sent_this_session,
                    start_time,
                    "HTTP",
                    is_metadata=is_metadata,
                )

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            handler_thread.log_message.emit('error', f"Error serving {original_filename}: {e}")

    def _send_file_chunk(self, file_obj, offset: int, count: int) -> int:
        """Send a slice of a file through the raw socket when available."""
        if hasattr(self.connection, 'sendfile'):
            self.wfile.flush()
            sent = self.connection.sendfile(file_obj, offset=offset, count=count)
            return count if sent is None else sent

        file_obj.seek(offset)
        buf = file_obj.read(count)
        if not buf:
            return 0
        self.wfile.write(buf)
        return len(buf)
