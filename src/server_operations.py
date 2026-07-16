"""
Server Operations for DBI Backend
"""
from datetime import datetime
from pathlib import Path
from typing import Dict

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QFormLayout, QSpinBox, QDialogButtonBox, QComboBox

from . import __version__
from .usb_handler import USBHandler, ConnectionStatus
from .http_handler import HTTPHandler
from .ftp_handler import FTPHandler
from .network_transfer_handler import NetworkTransferHandler
from .utility_functions import format_size, format_time


class ServerManager:
    """Manages starting, stopping, and handling events for USB, HTTP, and FTP servers."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.usb_handler = None
        self.http_handler = None
        self.ftp_handler = None
        
        self.transfer_stats = {
            'total_files': 0, 'completed_files': 0, 'skipped_files': 0, 'start_time': None
        }
        self.completed_files_set = set()
        self.skipped_files_set = set()
        self.current_processing_file = None
        self.reconnect_timer = QTimer()

    def toggle_server(self):
        mode = self.main_window.mode_switch.mode()
        
        is_running = (self.usb_handler and self.usb_handler.is_running) or \
                     (self.http_handler and self.http_handler.is_running) or \
                     (self.ftp_handler and self.ftp_handler.is_running)

        if not is_running:
            if mode == 'usb':
                self.start_usb_server()
            elif mode == 'ftp':
                self.start_ftp_server()
            else:
                self.start_http_server()
        else:
            if QMessageBox.question(self.main_window, 'Stop Server', 
                'Stop the current server?') == QMessageBox.StandardButton.Yes:
                if self.usb_handler:
                    self.stop_usb_server()
                elif self.http_handler:
                    self.stop_http_server()
                elif self.ftp_handler:
                    self.stop_ftp_server()

    def _active_network_handler(self):
        return self.http_handler or self.ftp_handler

    def get_checked_files(self) -> Dict[str, Path]:
        file_manager = self.main_window.file_manager
        checked_files: Dict[str, Path] = {}
        for item in file_manager.iter_checked_items():
            filename = item.text(1)
            path = file_manager.file_list.get(filename)
            if path is not None:
                checked_files[filename] = path
        return checked_files

    def _reset_ui_for_start(self):
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear()
        self.skipped_files_set.clear()
        self.current_processing_file = None
        self.main_window.progress_delegate.clear_all()
        for item in self.main_window.file_manager.iter_items():
            self.main_window.file_manager.update_file_status(item.text(1), '')
        self.main_window.current_progress.setValue(0)
        self.main_window.overall_progress.setValue(0)
        self.main_window.speed_label.setText('Speed: 0 MB/s')
        self.main_window.eta_label.setText('ETA: --:--:--')
        self.main_window.current_file_label.setText('Waiting for Switch...')

    def start_usb_server(self):
        checked_files = self.get_checked_files()
        if not checked_files:
            self.main_window.log('warning', 'No files selected!')
            return

        self._reset_ui_for_start()
        self.transfer_stats['total_files'] = len(checked_files)
        self.main_window.file_manager.dim_unchecked_items()
        
        tree = self.main_window.file_tree
        tree.sortItems(3, tree.header().sortIndicatorOrder())
        self.main_window.log('info', f'Starting USB server with {len(checked_files)} files')
        self.main_window.file_manager.handle_server_start()
        
        if self.main_window.taskbar_manager:
            self.main_window.taskbar_manager.show_progress()
            self.main_window.taskbar_manager.set_progress_value(0)

        self.usb_handler = USBHandler(checked_files)
        self.usb_handler.connection_changed.connect(self.on_connection_changed)
        self.usb_handler.log_message.connect(self.main_window.log)
        self.usb_handler.progress_updated.connect(self.on_progress_updated)
        self.usb_handler.file_progress.connect(self.on_file_progress)
        self.usb_handler.transfer_complete.connect(self.on_transfer_complete)
        self.usb_handler.file_skipped.connect(self.on_file_skipped)
        self.usb_handler.transfer_reset.connect(self.on_transfer_reset)
        self.usb_handler.all_transfers_complete.connect(self.on_all_transfers_complete)
        self.usb_handler.installation_begun.connect(self.on_installation_begun)
        self.usb_handler.finished.connect(self.on_usb_server_stopped)
        self.usb_handler.start()
        self.main_window.setWindowTitle(f"DBI Backend Qt v{__version__} | USB Mode Active")
        self._set_server_ui_state(True)
        self.transfer_stats['start_time'] = datetime.now()
        self.main_window.overall_label.setText(f'0 / {len(checked_files)} files')

    def stop_usb_server(self):
        if self.usb_handler:
            self.usb_handler.stop()

    def _prompt_network_settings(self, title: str, ip_key: str, port_key: str, default_port: int):
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        ip_combo = QComboBox()
        local_ips = NetworkTransferHandler.get_local_ips()
        ip_combo.addItems(local_ips)
        saved_ip = self.main_window.config.get(ip_key, '')
        if saved_ip in local_ips:
            ip_combo.setCurrentText(saved_ip)
        form.addRow("Switch URL IP:", ip_combo)

        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        port_spin.setValue(self.main_window.config.get(port_key, default_port))
        form.addRow("Port:", port_spin)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        selected_ip = ip_combo.currentText()
        selected_port = port_spin.value()
        self.main_window.config.set(ip_key, selected_ip)
        self.main_window.config.set(port_key, selected_port)
        self.main_window.config.save()
        return selected_ip, selected_port

    def _prepare_network_server_start(self, checked_files: Dict[str, Path]):
        self._reset_ui_for_start()
        self.transfer_stats['total_files'] = len(checked_files)
        self.main_window.file_manager.dim_unchecked_items()

        tree = self.main_window.file_tree
        tree.sortItems(3, tree.header().sortIndicatorOrder())

        if self.main_window.taskbar_manager:
            self.main_window.taskbar_manager.show_progress()
            self.main_window.taskbar_manager.set_progress_value(0)

        self.transfer_stats['start_time'] = datetime.now()
        self.main_window.overall_label.setText(f'0 / {len(checked_files)} files')

    def _connect_network_handler(self, handler, started_slot, stopped_slot):
        handler.log_message.connect(self.main_window.log)
        handler.server_started.connect(started_slot)
        handler.server_stopped.connect(stopped_slot)
        handler.progress_updated.connect(self.on_progress_updated)
        handler.file_progress.connect(self.on_file_progress)
        handler.transfer_complete.connect(self.on_transfer_complete)
        handler.file_skipped.connect(self.on_file_skipped)
        handler.all_transfers_complete.connect(self.on_all_transfers_complete)
        handler.finished.connect(stopped_slot)

    def _start_network_server(
        self,
        protocol: str,
        handler_cls,
        handler_attr: str,
        ip_key: str,
        port_key: str,
        default_port: int,
        started_slot,
        stopped_slot,
    ):
        checked_files = self.get_checked_files()
        if not checked_files:
            self.main_window.log('warning', 'No files selected!')
            return

        settings = self._prompt_network_settings(f"Start {protocol} Server", ip_key, port_key, default_port)
        if settings is None:
            return
        selected_ip, selected_port = settings

        self._prepare_network_server_start(checked_files)
        handler = handler_cls(checked_files, port=selected_port, display_ip=selected_ip)
        setattr(self, handler_attr, handler)
        self._connect_network_handler(handler, started_slot, stopped_slot)
        handler.start()
        protocol_lower = protocol.lower()
        self.main_window.setWindowTitle(
            f"DBI Backend Qt v{__version__} | {protocol} Server: {protocol_lower}://{selected_ip}:{selected_port}/"
        )
        self._set_server_ui_state(True)

    def start_http_server(self):
        self._start_network_server(
            "HTTP",
            HTTPHandler,
            "http_handler",
            "http_ip",
            "http_port",
            8080,
            self.on_http_server_started,
            self.on_http_server_stopped,
        )

    def stop_http_server(self):
        if self.http_handler:
            self.http_handler.stop()

    def start_ftp_server(self):
        self._start_network_server(
            "FTP",
            FTPHandler,
            "ftp_handler",
            "ftp_ip",
            "ftp_port",
            2121,
            self.on_ftp_server_started,
            self.on_ftp_server_stopped,
        )

    def stop_ftp_server(self):
        if self.ftp_handler:
            self.ftp_handler.stop()

    def on_progress_updated(self, filename, transferred, speed, total_req_size, num_files, cur_bytes, cur_size, _unused):
        self.main_window.current_file_label.setText(filename)
        
        if self.current_processing_file and self.current_processing_file != filename:
            status = self.main_window.file_manager.get_file_status_code(self.current_processing_file)
            if status != 2: # Not Completed
                self.main_window.file_manager.update_file_status(self.current_processing_file, 'skipped')
                if self.usb_handler:
                    self.usb_handler.progress_tracker.mark_file_skipped(self.current_processing_file)
                else:
                    network_handler = self._active_network_handler()
                    if network_handler:
                        network_handler.mark_file_skipped(self.current_processing_file)
                self.main_window.log('debug', f'Implicitly skipped: {self.current_processing_file}')
        
        if self.current_processing_file != filename:
            self.current_processing_file = filename
            self.main_window.file_manager.update_file_status(filename, 'process')
            self.main_window.file_tree.sortItems(3, self.main_window.file_tree.header().sortIndicatorOrder())

        if cur_size > 0:
            pct = int((cur_bytes / cur_size) * 100)
            self.main_window.current_progress.setFormat(f'{pct}% ({format_size(cur_bytes)} / {format_size(cur_size)})')
            self.main_window.current_progress.setValue(min(100, pct))
            if hasattr(self.main_window.current_progress, 'step_animation'):
                self.main_window.current_progress.step_animation()
        else:
            self.main_window.current_progress.setValue(0)
            self.main_window.current_progress.setFormat('Starting...')
        
        self.main_window.speed_label.setText(f'Speed: {speed:.1f} MB/s')
        
        completed = self.transfer_stats['completed_files'] + self.transfer_stats['skipped_files']
        total_files = self.transfer_stats['total_files']
        
        if total_req_size > 0:
            raw_pct = (transferred / total_req_size) * 100
            overall_pct = int(raw_pct)
            is_finished = (completed >= total_files and total_files > 0)
            
            if is_finished or raw_pct >= 99.9:
                overall_pct = 100
                self.main_window.eta_label.setText('ETA: Done')
            
            self.main_window.overall_progress.setValue(min(100, overall_pct))
            self.main_window.overall_progress.setFormat(f'{overall_pct}% ({format_size(transferred)} / {format_size(total_req_size)})')
            
            if self.main_window.taskbar_manager:
                self.main_window.taskbar_manager.set_progress_value(min(100, overall_pct))
        
        display_idx = min(completed + 1, total_files) if total_files > 0 else 0
        if completed >= total_files: display_idx = total_files
        self.main_window.overall_label.setText(f'{display_idx} / {total_files} files')

        if self.transfer_stats['start_time']:
            elapsed = int((datetime.now() - self.transfer_stats['start_time']).total_seconds())
            self.main_window.session_time_label.setText(f"Time: {format_time(elapsed)}")

        if completed < total_files:
            if speed > 0 and total_req_size > transferred:
                remaining_bytes = total_req_size - transferred
                sec = remaining_bytes / (speed * 1024 * 1024)
                self.main_window.eta_label.setText(f'ETA: {format_time(int(sec))}')

    def on_file_progress(self, filename, progress):
        self.main_window.progress_delegate.set_progress(filename, progress)
        # Repaint only the affected row instead of the entire viewport. With
        # high-throughput transfers progress signals fire up to 20x/sec; a
        # full viewport repaint forces the delegate to walk every visible row.
        item = self.main_window.file_manager.item_map.get(filename)
        if item is not None:
            rect = self.main_window.file_tree.visualItemRect(item)
            if rect.isValid() and not rect.isNull():
                self.main_window.file_tree.viewport().update(rect)
            else:
                self.main_window.file_tree.viewport().update()
        else:
            self.main_window.file_tree.viewport().update()

    def on_transfer_complete(self, filename):
        if filename not in self.completed_files_set:
            self.completed_files_set.add(filename)
            self.transfer_stats['completed_files'] += 1
            self.main_window.file_manager.update_file_status(filename, 'done')
            self.main_window.file_tree.sortItems(3, self.main_window.file_tree.header().sortIndicatorOrder())
            self.main_window.progress_delegate.set_progress(filename, 100)
            item = self.main_window.file_manager.item_map.get(filename)
            if item is not None:
                self.main_window.file_manager.set_item_checked(item, False)
            self.main_window.on_item_checked()
            
            # Console logging
            from .utility_functions import format_size
            path = self.main_window.file_manager.file_list.get(filename)
            fsize = path.stat().st_size if path else 0
            prog_fmt = self.main_window.overall_progress.format()
            network_handler = self._active_network_handler()
            tracker = self.usb_handler.progress_tracker if self.usb_handler else (network_handler.progress_tracker if network_handler else None)
            new_target = format_size(tracker.total_requested_size) if tracker else "N/A"
            print(f"[PROGRESS] Completed: {filename} ({format_size(fsize)}) | Overall: {prog_fmt} / Target: {new_target}")

            total = self.transfer_stats['total_files']
            done = self.transfer_stats['completed_files'] + self.transfer_stats['skipped_files']
            if total > 0 and done >= total:
                self.main_window.overall_progress.setValue(100)
                current_text = self.main_window.overall_progress.text() 
                if "(" in current_text:
                    sizes_part = current_text.split("(", 1)[1]
                    self.main_window.overall_progress.setFormat(f"100% ({sizes_part}")
                else:
                    self.main_window.overall_progress.setFormat("100%")
                self.main_window.eta_label.setText('ETA: Done')
                if self.main_window.taskbar_manager:
                    self.main_window.taskbar_manager.set_progress_value(100)

    def on_file_skipped(self, filename, size):
        if filename in self.skipped_files_set:
            return

        if self.usb_handler:
            self.usb_handler.progress_tracker.mark_file_skipped(filename)
        else:
            network_handler = self._active_network_handler()
            # Network mark_file_skipped already emits file_skipped,
            # so we check if it's already in skipped_files to avoid recursion if called from there
            if network_handler and filename not in network_handler.progress_tracker.skipped_files:
                network_handler.mark_file_skipped(filename)
                return

        self.skipped_files_set.add(filename)
        self.transfer_stats['skipped_files'] += 1
        self.main_window.file_manager.update_file_status(filename, 'skipped') # Fixed from 'failed'
        self.main_window.progress_delegate.mark_skipped(filename)
        self.main_window.log('warning', f'Skipped: {filename}')
        
        # Console logging
        from .utility_functions import format_size
        prog_fmt = self.main_window.overall_progress.format()
        print(f"[PROGRESS] Skipped: {filename} ({format_size(size)}) | Total: {prog_fmt}")

    def on_transfer_reset(self):
        self.main_window.log('info', 'Switch reset sequence.')
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear()
        self.skipped_files_set.clear()
        self.current_processing_file = None
        if self.usb_handler:
            self.usb_handler.progress_tracker.reset()
        self.main_window.file_manager.handle_server_stop() # Reset visual styles
        self.main_window.file_manager.handle_server_start() # Re-dim unchecked
        self.main_window.on_item_checked()

    def on_installation_begun(self, requested_filenames):
        if not self.usb_handler:
            return
        from .utility_functions import format_size
        # Clean null terminators from incoming requested names
        requested_set = {n.rstrip('\x00') for n in requested_filenames}
        
        self.main_window.log('info', 'Switch initiated installation phase...')
        
        # Calculate size of requested files for logging
        req_total_size = 0
        for name in requested_set:
            path = self.main_window.file_manager.file_list.get(name)
            if path: req_total_size += path.stat().st_size
            
        print(f"[DEBUG] Installation Begun. Requested files by DBI: {len(requested_set)} files, Total: {format_size(req_total_size)}")
        
        self.main_window.file_manager.handle_installation_start(list(requested_set))
        
        if self.usb_handler:
            checked = self.get_checked_files()
            for filename in checked:
                if filename not in requested_set:
                    path = self.main_window.file_manager.file_list.get(filename)
                    size = path.stat().st_size if path else 0
                    print(f"[DEBUG] File NOT requested by DBI (skipping from progress): {filename} ({format_size(size)})")
                    self.on_file_skipped(filename, size)
                    
        self.main_window.log('info', f'Progress recalculated. New target: {format_size(self.usb_handler.progress_tracker.total_requested_size) if self.usb_handler else "N/A"}')

    def on_all_transfers_complete(self):
        self.main_window.log('success', 'All transfers complete!')
        self.main_window.current_progress.setValue(100)
        self.main_window.overall_progress.setValue(100)
        self.main_window.eta_label.setText('ETA: Done')
        self.main_window.current_file_label.setText('Done')
        
        if self.main_window.taskbar_manager: self.main_window.taskbar_manager.hide_progress()
        
        success = self.transfer_stats['completed_files']
        skipped = self.transfer_stats['skipped_files']
        time_taken = "00:00:00"
        if self.transfer_stats['start_time']:
            elapsed = int((datetime.now() - self.transfer_stats['start_time']).total_seconds())
            time_taken = format_time(elapsed)

        msg = (f"Session Complete!\n\nInstalled: {success}\nSkipped: {skipped}\nTime: {time_taken}")
        QMessageBox.information(self.main_window, "Complete", msg)
        
        if self.usb_handler: self.usb_handler = None
        if self.http_handler: self.http_handler = None
        if self.ftp_handler: self.ftp_handler = None
        
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()

    # (Unchanged stubs)
    def on_http_server_started(self, ip, port):
        self.main_window.log('info', f'HTTP Server started: http://{ip}:{port}/')

    def on_ftp_server_started(self, ip, port):
        self.main_window.log('info', f'FTP Server started: ftp://{ip}:{port}/')
    
    def on_http_server_stopped(self):
        if self.http_handler is None:
            return
        self.http_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()
        self.main_window.log('info', 'HTTP Server stopped')

    def on_ftp_server_stopped(self):
        if self.ftp_handler is None:
            return
        self.ftp_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()
        self.main_window.log('info', 'FTP Server stopped')

    def on_usb_server_stopped(self):
        if self.usb_handler is None:
            return
        self.usb_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()
        self.main_window.log('info', 'USB Server stopped')
        self.main_window.connection_status.setText('🔴 Not connected')

    def _set_server_ui_state(self, running: bool):
        btn = self.main_window.start_server_btn
        if running:
            btn.setText('⏹')
            btn.setStyleSheet('QPushButton { background-color: #f44336; color: white; font-size: 32px; } QPushButton:hover { background-color: #da190b; }')
            self.main_window.server_label.setText('Stop Server')
            self.main_window.mode_switch.setEnabled(False) 
            self.main_window.add_files_btn.setEnabled(False)
            self.main_window.clear_list_btn.setEnabled(False)
        else:
            btn.setText('▶')
            
            mode = self.main_window.mode_switch.mode()

            if mode == 'http':
                btn.setStyleSheet(self.main_window._get_btn_style("#2196F3", "#1976D2"))
                self.main_window.server_label.setText('Start HTTP')
            elif mode == 'ftp':
                btn.setStyleSheet(self.main_window._get_btn_style("#FFC107", "#FFB300"))
                self.main_window.server_label.setText('Start FTP')
            else:
                btn.setStyleSheet(self.main_window._get_btn_style("#4CAF50", "#45a049"))
                self.main_window.server_label.setText('Start USB')
                
            self.main_window.mode_switch.setEnabled(True)
            self.main_window.add_files_btn.setEnabled(True)
            self.main_window.clear_list_btn.setEnabled(True)

    def check_connection(self):
        if self.main_window.mode_switch.mode() == 'usb':
            if self.usb_handler is None and self.main_window.file_tree.topLevelItemCount() > 0:
                 self.main_window.start_server_btn.setEnabled(True)
    
    def on_connection_changed(self, status):
        if status == ConnectionStatus.CONNECTED: self.main_window.connection_status.setText('🟢 Connected')
        elif status == ConnectionStatus.CONNECTING: self.main_window.connection_status.setText('🟡 Connecting...')
        else:
            self.main_window.connection_status.setText('🔴 Not connected')
            if self.usb_handler and not self.usb_handler.is_running: self._set_server_ui_state(False)
