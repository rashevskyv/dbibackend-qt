import socket
from http.server import HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Dict, Optional

from .http_request_handler import DBIRequestHandler
from .network_transfer_handler import NetworkTransferHandler

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
        except OSError:
            pass
        super().server_bind()

class HTTPHandler(NetworkTransferHandler):
    """Thread for running the HTTP Server"""

    def __init__(self, file_list: Dict[str, Path], port: int = 8080, display_ip: Optional[str] = None):
        super().__init__(file_list, port=port, display_ip=display_ip)
        self.httpd = None

    def run(self):
        try:
            self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), DBIRequestHandler)
            # Inject data into server instance so RequestHandler can access it
            self.httpd.file_map = self.file_map
            self.httpd.signal_emitter = self
            
            self.is_running = True
            self.server_started.emit(self.display_ip, self.port)
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
