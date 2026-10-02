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
    QMessageBox, QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QAction, QIcon, QKeySequence, QShortcut

from . import __version__
from .taskbar_manager import TaskbarManager
from .config_manager import ConfigManager
from .theme_manager import ThemeManager
from .widgets import CustomSplitter, CustomSplitterHandle
from .ui_manager import UIManager
from .file_operations import FileManager
from .server_operations import ServerManager
from .utility_functions import format_time
from .usb_driver import DriverInstallThread, UDEV_RULE_PATH, windows_driver_missing


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
        self.hibernate_checkbox = None
        self.switch_storage_label = None
        self._hibernate_timer = None
        self._hibernate_seconds_left = 0
        self._inactivity_check_timer = QTimer(self)
        self._inactivity_check_timer.timeout.connect(self._check_inactivity)
        self._inactivity_check_timer.start(1000)
        
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

        self._driver_thread = None
        self._driver_offered = False
        if windows_driver_missing():
            QTimer.singleShot(500, lambda: self.offer_usb_driver_install('no_driver'))

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == 'win32' and self.taskbar_manager is None:
            self.taskbar_manager = TaskbarManager(self.windowHandle())

    def init_ui(self):
        self.setWindowTitle(f'DBI Backend Qt v{__version__}')
        self.setMinimumSize(900, 700)

        icon_path = Path(__file__).parent.parent / 'icons' / 'icon.png'
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

        self.shortcut_move_up = QShortcut(QKeySequence("Alt+Up"), self)
        self.shortcut_move_up.activated.connect(self.move_selected_up)
        self.shortcut_move_down = QShortcut(QKeySequence("Alt+Down"), self)
        self.shortcut_move_down.activated.connect(self.move_selected_down)

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
    def move_selected_up(self): self.file_manager.move_selected_items(-1)
    def move_selected_down(self): self.file_manager.move_selected_items(1)
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
        for item in self.file_manager.iter_top_level_items():
            self.file_manager.set_item_checked(item, is_checked)
        self.file_manager.update_count_label()

    def on_item_checked(self):
        self._updating_header_checkbox = True
        total = sum(1 for _ in self.file_manager.iter_file_items())
        checked = sum(1 for _ in self.file_manager.iter_checked_items())

        if checked == 0: self.header_checkbox.setCheckState(Qt.CheckState.Unchecked)
        elif checked == total and total > 0: self.header_checkbox.setCheckState(Qt.CheckState.Checked)
        else: self.header_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
        self._updating_header_checkbox = False
        self.file_manager.update_count_label()

        if self.server_manager.usb_handler and self.server_manager.usb_handler.is_running:
            checked_names = {item.text(1) for item in self.file_manager.iter_checked_items()}
            self.server_manager.sync_usb_files(self.file_manager.file_list, checked_names, self.file_manager.file_targets)

    def show_context_menu(self, position):
        menu = QMenu()
        target_menu = menu.addMenu("Set Target")
        act_auto = target_menu.addAction("Auto")
        act_auto.triggered.connect(lambda: self.file_manager.set_target_for_selected(0))
        act_sd = target_menu.addAction("microSD")
        act_sd.triggered.connect(lambda: self.file_manager.set_target_for_selected(1))
        act_nand = target_menu.addAction("System memory (NAND)")
        act_nand.triggered.connect(lambda: self.file_manager.set_target_for_selected(2))

        menu.addSeparator()
        act_up = menu.addAction("Move Up (Alt+Up)")
        act_up.triggered.connect(self.move_selected_up)
        act_down = menu.addAction("Move Down (Alt+Down)")
        act_down.triggered.connect(self.move_selected_down)
        menu.addSeparator()

        remove_action = QAction("Remove Selected", self)
        remove_action.triggered.connect(self.remove_selected_files)
        menu.addAction(remove_action)
        menu.exec(self.file_tree.viewport().mapToGlobal(position))

    def remove_selected_files(self):
        selected = self.file_tree.selectedItems()
        if not selected: return
        self.file_manager.remove_selected_items(selected)

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
        try:
            with open("log.txt", 'a', encoding='utf-8') as f:
                f.write(f"[{t}] [{level.upper()}] {message}\n")
        except:
            pass

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
        QMessageBox.about(self, 'About', f'<h2>DBI Backend Qt</h2><p>Version {__version__}</p>')

    def offer_usb_driver_install(self, problem: str = 'manual'):
        """Ask once per run (always when chosen from the menu) and install the
        driver or udev rule the console needs."""
        if self._driver_thread is not None and self._driver_thread.isRunning():
            return
        if problem != 'manual':
            if self._driver_offered:
                return
            self._driver_offered = True
        if sys.platform == 'win32':
            text = ('Install the WinUSB driver for the Nintendo Switch?\n\n'
                    'Without it Windows does not let DBI Backend talk to the console over USB. '
                    'Windows will ask for administrator permission.')
        else:
            text = ('Allow your user to access the Nintendo Switch over USB?\n\n'
                    f'This installs a udev rule ({UDEV_RULE_PATH}) and asks for your password.')
        if QMessageBox.question(self, 'USB Driver', text) != QMessageBox.StandardButton.Yes:
            self.log('warning', 'USB driver not installed. Use Help > Install USB Driver to install it later.')
            return
        self.log('info', 'Installing USB driver...')
        self._driver_thread = DriverInstallThread(self)
        self._driver_thread.done.connect(self._on_usb_driver_installed)
        self._driver_thread.start()

    def _on_usb_driver_installed(self, ok: bool, message: str):
        self.log('success' if ok else 'error', message.splitlines()[0])
        if ok:
            QMessageBox.information(self, 'USB Driver', message)
        else:
            QMessageBox.warning(self, 'USB Driver', message)

    def handle_external_files(self, message: str):
        lines = [line.strip() for line in message.strip().split('\n') if line.strip()]
        if not lines:
            return
        if len(lines) == 1:
            p = Path(lines[0])
            if p.suffix.lower() == '.dbi' and p.exists():
                self.file_manager.load_preset(p)
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
                self.activateWindow()
                self.raise_()
                return

        paths = [Path(line) for line in lines]
        self.file_manager.ingest_paths(paths)
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()
        self.raise_()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        if not urls:
            return
        if len(urls) == 1:
            p = Path(urls[0].toLocalFile())
            if p.suffix.lower() == '.dbi' and p.exists():
                self.file_manager.load_preset(p)
                return

        paths = [Path(url.toLocalFile()) for url in urls]
        self.file_manager.ingest_paths(paths)

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


    def on_hibernate_toggled(self, checked: bool):
        self.config.set('hibernate_when_done', checked)
        self.config.save()
        if checked:
            self.server_manager.snooze_inactivity()
        self.log('info', f"Auto-hibernation {'enabled (5 min idle)' if checked else 'disabled'}")

    def _check_inactivity(self):
        """Periodically check if client has been idle for >= 5 minutes with hibernation enabled."""
        if not (self.hibernate_checkbox and self.hibernate_checkbox.isChecked()):
            return

        # If the countdown dialog is already visible, check if activity resumed
        if hasattr(self, '_hibernate_box') and self._hibernate_box and self._hibernate_box.isVisible():
            handler = self.server_manager.get_active_handler()
            if handler:
                inactivity = handler.get_inactivity_seconds()
                if inactivity is not None and inactivity < 5.0:
                    # Client activity resumed during countdown! Cancel countdown
                    if self._hibernate_timer and self._hibernate_timer.isActive():
                        self._hibernate_timer.stop()
                    self._hibernate_box.reject()
                    self.server_manager.snooze_inactivity()
                    self.log('info', 'Client activity detected: hibernation cancelled.')
            return

        inactivity_sec = self.server_manager.get_inactivity_seconds()
        if inactivity_sec is not None and inactivity_sec >= 300.0:  # 5 minutes
            self.log('warning', f'No client activity for 5 minutes. Preparing hibernation.')
            self.start_hibernation_countdown(30)

    def start_hibernation_countdown(self, seconds: int = 30):
        self._hibernate_seconds_left = seconds
        if self._hibernate_timer is None:
            self._hibernate_timer = QTimer(self)
            self._hibernate_timer.timeout.connect(self._on_hibernate_tick)

        self._hibernate_box = QMessageBox(self)
        self._hibernate_box.setWindowTitle("PC Hibernation")
        self._hibernate_box.setIcon(QMessageBox.Icon.Information)
        self._hibernate_box.setText(
            f"No activity between Switch and PC for over 5 minutes.\n\n"
            f"Console is idle. PC will enter hibernation in {seconds} seconds."
        )
        cancel_btn = self._hibernate_box.addButton("Cancel Hibernation", QMessageBox.ButtonRole.RejectRole)
        self._hibernate_box.setDefaultButton(cancel_btn)
        self._hibernate_timer.start(1000)

        res = self._hibernate_box.exec()
        if self._hibernate_timer.isActive():
            self._hibernate_timer.stop()
            self.server_manager.snooze_inactivity()
            self.log('info', 'PC Hibernation cancelled by user.')

    def _on_hibernate_tick(self):
        self._hibernate_seconds_left -= 1
        if hasattr(self, '_hibernate_box') and self._hibernate_box.isVisible():
            self._hibernate_box.setText(
                f"No activity between Switch and PC for over 5 minutes.\n\n"
                f"Console is idle. PC will enter hibernation in {self._hibernate_seconds_left} seconds."
            )
        if self._hibernate_seconds_left <= 0:
            self._hibernate_timer.stop()
            if hasattr(self, '_hibernate_box') and self._hibernate_box.isVisible():
                self._hibernate_box.done(0)
            self.execute_hibernation()

    def execute_hibernation(self):
        self.log('warning', 'Putting PC into hibernation now...')
        # Safely stop any running servers before hibernation
        try:
            if self.server_manager.usb_handler:
                self.server_manager.stop_usb_server()
            if self.server_manager.http_handler:
                self.server_manager.stop_http_server()
            if self.server_manager.ftp_handler:
                self.server_manager.stop_ftp_server()
        except Exception as e:
            self.log('error', f'Error stopping servers before hibernation: {e}')

        import os
        if sys.platform == 'win32':
            os.system("shutdown /h")
        else:
            self.log('error', 'Hibernation is only supported on Windows')

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
