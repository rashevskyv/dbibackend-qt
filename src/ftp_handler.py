"""
FTP Handler for DBI Backend.
Provides a small read-only FTP server over the selected file list.
"""

import os
import socket
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from . import dbi_protocol
from .network_transfer_handler import NetworkTransferHandler


class FTPControlSession:
    """One FTP control connection."""

    CHUNK_SIZE = 4 * 1024 * 1024

    def __init__(self, server: "FTPHandler", conn: socket.socket, addr):
        self.server = server
        self.conn = conn
        self.addr = addr
        self.buffer = b""
        self.cwd = "/"
        self.rest_offset = 0
        self.passive_sock: Optional[socket.socket] = None
        self.active_addr = None
        self.username = ""
        self.password = ""
        self.is_dbi = False

    def run(self):
        self.conn.settimeout(60)
        self._send_response(220, "DBI Backend Qt FTP ready")
        try:
            while self.server.is_running:
                line = self._readline()
                if line is None:
                    break
                if not line:
                    continue
                if not self._handle_command(line):
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            self._close_passive_socket()
            try:
                self.conn.close()
            except OSError:
                pass

    def _readline(self) -> Optional[str]:
        while b"\n" not in self.buffer:
            data = self.conn.recv(4096)
            if not data:
                return None
            self.buffer += data
        raw, self.buffer = self.buffer.split(b"\n", 1)
        return raw.rstrip(b"\r").decode("utf-8", "replace").strip()

    def _send_response(self, code: int, message: str):
        self.conn.sendall(f"{code} {message}\r\n".encode("utf-8"))

    def _check_is_dbi(self, username: str, password: str) -> bool:
        u = username.lower()
        p = password.lower()
        if 'dbi' in u or 'switch' in u or 'dbi' in p or 'switch' in p or 'curl' in p:
            return True
        return False

    def _normalize_ftp_path(self, arg: str) -> str:
        if arg.startswith("/"):
            path = arg
        else:
            path = os.path.join(self.cwd, arg)
            
        parts = []
        for part in path.split("/"):
            if part == "" or part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def _handle_command(self, line: str) -> bool:
        parts = line.split(" ", 1)
        command = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "USER":
            self.username = arg
            self._send_response(331, "User name okay, need password")
        elif command == "PASS":
            self.password = arg
            self.is_dbi = self._check_is_dbi(self.username, self.password)
            self._send_response(230, "Login successful")
        elif command == "SYST":
            self._send_response(215, "UNIX Type: L8")
        elif command == "FEAT":
            self.conn.sendall(
                b"211-Features\r\n"
                b" UTF8\r\n"
                b" MLST type*;size*;modify*;\r\n"
                b" REST STREAM\r\n"
                b"211 End\r\n"
            )
        elif command == "OPTS":
            self._send_response(200, "OK")
        elif command == "PWD":
            self._send_response(257, f'"{self.cwd}"')
        elif command in {"CWD", "CDUP"}:
            if command == "CDUP":
                if self.cwd == "/":
                    self._send_response(250, "Directory changed")
                else:
                    parent = os.path.dirname(self.cwd.rstrip("/"))
                    self.cwd = parent if parent else "/"
                    self._send_response(250, "Directory changed")
            elif arg in {"", "/", "."}:
                self.cwd = "/"
                self._send_response(250, "Directory changed")
            else:
                target_cwd = self._normalize_ftp_path(arg)
                disk_path, is_dir, _ = self.server.resolve_virtual_path(target_cwd.strip("/"))
                if disk_path and is_dir:
                    self.cwd = target_cwd
                    self._send_response(250, "Directory changed")
                else:
                    self._send_response(550, "No such directory")
        elif command == "TYPE":
            self._send_response(200, "Type set")
        elif command in {"PASV", "EPSV"}:
            self._enter_passive_mode(command)
        elif command == "PORT":
            self._enter_active_mode(arg)
        elif command == "EPRT":
            self._enter_extended_active_mode(arg)
        elif command == "LIST":
            self._send_listing(kind="list")
        elif command == "NLST":
            self._send_listing(kind="nlst")
        elif command == "MLSD":
            self._send_listing(kind="mlsd")
        elif command == "SIZE":
            self._send_size(arg)
        elif command == "MDTM":
            self._send_mdtm(arg)
        elif command == "REST":
            self._set_restart_offset(arg)
        elif command == "RETR":
            self._retrieve_file(arg)
        elif command == "NOOP":
            self._send_response(200, "OK")
        elif command == "QUIT":
            self._send_response(221, "Goodbye")
            return False
        else:
            self._send_response(502, "Command not implemented")
        return True

    def _enter_passive_mode(self, command: str):
        self._close_passive_socket()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        sock.settimeout(20)
        self.passive_sock = sock
        self.active_addr = None
        port = sock.getsockname()[1]

        if command == "EPSV":
            self._send_response(229, f"Entering Extended Passive Mode (|||{port}|)")
            return

        ip = self.server.display_ip.replace(".", ",")
        self._send_response(227, f"Entering Passive Mode ({ip},{port // 256},{port % 256})")

    def _enter_active_mode(self, arg: str):
        parts = arg.split(",")
        if len(parts) != 6:
            self._send_response(501, "Invalid PORT command")
            return
        try:
            ip = ".".join(parts[:4])
            port = int(parts[4]) * 256 + int(parts[5])
        except ValueError:
            self._send_response(501, "Invalid PORT command")
            return
        self._close_passive_socket()
        self.active_addr = (ip, port)
        self._send_response(200, "PORT command successful")

    def _enter_extended_active_mode(self, arg: str):
        try:
            delimiter = arg[0]
            _empty, _af, ip, port, _tail = arg.split(delimiter)
            port_num = int(port)
        except (IndexError, ValueError):
            self._send_response(501, "Invalid EPRT command")
            return
        self._close_passive_socket()
        self.active_addr = (ip, port_num)
        self._send_response(200, "EPRT command successful")

    def _open_data_connection(self) -> Optional[socket.socket]:
        if self.passive_sock is None and self.active_addr is None:
            self._send_response(425, "Use PASV first")
            return None
        if self.active_addr is not None:
            try:
                data_conn = socket.create_connection(self.active_addr, timeout=20)
                data_conn.settimeout(60)
                return data_conn
            except OSError:
                self._send_response(425, "Could not open active data connection")
                return None
            finally:
                self.active_addr = None

        try:
            data_conn, _ = self.passive_sock.accept()
            data_conn.settimeout(60)
            try:
                data_conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
            except OSError:
                pass
            return data_conn
        except OSError:
            self._send_response(425, "Could not open data connection")
            return None
        finally:
            self._close_passive_socket()

    def _close_passive_socket(self):
        if self.passive_sock is not None:
            try:
                self.passive_sock.close()
            except OSError:
                pass
            self.passive_sock = None

    def _send_listing(self, kind: str):
        self._send_response(150, "Opening data connection")
        data_conn = self._open_data_connection()
        if data_conn is None:
            return

        try:
            payload = self._build_listing(kind).encode("utf-8")
            data_conn.sendall(payload)
            self._send_response(226, "Transfer complete")
        except OSError:
            self._send_response(426, "Transfer aborted")
        finally:
            try:
                data_conn.close()
            except OSError:
                pass

    def _build_listing(self, kind: str) -> str:
        rows = []
        supported = {'.nsp', '.nsz', '.xci', '.xcz'}
        
        clean_cwd = self.cwd.strip("/")
        if not clean_cwd:
            # Root level: show items in self.server.file_map
            for safe_name in sorted(self.server.file_map.keys()):
                entry = self.server.file_map[safe_name]
                path = entry["path"]
                try:
                    is_dir = path.is_dir()
                    # If DBI, skip non-compatible files
                    if self.is_dbi and not is_dir and path.suffix.lower() not in supported:
                        continue
                        
                    stat = path.stat()
                    if is_dir:
                        try:
                            size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
                        except Exception:
                            size = 0
                    else:
                        size = stat.st_size
                except OSError:
                    continue
                    
                if kind == "nlst":
                    rows.append(safe_name)
                elif kind == "mlsd":
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d%H%M%S")
                    t_str = "dir" if is_dir else "file"
                    rows.append(f"type={t_str};size={size};modify={modified}; {safe_name}")
                else:
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d %H:%M")
                    d_char = "d" if is_dir else "-"
                    rows.append(f"{d_char}rw-r--r-- 1 owner group {size:>12} {modified} {safe_name}")
        else:
            # Subdirectory level: resolve and show actual files on disk
            disk_path, is_dir, _ = self.server.resolve_virtual_path(clean_cwd)
            if disk_path and is_dir:
                try:
                    for item in sorted(disk_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                        name = item.name
                        is_item_dir = item.is_dir()
                        # If DBI, skip non-compatible files
                        if self.is_dbi and not is_item_dir and item.suffix.lower() not in supported:
                            continue
                            
                        try:
                            stat = item.stat()
                            if is_item_dir:
                                size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                            else:
                                size = stat.st_size
                        except OSError:
                            continue
                            
                        if kind == "nlst":
                            rows.append(name)
                        elif kind == "mlsd":
                            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d%H%M%S")
                            t_str = "dir" if is_item_dir else "file"
                            rows.append(f"type={t_str};size={size};modify={modified}; {name}")
                        else:
                            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d %H:%M")
                            d_char = "d" if is_item_dir else "-"
                            rows.append(f"{d_char}rw-r--r-- 1 owner group {size:>12} {modified} {name}")
                except Exception:
                    pass
        return "\r\n".join(rows) + "\r\n"

    def _send_size(self, arg: str):
        entry = self._find_entry(arg)
        if entry is None:
            self._send_response(550, "File not found")
            return
        self._send_response(213, str(entry["path"].stat().st_size))

    def _send_mdtm(self, arg: str):
        entry = self._find_entry(arg)
        if entry is None:
            self._send_response(550, "File not found")
            return
        modified = datetime.fromtimestamp(entry["path"].stat().st_mtime).strftime("%Y%m%d%H%M%S")
        self._send_response(213, modified)

    def _set_restart_offset(self, arg: str):
        try:
            self.rest_offset = max(0, int(arg))
        except ValueError:
            self.rest_offset = 0
        self._send_response(350, f"Restarting at {self.rest_offset}")

    def _retrieve_file(self, arg: str):
        entry = self._find_entry(arg)
        if entry is None:
            self._send_response(550, "File not found")
            return

        file_path = entry["path"]
        original_name = entry["orig_name"]
        file_size = file_path.stat().st_size
        start = min(self.rest_offset, file_size)
        self.rest_offset = 0

        is_metadata = self.server.begin_file_transfer(
            original_name, file_size, start, file_size - start, "FTP"
        )
        self._send_response(150, "Opening binary mode data connection")
        data_conn = self._open_data_connection()
        if data_conn is None:
            return

        bytes_sent = 0
        start_time = time.time()
        last_emit_time = start_time

        try:
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = file_size - start
                while remaining > 0 and self.server.is_running:
                    read_size = min(self.CHUNK_SIZE, remaining)
                    sent = self._send_file_chunk(data_conn, f, start + bytes_sent, read_size)
                    if sent <= 0:
                        break

                    bytes_sent += sent
                    remaining -= sent

                    current_time = time.time()
                    if current_time - last_emit_time > 0.5:
                        if not is_metadata:
                            self.server.emit_transfer_progress(
                                original_name,
                                file_size,
                                start,
                                bytes_sent,
                                start_time,
                            )
                        last_emit_time = current_time

                self.server.finish_file_transfer(
                    original_name,
                    file_size,
                    start,
                    bytes_sent,
                    start_time,
                    "FTP",
                    is_metadata=is_metadata,
                )
                data_conn.close()
                self._send_response(226, "Transfer complete")
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            if 0 < bytes_sent < dbi_protocol.METADATA_THRESHOLD:
                self.server.finish_file_transfer(
                    original_name,
                    file_size,
                    start,
                    bytes_sent,
                    start_time,
                    "FTP",
                    is_metadata=True,
                )
            self.server.log_message.emit("warning", f"FTP transfer interrupted: {e}")
            try:
                self._send_response(426, "Transfer aborted")
            except OSError:
                pass
        finally:
            try:
                data_conn.close()
            except OSError:
                pass

    def _send_file_chunk(self, data_conn: socket.socket, file_obj, offset: int, count: int) -> int:
        if hasattr(data_conn, "sendfile"):
            sent = data_conn.sendfile(file_obj, offset=offset, count=count)
            return count if sent is None else sent

        file_obj.seek(offset)
        chunk = file_obj.read(count)
        if not chunk:
            return 0
        data_conn.sendall(chunk)
        return len(chunk)

    def _find_entry(self, arg: str) -> Optional[Dict[str, Any]]:
        path_str = urllib.parse.unquote(arg).replace("\\", "/")
        normalized_path = self._normalize_ftp_path(path_str).strip("/")
        
        disk_path, is_dir, orig_name = self.server.resolve_virtual_path(normalized_path)
        if disk_path and not is_dir:
            if self.is_dbi and disk_path.suffix.lower() not in {'.nsp', '.nsz', '.xci', '.xcz'}:
                return None
            return {
                "path": disk_path,
                "orig_name": orig_name
            }
        return None


class FTPHandler(NetworkTransferHandler):
    """Thread for running the FTP server."""

    def __init__(self, file_list: Dict[str, Path], port: int = 2121, display_ip: Optional[str] = None):
        super().__init__(file_list, port=port, display_ip=display_ip)
        self.is_running = False
        self.server_sock: Optional[socket.socket] = None
        self.sessions = []

    def run(self):
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind(("0.0.0.0", self.port))
            self.server_sock.listen(16)
            self.server_sock.settimeout(0.5)

            self.is_running = True
            self.server_started.emit(self.display_ip, self.port)

            while self.is_running:
                try:
                    conn, addr = self.server_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                session = FTPControlSession(self, conn, addr)
                thread = threading.Thread(target=session.run, daemon=True)
                self.sessions.append((session, thread))
                thread.start()
        except Exception as e:
            self.log_message.emit("error", f"FTP Server crashed: {e}")
        finally:
            self.is_running = False
            self._close_server_socket()

    def stop(self):
        self.is_running = False
        self._close_server_socket()
        for session, _thread in self.sessions:
            session._close_passive_socket()
            try:
                session.conn.close()
            except OSError:
                pass
        self.server_stopped.emit()
        self.wait()

    def _close_server_socket(self):
        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except OSError:
                pass
            self.server_sock = None
