#!/usr/bin/env python3
"""
DBI Backend Qt - Main Window
Enhanced GUI for DBI file transfer to Nintendo Switch
"""

import sys
import json
import base64
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QLabel, QProgressBar, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QLineEdit, QStatusBar, QSplitter, QSplitterHandle,
    QHeaderView, QStyle, QCheckBox, QGroupBox, QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QRect
from PyQt6.QtGui import QAction, QIcon, QDragEnterEvent, QDropEvent, QColor, QPainter, QBrush

from usb_handler import USBHandler, ConnectionStatus
from config_manager import ConfigManager
from theme_manager import ThemeManager


class CustomSplitterHandle(QSplitterHandle):
    """Custom splitter handle that changes color when sections are collapsed"""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.is_collapsed = False

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to collapse/expand sections"""
        splitter = self.splitter()
        sizes = splitter.sizes()

        # Find which handle this is (handle index = widget index after it)
        handle_index = splitter.indexOf(self)

        if handle_index > 0 and handle_index < len(sizes):
            # This handle is between widget (handle_index - 1) and widget (handle_index)
            widget_after_index = handle_index

            if sizes[widget_after_index] == 0:
                # Widget is collapsed, expand it
                # Restore to a reasonable size (e.g., 200px)
                new_sizes = sizes.copy()
                new_sizes[widget_after_index] = 200

                # Reduce size from the largest widget to make room
                max_index = sizes.index(max(sizes))
                if new_sizes[max_index] > 200:
                    new_sizes[max_index] -= 200

                splitter.setSizes(new_sizes)
            else:
                # Widget is expanded, collapse it
                new_sizes = sizes.copy()
                # Add current size to the widget before
                if widget_after_index > 0:
                    new_sizes[widget_after_index - 1] += new_sizes[widget_after_index]
                new_sizes[widget_after_index] = 0

                splitter.setSizes(new_sizes)

    def paintEvent(self, event):
        """Custom paint to show different colors for collapsed state"""
        painter = QPainter(self)

        # Choose color based on collapsed state
        if self.is_collapsed:
            color = QColor('#2196F3')  # Blue when collapsed
        else:
            color = QColor('#e0e0e0')  # Gray when normal

        # Draw the handle with margin (create visual spacing)
        rect = self.rect()
        if self.orientation() == Qt.Orientation.Vertical:
            # Vertical splitter - add margin top and bottom
            painter.fillRect(rect.x(), rect.y() + 2, rect.width(), rect.height() - 4, color)
        else:
            # Horizontal splitter - add margin left and right
            painter.fillRect(rect.x() + 2, rect.y(), rect.width() - 4, rect.height(), color)


class CustomSplitter(QSplitter):
    """Custom splitter that uses custom handles"""

    # Signal emitted when sizes change (for handle color updates)
    sizes_changed = pyqtSignal()

    def createHandle(self):
        """Create custom handle"""
        return CustomSplitterHandle(self.orientation(), self)

    def setSizes(self, sizes):
        """Override to emit signal when sizes change"""
        super().setSizes(sizes)
        self.sizes_changed.emit()


class ProgressDelegate(QStyledItemDelegate):
    """Custom delegate to draw progress bar background for file items"""

    def __init__(self, tree_widget, parent=None):
        super().__init__(parent)
        self.tree_widget = tree_widget
        self.progress_data = {}  # filename -> progress%

    def set_progress(self, filename: str, progress: int):
        """Set progress for a file"""
        self.progress_data[filename] = max(0, min(100, progress))

    def paint(self, painter, option, index):
        """Custom paint with progress bar background"""
        # Get the item from the tree widget
        item = self.tree_widget.itemFromIndex(index)
        if item:
            # Get filename from column 1 (name column)
            filename = item.text(1)
            progress = self.progress_data.get(filename, 0)

            if progress > 0:
                # Draw progress background (left to right fill)
                painter.save()

                # Calculate progress width
                progress_width = int((option.rect.width() * progress) / 100)
                progress_rect = QRect(option.rect.x(), option.rect.y(),
                                     progress_width, option.rect.height())

                # Draw green progress background
                if progress >= 100:
                    # Complete - brighter green
                    color = QColor(80, 200, 80, 100)
                else:
                    # In progress - semi-transparent green
                    color = QColor(60, 180, 60, 80)

                painter.fillRect(progress_rect, QBrush(color))
                painter.restore()

        # Draw the default item content on top
        super().paint(painter, option, index)


class MainWindow(QMainWindow):
    """Main application window with enhanced UI"""

    # Supported file extensions for Nintendo Switch
    SUPPORTED_EXTENSIONS = {'.nsp', '.nsz', '.xci', '.xcz'}

    def __init__(self):
        super().__init__()

        self.config = ConfigManager()
        self.theme_manager = ThemeManager()
        self.usb_handler = None
        self.file_list: Dict[str, Path] = {}
        self.transfer_stats = {
            'total_files': 0,
            'transferred_files': 0,
            'completed_files': 0,  # Files fully transferred
            'total_size': 0,
            'transferred_size': 0,
            'start_time': None,
            'current_speed': 0
        }

        self.init_ui()
        self.apply_theme(self.config.get('theme', 'light'))
        self.restore_geometry()
        self.restore_splitter_sizes()

        # Setup auto-reconnect timer
        self.reconnect_timer = QTimer()
        self.reconnect_timer.timeout.connect(self.check_connection)
        self.reconnect_timer.start(2000)  # Check every 2 seconds

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle('DBI Backend Qt v2.3.1')
        self.setMinimumSize(900, 700)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Create menu bar
        self.create_menu_bar()

        # Create toolbar
        self.create_toolbar(main_layout)

        # Create splitter for file list and log
        self.splitter = CustomSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(10)

        # Connect signals to detect when sections are collapsed
        self.splitter.splitterMoved.connect(self.update_splitter_handles)
        self.splitter.sizes_changed.connect(self.update_splitter_handles)

        # File list section
        file_section = self.create_file_section()
        self.splitter.addWidget(file_section)

        # Progress section
        progress_section = self.create_progress_section()
        self.splitter.addWidget(progress_section)

        # Log section
        log_section = self.create_log_section()
        self.splitter.addWidget(log_section)

        # Set splitter proportions
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 2)

        main_layout.addWidget(self.splitter)

        # Status bar
        self.create_status_bar()

        # Enable drag and drop
        self.setAcceptDrops(True)

    def create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu('&File')

        add_files_action = QAction('Add &Files...', self)
        add_files_action.setShortcut('Ctrl+O')
        add_files_action.triggered.connect(self.add_files)
        file_menu.addAction(add_files_action)

        add_folder_action = QAction('Add F&older...', self)
        add_folder_action.setShortcut('Ctrl+Shift+O')
        add_folder_action.triggered.connect(self.add_folder)
        file_menu.addAction(add_folder_action)

        file_menu.addSeparator()

        save_list_action = QAction('&Save List (JSON)...', self)
        save_list_action.setShortcut('Ctrl+S')
        save_list_action.triggered.connect(self.save_file_list)
        file_menu.addAction(save_list_action)

        save_batch_action = QAction('Save as &Batch...', self)
        save_batch_action.setShortcut('Ctrl+B')
        save_batch_action.triggered.connect(self.save_file_list_as_batch)
        file_menu.addAction(save_batch_action)

        load_list_action = QAction('&Load List...', self)
        load_list_action.setShortcut('Ctrl+L')
        load_list_action.triggered.connect(self.load_file_list)
        file_menu.addAction(load_list_action)

        file_menu.addSeparator()

        exit_action = QAction('E&xit', self)
        exit_action.setShortcut('Alt+F4')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu('&View')

        light_theme_action = QAction('&Light Theme', self)
        light_theme_action.triggered.connect(lambda: self.apply_theme('light'))
        view_menu.addAction(light_theme_action)

        dark_theme_action = QAction('&Dark Theme', self)
        dark_theme_action.triggered.connect(lambda: self.apply_theme('dark'))
        view_menu.addAction(dark_theme_action)

        view_menu.addSeparator()

        clear_log_action = QAction('Clear &Log', self)
        clear_log_action.triggered.connect(self.clear_log)
        view_menu.addAction(clear_log_action)

        # Help menu
        help_menu = menubar.addMenu('&Help')

        about_action = QAction('&About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_toolbar(self, layout):
        """Create toolbar with main actions"""
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(10)

        # Helper function to create button with icon and label below
        def create_button(icon, label, callback):
            btn_container = QWidget()
            btn_layout = QVBoxLayout(btn_container)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(2)

            btn = QPushButton(icon)
            btn.setFixedSize(60, 60)
            btn.setStyleSheet('QPushButton { font-size: 32px; }')
            btn.clicked.connect(callback)
            btn_layout.addWidget(btn)

            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet('font-size: 10px;')
            btn_layout.addWidget(lbl)

            return btn_container, btn

        # Add Files button
        files_container, self.add_files_btn = create_button('📄', 'Add Files', self.add_files)
        toolbar_layout.addWidget(files_container)

        # Add Folder button
        folder_container, self.add_folder_btn = create_button('📁', 'Add Folder', self.add_folder)
        toolbar_layout.addWidget(folder_container)

        # Clear List button
        clear_container, self.clear_list_btn = create_button('🗑️', 'Clear List', self.clear_file_list)
        toolbar_layout.addWidget(clear_container)

        # Search box - takes all remaining space
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText('🔍 Search files...')
        self.search_box.textChanged.connect(self.filter_file_list)
        self.search_box.setMinimumHeight(30)
        toolbar_layout.addWidget(self.search_box, 1)  # stretch factor 1

        # Start/Stop Server button
        server_container = QWidget()
        server_layout = QVBoxLayout(server_container)
        server_layout.setContentsMargins(0, 0, 0, 0)
        server_layout.setSpacing(2)

        self.start_server_btn = QPushButton('▶')
        self.start_server_btn.setFixedSize(60, 60)
        self.start_server_btn.clicked.connect(self.toggle_server)
        self.start_server_btn.setEnabled(False)
        self.start_server_btn.setStyleSheet('''
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 32px;
            }
            QPushButton:hover:enabled {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
                color: #757575;
            }
        ''')
        server_layout.addWidget(self.start_server_btn)

        self.server_label = QLabel('Start Server')
        self.server_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.server_label.setStyleSheet('font-size: 10px;')
        server_layout.addWidget(self.server_label)

        toolbar_layout.addWidget(server_container)

        layout.addLayout(toolbar_layout)

    def create_file_section(self):
        """Create file list section"""
        group = QGroupBox('File Queue')
        layout = QVBoxLayout()

        # File tree widget
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(['', 'Filename', 'Size', 'Path', ''])
        self.file_tree.setColumnWidth(0, 50)  # Checkbox
        self.file_tree.setColumnWidth(1, 250)  # Filename
        self.file_tree.setColumnWidth(2, 100)  # Size
        self.file_tree.setColumnWidth(3, 300)  # Path
        self.file_tree.setColumnWidth(4, 40)  # Delete button
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # Enable multiple selection
        self.file_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        # Enable context menu
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.show_context_menu)

        # Set custom delegate for progress visualization
        self.progress_delegate = ProgressDelegate(self.file_tree, self.file_tree)
        self.file_tree.setItemDelegate(self.progress_delegate)

        layout.addWidget(self.file_tree)

        # File count label
        self.file_count_label = QLabel('0 files, 0 B total')
        layout.addWidget(self.file_count_label)

        group.setLayout(layout)
        return group

    def create_progress_section(self):
        """Create progress bars section"""
        group = QGroupBox('Transfer Progress')
        group.setMaximumHeight(180)
        layout = QVBoxLayout()

        # Current file progress
        current_layout = QHBoxLayout()
        current_layout.addWidget(QLabel('Current:'))
        self.current_file_label = QLabel('No transfer in progress')
        current_layout.addWidget(self.current_file_label)
        current_layout.addStretch()
        layout.addLayout(current_layout)

        self.current_progress = QProgressBar()
        self.current_progress.setTextVisible(True)
        self.current_progress.setFormat('%p% @ %v MB/s')
        layout.addWidget(self.current_progress)

        # Overall progress
        overall_layout = QHBoxLayout()
        overall_layout.addWidget(QLabel('Overall:'))
        self.overall_label = QLabel('0 / 0 files')
        overall_layout.addWidget(self.overall_label)
        overall_layout.addStretch()
        self.eta_label = QLabel('ETA: --:--:--')
        overall_layout.addWidget(self.eta_label)
        layout.addLayout(overall_layout)

        self.overall_progress = QProgressBar()
        self.overall_progress.setTextVisible(True)
        layout.addWidget(self.overall_progress)

        # Statistics
        stats_layout = QHBoxLayout()
        self.speed_label = QLabel('Speed: 0 MB/s')
        stats_layout.addWidget(self.speed_label)
        stats_layout.addStretch()
        self.session_time_label = QLabel('Session: 00:00:00')
        stats_layout.addWidget(self.session_time_label)
        layout.addLayout(stats_layout)

        group.setLayout(layout)
        return group

    def create_log_section(self):
        """Create log section"""
        group = QGroupBox('Activity Log')
        layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(100)

        layout.addWidget(self.log_text)

        group.setLayout(layout)
        return group

    def create_status_bar(self):
        """Create status bar"""
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)

        self.connection_status = QLabel('🔴 Not connected')
        self.statusBar.addPermanentWidget(self.connection_status)

    def is_supported_file(self, file_path: Path) -> bool:
        """Check if file has supported extension"""
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def add_files(self):
        """Open file dialog to add files"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            'Select Files',
            self.config.get('last_directory', ''),
            'Switch Files (*.nsp *.nsz *.xci *.xcz);;NSP Files (*.nsp);;NSZ Files (*.nsz);;XCI Files (*.xci);;XCZ Files (*.xcz);;All Files (*.*)'
        )

        if files:
            last_dir = str(Path(files[0]).parent)
            self.config.set('last_directory', last_dir)
            self.config.save()
            self.log('debug', f'Saved last_directory: {last_dir}')
            added_count = 0
            for file_path in files:
                path = Path(file_path)
                if self.is_supported_file(path):
                    self.file_list[path.name] = path.resolve()
                    added_count += 1
                else:
                    self.log('warning', f'Skipped unsupported file: {path.name}')

            if added_count > 0:
                self.update_file_list()
                self.log('info', f'Added {added_count} file(s)')

    def add_folder(self):
        """Open folder dialog to add all files from folder (recursively)"""
        folder = QFileDialog.getExistingDirectory(
            self,
            'Select Folder',
            self.config.get('last_directory', '')
        )

        if folder:
            self.config.set('last_directory', folder)
            self.config.save()
            self.log('debug', f'Saved last_directory: {folder}')
            path = Path(folder)
            added_count = 0
            skipped_count = 0

            # Recursively find all supported files in folder and subfolders
            for file_path in path.rglob('*'):
                if file_path.is_file():
                    if self.is_supported_file(file_path):
                        self.file_list[file_path.name] = file_path.resolve()
                        added_count += 1
                    else:
                        skipped_count += 1

            if added_count > 0:
                self.update_file_list()
                self.log('info', f'Added {added_count} file(s) from folder')

            if skipped_count > 0:
                self.log('warning', f'Skipped {skipped_count} unsupported file(s)')

    def update_file_list(self):
        """Update the file tree widget"""
        self.file_tree.clear()
        total_size = 0

        for name, path in sorted(self.file_list.items()):
            item = QTreeWidgetItem()

            # Checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self.file_tree.addTopLevelItem(item)
            self.file_tree.setItemWidget(item, 0, checkbox)

            # Filename
            item.setText(1, name)

            # Size (with error handling - file might not exist)
            try:
                size = path.stat().st_size
                total_size += size
                item.setText(2, self.format_size(size))
            except Exception as e:
                item.setText(2, "Error")
                self.log('error', f'Cannot get size for {name}: {e}')

            # Path
            item.setText(3, str(path.parent))

            # Delete button
            delete_btn = QPushButton('❌')
            delete_btn.setMaximumWidth(40)
            delete_btn.clicked.connect(lambda checked, n=name: self.remove_file(n))
            self.file_tree.setItemWidget(item, 4, delete_btn)

        # Update count label
        count = len(self.file_list)
        self.file_count_label.setText(f'{count} file{"s" if count != 1 else ""}, {self.format_size(total_size)} total')

        # Enable/disable start button
        self.start_server_btn.setEnabled(count > 0)

    def remove_file(self, filename: str):
        """Remove a file from the list"""
        if filename in self.file_list:
            del self.file_list[filename]
            self.update_file_list()

    def clear_file_list(self):
        """Clear all files from the list"""
        if self.file_list:
            reply = QMessageBox.question(
                self,
                'Clear List',
                'Are you sure you want to clear all files?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.file_list.clear()
                self.update_file_list()

    def show_context_menu(self, position):
        """Show context menu for file tree"""
        selected_items = self.file_tree.selectedItems()

        if not selected_items:
            return

        menu = QMenu()

        # Delete selected
        delete_action = QAction(f'🗑️ Delete selected ({len(selected_items)} files)', self)
        delete_action.triggered.connect(self.delete_selected_files)
        menu.addAction(delete_action)

        menu.addSeparator()

        # Check/Uncheck actions
        check_action = QAction('✅ Check selected', self)
        check_action.triggered.connect(self.check_selected_files)
        menu.addAction(check_action)

        uncheck_action = QAction('☐ Uncheck selected', self)
        uncheck_action.triggered.connect(self.uncheck_selected_files)
        menu.addAction(uncheck_action)

        invert_action = QAction('🔄 Invert selection', self)
        invert_action.triggered.connect(self.invert_selected_files)
        menu.addAction(invert_action)

        menu.addSeparator()

        # Select all / Select none
        select_all_action = QAction('⬜ Select all files', self)
        select_all_action.triggered.connect(self.file_tree.selectAll)
        menu.addAction(select_all_action)

        select_none_action = QAction('Clear selection', self)
        select_none_action.triggered.connect(self.file_tree.clearSelection)
        menu.addAction(select_none_action)

        menu.exec(self.file_tree.viewport().mapToGlobal(position))

    def delete_selected_files(self):
        """Delete all selected files from the list"""
        selected_items = self.file_tree.selectedItems()

        if not selected_items:
            return

        reply = QMessageBox.question(
            self,
            'Delete Files',
            f'Delete {len(selected_items)} selected file(s)?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                filename = item.text(1)
                if filename in self.file_list:
                    del self.file_list[filename]

            self.update_file_list()
            self.log('info', f'Deleted {len(selected_items)} file(s) from queue')

    def check_selected_files(self):
        """Check (enable) all selected files"""
        selected_items = self.file_tree.selectedItems()

        for item in selected_items:
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox:
                checkbox.setChecked(True)

        self.log('info', f'Checked {len(selected_items)} file(s)')

    def uncheck_selected_files(self):
        """Uncheck (disable) all selected files"""
        selected_items = self.file_tree.selectedItems()

        for item in selected_items:
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox:
                checkbox.setChecked(False)

        self.log('info', f'Unchecked {len(selected_items)} file(s)')

    def invert_selected_files(self):
        """Invert checkbox state for all selected files"""
        selected_items = self.file_tree.selectedItems()

        for item in selected_items:
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox:
                checkbox.setChecked(not checkbox.isChecked())

        self.log('info', f'Inverted {len(selected_items)} file(s)')

    def filter_file_list(self, text: str):
        """Filter file list based on search text"""
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            filename = item.text(1)
            item.setHidden(text.lower() not in filename.lower())

    def save_file_list(self):
        """Save current file list to JSON"""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Save File List',
            '',
            'JSON Files (*.json)'
        )

        if filename:
            data = {name: str(path) for name, path in self.file_list.items()}
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.log('info', f'File list saved to {filename}')

    def save_file_list_as_batch(self):
        """Save current file list as Windows batch file"""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Save as Batch File',
            'load_files.bat',
            'Batch Files (*.bat)'
        )

        if filename:
            try:
                # Get path to main.py or executable
                import sys
                if getattr(sys, 'frozen', False):
                    # Running as compiled executable
                    app_path = sys.executable
                else:
                    # Running as script
                    app_path = str(Path(__file__).parent.parent / 'main.py')
                    # Use python/python3 command
                    app_path = f'python "{app_path}"'

                with open(filename, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('REM DBI Backend Qt - Auto-generated batch file\n')
                    f.write('REM Double-click to load these files into DBI Backend Qt\n\n')

                    # Build command line
                    f.write(f'{app_path}')

                    # Add all files as arguments
                    for name, path in sorted(self.file_list.items()):
                        f.write(f' "{path}"')

                    f.write('\n')

                self.log('success', f'Batch file saved: {filename}')
                self.log('info', f'Saved {len(self.file_list)} file(s) to batch')
            except Exception as e:
                self.log('error', f'Failed to save batch file: {e}')
                QMessageBox.warning(self, 'Error', f'Failed to save batch file:\n{e}')

    def load_file_list(self):
        """Load file list from JSON"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Load File List',
            '',
            'JSON Files (*.json)'
        )

        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.file_list.clear()
                for name, path_str in data.items():
                    path = Path(path_str)
                    if path.exists():
                        self.file_list[name] = path
                    else:
                        self.log('warning', f'File not found: {path}')
                self.update_file_list()
                self.log('info', f'File list loaded from {filename}')
            except Exception as e:
                QMessageBox.warning(self, 'Error', f'Failed to load file list: {e}')

    def toggle_server(self):
        """Start or stop the server"""
        if self.usb_handler is None or not self.usb_handler.is_running:
            self.start_server()
        else:
            self.stop_server()

    def start_server(self):
        """Start the USB server"""
        # Reset transfer stats
        self.transfer_stats['completed_files'] = 0

        self.usb_handler = USBHandler(self.file_list)
        self.usb_handler.connection_changed.connect(self.on_connection_changed)
        self.usb_handler.log_message.connect(self.log)
        self.usb_handler.progress_updated.connect(self.on_progress_updated)
        self.usb_handler.file_progress.connect(self.on_file_progress)
        self.usb_handler.transfer_complete.connect(self.on_transfer_complete)
        self.usb_handler.all_transfers_complete.connect(self.on_all_transfers_complete)

        self.usb_handler.start()

        # Change button to Stop (red)
        self.start_server_btn.setText('⏹')
        self.start_server_btn.setStyleSheet('''
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 32px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #c1170a;
            }
        ''')
        self.server_label.setText('Stop Server')

        self.add_folder_btn.setEnabled(False)
        self.add_files_btn.setEnabled(False)
        self.clear_list_btn.setEnabled(False)

        self.transfer_stats['start_time'] = datetime.now()
        self.transfer_stats['total_files'] = len(self.file_list)

        # Show placeholder until Switch requests files
        self.overall_label.setText(f'0 / ? files')

        self.log('info', 'Server started')

    def stop_server(self):
        """Stop the USB server"""
        if self.usb_handler:
            self.usb_handler.stop()
            self.usb_handler = None

        # Change button back to Start (green)
        self.start_server_btn.setText('▶')
        self.start_server_btn.setStyleSheet('''
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 32px;
            }
            QPushButton:hover:enabled {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
                color: #757575;
            }
        ''')
        self.server_label.setText('Start Server')

        self.add_folder_btn.setEnabled(True)
        self.add_files_btn.setEnabled(True)
        self.clear_list_btn.setEnabled(True)

        self.log('info', 'Server stopped')

    def check_connection(self):
        """Check USB connection status"""
        if self.usb_handler and self.usb_handler.is_running:
            # Connection check is handled by USBHandler
            pass

    def on_connection_changed(self, status: ConnectionStatus):
        """Handle connection status changes"""
        if status == ConnectionStatus.CONNECTED:
            self.connection_status.setText('🟢 Connected')
            self.log('success', 'Connected to Switch')
        elif status == ConnectionStatus.CONNECTING:
            self.connection_status.setText('🟡 Connecting...')
        else:
            self.connection_status.setText('🔴 Not connected')
            if self.usb_handler and self.usb_handler.is_running:
                self.log('warning', 'Connection lost, retrying...')

    def on_progress_updated(self, filename: str, transferred_bytes: int, speed_mbps: float, total_requested_size: int, num_requested_files: int, current_file_bytes: int, current_file_size: int, _unused: int):
        """Handle progress updates - with actual progress based on requested files and current file"""
        try:
            # Update current file
            self.current_file_label.setText(f'Current: {filename}')

            # Show current file progress (if we have size info)
            if current_file_size > 0:
                # Calculate progress, allow 100% when bytes match size
                if current_file_bytes >= current_file_size:
                    current_percent = 100
                else:
                    current_percent = int((current_file_bytes / current_file_size) * 100)
                current_bytes_str = self.format_size(current_file_bytes)
                current_size_str = self.format_size(current_file_size)
                self.current_progress.setFormat(f'{current_percent}% ({current_bytes_str} / {current_size_str})')
                self.current_progress.setValue(current_percent)
            else:
                # Metadata phase or unknown size
                current_bytes_str = self.format_size(current_file_bytes)
                self.current_progress.setFormat(f'{current_bytes_str} transferred')
                self.current_progress.setValue(0)

            # Update overall progress (bottom progress bar) - DO NOT MODIFY THIS CALL
            self._update_overall_progress(transferred_bytes, total_requested_size, num_requested_files)

            # Update speed
            self.speed_label.setText(f'Speed: {speed_mbps:.1f} MB/s')

            # Update session time
            if self.transfer_stats.get('start_time'):
                elapsed = datetime.now() - self.transfer_stats['start_time']
                self.session_time_label.setText(f'Session: {self.format_time(int(elapsed.total_seconds()))}')

        except Exception as e:
            self.log('error', f'Progress update error: {e}')

    def on_file_progress(self, filename: str, progress: int):
        """Update visual progress for a file in the list"""
        # Update progress in delegate
        self.progress_delegate.set_progress(filename, progress)

        # Find the file item and trigger repaint + auto-scroll
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item.text(1) == filename:  # Column 1 is the filename
                # Trigger repaint for all columns of this row
                for col in range(self.file_tree.columnCount()):
                    index = self.file_tree.indexFromItem(item, col)
                    self.file_tree.update(index)

                # Ensure item is visible (auto-scroll)
                self.file_tree.scrollToItem(item, QTreeWidget.ScrollHint.PositionAtCenter)
                break

    def _update_overall_progress(self, transferred_bytes: int, total_requested_size: int, num_requested_files: int):
        """
        Update overall (bottom) progress bar based on transferred bytes.

        ===================================================================
        BYTE-BASED PROGRESS BAR
        ===================================================================
        Progress is based on transferred bytes vs total size.
        Formula: (transferred_bytes / total_requested_size) * 100%

        This ensures smooth, continuous progress as bytes are transferred.
        ===================================================================
        """
        transferred_str = self.format_size(transferred_bytes)

        if total_requested_size > 0 and num_requested_files > 0:
            completed = self.transfer_stats['completed_files']

            # Calculate byte-based progress
            overall_percent = int((transferred_bytes / total_requested_size) * 100)

            # Cap at 99% until all files are actually completed
            if completed >= num_requested_files:
                overall_percent = 100
            else:
                overall_percent = min(99, overall_percent)

            total_str = self.format_size(total_requested_size)

            # Show byte-based progress percentage with transferred bytes
            self.overall_progress.setFormat(f'{overall_percent}% ({transferred_str} / {total_str})')
            self.overall_progress.setValue(overall_percent)

            # Update files counter - show current file being installed (+1)
            # But when all files are completed (completed == num_requested_files), don't add +1
            if completed < num_requested_files:
                display_current = completed + 1
            else:
                display_current = completed
            self.overall_label.setText(f'{display_current} / {num_requested_files} files')

            # Calculate ETA based on bytes transferred and elapsed time
            if transferred_bytes > 0 and completed < num_requested_files:
                if self.transfer_stats.get('start_time'):
                    elapsed = (datetime.now() - self.transfer_stats['start_time']).total_seconds()
                    if elapsed > 0:
                        bytes_per_second = transferred_bytes / elapsed
                        remaining_bytes = total_requested_size - transferred_bytes
                        remaining_seconds = remaining_bytes / bytes_per_second if bytes_per_second > 0 else 0
                        eta_str = self.format_time(int(max(0, remaining_seconds)))
                        self.eta_label.setText(f'ETA: {eta_str}')
                    else:
                        self.eta_label.setText('ETA: Calculating...')
                else:
                    self.eta_label.setText('ETA: Calculating...')
            else:
                self.eta_label.setText('ETA: Calculating...')
        else:
            # Metadata phase or no data yet - show 0% progress
            self.overall_progress.setFormat(f'{transferred_str} total')
            self.overall_progress.setValue(0)
            self.eta_label.setText('ETA: Calculating...')

            if num_requested_files > 0:
                self.overall_label.setText(f'0 / {num_requested_files} files')

    def on_transfer_complete(self, filename: str):
        """Handle transfer completion"""
        self.transfer_stats['completed_files'] += 1
        self.log('success', f'Transfer complete: {filename}')

        # Mark file as 100% complete (delegate will show it with brighter color)
        self.progress_delegate.set_progress(filename, 100)

        # Update current progress bar to 100% for completed file
        self.current_progress.setValue(100)
        self.current_progress.setFormat('100%')

        # Trigger repaint
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item.text(1) == filename:
                for col in range(self.file_tree.columnCount()):
                    index = self.file_tree.indexFromItem(item, col)
                    self.file_tree.update(index)
                break

    def on_all_transfers_complete(self):
        """Handle completion of all transfers (Switch sent EXIT command)"""
        self.log('success', 'All transfers complete!')

        # Force both progress bars to 100%
        self.current_progress.setValue(100)
        self.current_progress.setFormat('100%')
        self.overall_progress.setValue(100)

    def log(self, level: str, message: str):
        """Add a log message with color coding"""
        timestamp = datetime.now().strftime('%H:%M:%S')

        color_map = {
            'info': '#2196F3',
            'success': '#4CAF50',
            'warning': '#FF9800',
            'error': '#F44336'
        }

        color = color_map.get(level, '#000000')
        icon_map = {
            'info': 'ℹ️',
            'success': '✓',
            'warning': '⚠',
            'error': '✗'
        }
        icon = icon_map.get(level, '')

        formatted = f'<span style="color: {color};">[{timestamp}] {icon} {message}</span>'
        self.log_text.append(formatted)

        # Limit log size
        if self.log_text.document().lineCount() > 1000:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()

    def clear_log(self):
        """Clear the log"""
        self.log_text.clear()

    def apply_theme(self, theme_name: str):
        """Apply a theme to the application"""
        stylesheet = self.theme_manager.get_theme(theme_name)
        self.setStyleSheet(stylesheet)
        self.config.set('theme', theme_name)
        self.log('info', f'Applied {theme_name} theme')

    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            'About DBI Backend Qt',
            '<h2>DBI Backend Qt</h2>'
            '<p>Enhanced GUI for transferring files to Nintendo Switch via DBI</p>'
            '<p><b>Features:</b></p>'
            '<ul>'
            '<li>Modern Qt interface with visual progress</li>'
            '<li>Accurate progress tracking (current & overall)</li>'
            '<li>Dark/Light themes</li>'
            '<li>Drag & drop support</li>'
            '<li>Windows Send to integration</li>'
            '<li>Batch file export (Ctrl+B)</li>'
            '<li>Multiple file selection</li>'
            '<li>Detailed logging to file</li>'
            '</ul>'
            '<p><b>Version 2.3.1</b></p>'
            '<p>Fixed progress bars, added visual feedback, detailed logging</p>'
        )

    def handle_external_files(self, message: str):
        """
        Handle files sent from another instance (via Send to or command line)
        Message format: file paths separated by newlines
        """
        paths = message.strip().split('\n')
        files_added = 0
        skipped_count = 0

        for path_str in paths:
            path_str = path_str.strip()
            if not path_str:
                continue

            file_path = Path(path_str)
            if not file_path.exists():
                continue

            if file_path.is_file():
                if self.is_supported_file(file_path):
                    self.file_list[file_path.name] = file_path.resolve()
                    files_added += 1
                else:
                    skipped_count += 1
            elif file_path.is_dir():
                # Recursively find all supported files in folder
                for f in file_path.rglob('*'):
                    if f.is_file():
                        if self.is_supported_file(f):
                            self.file_list[f.name] = f.resolve()
                            files_added += 1
                        else:
                            skipped_count += 1

        if files_added > 0:
            self.update_file_list()
            self.log("info", f"Added {files_added} file(s) from external source")

            if skipped_count > 0:
                self.log("warning", f"Skipped {skipped_count} unsupported file(s)")

            # Bring window to front and focus
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
                if self.is_supported_file(path):
                    files.append(path)
            elif path.is_dir():
                # Recursively find all supported files in dropped folder
                files.extend([f for f in path.rglob('*') if f.is_file() and self.is_supported_file(f)])

        added_count = 0
        for path in files:
            self.file_list[path.name] = path.resolve()
            added_count += 1

        if added_count > 0:
            self.update_file_list()
            self.log('info', f'Added {added_count} file(s) via drag & drop')

    def restore_geometry(self):
        """Restore window geometry from settings"""
        geometry = self.config.get('window_geometry')
        if geometry:
            try:
                # Decode from base64 string
                geometry_bytes = base64.b64decode(geometry)
                self.restoreGeometry(geometry_bytes)
            except Exception as e:
                print(f'Failed to restore geometry: {e}')

    def restore_splitter_sizes(self):
        """Restore splitter section sizes from settings"""
        sizes = self.config.get('splitter_sizes')
        if sizes and isinstance(sizes, list) and len(sizes) == self.splitter.count():
            self.splitter.setSizes(sizes)
            print(f'Restored splitter sizes: {sizes}')

    def closeEvent(self, event):
        """Handle window close event"""
        # Save window geometry (encode to base64 string for JSON)
        geometry_bytes = self.saveGeometry()
        geometry_str = base64.b64encode(geometry_bytes).decode('utf-8')
        self.config.set('window_geometry', geometry_str)

        # Save splitter sizes
        self.config.set('splitter_sizes', self.splitter.sizes())

        # Stop server if running
        if self.usb_handler and self.usb_handler.is_running:
            reply = QMessageBox.question(
                self,
                'Confirm Exit',
                'Server is running. Are you sure you want to exit?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.stop_server()

        self.config.save()
        event.accept()

    def update_splitter_handles(self):
        """Update splitter handle colors based on collapsed state"""
        sizes = self.splitter.sizes()

        # There are count-1 handles for count widgets
        for i in range(self.splitter.count() - 1):
            handle = self.splitter.handle(i + 1)  # Handle indices start at 1
            if isinstance(handle, CustomSplitterHandle):
                # This handle is between widget i and widget i+1
                # It should be blue ONLY if the widget AFTER it (i+1) is collapsed
                widget_after_collapsed = sizes[i + 1] == 0

                handle.is_collapsed = widget_after_collapsed
                handle.update()  # Trigger repaint

    @staticmethod
    def format_size(size: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f'{size:.1f} {unit}'
            size /= 1024.0
        return f'{size:.1f} PB'

    @staticmethod
    def format_time(seconds: int) -> str:
        """Format time in HH:MM:SS format"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f'{hours:02d}:{minutes:02d}:{secs:02d}'
