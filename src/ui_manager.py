"""
UI Manager for DBI Backend
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QProgressBar, QMenuBar, QMenu, QLineEdit, QStatusBar,
    QHeaderView, QCheckBox, QGroupBox, QComboBox, QTreeWidget,
    QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

# Import custom widgets
from .widgets import (
    ZoomableTreeWidget, CustomSplitter, ProgressDelegate, AnimatedProgressBar,
    ModeSwitch, CheckBoxHeaderView, ElidingLabel
)
from .storage_widget import SwitchStorageWidget
from .usb_driver import can_install_driver


class UIManager:
    """Manages the creation of UI components."""

    def __init__(self, main_window):
        self.main_window = main_window

    def create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.main_window.menuBar()

        # File menu
        file_menu = menubar.addMenu('&File')
        
        add_files_action = QAction('Add &Files...', self.main_window)
        add_files_action.setShortcut('Ctrl+O')
        add_files_action.triggered.connect(self.main_window.add_files)
        file_menu.addAction(add_files_action)

        add_folder_action = QAction('Add F&older...', self.main_window)
        add_folder_action.setShortcut('Ctrl+Shift+O')
        add_folder_action.triggered.connect(self.main_window.add_folder)
        file_menu.addAction(add_folder_action)

        file_menu.addSeparator()

        save_batch_action = QAction('Save as &Batch...', self.main_window)
        save_batch_action.setShortcut('Ctrl+B')
        save_batch_action.triggered.connect(self.main_window.save_file_list_as_batch)
        file_menu.addAction(save_batch_action)

        file_menu.addSeparator()

        exit_action = QAction('E&xit', self.main_window)
        exit_action.setShortcut('Alt+F4')
        exit_action.triggered.connect(self.main_window.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu('&View')

        auto_theme_action = QAction('&Automatic Theme', self.main_window)
        auto_theme_action.triggered.connect(lambda: self.main_window.apply_theme('auto'))
        view_menu.addAction(auto_theme_action)
        
        view_menu.addSeparator()

        light_theme_action = QAction('&Light Theme', self.main_window)
        light_theme_action.triggered.connect(lambda: self.main_window.apply_theme('light'))
        view_menu.addAction(light_theme_action)

        dark_theme_action = QAction('&Dark Theme', self.main_window)
        dark_theme_action.triggered.connect(lambda: self.main_window.apply_theme('dark'))
        view_menu.addAction(dark_theme_action)

        view_menu.addSeparator()

        clear_log_action = QAction('Clear &Log', self.main_window)
        clear_log_action.triggered.connect(self.main_window.clear_log)
        view_menu.addAction(clear_log_action)

        # Presets menu
        self.main_window.presets_menu = menubar.addMenu('&Presets')
        self.main_window.presets_menu.aboutToShow.connect(self.main_window.update_presets_menu)
        
        # Flattened Presets Menu Actions
        save_preset_action = QAction('Save Preset...', self.main_window)
        save_preset_action.setShortcut('Ctrl+Shift+S')
        save_preset_action.triggered.connect(self.main_window.save_preset)
        self.main_window.presets_menu.addAction(save_preset_action)

        load_preset_action = QAction('Load Preset from File...', self.main_window)
        load_preset_action.setShortcut('Ctrl+Shift+L')
        load_preset_action.triggered.connect(self.main_window.load_preset)
        self.main_window.presets_menu.addAction(load_preset_action)

        delete_preset_action = QAction('Delete Preset...', self.main_window)
        delete_preset_action.triggered.connect(self.main_window.delete_preset)
        self.main_window.presets_menu.addAction(delete_preset_action)

        self.main_window.presets_menu.addSeparator()

        # Help menu
        help_menu = menubar.addMenu('&Help')
        if can_install_driver():
            driver_action = QAction('Install USB Driver...', self.main_window)
            driver_action.triggered.connect(lambda: self.main_window.offer_usb_driver_install('manual'))
            help_menu.addAction(driver_action)
        about_action = QAction('&About', self.main_window)
        about_action.triggered.connect(self.main_window.show_about)
        help_menu.addAction(about_action)

    def create_toolbar(self, layout):
        """Create toolbar with main actions"""
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(10)

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

        files_container, self.main_window.add_files_btn = create_button('📄', 'Add Files', self.main_window.add_files)
        toolbar_layout.addWidget(files_container)

        folder_container, self.main_window.add_folder_btn = create_button('📁', 'Add Folder', self.main_window.add_folder)
        toolbar_layout.addWidget(folder_container)

        clear_container, self.main_window.clear_list_btn = create_button('🗑️', 'Clear List', self.main_window.clear_file_list)
        toolbar_layout.addWidget(clear_container)

        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        self.main_window.search_box = QLineEdit()
        self.main_window.search_box.setPlaceholderText('🔍 Search files...')
        self.main_window.search_box.textChanged.connect(self.main_window.on_search_text_changed)
        self.main_window.search_box.setMinimumHeight(30)
        search_layout.addWidget(self.main_window.search_box)

        self.main_window.search_clear_btn = QPushButton('✕')
        self.main_window.search_clear_btn.setFixedSize(30, 30)
        self.main_window.search_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_window.search_clear_btn.clicked.connect(self.main_window.clear_search)
        self.main_window.search_clear_btn.setVisible(False)
        self.main_window.search_clear_btn.setStyleSheet('''
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
        search_layout.addWidget(self.main_window.search_clear_btn)

        toolbar_layout.addWidget(search_container, 1)

        server_container = QWidget()
        server_layout = QVBoxLayout(server_container)
        server_layout.setContentsMargins(0, 0, 0, 0)
        server_layout.setSpacing(2)

        self.main_window.start_server_btn = QPushButton('▶')
        self.main_window.start_server_btn.setFixedSize(60, 60)
        self.main_window.start_server_btn.clicked.connect(self.main_window.toggle_server)
        self.main_window.start_server_btn.setEnabled(True)
        self.main_window.start_server_btn.setStyleSheet('''
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
        server_layout.addWidget(self.main_window.start_server_btn)

        self.main_window.server_label = QLabel('Start Server')
        self.main_window.server_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_window.server_label.setStyleSheet('font-size: 10px;')
        server_layout.addWidget(self.main_window.server_label)

        toolbar_layout.addWidget(server_container)

        layout.addLayout(toolbar_layout)

    def create_file_section(self):
        """Create file list section with Mode Toggle and IP Label"""
        group = QGroupBox('File Queue')
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Pass main_window to tree for file_manager access
        self.main_window.file_tree = ZoomableTreeWidget(self.main_window)
        header = CheckBoxHeaderView(Qt.Orientation.Horizontal, self.main_window.file_tree)
        self.main_window.file_tree.setHeader(header)
        self.main_window.header_checkbox = header.checkbox
        self.main_window.header_checkbox.stateChanged.connect(self.main_window.on_header_checkbox_changed)
        self.main_window.file_tree.horizontalScrollBar().valueChanged.connect(header.update_checkbox_geometry)

        self.main_window.file_tree.setHeaderLabels(['', 'Filename', 'Size', 'Target', 'Status', 'Path'])
        self.main_window.file_tree.setColumnWidth(0, 50)
        self.main_window.file_tree.setColumnWidth(1, 250)
        self.main_window.file_tree.setColumnWidth(2, 90)
        self.main_window.file_tree.setColumnWidth(3, 110)
        self.main_window.file_tree.setColumnWidth(4, 90)
        self.main_window.file_tree.setColumnWidth(5, 300)
        self.main_window.file_tree.setAlternatingRowColors(True)
        self.main_window.file_tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self.main_window.file_tree.setSortingEnabled(False)

        self.main_window.file_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        self.main_window.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.main_window.file_tree.customContextMenuRequested.connect(self.main_window.show_context_menu)

        self.main_window.progress_delegate = ProgressDelegate(self.main_window.file_tree, self.main_window.file_tree)
        self.main_window.file_tree.setItemDelegate(self.main_window.progress_delegate)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(10)

        self.header_widget = header_widget

        # Sphaira-style dual storage bars for microSD and NAND
        self.main_window.storage_bars = SwitchStorageWidget(header_widget)
        self.storage_bars = self.main_window.storage_bars
        header_layout.addWidget(self.main_window.storage_bars, 2)

        # Retain switch_storage_label for tests and backwards compatibility
        self.main_window.switch_storage_label = ElidingLabel("")
        self.switch_storage_label = self.main_window.switch_storage_label
        self.main_window.switch_storage_label.hide()
        header_layout.addWidget(self.main_window.switch_storage_label)

        header_layout.addStretch(1)
        
        # --- Mode Switch ---
        self.main_window.usb_label = QLabel("USB")
        self.main_window.usb_label.setStyleSheet("font-weight: bold; color: #4CAF50;") # Default USB active
        header_layout.addWidget(self.main_window.usb_label)

        mode_container = QWidget()
        mode_layout = QVBoxLayout(mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(0)
        self.main_window.http_label = QLabel("HTTP")
        self.main_window.http_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_window.http_label.setFixedHeight(14)
        self.main_window.http_label.setStyleSheet("color: gray; font-size: 10px;")
        mode_layout.addWidget(self.main_window.http_label)

        self.main_window.mode_switch = ModeSwitch()
        self.main_window.mode_switch.modeChanged.connect(self.main_window.on_mode_switched)
        mode_layout.addWidget(self.main_window.mode_switch)
        header_layout.addWidget(mode_container)

        self.main_window.ftp_label = QLabel("FTP")
        self.main_window.ftp_label.setStyleSheet("color: gray;")
        header_layout.addWidget(self.main_window.ftp_label)
        
        self.main_window.ip_label = QLabel("")
        self.main_window.ip_label.setStyleSheet("color: #2196F3; font-weight: bold; margin-left: 10px;")
        self.main_window.ip_label.setVisible(False)
        header_layout.addWidget(self.main_window.ip_label)
        
        layout.insertWidget(0, header_widget)

        layout.addWidget(self.main_window.file_tree)

        self.main_window.file_count_label = QLabel('0 files, 0 B total')
        layout.addWidget(self.main_window.file_count_label)

        group.setLayout(layout)
        return group
    
    def create_progress_section(self):
        """Create progress bars section"""
        group = QGroupBox('Transfer Progress')
        group.setMaximumHeight(180)
        layout = QVBoxLayout()

        current_layout = QHBoxLayout()
        current_layout.addWidget(QLabel('Current:'))
        self.main_window.current_file_label = QLabel('No transfer in progress')
        current_layout.addWidget(self.main_window.current_file_label)
        current_layout.addStretch()
        layout.addLayout(current_layout)

        # Use AnimatedProgressBar
        self.main_window.current_progress = AnimatedProgressBar()
        self.main_window.current_progress.setTextVisible(True)
        self.main_window.current_progress.setFormat('%p%')
        layout.addWidget(self.main_window.current_progress)

        overall_layout = QHBoxLayout()
        overall_layout.addWidget(QLabel('Overall:'))
        self.main_window.overall_label = QLabel('0 / 0 files')
        overall_layout.addWidget(self.main_window.overall_label)
        overall_layout.addStretch()
        self.main_window.eta_label = QLabel('ETA: --:--:--')
        overall_layout.addWidget(self.main_window.eta_label)
        layout.addLayout(overall_layout)

        self.main_window.overall_progress = QProgressBar()
        self.main_window.overall_progress.setTextVisible(True)
        layout.addWidget(self.main_window.overall_progress)

        stats_layout = QHBoxLayout()
        self.main_window.speed_label = QLabel('Speed: 0 MB/s')
        stats_layout.addWidget(self.main_window.speed_label)
        stats_layout.addStretch()

        self.main_window.auto_connect_checkbox = QCheckBox('Start USB server when Switch connects')
        self.main_window.auto_connect_checkbox.setToolTip('Start the USB server by itself as soon as a Switch in USB install mode is plugged in (Kefir Hub opens that mode automatically)')
        self.main_window.auto_connect_checkbox.setChecked(bool(self.main_window.config.get('auto_connect', True)))
        self.main_window.auto_connect_checkbox.toggled.connect(lambda c: self.main_window.server_manager.on_auto_connect_toggled(c))
        stats_layout.addWidget(self.main_window.auto_connect_checkbox)

        self.main_window.hibernate_checkbox = QCheckBox('Hibernate PC when idle (5 min)')
        self.main_window.hibernate_checkbox.setToolTip('Automatically hibernate PC after 5 minutes of inactivity between Switch and PC')
        self.main_window.hibernate_checkbox.setChecked(self.main_window.config.get('hibernate_when_done', False))
        self.main_window.hibernate_checkbox.toggled.connect(self.main_window.on_hibernate_toggled)
        stats_layout.addWidget(self.main_window.hibernate_checkbox)

        self.main_window.session_time_label = QLabel('')
        stats_layout.addWidget(self.main_window.session_time_label)
        layout.addLayout(stats_layout)

        group.setLayout(layout)
        return group

    def create_log_section(self):
        """Create log section"""
        group = QGroupBox('Activity Log')
        layout = QVBoxLayout()

        self.main_window.log_text = QTextEdit()
        self.main_window.log_text.setReadOnly(True)
        self.main_window.log_text.setMinimumHeight(100)

        layout.addWidget(self.main_window.log_text)

        group.setLayout(layout)
        return group

    def create_status_bar(self):
        """Create status bar"""
        self.main_window.statusBar = QStatusBar()
        self.main_window.setStatusBar(self.main_window.statusBar)

        self.main_window.queue_sync_status = QLabel('')
        self.main_window.queue_sync_status.setStyleSheet('color: #2196F3; margin-right: 15px;')
        self.main_window.statusBar.addPermanentWidget(self.main_window.queue_sync_status)

        self.main_window.connection_status = QLabel('🔴 Not connected')
        self.main_window.statusBar.addPermanentWidget(self.main_window.connection_status)
