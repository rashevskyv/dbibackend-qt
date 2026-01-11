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
        mode = self.main_window.mode_combo.currentText()
        is_usb = "USB" in mode
        is_running = (self.usb_handler and self.usb_handler.is_running) or \
                     (self.http_handler and self.http_handler.is_running)

        if not is_running:
            if is_usb: self.start_usb_server()
            else: self.start_http_server()
        else:
            if QMessageBox.question(self.main_window, 'Stop Server', 
                'Stop the current server?') == QMessageBox.StandardButton.Yes:
                if is_usb: self.stop_usb_server()
                else: self.stop_http_server()

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
        self.main_window.file_manager.dim_unchecked_items()
        
        tree = self.main_window.file_tree
        tree.sortItems(3, tree.header().sortIndicatorOrder())
        self.main_window.log('info', f'Starting USB server with {len(checked_files)} files')
        
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
        self.usb_handler.start()
        self._set_server_ui_state(True)
        self.transfer_stats['start_time'] = datetime.now()
        self.main_window.overall_label.setText(f'0 / {len(checked_files)} files')

    def stop_usb_server(self):
        if self.usb_handler:
            self.usb_handler.stop()
            self.usb_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.reset_items_visuals()
        if self.main_window.taskbar_manager: self.main_window.taskbar_manager.hide_progress()
        self.main_window.log('info', 'USB Server stopped')
        self.main_window.current_file_label.setText('Server stopped')

    def start_http_server(self):
        # Implementation is similar to start_usb_server
        pass

    def stop_http_server(self):
        if self.http_handler:
            self.http_handler.stop()
            self.http_handler = None
        self._set_server_ui_state(False)
        self.main_window.file_manager.reset_items_visuals()
        if self.main_window.taskbar_manager: self.main_window.taskbar_manager.hide_progress()

    def on_progress_updated(self, filename, transferred, speed, total_req_size, num_files, cur_bytes, cur_size, _unused):
        self.main_window.current_file_label.setText(filename)
        if self.current_processing_file != filename:
            self.current_processing_file = filename
            self.main_window.file_manager.update_file_status(filename, 'process')

        if cur_size > 0:
            pct = int((cur_bytes / cur_size) * 100)
            self.main_window.current_progress.setFormat(f'{pct}% ({format_size(cur_bytes)} / {format_size(cur_size)})')
            self.main_window.current_progress.setValue(min(100, pct))
        
        self.main_window.speed_label.setText(f'Speed: {speed:.1f} MB/s')
        
        completed = self.transfer_stats['completed_files'] + self.transfer_stats['skipped_files']
        if total_req_size > 0:
            overall_pct = int((transferred / total_req_size) * 100)
            
            # --- NEW: Force 100% if all files are processed ---
            if completed >= num_files and num_files > 0:
                overall_pct = 100
                
            self.main_window.overall_progress.setValue(min(100, overall_pct))
            self.main_window.overall_progress.setFormat(f'{overall_pct}% ({format_size(transferred)} / {format_size(total_req_size)})')
            
            if self.main_window.taskbar_manager:
                self.main_window.taskbar_manager.set_progress_value(min(100, overall_pct))
        
        display_idx = min(completed + 1, num_files) if num_files > 0 else 0
        if completed >= num_files: display_idx = num_files
        self.main_window.overall_label.setText(f'{display_idx} / {num_files} files')

        if self.transfer_stats['start_time']:
            elapsed = (datetime.now() - self.transfer_stats['start_time']).seconds
            self.main_window.session_time_label.setText(f"Time: {format_time(elapsed)}")

        if speed > 0 and total_req_size > transferred:
            sec = (total_req_size - transferred) / (speed * 1024 * 1024)
            self.main_window.eta_label.setText(f'ETA: {format_time(int(sec))}')
        elif completed >= num_files and num_files > 0:
             self.main_window.eta_label.setText('ETA: Done')

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
        self.main_window.file_manager.reset_items_visuals()
        self.main_window.current_progress.setValue(0)
        self.main_window.overall_progress.setValue(0)
        self.main_window.current_file_label.setText("No transfer in progress")
        self.main_window.overall_label.setText("0 / 0 files")

    # (The rest of the file is unchanged)
    def on_http_server_started(self, ip, port): pass
    def on_http_server_stopped(self): pass
    def _set_server_ui_state(self, running: bool):
        btn = self.main_window.start_server_btn
        if running:
            btn.setText('⏹')
            btn.setStyleSheet('QPushButton { background-color: #f44336; color: white; font-size: 32px; } QPushButton:hover { background-color: #da190b; }')
            self.main_window.server_label.setText('Stop Server')
            self.main_window.mode_combo.setEnabled(False)
            self.main_window.add_files_btn.setEnabled(False)
            self.main_window.clear_list_btn.setEnabled(False)
        else:
            btn.setText('▶')
            btn.setStyleSheet('QPushButton { background-color: #4CAF50; color: white; font-size: 32px; } QPushButton:hover:enabled { background-color: #45a049; } QPushButton:disabled { background-color: #BDBDBD; }')
            mode = self.main_window.mode_combo.currentText()
            self.main_window.server_label.setText(f'Start {"HTTP" if "HTTP" in mode else "USB"}')
            self.main_window.mode_combo.setEnabled(True)
            self.main_window.add_files_btn.setEnabled(True)
            self.main_window.clear_list_btn.setEnabled(True)
    def check_connection(self):
        if "USB" in self.main_window.mode_combo.currentText():
            if self.usb_handler is None and self.main_window.file_tree.topLevelItemCount() > 0:
                 self.main_window.start_server_btn.setEnabled(True)
    def on_connection_changed(self, status):
        if status == ConnectionStatus.CONNECTED: self.main_window.connection_status.setText('🟢 Connected')
        elif status == ConnectionStatus.CONNECTING: self.main_window.connection_status.setText('🟡 Connecting...')
        else:
            self.main_window.connection_status.setText('🔴 Not connected')
            if self.usb_handler and not self.usb_handler.is_running: self._set_server_ui_state(False)
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
                    if w: w.findChild(QCheckBox).setChecked(False)
                    break
            self.main_window.on_item_checked()
    def on_file_skipped(self, filename, size):
        self.transfer_stats['skipped_files'] += 1
        self.main_window.file_manager.update_file_status(filename, 'failed')
        self.main_window.progress_delegate.mark_skipped(filename)
        self.main_window.log('warning', f'Skipped: {filename}')
    def on_transfer_reset(self):
        self.main_window.log('info', 'Switch reset sequence.')
        self._reset_ui_for_start()
        self.main_window.file_manager.dim_unchecked_items()