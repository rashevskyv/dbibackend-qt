#!/usr/bin/env python3
"""
DBI Backend Qt - Main Window
"""

import sys
import base64
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMessageBox, QCheckBox, QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QAction

from .config_manager import ConfigManager
from .theme_manager import ThemeManager
from .widgets import CustomSplitter, CustomSplitterHandle
from .ui_manager import UIManager
from .file_operations import FileManager
from .server_operations import ServerManager
from .utility_functions import format_time


class MainWindow(QMainWindow):
    """Main application window with enhanced UI"""

    def __init__(self):
        super().__init__()

        self.config = ConfigManager()
        self.theme_manager = ThemeManager()
        
        # Initialize Managers
        self.ui_manager = UIManager(self)
        self.file_manager = FileManager(self)
        self.server_manager = ServerManager(self)
        
        # UI Placeholders (populated by ui_manager)
        self.file_tree = None
        self.header_checkbox = None
        self._updating_header_checkbox = False
        self.file_count_label = None
        self.search_box = None
        self.search_clear_btn = None
        self.start_server_btn = None
        self.server_label = None
        self.mode_combo = None
        self.ip_label = None
        self.current_file_label = None
        self.current_progress = None
        self.overall_label = None
        self.eta_label = None
        self.overall_progress = None
        self.speed_label = None
        self.session_time_label = None
        self.log_text = None
        self.connection_status = None
        self.presets_menu = None
        
        # Build UI
        self.init_ui()
        
        # Apply theme (defaults to auto)
        self.apply_theme(self.config.get('theme', 'auto'))
        
        # Listen for system theme changes (Windows Dark/Light mode toggle)
        QApplication.styleHints().colorSchemeChanged.connect(self.on_system_theme_changed)

        # Restore State
        self.restore_geometry()
        self.restore_splitter_sizes()
        self.restore_zoom_level()
        self.update_presets_menu()
        self._init_log_file()
        
        # Start connection timer
        self.server_manager.reconnect_timer.timeout.connect(self.server_manager.check_connection)
        self.server_manager.reconnect_timer.start(2000)

    def init_ui(self):
        self.setWindowTitle('DBI Backend Qt v2.3.5')
        self.setMinimumSize(900, 700)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        self.ui_manager.create_menu_bar()
        self.ui_manager.create_toolbar(main_layout)

        self.splitter = CustomSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(10)
        self.splitter.splitterMoved.connect(self.update_splitter_handles)
        self.splitter.sizes_changed.connect(self.update_splitter_handles)

        file_section = self.ui_manager.create_file_section()
        self.splitter.addWidget(file_section)

        progress_section = self.ui_manager.create_progress_section()
        self.splitter.addWidget(progress_section)

        log_section = self.ui_manager.create_log_section()
        self.splitter.addWidget(log_section)

        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 2)

        main_layout.addWidget(self.splitter)

        self.ui_manager.create_status_bar()

        self.setAcceptDrops(True)

    # --- Delegation to FileManager ---
    def add_files(self):
        self.file_manager.add_files()

    def add_folder(self):
        self.file_manager.add_folder()

    def clear_file_list(self):
        self.file_manager.clear_file_list()

    def save_file_list_as_batch(self):
        self.file_manager.save_file_list_as_batch()

    def save_preset(self):
        self.file_manager.save_preset()

    def load_preset(self):
        self.file_manager.load_preset()
        
    def delete_preset(self):
        self.file_manager.delete_preset()

    # --- UI Events ---
    def on_search_text_changed(self, text):
        self.search_clear_btn.setVisible(bool(text))
        self.file_manager.filter_files(text)

    def clear_search(self):
        self.search_box.clear()
        self.file_manager.filter_files("")

    def on_mode_changed(self, index):
        mode = self.mode_combo.currentText()
        if "HTTP" in mode:
            self.server_label.setText("Start HTTP")
            self.connection_status.setText("🌐 HTTP Mode")
        else:
            self.server_label.setText("Start USB")
            self.connection_status.setText("🔴 Not connected")

    def toggle_server(self):
        self.server_manager.toggle_server()

    def on_header_checkbox_changed(self, state):
        """Toggle all file checkboxes"""
        if self._updating_header_checkbox:
            return
        
        is_checked = (state == 2) # Qt.CheckState.Checked
        
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            widget = self.file_tree.itemWidget(item, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(is_checked)

    def on_item_checked(self):
        """Update header checkbox based on individual item states"""
        self._updating_header_checkbox = True
        
        checked_count = 0
        total_count = self.file_tree.topLevelItemCount()
        
        for i in range(total_count):
            item = self.file_tree.topLevelItem(i)
            widget = self.file_tree.itemWidget(item, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    checked_count += 1
        
        if checked_count == 0:
            self.header_checkbox.setCheckState(Qt.CheckState.Unchecked)
        elif checked_count == total_count:
            self.header_checkbox.setCheckState(Qt.CheckState.Checked)
        else:
            self.header_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
            
        self._updating_header_checkbox = False

    def show_context_menu(self, position):
        """Show context menu for file list"""
        menu = QMenu()
        
        remove_action = QAction("Remove Selected", self)
        remove_action.triggered.connect(self.remove_selected_files)
        menu.addAction(remove_action)
        
        menu.exec(self.file_tree.viewport().mapToGlobal(position))

    def remove_selected_files(self):
        """Remove selected files from list"""
        selected_items = self.file_tree.selectedItems()
        if not selected_items:
            return
            
        for item in selected_items:
            filename = item.text(1)
            if filename in self.file_manager.file_list:
                del self.file_manager.file_list[filename]
            
            index = self.file_tree.indexOfTopLevelItem(item)
            self.file_tree.takeTopLevelItem(index)
            
        self.file_manager.update_count_label()
        self.on_item_checked()

    def update_presets_menu(self):
        """Update the list of presets in the menu"""
        if not self.presets_menu:
            return
            
        for action in self.presets_menu.actions():
            if action.menu() != self.manage_presets_menu:
                self.presets_menu.removeAction(action)
                
        if self.file_manager.presets_dir.exists():
            for preset_file in sorted(self.file_manager.presets_dir.glob('*.json')):
                action = QAction(preset_file.stem, self)
                action.triggered.connect(lambda checked, p=preset_file: self.file_manager.load_preset(p))
                self.presets_menu.addAction(action)

    # --- Core functionality ---

    def log(self, level: str, message: str):
        """Add a log message with color coding"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        color_map = {
            'debug': '#9E9E9E',
            'info': '#2196F3',
            'success': '#4CAF50',
            'warning': '#FF9800',
            'error': '#F44336'
        }
        color = color_map.get(level, '#000000')
        icon = {'debug': '🔍', 'info': 'ℹ️', 'success': '✓', 'warning': '⚠', 'error': '✗'}.get(level, '')
        
        formatted = f'<span style="color: {color};">[{timestamp}] {icon} {message}</span>'
        self.log_text.append(formatted)

        if self.log_text.document().lineCount() > 1000:
             self.log_text.setPlainText(self.log_text.toPlainText()[-5000:]) 

    def clear_log(self):
        self.log_text.clear()

    def apply_theme(self, theme_mode: str):
        """Apply a theme to the application (light/dark/auto)"""
        self.config.set('theme', theme_mode)
        
        target_theme = theme_mode
        if theme_mode == 'auto':
            target_theme = self.theme_manager.get_system_theme()
        
        stylesheet = self.theme_manager.get_theme(target_theme)
        self.setStyleSheet(stylesheet)
        
        if theme_mode != 'auto':
            self.log('info', f'Applied {theme_mode} theme')

    def on_system_theme_changed(self):
        """Handle OS theme change events (e.g. Windows Dark Mode toggle)"""
        if self.config.get('theme') == 'auto':
            new_theme = self.theme_manager.get_system_theme()
            stylesheet = self.theme_manager.get_theme(new_theme)
            self.setStyleSheet(stylesheet)

    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            'About DBI Backend Qt',
            '<h2>DBI Backend Qt</h2>'
            '<p>Version 2.3.5</p>'
            '<p>Enhanced GUI for transferring files to Nintendo Switch via DBI</p>'
        )

    def handle_external_files(self, message: str):
        """Handle files sent from another instance"""
        paths = message.strip().split('\n')
        current_checked = self.file_manager._get_current_checked_state()
        added_count = 0

        for path_str in paths:
            path_str = path_str.strip()
            if not path_str: continue

            file_path = Path(path_str)
            if not file_path.exists(): continue

            if file_path.is_file():
                if self.file_manager.is_supported_file(file_path):
                    self.file_manager.file_list[file_path.name] = file_path.resolve()
                    added_count += 1
            elif file_path.is_dir():
                for f in file_path.rglob('*'):
                    if f.is_file() and self.file_manager.is_supported_file(f):
                        self.file_manager.file_list[f.name] = f.resolve()
                        added_count += 1

        if added_count > 0:
            self.file_manager.update_file_list(current_checked)
            self.log("info", f"Added {added_count} file(s) from external source")
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            self.activateWindow()
            self.raise_()

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle drop events"""
        files = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file():
                if self.file_manager.is_supported_file(path):
                    files.append(path)
            elif path.is_dir():
                files.extend([f for f in path.rglob('*') if f.is_file() and self.file_manager.is_supported_file(f)])

        current_checked = self.file_manager._get_current_checked_state()
        added_count = 0
        for path in files:
            self.file_manager.file_list[path.name] = path.resolve()
            added_count += 1

        if added_count > 0:
            self.file_manager.update_file_list(current_checked)
            self.log('info', f'Added {added_count} file(s) via drag & drop')

    def restore_geometry(self):
        """Restore window geometry from settings"""
        geometry = self.config.get('window_geometry')
        if geometry:
            try:
                geometry_bytes = base64.b64decode(geometry)
                self.restoreGeometry(geometry_bytes)
            except Exception as e:
                pass

    def restore_splitter_sizes(self):
        """Restore splitter section sizes from settings"""
        sizes = self.config.get('splitter_sizes')
        if sizes and isinstance(sizes, list) and len(sizes) == self.splitter.count():
            self.splitter.setSizes(sizes)

    def restore_zoom_level(self):
        """Restore file tree zoom level from settings"""
        zoom_level = self.config.get('file_tree_zoom', 0)
        if isinstance(zoom_level, int):
            self.file_tree.zoom_level = zoom_level
            self.file_tree.apply_zoom()

    def update_splitter_handles(self):
        """Update splitter handle colors based on collapsed state"""
        sizes = self.splitter.sizes()
        for i in range(self.splitter.count() - 1):
            handle = self.splitter.handle(i + 1)
            if isinstance(handle, CustomSplitterHandle):
                handle.is_collapsed = (sizes[i + 1] == 0)
                handle.update()
    
    def closeEvent(self, event):
        """Handle window close event"""
        if self.server_manager.usb_handler and self.server_manager.usb_handler.is_running:
            reply = QMessageBox.question(
                self, 'Confirm Exit', 'USB Server is running. Exit?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.server_manager.stop_usb_server()
            
        if self.server_manager.http_handler and self.server_manager.http_handler.is_running:
            self.server_manager.stop_http_server()

        geometry_bytes = self.saveGeometry()
        geometry_str = base64.b64encode(geometry_bytes).decode('utf-8')
        self.config.set('window_geometry', geometry_str)
        self.config.set('splitter_sizes', self.splitter.sizes())
        self.config.set('file_tree_zoom', self.file_tree.zoom_level)

        self.config.save()
        event.accept()

    def _init_log_file(self):
        """Initialize log file for new session"""
        try:
            with open("log.txt", 'w', encoding='utf-8') as f:
                f.write(f"=== DBI Backend Qt Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception as e:
            pass

    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key.Key_Space:
            self.file_manager.invert_selected_files()
            event.accept()
        else:
            super().keyPressEvent(event)