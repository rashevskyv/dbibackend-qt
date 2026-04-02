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
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QAction, QIcon

from .taskbar_manager import TaskbarManager
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
        
        self.ui_manager = UIManager(self)
        self.file_manager = FileManager(self)
        self.server_manager = ServerManager(self)
        
        # UI Placeholders
        self.file_tree = None
        self.header_checkbox = None
        self._updating_header_checkbox = False
        self.file_count_label = None
        self.search_box = None
        self.search_clear_btn = None
        self.start_server_btn = None
        self.server_label = None
        
        self.mode_switch = None
        self.usb_label = None
        self.http_label = None
        
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
        
        self.taskbar_manager = None
            
        self.init_ui()
        
        self.apply_theme(self.config.get('theme', 'auto'))
        QApplication.styleHints().colorSchemeChanged.connect(self.on_system_theme_changed)

        self.restore_geometry()
        self.restore_splitter_sizes()
        self.restore_zoom_level()
        self.update_presets_menu()
        self._init_log_file()
        
        self.server_manager.reconnect_timer.timeout.connect(self.server_manager.check_connection)
        self.server_manager.reconnect_timer.start(2000)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == 'win32' and self.taskbar_manager is None:
            self.taskbar_manager = TaskbarManager(self.windowHandle())

    def init_ui(self):
        self.setWindowTitle('DBI Backend Qt v2.3.18')
        self.setMinimumSize(900, 700)

        icon_path = Path('icons/icon.png')
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
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
        
        self.file_tree.space_pressed.connect(self.file_manager.invert_selected_files)

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

    # --- Delegation ---
    def add_files(self): self.file_manager.add_files()
    def add_folder(self): self.file_manager.add_folder()
    def clear_file_list(self): self.file_manager.clear_file_list()
    def save_file_list_as_batch(self): self.file_manager.save_file_list_as_batch()
    def save_preset(self): self.file_manager.save_preset()
    def load_preset(self, path=None): self.file_manager.load_preset(path)
    def delete_preset(self): self.file_manager.delete_preset()

    # --- UI Events ---
    def on_search_text_changed(self, text):
        self.search_clear_btn.setVisible(bool(text))
        self.file_manager.filter_files(text)

    def clear_search(self):
        self.search_box.clear()
        self.file_manager.filter_files("")

    def _get_btn_style(self, color, hover_color):
        return f'''
            QPushButton {{
                background-color: {color};
                color: white;
                font-size: 32px;
            }}
            QPushButton:hover:enabled {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {color};
            }}
            QPushButton:disabled {{
                background-color: #BDBDBD;
                color: #757575;
            }}
        '''

    def on_mode_switched(self, checked):
        # Checked = HTTP, Unchecked = USB
        if checked: # HTTP Mode
            self.server_label.setText("Start HTTP")
            self.connection_status.setText("🌐 HTTP Mode")
            self.usb_label.setStyleSheet("color: gray;")
            self.http_label.setStyleSheet("font-weight: bold; color: #2196F3;")
            self.start_server_btn.setStyleSheet(self._get_btn_style("#2196F3", "#1976D2"))
            
        else: # USB Mode
            self.server_label.setText("Start USB")
            self.connection_status.setText("🔴 Not connected")
            self.usb_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            self.http_label.setStyleSheet("color: gray;")
            self.start_server_btn.setStyleSheet(self._get_btn_style("#4CAF50", "#45a049"))
        
        # Reset progress bars and visuals on mode switch
        self.file_manager.handle_server_stop()

    def toggle_server(self): self.server_manager.toggle_server()

    def on_header_checkbox_changed(self, state):
        if self._updating_header_checkbox: return
        is_checked = (state == 2)
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            w = self.file_tree.itemWidget(item, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb: cb.setChecked(is_checked)
        self.file_manager.update_count_label()

    def on_item_checked(self):
        self._updating_header_checkbox = True
        checked = 0
        total = self.file_tree.topLevelItemCount()
        for i in range(total):
            item = self.file_tree.topLevelItem(i)
            w = self.file_tree.itemWidget(item, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb and cb.isChecked(): checked += 1
        
        if checked == 0: self.header_checkbox.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total: self.header_checkbox.setCheckState(Qt.CheckState.Checked)
        else: self.header_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
        self._updating_header_checkbox = False
        self.file_manager.update_count_label()

    def show_context_menu(self, position):
        menu = QMenu()
        remove_action = QAction("Remove Selected", self)
        remove_action.triggered.connect(self.remove_selected_files)
        menu.addAction(remove_action)
        menu.exec(self.file_tree.viewport().mapToGlobal(position))

    def remove_selected_files(self):
        selected = self.file_tree.selectedItems()
        if not selected: return
        for item in selected:
            if item.text(1) in self.file_manager.file_list:
                del self.file_manager.file_list[item.text(1)]
            self.file_tree.takeTopLevelItem(self.file_tree.indexOfTopLevelItem(item))
        self.file_manager.update_count_label()
        self.on_item_checked()

    def update_presets_menu(self):
        if not self.presets_menu: return
        for action in self.presets_menu.actions():
            if action.data(): self.presets_menu.removeAction(action)
        if self.file_manager.presets_dir.exists():
            for p in sorted(self.file_manager.presets_dir.glob('*.dbi')):
                a = QAction(p.stem, self)
                a.setData(str(p))
                a.triggered.connect(lambda c, f=p: self.file_manager.load_preset(f))
                self.presets_menu.addAction(a)

    def log(self, level, message):
        t = datetime.now().strftime('%H:%M:%S')
        print(f"[{t}] [{level.upper()}] {message}") # Console logging
        c = {'debug':'#9E9E9E','info':'#2196F3','success':'#4CAF50','warning':'#FF9800','error':'#F44336'}.get(level,'#000')
        i = {'debug':'🔍','info':'ℹ️','success':'✓','warning':'⚠','error':'✗'}.get(level,'')
        self.log_text.append(f'<span style="color:{c};">[{t}] {i} {message}</span>')
        if self.log_text.document().lineCount() > 1000:
             self.log_text.setPlainText(self.log_text.toPlainText()[-5000:])

    def clear_log(self): self.log_text.clear()

    def apply_theme(self, theme_mode: str):
        self.config.set('theme', theme_mode)
        target = self.theme_manager.get_system_theme() if theme_mode == 'auto' else theme_mode
        self.setStyleSheet(self.theme_manager.get_theme(target))
        
        if self.progress_delegate:
            if target == 'dark': self.progress_delegate.set_theme_color('#2196F3')
            else: self.progress_delegate.set_theme_color('#4CAF50')
            self.file_tree.viewport().update()

        if hasattr(self, 'current_progress') and hasattr(self.current_progress, 'set_theme_color'):
            if target == 'dark': self.current_progress.set_theme_color('#2196F3')
            else: self.current_progress.set_theme_color('#4CAF50')

        if theme_mode != 'auto': self.log('info', f'Applied {theme_mode} theme')

    def on_system_theme_changed(self):
        if self.config.get('theme') == 'auto': self.apply_theme('auto')

    def show_about(self):
        QMessageBox.about(self, 'About', '<h2>DBI Backend Qt</h2><p>Version 2.3.16</p>')

    def handle_external_files(self, message: str):
        paths = message.strip().split('\n')
        if len(paths) == 1:
            p = Path(paths[0].strip())
            if p.suffix.lower() == '.dbi' and p.exists():
                self.file_manager.load_preset(p)
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
                self.activateWindow()
                self.raise_()
                return

        current = self.file_manager._get_current_checked_state()
        added = 0
        for p_str in paths:
            path = Path(p_str.strip())
            if not path.exists(): continue
            if path.is_file() and self.file_manager.is_supported_file(path):
                self.file_manager.file_list[path.name] = path.resolve()
                current.add(path.name)
                added += 1
            elif path.is_dir():
                for f in path.rglob('*'):
                    if f.is_file() and self.file_manager.is_supported_file(f):
                         self.file_manager.file_list[f.name] = f.resolve()
                         current.add(f.name)
                         added += 1
        if added:
            self.file_manager.update_file_list(current)
            self.log("info", f"External: Added {added} files")
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            self.activateWindow()
            self.raise_()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        files = []
        urls = e.mimeData().urls()
        if len(urls) == 1:
            p = Path(urls[0].toLocalFile())
            if p.suffix.lower() == '.dbi':
                self.file_manager.load_preset(p)
                return
        for url in urls:
            p = Path(url.toLocalFile())
            if p.is_file() and self.file_manager.is_supported_file(p): files.append(p)
            elif p.is_dir(): files.extend([f for f in p.rglob('*') if f.is_file() and self.file_manager.is_supported_file(f)])
        
        current = self.file_manager._get_current_checked_state()
        for p in files: 
            self.file_manager.file_list[p.name] = p.resolve()
            current.add(p.name)
            
        if files:
            self.file_manager.update_file_list(current)
            self.log('info', f'Dropped {len(files)} files')

    def restore_geometry(self):
        g = self.config.get('window_geometry')
        if g:
            try: self.restoreGeometry(base64.b64decode(g))
            except: pass

    def restore_splitter_sizes(self):
        s = self.config.get('splitter_sizes')
        if s: self.splitter.setSizes(s)

    def restore_zoom_level(self):
        z = self.config.get('file_tree_zoom', 0)
        self.file_tree.zoom_level = z
        self.file_tree.apply_zoom()

    def update_splitter_handles(self):
        s = self.splitter.sizes()
        for i in range(self.splitter.count() - 1):
            h = self.splitter.handle(i + 1)
            if isinstance(h, CustomSplitterHandle):
                h.is_collapsed = (s[i + 1] == 0)
                h.update()

    def closeEvent(self, e):
        if self.server_manager.usb_handler and self.server_manager.usb_handler.is_running:
            if QMessageBox.question(self, 'Confirm', 'Server running. Exit?') == QMessageBox.StandardButton.No:
                e.ignore(); return
            self.server_manager.stop_usb_server()
        if self.server_manager.http_handler and self.server_manager.http_handler.is_running:
            self.server_manager.stop_http_server()
        
        self.config.set('window_geometry', base64.b64encode(self.saveGeometry()).decode('utf-8'))
        self.config.set('splitter_sizes', self.splitter.sizes())
        self.config.set('file_tree_zoom', self.file_tree.zoom_level)
        self.config.save()
        e.accept()

    def _init_log_file(self):
        try:
            with open("log.txt", 'w', encoding='utf-8') as f:
                f.write(f"=== Log {datetime.now()} ===\n")
        except: pass

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.file_manager.invert_selected_files()
            e.accept()
        else: super().keyPressEvent(e)