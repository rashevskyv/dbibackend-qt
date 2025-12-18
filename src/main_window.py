#!/usr/bin/env python3
"""
DBI Backend Qt - Main Window
Enhanced GUI for DBI file transfer to Nintendo Switch
"""

import sys
import json
import base64
import re
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QLabel, QProgressBar, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QLineEdit, QStatusBar, QSplitter, QSplitterHandle,
    QHeaderView, QStyle, QCheckBox, QGroupBox, QStyledItemDelegate,
    QInputDialog, QApplication, QTreeWidgetItemIterator, QComboBox,
    QDialog, QFormLayout, QSpinBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QRect, QEvent
from PyQt6.QtGui import QAction, QIcon, QDragEnterEvent, QDropEvent, QColor, QPainter, QBrush, QWheelEvent, QFont

from usb_handler import USBHandler, ConnectionStatus
from http_handler import HTTPHandler
from config_manager import ConfigManager
from theme_manager import ThemeManager


class FileTreeWidgetItem(QTreeWidgetItem):
    """Custom tree widget item that properly sorts numeric values and statuses"""
    
    def __lt__(self, other):
        """Override comparison for proper sorting"""
        if not isinstance(other, FileTreeWidgetItem):
            return super().__lt__(other)
            
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        
        # For checkbox column (column 0), compare checked state stored in UserRole
        if column == 0:
            self_state = self.data(0, Qt.ItemDataRole.UserRole) or 0
            other_state = other.data(0, Qt.ItemDataRole.UserRole) or 0
            return self_state < other_state
        
        # For size column (column 2), compare numeric values
        if column == 2:
            self_size = self.data(2, Qt.ItemDataRole.UserRole) or 0
            other_size = other.data(2, Qt.ItemDataRole.UserRole) or 0
            return self_size < other_size

        # For status column (column 3), compare status weights (Pending < Process < Failed < Done)
        if column == 3:
            self_status = self.data(3, Qt.ItemDataRole.UserRole) or 0
            other_status = other.data(3, Qt.ItemDataRole.UserRole) or 0
            return self_status < other_status
            
        # For other columns, use default comparison
        return super().__lt__(other)


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


class ZoomableTreeWidget(QTreeWidget):
    """QTreeWidget with Ctrl+Wheel zoom support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_level = 0  # Default zoom level (0 = 100%)
        self.base_font_size = 9  # Base font size in points
        self.min_zoom = -5  # Minimum zoom level
        self.max_zoom = 10  # Maximum zoom level
        # Default sort by Status (column 3)
        self.sortByColumn(3, Qt.SortOrder.AscendingOrder)
        self.header().setSortIndicatorShown(True)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel events for zooming with Ctrl"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Zoom with Ctrl+Wheel
            delta = event.angleDelta().y()
            if delta > 0:
                # Zoom in
                self.zoom_level = min(self.zoom_level + 1, self.max_zoom)
            else:
                # Zoom out
                self.zoom_level = max(self.zoom_level - 1, self.min_zoom)

            self.apply_zoom()
            event.accept()
        else:
            # Normal scrolling
            super().wheelEvent(event)

    def apply_zoom(self):
        """Apply the current zoom level to the widget"""
        # Calculate new font size based on zoom level
        new_size = self.base_font_size + self.zoom_level

        # Update font
        font = self.font()
        font.setPointSize(new_size)
        self.setFont(font)

        # Update row height to match new font size
        self.setStyleSheet(f"QTreeWidget {{ font-size: {new_size}pt; }}")

    def keyPressEvent(self, event):
        """Handle key press events for the tree widget"""
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            selected_items = self.selectedItems()
            if selected_items:
                window = self.window()
                if hasattr(window, "invert_selected_files"):
                    window.invert_selected_files()
                else:
                    # Fallback: invert directly if window handler is unavailable
                    for item in selected_items:
                        checkbox = self.itemWidget(item, 0)
                        if checkbox:
                            checkbox.setChecked(not checkbox.isChecked())
                event.accept()
                return

        super().keyPressEvent(event)


class ProgressDelegate(QStyledItemDelegate):
    """Custom delegate to draw progress bar background for file items"""

    def __init__(self, tree_widget, parent=None):
        super().__init__(parent)
        self.tree_widget = tree_widget
        self.progress_data = {}  # filename -> progress%
        self.skipped_files = set()  # filenames that were skipped

    def set_progress(self, filename: str, progress: int):
        """Set progress for a file"""
        self.progress_data[filename] = max(0, min(100, progress))

    def mark_skipped(self, filename: str):
        """Mark a file as skipped (will be shown in red)"""
        self.skipped_files.add(filename)

    def paint(self, painter, option, index):
        """Custom paint with progress bar background"""
        # Get the item from the tree widget
        item = self.tree_widget.itemFromIndex(index)
        if item:
            # Get filename from column 1 (name column)
            filename = item.text(1)

            # Check if file was skipped - show red background
            if filename in self.skipped_files:
                painter.save()
                # Full width red background for skipped files
                color = QColor(244, 67, 54, 100)  # Red with transparency
                painter.fillRect(option.rect, QBrush(color))
                painter.restore()
            else:
                # Normal progress display
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
        self.http_handler = None # New HTTP Handler
        self.file_list: Dict[str, Path] = {}
        self.transfer_stats = {
            'total_files': 0,
            'transferred_files': 0,
            'completed_files': 0,  # Files fully transferred
            'skipped_files': 0,  # Files skipped/interrupted by Switch
            'total_size': 0,
            'transferred_size': 0,
            'start_time': None,
            'current_speed': 0
        }
        self.completed_files_set = set() # Track unique completed files to avoid double counting
        self.current_processing_file = None  # Track which file is currently being processed
        self.presets_dir = self._get_presets_directory()

        self.init_ui()
        self.apply_theme(self.config.get('theme', 'light'))
        self.restore_geometry()
        self.restore_splitter_sizes()
        self.restore_zoom_level()

        # Initialize log file for new session (overwrite previous log)
        self._init_log_file()

        # Setup auto-reconnect timer
        self.reconnect_timer = QTimer()
        self.reconnect_timer.timeout.connect(self.check_connection)
        self.reconnect_timer.start(2000)  # Check every 2 seconds

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle('DBI Backend Qt v2.3.4')
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

        save_batch_action = QAction('Save as &Batch...', self)
        save_batch_action.setShortcut('Ctrl+B')
        save_batch_action.triggered.connect(self.save_file_list_as_batch)
        file_menu.addAction(save_batch_action)

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

        # Presets menu (Quick Load) - main menu with list of presets
        self.presets_menu = menubar.addMenu('&Presets')
        self.presets_menu.aboutToShow.connect(self.update_presets_menu)
        
        # Manage Presets submenu - store reference
        self.manage_presets_menu = self.presets_menu.addMenu('&Manage Presets')
        
        save_preset_action = QAction('Save Preset...', self)
        save_preset_action.setShortcut('Ctrl+Shift+S')
        save_preset_action.triggered.connect(self.save_preset)
        self.manage_presets_menu.addAction(save_preset_action)

        load_preset_action = QAction('Load Preset...', self)
        load_preset_action.setShortcut('Ctrl+Shift+L')
        load_preset_action.triggered.connect(self.load_preset)
        self.manage_presets_menu.addAction(load_preset_action)

        delete_preset_action = QAction('Delete Preset...', self)
        delete_preset_action.triggered.connect(self.delete_preset)
        self.manage_presets_menu.addAction(delete_preset_action)

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

        # Search box container - takes all remaining space
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText('🔍 Search files...')
        self.search_box.textChanged.connect(self.on_search_text_changed)
        self.search_box.setMinimumHeight(30)
        search_layout.addWidget(self.search_box)

        # Clear button (hidden by default)
        self.search_clear_btn = QPushButton('✕')
        self.search_clear_btn.setFixedSize(30, 30)
        self.search_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_clear_btn.clicked.connect(self.clear_search)
        self.search_clear_btn.setVisible(False)
        self.search_clear_btn.setStyleSheet('''
            QPushButton {
                border: none;
                background-color: transparent;
                color: #666;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #f44336;
                background-color: rgba(244, 67, 54, 0.1);
                border-radius: 15px;
            }
        ''')
        search_layout.addWidget(self.search_clear_btn)

        toolbar_layout.addWidget(search_container, 1)  # stretch factor 1

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
        """Create file list section with Mode Toggle and IP Label"""
        group = QGroupBox('File Queue')
        layout = QVBoxLayout()

        # File tree widget with zoom support
        self.file_tree = ZoomableTreeWidget()
        self.file_tree.setHeaderLabels(['', 'Filename', 'Size', 'Status', 'Path'])
        self.file_tree.setColumnWidth(0, 50)  # Checkbox
        self.file_tree.setColumnWidth(1, 250)  # Filename
        self.file_tree.setColumnWidth(2, 100)  # Size
        self.file_tree.setColumnWidth(3, 80)  # Status
        self.file_tree.setColumnWidth(4, 300)  # Path
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        # Enable sorting by clicking column headers
        self.file_tree.setSortingEnabled(True)
        # Default sort by Status (column 3), then Filename
        self.file_tree.sortByColumn(3, Qt.SortOrder.AscendingOrder) 

        # Enable multiple selection
        self.file_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        # Enable context menu
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.show_context_menu)

        # Set custom delegate for progress visualization
        self.progress_delegate = ProgressDelegate(self.file_tree, self.file_tree)
        self.file_tree.setItemDelegate(self.progress_delegate)

        # Add "select all" checkbox and Mode Toggle in header for column 0 area
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        # 1. Select All Checkbox
        self.header_checkbox = QCheckBox()
        self.header_checkbox.setTristate(True)  # Enable three states
        self.header_checkbox.setChecked(False) 
        self._updating_header_checkbox = False 
        self.header_checkbox.stateChanged.connect(self.on_header_checkbox_changed)
        header_layout.addWidget(self.header_checkbox)

        # Spacer
        header_layout.addStretch()

        # 2. Mode Toggle (USB / HTTP)
        header_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["USB Backend", "HTTP Server"])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        header_layout.addWidget(self.mode_combo)
        
        # 3. IP Label (Hidden in USB mode)
        self.ip_label = QLabel("")
        self.ip_label.setStyleSheet("color: #2196F3; font-weight: bold; margin-left: 10px;")
        self.ip_label.setVisible(False)
        header_layout.addWidget(self.ip_label)

        # Insert header widget before file tree
        layout.insertWidget(0, header_widget)

        layout.addWidget(self.file_tree)

        # File count label
        self.file_count_label = QLabel('0 files, 0 B total')
        layout.addWidget(self.file_count_label)

        group.setLayout(layout)
        return group
    
    def on_mode_changed(self, index):
        """Handle mode change (USB/HTTP)"""
        mode = self.mode_combo.currentText()
        if mode == "HTTP Server":
            self.server_label.setText("Start HTTP")
            self.connection_status.setText("🌐 HTTP Mode")
        else:
            self.server_label.setText("Start USB")
            self.connection_status.setText("🔴 Not connected")
            self.ip_label.setVisible(False)
            self.ip_label.setText("")

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
            
            current_checked_state = self._get_current_checked_state()
            added_count = 0
            for file_path in files:
                path = Path(file_path)
                if self.is_supported_file(path):
                    self.file_list[path.name] = path.resolve()
                    added_count += 1
                else:
                    self.log('warning', f'Skipped unsupported file: {path.name}')

            if added_count > 0:
                self.update_file_list(current_checked_state)
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

            current_checked_state = self._get_current_checked_state()
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
                self.update_file_list(current_checked_state)
                self.log('info', f'Added {added_count} file(s) from folder')

            if skipped_count > 0:
                self.log('warning', f'Skipped {skipped_count} unsupported file(s)')

    def on_item_checkbox_state_changed(self, item: QTreeWidgetItem, state: int):
        """Update stored state and refresh totals when an item's checkbox changes"""
        checked = (state == Qt.CheckState.Checked.value)
        item.setData(0, Qt.ItemDataRole.UserRole, 1 if checked else 0)
        self.update_total_size()
        self.update_header_checkbox_state()

    def update_file_list(self, checked_state: Optional[Dict[str, bool]] = None):
        """Update the file tree widget"""
        # Disable sorting during update for better performance
        self.file_tree.setSortingEnabled(False)
        self.file_tree.clear()

        for name, path in sorted(self.file_list.items()):
            item = FileTreeWidgetItem()

            # Checkbox
            checkbox = QCheckBox()
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            if checked_state and name in checked_state:
                checkbox.setChecked(bool(checked_state[name]))
            checkbox.blockSignals(False)
            # Store initial state for sorting
            item.setData(0, Qt.ItemDataRole.UserRole, 1 if checkbox.isChecked() else 0)
            checkbox.stateChanged.connect(
                lambda state, item=item: self.on_item_checkbox_state_changed(item, state)
            )
            self.file_tree.addTopLevelItem(item)
            self.file_tree.setItemWidget(item, 0, checkbox)

            # Filename
            item.setText(1, name)

            # Size (with error handling - file might not exist)
            try:
                size = path.stat().st_size
                item.setText(2, self.format_size(size))
                # Store numeric size for proper sorting
                item.setData(2, Qt.ItemDataRole.UserRole, size)
            except Exception as e:
                item.setText(2, "Error")
                item.setData(2, Qt.ItemDataRole.UserRole, 0)
                self.log('error', f'Cannot get size for {name}: {e}')

            # Status (initially empty)
            item.setText(3, "")
            # Set default sorting weight for status (0 = Pending)
            item.setData(3, Qt.ItemDataRole.UserRole, 0)

            # Path
            item.setText(4, str(path.parent))

        # Re-enable sorting after update
        self.file_tree.setSortingEnabled(True)

        # Update count label and total size
        self.update_total_size()
        
        # Update header checkbox state
        self.update_header_checkbox_state()

        # Enable/disable start button
        count = len(self.file_list)
        self.start_server_btn.setEnabled(count > 0)

    def update_total_size(self):
        """Update the total size label based on checked files only"""
        total_size = 0
        total_items = self.file_tree.topLevelItemCount()
        checked_count = 0

        for i in range(total_items):
            item = self.file_tree.topLevelItem(i)
            checkbox = self.file_tree.itemWidget(item, 0)

            if checkbox and checkbox.isChecked():
                checked_count += 1
                filename = item.text(1)
                if filename in self.file_list:
                    path = self.file_list[filename]
                    try:
                        size = path.stat().st_size
                        total_size += size
                    except Exception:
                        pass  # Size already shown as "Error" in the tree

        # Update count label
        count = len(self.file_list)
        if checked_count < count:
            self.file_count_label.setText(f'{count} file{"s" if count != 1 else ""} ({checked_count} checked), {self.format_size(total_size)} total')
        else:
            self.file_count_label.setText(f'{count} file{"s" if count != 1 else ""}, {self.format_size(total_size)} total')

    def update_file_status(self, filename: str, status: str):
        """Update the status of a file in the tree"""
        # Define sorting weights for statuses
        # 0: Pending (empty)
        # 1: Processing
        # 2: Failed
        # 3: Done
        status_weights = {
            '': 0,
            'process': 1,
            'failed': 2,
            'done': 3
        }

        highlight_colors = {
            'process': QColor('#E3F2FD'),  # Light blue
            'done': QColor('#E8F5E9'),     # Light green
            'failed': QColor('#FFEBEE')    # Light red
        }
        
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item.text(1) == filename:  # Column 1 is filename
                # Update status text with icon
                if status == 'process':
                    item.setText(3, '🔄 Process')
                    item.setForeground(3, QColor('#2196F3'))  # Blue
                elif status == 'done':
                    item.setText(3, '✓ Done')
                    item.setForeground(3, QColor('#4CAF50'))  # Green
                elif status == 'failed':
                    item.setText(3, '✗ Failed')
                    item.setForeground(3, QColor('#F44336'))  # Red
                else:
                    item.setText(3, '')
                    item.setForeground(3, self.palette().text().color())

                # Set numeric weight for sorting
                item.setData(3, Qt.ItemDataRole.UserRole, status_weights.get(status, 0))

                self._set_item_highlight(item, highlight_colors.get(status))
                break

    def get_file_status(self, filename: str) -> str:
        """Get the current status of a file in the tree"""
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item.text(1) == filename:  # Column 1 is filename
                return item.text(3)  # Column 3 is status
        return ''

    def _set_item_highlight(self, item: QTreeWidgetItem, color: Optional[QColor]):
        """Apply a background highlight color to all columns of an item"""
        brush = QBrush(color) if color else QBrush()
        for col in range(self.file_tree.columnCount()):
            item.setBackground(col, brush)

    def remove_file(self, filename: str):
        """Remove a file from the list"""
        if filename in self.file_list:
            current_checked_state = self._get_current_checked_state()
            del self.file_list[filename]
            self.update_file_list(current_checked_state)

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
        item = self.file_tree.itemAt(position)
        selected_items = self.file_tree.selectedItems()
        menu = QMenu()

        # Check/Uncheck Same Status
        if item:
            status = item.text(3)
            status_map = {
                '✓ Done': 'Done',
                '✗ Failed': 'Failed',
                '🔄 Process': 'Processing',
                '': 'Pending'
            }
            status_name = status_map.get(status, 'Pending')

            iterator = QTreeWidgetItemIterator(self.file_tree)
            same_status_items = []
            all_are_checked = True

            while iterator.value():
                it = iterator.value()
                if it.text(3) == status:
                    same_status_items.append(it)
                    checkbox = self.file_tree.itemWidget(it, 0)
                    if checkbox and not checkbox.isChecked():
                        all_are_checked = False
                iterator += 1

            if same_status_items:
                if all_are_checked:
                    action_text = f'☐ Uncheck all "{status_name}"'
                    target_state = False
                else:
                    action_text = f'✅ Check all "{status_name}"'
                    target_state = True

                action = QAction(action_text, self)
                action.triggered.connect(lambda _, s=status, st=target_state: self.set_check_state_by_status(s, st))
                menu.addAction(action)
                menu.addSeparator()

        # Delete selected
        if selected_items:
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

        # Invert selection
        invert_sel_action = QAction('🔄 Invert selected checks', self)
        invert_sel_action.triggered.connect(self.invert_selected_files)
        menu.addAction(invert_sel_action)

        # Invert All
        invert_all_action = QAction('🔄 Invert ALL checks', self)
        invert_all_action.triggered.connect(self.invert_all_checkboxes)
        menu.addAction(invert_all_action)

        menu.addSeparator()

        # Copy checked file names
        checked_count = self._count_checked_files()
        if checked_count > 0:
            copy_action = QAction(f'📋 Copy checked file names ({checked_count} files)', self)
            copy_action.triggered.connect(self.copy_checked_file_names)
            menu.addAction(copy_action)
            menu.addSeparator()

        # Select all / Select none
        select_all_action = QAction('⬜ Select all files', self)
        select_all_action.triggered.connect(self.file_tree.selectAll)
        menu.addAction(select_all_action)

        select_none_action = QAction('Clear selection', self)
        select_none_action.triggered.connect(self.file_tree.clearSelection)
        menu.addAction(select_none_action)

        menu.exec(self.file_tree.viewport().mapToGlobal(position))

    def set_check_state_by_status(self, status_text: str, state: bool):
        """Set checkbox state for all files matching a specific status"""
        iterator = QTreeWidgetItemIterator(self.file_tree)
        changed_count = 0
        
        while iterator.value():
            item = iterator.value()
            if item.text(3) == status_text:
                checkbox = self.file_tree.itemWidget(item, 0)
                if checkbox and checkbox.isChecked() != state:
                    checkbox.setChecked(state)
                    changed_count += 1
            iterator += 1
            
        if changed_count > 0:
            self.update_header_checkbox_state()
            action_name = "Checked" if state else "Unchecked"
            self.log('info', f'{action_name} {changed_count} files with status "{status_text}"')

    def invert_all_checkboxes(self):
        """Invert checkboxes for ALL files in the list"""
        iterator = QTreeWidgetItemIterator(self.file_tree)
        count = 0
        
        while iterator.value():
            item = iterator.value()
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox:
                checkbox.setChecked(not checkbox.isChecked())
                count += 1
            iterator += 1
            
        if count > 0:
            self.update_header_checkbox_state()
            self.log('info', f'Inverted checkboxes for all {count} files')

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
            current_checked_state = self._get_current_checked_state()
            for item in selected_items:
                filename = item.text(1)
                if filename in self.file_list:
                    del self.file_list[filename]

            self.update_file_list(current_checked_state)
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
        self.update_header_checkbox_state()

    def _count_checked_files(self) -> int:
        """Count files with checked checkboxes"""
        checked_count = 0
        total_items = self.file_tree.topLevelItemCount()
        for i in range(total_items):
            item = self.file_tree.topLevelItem(i)
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox and checkbox.isChecked():
                checked_count += 1
        return checked_count

    def _get_current_checked_state(self) -> Dict[str, bool]:
        """Get the current checked state of all items in the file tree"""
        states = {}
        iterator = QTreeWidgetItemIterator(self.file_tree)
        while iterator.value():
            item = iterator.value()
            filename = item.text(1)
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox:
                states[filename] = checkbox.isChecked()
            iterator += 1
        return states

    def copy_checked_file_names(self):
        """Copy names of all checked files to clipboard"""
        checked_names = []
        total_items = self.file_tree.topLevelItemCount()
        for i in range(total_items):
            item = self.file_tree.topLevelItem(i)
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox and checkbox.isChecked():
                filename = item.text(1)  # Column 1 is filename
                checked_names.append(filename)
        
        if checked_names:
            text_to_copy = '\n'.join(checked_names)
            clipboard = QApplication.clipboard()
            clipboard.setText(text_to_copy)
            self.log('info', f'Copied {len(checked_names)} file name(s) to clipboard')
        else:
            self.log('warning', 'No checked files to copy')

    def on_header_checkbox_changed(self, state):
        """Handle header checkbox state change - check/uncheck all files"""
        if self._updating_header_checkbox:
            return
        
        total_items = self.file_tree.topLevelItemCount()
        if total_items == 0:
            return
        
        checked_count = self._count_checked_files()
        
        if checked_count == total_items:
            target_checked = False  # All checked -> uncheck all
        else:
            target_checked = True   # Not all checked -> check all
        
        self._updating_header_checkbox = True
        
        for i in range(total_items):
            item = self.file_tree.topLevelItem(i)
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox:
                checkbox.blockSignals(True)
                checkbox.setChecked(target_checked)
                checkbox.blockSignals(False)
                item.setData(0, Qt.ItemDataRole.UserRole, 1 if target_checked else 0)
        
        self._updating_header_checkbox = False
        
        self.update_total_size()
        self.update_header_checkbox_state()

    def update_header_checkbox_state(self):
        """Update header checkbox state based on current file checkboxes"""
        self._updating_header_checkbox = True
        
        total_items = self.file_tree.topLevelItemCount()
        if total_items == 0:
            self.header_checkbox.setChecked(False)
            self.header_checkbox.setCheckState(Qt.CheckState.Unchecked)
            self._updating_header_checkbox = False
            return
        
        checked_count = self._count_checked_files()
        
        if checked_count == total_items:
            self.header_checkbox.setCheckState(Qt.CheckState.Unchecked)
        elif checked_count == 0:
            self.header_checkbox.setCheckState(Qt.CheckState.Checked)
        else:
            self.header_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
        
        self._updating_header_checkbox = False

    def on_search_text_changed(self, text: str):
        """Handle search text changes"""
        self.search_clear_btn.setVisible(bool(text))
        self.filter_file_list(text)

    def clear_search(self):
        """Clear search box text"""
        self.search_box.clear()

    def filter_file_list(self, text: str):
        """Filter file list based on search text"""
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            filename = item.text(1)
            item.setHidden(text.lower() not in filename.lower())

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
                import sys
                if getattr(sys, 'frozen', False):
                    app_path = sys.executable
                else:
                    app_path = str(Path(__file__).parent.parent / 'main.py')
                    app_path = f'python "{app_path}"'

                with open(filename, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('REM DBI Backend Qt - Auto-generated batch file\n')
                    f.write('REM Double-click to load these files into DBI Backend Qt\n\n')
                    f.write(f'{app_path}')
                    for name, path in sorted(self.file_list.items()):
                        f.write(f' "{path}"')
                    f.write('\n')

                self.log('success', f'Batch file saved: {filename}')
            except Exception as e:
                self.log('error', f'Failed to save batch file: {e}')
                QMessageBox.warning(self, 'Error', f'Failed to save batch file:\n{e}')

    def _get_current_preset_entries(self):
        """Return current file list with checkbox states"""
        entries = []
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            filename = item.text(1)
            path = self.file_list.get(filename)
            checkbox = self.file_tree.itemWidget(item, 0)
            entries.append({
                'name': filename,
                'path': str(path) if path else '',
                'checked': bool(checkbox.isChecked()) if checkbox else True
            })
        return entries

    def _prompt_preset_name(self) -> Optional[str]:
        """Prompt user for preset name"""
        name, ok = QInputDialog.getText(self, 'Save Preset', 'Preset name:')
        if not ok:
            return None
        sanitized = re.sub(r'[^\w\s\-]+', '', name).strip()
        if not sanitized:
            QMessageBox.warning(self, 'Invalid Name', 'Preset name cannot be empty.')
            return None
        return sanitized

    def _select_preset_file(self, title: str) -> Optional[Path]:
        """Prompt user to choose an existing preset"""
        presets = sorted(self.presets_dir.glob('*.json'))
        if not presets:
            QMessageBox.information(self, 'No Presets', 'No presets found. Save one first.')
            return None
        options = [preset.stem for preset in presets]
        name, ok = QInputDialog.getItem(self, title, 'Select preset:', options, 0, False)
        if not ok:
            return None
        selected = self.presets_dir / f'{name}.json'
        if not selected.exists():
            QMessageBox.warning(self, 'Not Found', f'Preset "{name}" does not exist.')
            return None
        return selected

    def save_preset(self):
        """Save current file list and checkbox states as preset"""
        if not self.file_list:
            QMessageBox.information(self, 'No Files', 'Add files before saving a preset.')
            return

        preset_name = self._prompt_preset_name()
        if not preset_name:
            return

        preset_path = self.presets_dir / f'{preset_name}.json'
        data = {
            'name': preset_name,
            'created_at': datetime.now().isoformat(),
            'files': self._get_current_preset_entries()
        }
        try:
            with open(preset_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.log('success', f'Preset saved: {preset_name}')
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Failed to save preset:\n{e}')

    def update_presets_menu(self):
        """Update presets menu with current presets list"""
        self.presets_menu.clear()
        presets = sorted(self.presets_dir.glob('*.json'))
        
        if not presets:
            no_presets_action = QAction('(No presets available)', self)
            no_presets_action.setEnabled(False)
            self.presets_menu.addAction(no_presets_action)
        else:
            for preset_file in presets:
                preset_name = preset_file.stem
                action = QAction(preset_name, self)
                action.triggered.connect(lambda checked, path=preset_file: self.load_preset_file(path))
                self.presets_menu.addAction(action)
        
        self.presets_menu.addSeparator()
        self.presets_menu.addMenu(self.manage_presets_menu)

    def load_preset_file(self, preset_file: Path):
        """Load preset from file path"""
        if not preset_file.exists():
            QMessageBox.warning(self, 'Not Found', f'Preset file does not exist.')
            return

        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            files = data.get('files', [])
            new_file_list = {}
            checked_state = {}
            missing = []

            for entry in files:
                path_str = entry.get('path')
                if not path_str:
                    continue
                path = Path(path_str)
                if not path.exists():
                    missing.append(path_str)
                    continue
                new_file_list[path.name] = path.resolve()
                checked_state[path.name] = bool(entry.get('checked', True))

            if not new_file_list:
                QMessageBox.warning(self, 'Preset Empty', 'No available files were found in this preset.')
                return

            self.file_list = new_file_list
            self.update_file_list(checked_state)
            self.log('success', f'Preset loaded: {preset_file.stem} ({len(new_file_list)} files)')

            if missing:
                self.log('warning', f'{len(missing)} file(s) from preset not found: {", ".join(missing[:5])}{"..." if len(missing) > 5 else ""}')
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Failed to load preset:\n{e}')
            self.log('error', f'Failed to load preset: {e}')

    def load_preset(self):
        """Load preset from a JSON file"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Load Preset File',
            str(self.presets_dir),
            'Preset Files (*.json);;All Files (*.*)'
        )

        if not filename:
            return

        preset_file = Path(filename)
        self.load_preset_file(preset_file)

    def delete_preset(self):
        """Delete a preset file"""
        preset_file = self._select_preset_file('Delete Preset')
        if not preset_file:
            return

        reply = QMessageBox.question(
            self,
            'Delete Preset',
            f'Delete preset "{preset_file.stem}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            preset_file.unlink()
            self.log('info', f'Preset deleted: {preset_file.stem}')
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Failed to delete preset:\n{e}')

    def toggle_server(self):
        """Start or stop the server (USB or HTTP based on mode)"""
        mode = self.mode_combo.currentText()
        
        if mode == "USB Backend":
            # USB Logic
            if self.usb_handler is None or not self.usb_handler.is_running:
                self.start_usb_server()
            else:
                reply = QMessageBox.question(
                    self,
                    'Stop USB Server',
                    'Stop USB server? Any ongoing transfer will be interrupted.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.stop_usb_server()
        else:
            # HTTP Logic
            if self.http_handler is None or not self.http_handler.is_running:
                self.start_http_server()
            else:
                self.stop_http_server()

    def get_checked_files(self) -> Dict[str, Path]:
        """Get only checked files from the file list"""
        checked_files = {}
        total_items = self.file_tree.topLevelItemCount()

        for i in range(total_items):
            item = self.file_tree.topLevelItem(i)
            checkbox = self.file_tree.itemWidget(item, 0)
            if checkbox and checkbox.isChecked():
                filename = item.text(1)
                if filename in self.file_list:
                    checked_files[filename] = self.file_list[filename]

        self.log('info', f'Selected {len(checked_files)} of {total_items} files')
        return checked_files

    def start_usb_server(self):
        """Start the USB server"""
        # Reset transfer stats and UI
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear() # Reset set
        self.current_processing_file = None
        self.progress_delegate.progress_data.clear()
        self.progress_delegate.skipped_files.clear()
        
        # Clear statuses
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            self.update_file_status(item.text(1), '')
            for col in range(self.file_tree.columnCount()):
                index = self.file_tree.indexFromItem(item, col)
                self.file_tree.update(index)

        checked_files = self.get_checked_files()
        if not checked_files:
            self.log('warning', 'No files selected! Please check at least one file.')
            return

        self.log('info', f'Starting USB server with {len(checked_files)} files')
        self.usb_handler = USBHandler(checked_files)
        self.usb_handler.connection_changed.connect(self.on_connection_changed)
        self.usb_handler.log_message.connect(self.log)
        self.usb_handler.progress_updated.connect(self.on_progress_updated)
        self.usb_handler.file_progress.connect(self.on_file_progress)
        self.usb_handler.transfer_complete.connect(self.on_transfer_complete)
        self.usb_handler.file_skipped.connect(self.on_file_skipped)
        self.usb_handler.transfer_reset.connect(self.on_transfer_reset)
        self.usb_handler.all_transfers_complete.connect(self.on_all_transfers_complete)

        self.usb_handler.start()
        self._set_server_ui_state(True)
        self.transfer_stats['start_time'] = datetime.now()
        self.transfer_stats['total_files'] = len(self.file_list)
        self.overall_label.setText(f'0 / ? files')
        self.log('info', 'USB Server started')

    def stop_usb_server(self):
        """Stop the USB server"""
        if self.usb_handler:
            self.usb_handler.stop()
            self.usb_handler = None
        
        self._set_server_ui_state(False)
        self.log('info', 'USB Server stopped')

    def start_http_server(self):
        """Start the HTTP server after configuring port"""
        checked_files = self.get_checked_files()
        if not checked_files:
            self.log('warning', 'No files selected! Please check at least one file.')
            return

        # 1. Prepare configuration dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Start HTTP Server")
        dialog.setMinimumWidth(300)
        
        layout = QVBoxLayout(dialog)
        form_layout = QFormLayout()
        
        # IP Display
        local_ip = HTTPHandler.get_local_ip()
        ip_label = QLabel(local_ip)
        ip_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        form_layout.addRow("Your IP:", ip_label)
        
        # Port Input
        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        # Use last used port or default 8080
        default_port = self.config.get('http_port', 8080)
        port_spin.setValue(default_port)
        form_layout.addRow("Port:", port_spin)
        
        layout.addLayout(form_layout)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        # 2. Show Dialog
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return # User cancelled
            
        selected_port = port_spin.value()
        
        # Save port for next time
        self.config.set('http_port', selected_port)
        self.config.save()

        # 3. Reset UI Stats
        self.transfer_stats['completed_files'] = 0
        self.completed_files_set.clear() # Reset set
        self.transfer_stats['start_time'] = datetime.now()
        self.progress_delegate.progress_data.clear()
        
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            self.update_file_status(item.text(1), '')
            for col in range(self.file_tree.columnCount()):
                index = self.file_tree.indexFromItem(item, col)
                self.file_tree.update(index)

        # 4. Initialize Handler with selected port
        self.http_handler = HTTPHandler(checked_files, port=selected_port)
        
        self.http_handler.log_message.connect(self.log)
        self.http_handler.server_started.connect(self.on_http_server_started)
        self.http_handler.server_stopped.connect(self.on_http_server_stopped)
        
        self.http_handler.progress_updated.connect(self.on_progress_updated)
        self.http_handler.file_progress.connect(self.on_file_progress)
        self.http_handler.transfer_complete.connect(self.on_transfer_complete)
        
        self.http_handler.start()
        self._set_server_ui_state(True)

    def stop_http_server(self):
        """Stop the HTTP server"""
        if self.http_handler:
            self.http_handler.stop()
            self.http_handler = None
        self._set_server_ui_state(False)

    def on_http_server_started(self, ip, port):
        """Handle HTTP server start confirmation"""
        url = f"http://{ip}:{port}/"
        dbi_config = f"Network repo=ApacheHTTP|{url}"
        
        self.log('success', f'HTTP Server listening at {url}')
        self.ip_label.setText(f"IP: {url}")
        self.ip_label.setVisible(True)
        self.connection_status.setText("🟢 HTTP Running")
        
        # Copy to clipboard automatically for convenience
        clipboard = QApplication.clipboard()
        clipboard.setText(dbi_config)
        self.log('info', 'DBI config line copied to clipboard!')

    def on_http_server_stopped(self):
        """Handle HTTP server stop"""
        self.log('info', 'HTTP Server stopped')
        self.ip_label.setVisible(False)
        self.connection_status.setText("🌐 HTTP Mode")

    def _set_server_ui_state(self, running: bool):
        """Update UI based on server running state"""
        if running:
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
            ''')
            self.server_label.setText('Stop Server')
            self.add_folder_btn.setEnabled(False)
            self.add_files_btn.setEnabled(False)
            self.clear_list_btn.setEnabled(False)
            self.mode_combo.setEnabled(False)
        else:
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
                QPushButton:disabled {
                    background-color: #BDBDBD;
                }
            ''')
            mode = self.mode_combo.currentText()
            self.server_label.setText(f'Start {"HTTP" if "HTTP" in mode else "USB"}')
            self.add_folder_btn.setEnabled(True)
            self.add_files_btn.setEnabled(True)
            self.clear_list_btn.setEnabled(True)
            self.mode_combo.setEnabled(True)

    def check_connection(self):
        """Check USB connection status"""
        # Only meaningful in USB mode
        if self.mode_combo.currentText() == "USB Backend":
             if self.usb_handler and self.usb_handler.is_running:
                 pass # USB Handler handles status updates
             elif not self.usb_handler:
                 # Check for idle connection? Usually we just wait for user to start
                 pass

    def on_connection_changed(self, status: ConnectionStatus):
        """Handle connection status changes (USB)"""
        if status == ConnectionStatus.CONNECTED:
            self.connection_status.setText('🟢 Connected')
            self.log('success', 'Connected to Switch')
        elif status == ConnectionStatus.CONNECTING:
            self.connection_status.setText('🟡 Connecting...')
        else:
            self.connection_status.setText('🔴 Not connected')
            if self.usb_handler and not self.usb_handler.is_running:
                 self._set_server_ui_state(False)

    def on_progress_updated(self, filename: str, transferred_bytes: int, speed_mbps: float, total_requested_size: int, num_requested_files: int, current_file_bytes: int, current_file_size: int, _unused: int):
        """Handle progress updates"""
        try:
            self.current_file_label.setText(filename) # Fixed double "Current:" text
            is_transfer_phase = current_file_size > 1024 * 1024 

            if is_transfer_phase:
                if self.current_processing_file != filename:
                    if self.current_processing_file is not None:
                        prev_status = self.get_file_status(self.current_processing_file)
                        if prev_status == '🔄 Process':
                            self.update_file_status(self.current_processing_file, 'done')

                    self.current_processing_file = filename
                    self.update_file_status(filename, 'process')

            if current_file_size > 0:
                if current_file_bytes >= current_file_size:
                    current_percent = 100
                else:
                    current_percent = int((current_file_bytes / current_file_size) * 100)
                current_bytes_str = self.format_size(current_file_bytes)
                current_size_str = self.format_size(current_file_size)
                self.current_progress.setFormat(f'{current_percent}% ({current_bytes_str} / {current_size_str})')
                self.current_progress.setValue(current_percent)
            else:
                current_bytes_str = self.format_size(current_file_bytes)
                self.current_progress.setFormat(f'{current_bytes_str} transferred')
                self.current_progress.setValue(0)

            self._update_overall_progress(transferred_bytes, total_requested_size, num_requested_files)

            self.speed_label.setText(f'Speed: {speed_mbps:.1f} MB/s')

            if self.transfer_stats.get('start_time'):
                elapsed = datetime.now() - self.transfer_stats['start_time']
                self.session_time_label.setText(f'Session: {self.format_time(int(elapsed.total_seconds()))}')

        except Exception as e:
            self.log('error', f'Progress update error: {e}')

    def on_file_progress(self, filename: str, progress: int):
        """Update visual progress for a file in the list"""
        self.progress_delegate.set_progress(filename, progress)
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item.text(1) == filename:
                for col in range(self.file_tree.columnCount()):
                    index = self.file_tree.indexFromItem(item, col)
                    self.file_tree.update(index)
                # REMOVED AUTO-SCROLL to fix jumping behavior
                # self.file_tree.scrollToItem(item, QTreeWidget.ScrollHint.PositionAtCenter)
                break

    def _update_overall_progress(self, transferred_bytes: int, total_requested_size: int, num_requested_files: int):
        """Update overall progress bar"""
        transferred_str = self.format_size(transferred_bytes)

        if total_requested_size > 0 and num_requested_files > 0:
            completed = self.transfer_stats['completed_files']
            skipped = self.transfer_stats['skipped_files']
            processed = completed + skipped
            
            # Calculate percentage
            if total_requested_size > 0:
                raw_percent = (transferred_bytes / total_requested_size) * 100
            else:
                raw_percent = 0
            
            # Use standard rounding
            overall_percent = int(round(raw_percent))
            
            # Allow 100% if we have transferred all bytes OR if all files are processed
            if transferred_bytes >= total_requested_size or processed >= num_requested_files:
                overall_percent = 100
            else:
                overall_percent = min(99, overall_percent)

            total_str = self.format_size(total_requested_size)
            self.overall_progress.setFormat(f'{overall_percent}% ({transferred_str} / {total_str})')
            self.overall_progress.setValue(overall_percent)

            # Cap display at num_requested_files
            display_current = min(processed + 1, num_requested_files)
            if processed >= num_requested_files:
                display_current = num_requested_files
                
            self.overall_label.setText(f'{display_current} / {num_requested_files} files')

            if transferred_bytes > 0 and processed < num_requested_files:
                if self.transfer_stats.get('start_time'):
                    elapsed = (datetime.now() - self.transfer_stats['start_time']).total_seconds()
                    if elapsed > 0:
                        bytes_per_second = transferred_bytes / elapsed
                        if bytes_per_second > 0:
                            remaining_bytes = max(0, total_requested_size - transferred_bytes)
                            remaining_seconds = remaining_bytes / bytes_per_second
                            eta_str = self.format_time(int(remaining_seconds))
                            self.eta_label.setText(f'ETA: {eta_str}')
                        else:
                            self.eta_label.setText('ETA: --:--:--')
                    else:
                        self.eta_label.setText('ETA: Calculating...')
            elif overall_percent >= 100:
                 self.eta_label.setText('ETA: Done')
        else:
            self.overall_progress.setFormat(f'{transferred_str} total')
            self.overall_progress.setValue(0)
            self.eta_label.setText('ETA: Calculating...')
            if num_requested_files > 0:
                self.overall_label.setText(f'0 / {num_requested_files} files')

    def on_transfer_complete(self, filename: str):
        """Handle transfer completion"""
        # Ensure we don't double count completed files in HTTP mode
        if filename not in self.completed_files_set:
            self.completed_files_set.add(filename)
            self.transfer_stats['completed_files'] += 1
            self.log('success', f'Transfer complete: {filename}')
            self.update_file_status(filename, 'done')
            self.progress_delegate.set_progress(filename, 100)
            
            # Update item visuals
            for i in range(self.file_tree.topLevelItemCount()):
                item = self.file_tree.topLevelItem(i)
                if item.text(1) == filename:
                    checkbox = self.file_tree.itemWidget(item, 0)
                    if checkbox:
                        checkbox.setChecked(False)
                    for col in range(self.file_tree.columnCount()):
                        index = self.file_tree.indexFromItem(item, col)
                        self.file_tree.update(index)
                    break
        
        self.current_progress.setValue(100)
        self.current_progress.setFormat('100%')
        
        # Force update overall progress to check if we are at 100% now
        if self.http_handler and self.http_handler.is_running:
             # Use cached values from handler to refresh UI
             self._update_overall_progress(
                 self.http_handler.total_bytes_transferred, # approximation or get from thread safely
                 self.http_handler.total_requested_size,
                 len(self.http_handler.requested_files)
             )

    def on_file_skipped(self, filename: str, file_size: int):
        """Handle file skip/interruption"""
        self.transfer_stats['skipped_files'] += 1
        self.log('warning', f'File skipped by Switch: {filename}')
        self.update_file_status(filename, 'failed')
        if self.current_processing_file == filename:
            self.current_processing_file = None
        self.progress_delegate.mark_skipped(filename)
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            if item.text(1) == filename:
                for col in range(self.file_tree.columnCount()):
                    index = self.file_tree.indexFromItem(item, col)
                    self.file_tree.update(index)
                break

    def on_transfer_reset(self):
        """Handle transfer reset"""
        self.log('info', 'Transfer reset - Switch restarted file selection')
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear()
        self.transfer_stats['start_time'] = None
        self.progress_delegate.progress_data.clear()
        self.progress_delegate.skipped_files.clear()
        self.current_processing_file = None
        
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            self.update_file_status(item.text(1), '')
            for col in range(self.file_tree.columnCount()):
                index = self.file_tree.indexFromItem(item, col)
                self.file_tree.update(index)

        self.current_progress.setValue(0)
        self.overall_progress.setValue(0)
        self.current_file_label.setText('No transfer in progress')

    def on_all_transfers_complete(self):
        """Handle completion of all transfers"""
        self.log('success', 'All transfers complete!')
        if self.current_processing_file is not None:
            prev_status = self.get_file_status(self.current_processing_file)
            if prev_status == '🔄 Process':
                self.update_file_status(self.current_processing_file, 'done')
            self.current_processing_file = None
        self.current_progress.setValue(100)
        self.overall_progress.setValue(100)

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
        icon_map = {
            'debug': '🔍',
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
            '<li>USB Backend (MTP/DBI Protocol)</li>'
            '<li>HTTP Server (Install from HTTP)</li>'
            '<li>Modern Qt interface with visual progress</li>'
            '<li>Accurate progress tracking</li>'
            '<li>Dark/Light themes</li>'
            '<li>Drag & drop support</li>'
            '</ul>'
            '<p><b>Version 2.3.4</b></p>'
        )

    def handle_external_files(self, message: str):
        """Handle files sent from another instance"""
        current_checked_state = self._get_current_checked_state()
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
                for f in file_path.rglob('*'):
                    if f.is_file():
                        if self.is_supported_file(f):
                            self.file_list[f.name] = f.resolve()
                            files_added += 1
                        else:
                            skipped_count += 1

        if files_added > 0:
            self.update_file_list(current_checked_state)
            self.log("info", f"Added {files_added} file(s) from external source")

            if skipped_count > 0:
                self.log("warning", f"Skipped {skipped_count} unsupported file(s)")

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
                files.extend([f for f in path.rglob('*') if f.is_file() and self.is_supported_file(f)])

        current_checked_state = self._get_current_checked_state()
        added_count = 0
        for path in files:
            self.file_list[path.name] = path.resolve()
            added_count += 1

        if added_count > 0:
            self.update_file_list(current_checked_state)
            self.log('info', f'Added {added_count} file(s) via drag & drop')

    def restore_geometry(self):
        """Restore window geometry from settings"""
        geometry = self.config.get('window_geometry')
        if geometry:
            try:
                geometry_bytes = base64.b64decode(geometry)
                self.restoreGeometry(geometry_bytes)
            except Exception as e:
                print(f'Failed to restore geometry: {e}')

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

    def closeEvent(self, event):
        """Handle window close event"""
        geometry_bytes = self.saveGeometry()
        geometry_str = base64.b64encode(geometry_bytes).decode('utf-8')
        self.config.set('window_geometry', geometry_str)
        self.config.set('splitter_sizes', self.splitter.sizes())
        self.config.set('file_tree_zoom', self.file_tree.zoom_level)

        if self.usb_handler and self.usb_handler.is_running:
            reply = QMessageBox.question(
                self, 'Confirm Exit', 'USB Server is running. Exit?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.stop_usb_server()
            
        if self.http_handler and self.http_handler.is_running:
            self.stop_http_server()

        self.config.save()
        event.accept()

    def _init_log_file(self):
        """Initialize log file for new session"""
        try:
            log_file = Path("log.txt")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== DBI Backend Qt Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception as e:
            print(f"Cannot create log file: {e}")

    def update_splitter_handles(self):
        """Update splitter handle colors based on collapsed state"""
        sizes = self.splitter.sizes()
        for i in range(self.splitter.count() - 1):
            handle = self.splitter.handle(i + 1)
            if isinstance(handle, CustomSplitterHandle):
                widget_after_collapsed = sizes[i + 1] == 0
                handle.is_collapsed = widget_after_collapsed
                handle.update()

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

    def _get_presets_directory(self) -> Path:
        """Ensure and return the presets directory"""
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).parent.parent

        presets_dir = base_dir / 'presets'
        presets_dir.mkdir(exist_ok=True)
        return presets_dir

    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key.Key_Space:
            self.invert_selected_files()
            event.accept()
        else:
            super().keyPressEvent(event)