"""
Server Operations for DBI Backend
"""
from datetime import datetime
from pathlib import Path
from typing import Dict

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QFormLayout, QLabel, QSpinBox, QDialogButtonBox, QApplication, QCheckBox

from .usb_handler import USBHandler, ConnectionStatus
from .http_handler import HTTPHandler
from .utility_functions import format_size, format_time


class ServerManager:
    """Manages starting, stopping, and handling events for USB and HTTP servers."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.usb_handler = None
        self.http_handler = None
        
        self.transfer_stats = {
            'total_files': 0, 'completed_files': 0, 'skipped_files': 0, 'start_time': None
        }
        self.completed_files_set = set()
        self.current_processing_file = None
        self.reconnect_timer = QTimer()

    def toggle_server(self):
        # FIX: Replaced mode_combo with mode_switch
        # Unchecked = USB (False), Checked = HTTP (True)
        is_http = self.main_window.mode_switch.isChecked()
        is_usb = not is_http
        
        is_running = (self.usb_handler and self.usb_handler.is_running) or \
                     (self.http_handler and self.http_handler.is_running)

        if not is_running:
            if is_usb:
                self.start_usb_server()
            else:
                self.start_http_server()
        else:
            if QMessageBox.question(self.main_window, 'Stop Server', 
                'Stop the current server?') == QMessageBox.StandardButton.Yes:
                if self.usb_handler:
                    self.stop_usb_server()
                elif self.http_handler:
                    self.stop_http_server()

    def get_checked_files(self) -> Dict[str, Path]:
        checked_files = {}
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            widget = self.main_window.file_tree.itemWidget(item, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    filename = item.text(1)
                    if filename in self.main_window.file_manager.file_list:
                        checked_files[filename] = self.main_window.file_manager.file_list[filename]
        return checked_files

    def _reset_ui_for_start(self):
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear()
        self.current_processing_file = None
        self.main_window.progress_delegate.clear_all()
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
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
        self.usb_handler.start()
        self.main_window.setWindowTitle(f"DBI Backend Qt v2.3.14 | USB Mode Active")
        self._set_server_ui_state(True)
        self.transfer_stats['start_time'] = datetime.now()
        self.main_window.overall_label.setText(f'0 / {len(checked_files)} files')

    def stop_usb_server(self):
        if self.usb_handler:
            self.usb_handler.stop()
            self.usb_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()
        self.main_window.current_progress.setValue(0)
        self.main_window.overall_progress.setValue(0)
        if self.main_window.taskbar_manager: self.main_window.taskbar_manager.hide_progress()
        self.main_window.setWindowTitle("DBI Backend Qt v2.3.14")
        self.main_window.log('info', 'USB Server stopped')
        self.main_window.current_file_label.setText('Server stopped')

    def start_http_server(self):
        checked_files = self.get_checked_files()
        if not checked_files:
            self.main_window.log('warning', 'No files selected!')
            return

        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Start HTTP Server")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        ip_label = QLabel(HTTPHandler.get_local_ip())
        form.addRow("Your IP:", ip_label)
        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        port_spin.setValue(self.main_window.config.get('http_port', 8080))
        form.addRow("Port:", port_spin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
            
        selected_port = port_spin.value()
        self.main_window.config.set('http_port', selected_port)
        self.main_window.config.save()

        self._reset_ui_for_start()
        self.transfer_stats['total_files'] = len(checked_files)
        self.main_window.file_manager.dim_unchecked_items()
        
        tree = self.main_window.file_tree
        tree.sortItems(3, tree.header().sortIndicatorOrder())

        if self.main_window.taskbar_manager:
            self.main_window.taskbar_manager.show_progress()
            self.main_window.taskbar_manager.set_progress_value(0)
            
        self.transfer_stats['start_time'] = datetime.now()

        self.http_handler = HTTPHandler(checked_files, port=selected_port)
        self.http_handler.log_message.connect(self.main_window.log)
        self.http_handler.server_started.connect(self.on_http_server_started)
        self.http_handler.server_stopped.connect(self.on_http_server_stopped)
        self.http_handler.progress_updated.connect(self.on_progress_updated)
        self.http_handler.file_progress.connect(self.on_file_progress)
        self.http_handler.transfer_complete.connect(self.on_transfer_complete)
        
        self.http_handler.start()
        self.main_window.setWindowTitle(f"DBI Backend Qt v2.3.14 | HTTP Server: http://{HTTPHandler.get_local_ip()}:{selected_port}/")
        self._set_server_ui_state(True)

    def stop_http_server(self):
        if self.http_handler:
            self.http_handler.stop()
            self.http_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()
        self.main_window.current_progress.setValue(0)
        self.main_window.overall_progress.setValue(0)
        if self.main_window.taskbar_manager: self.main_window.taskbar_manager.hide_progress()

    def on_progress_updated(self, filename, transferred, speed, total_req_size, num_files, cur_bytes, cur_size, _unused):
        self.main_window.current_file_label.setText(filename)
        
        if self.current_processing_file and self.current_processing_file != filename:
            status = self.main_window.file_manager.get_file_status_code(self.current_processing_file)
            if status != 2: self.main_window.file_manager.update_file_status(self.current_processing_file, 'skipped')
        
        if self.current_processing_file != filename:
            self.current_processing_file = filename
            self.main_window.file_manager.update_file_status(filename, 'process')

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
            elapsed = (datetime.now() - self.transfer_stats['start_time']).seconds
            self.main_window.session_time_label.setText(f"Time: {format_time(elapsed)}")

        if completed < total_files:
            if speed > 0 and total_req_size > transferred:
                remaining_bytes = total_req_size - transferred
                sec = remaining_bytes / (speed * 1024 * 1024)
                self.main_window.eta_label.setText(f'ETA: {format_time(int(sec))}')

    def on_file_progress(self, filename, progress):
        self.main_window.progress_delegate.set_progress(filename, progress)
        self.main_window.file_tree.viewport().update()

    def on_transfer_complete(self, filename):
        if filename not in self.completed_files_set:
            self.completed_files_set.add(filename)
            self.transfer_stats['completed_files'] += 1
            self.main_window.file_manager.update_file_status(filename, 'done')
            self.main_window.progress_delegate.set_progress(filename, 100)
            for i in range(self.main_window.file_tree.topLevelItemCount()):
                item = self.main_window.file_tree.topLevelItem(i)
                if item.text(1) == filename:
                    w = self.main_window.file_tree.itemWidget(item, 0)
                    if w:
                        cb = w.findChild(QCheckBox)
                        if cb: cb.setChecked(False)
                    break
            self.main_window.on_item_checked()
            
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
        self.transfer_stats['skipped_files'] += 1
        self.main_window.file_manager.update_file_status(filename, 'failed')
        self.main_window.progress_delegate.mark_skipped(filename)
        self.main_window.log('warning', f'Skipped: {filename}')

    def on_transfer_reset(self):
        self.main_window.log('info', 'Switch reset sequence.')
        self.main_window.file_manager.handle_server_stop() # Reset visual styles
        self.main_window.file_manager.handle_server_start() # Re-dim unchecked
        self.main_window.on_item_checked()

    def on_installation_begun(self, requested_filenames):
        self.main_window.file_manager.handle_installation_start(requested_filenames)

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
            elapsed = (datetime.now() - self.transfer_stats['start_time']).seconds
            time_taken = format_time(elapsed)

        msg = (f"Session Complete!\n\nInstalled: {success}\nSkipped: {skipped}\nTime: {time_taken}")
        QMessageBox.information(self.main_window, "Complete", msg)
        
        if self.usb_handler: self.usb_handler = None
        if self.http_handler: self.http_handler = None
        
        self._set_server_ui_state(False)
        self.main_window.file_manager.handle_server_stop()
        self.main_window.current_progress.setValue(0)
        self.main_window.overall_progress.setValue(0)
        self.main_window.current_file_label.setText("No transfer in progress")
        self.main_window.overall_label.setText("0 / 0 files")

    # (Unchanged stubs)
    def on_http_server_started(self, ip, port): pass
    def on_http_server_stopped(self): pass

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
            
            # --- FIX: Check toggle state instead of combo text ---
            is_http = self.main_window.mode_switch.isChecked()
            
            if is_http:
                btn.setStyleSheet(self.main_window._get_btn_style("#2196F3", "#1976D2"))
                self.main_window.server_label.setText('Start HTTP')
            else:
                btn.setStyleSheet(self.main_window._get_btn_style("#4CAF50", "#45a049"))
                self.main_window.server_label.setText('Start USB')
                
            self.main_window.mode_switch.setEnabled(True)
            self.main_window.add_files_btn.setEnabled(True)
            self.main_window.clear_list_btn.setEnabled(True)

    def check_connection(self):
        # FIX: Check toggle state instead of combo text
        is_usb = not self.main_window.mode_switch.isChecked()
        if is_usb:
            if self.usb_handler is None and self.main_window.file_tree.topLevelItemCount() > 0:
                 self.main_window.start_server_btn.setEnabled(True)
    
    def on_connection_changed(self, status):
        if status == ConnectionStatus.CONNECTED: self.main_window.connection_status.setText('🟢 Connected')
        elif status == ConnectionStatus.CONNECTING: self.main_window.connection_status.setText('🟡 Connecting...')
        else:
            self.main_window.connection_status.setText('🔴 Not connected')
            if self.usb_handler and not self.usb_handler.is_running: self._set_server_ui_state(False)