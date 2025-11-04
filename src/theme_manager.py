"""
Theme Manager
Provides light and dark themes for the application
"""


class ThemeManager:
    """Manages application themes"""

    LIGHT_THEME = """
    QMainWindow {
        background-color: #f5f5f5;
    }

    QMenuBar {
        background-color: #ffffff;
        border-bottom: 1px solid #e0e0e0;
    }

    QMenu {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
    }

    QMenu::item:selected {
        background-color: #e3f2fd;
        color: #000000;
    }

    QPushButton {
        background-color: #2196F3;
        color: white;
        border: none;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 13px;
    }

    QPushButton:hover {
        background-color: #1976D2;
    }

    QPushButton:pressed {
        background-color: #0D47A1;
    }

    QPushButton:disabled {
        background-color: #BDBDBD;
    }

    QLineEdit {
        background-color: white;
        border: 1px solid #BDBDBD;
        border-radius: 4px;
        padding: 6px;
        font-size: 13px;
    }

    QLineEdit:focus {
        border: 2px solid #2196F3;
    }

    QTreeWidget {
        background-color: white;
        border: 1px solid #e0e0e0;
        border-radius: 4px;
        alternate-background-color: #f9f9f9;
    }

    QTreeWidget::item:selected {
        background-color: #e3f2fd;
        color: black;
    }

    QTreeWidget::item:hover {
        background-color: #f5f5f5;
    }

    QHeaderView::section {
        background-color: #f5f5f5;
        padding: 6px;
        border: none;
        border-bottom: 2px solid #2196F3;
        font-weight: bold;
    }

    QProgressBar {
        border: 1px solid #e0e0e0;
        border-radius: 4px;
        text-align: center;
        background-color: white;
    }

    QProgressBar::chunk {
        background-color: #4CAF50;
        border-radius: 3px;
    }

    QTextEdit {
        background-color: white;
        border: 1px solid #e0e0e0;
        border-radius: 4px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 12px;
    }

    QGroupBox {
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        margin-top: 12px;
        font-weight: bold;
        padding-top: 10px;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        background-color: #f5f5f5;
        color: #2196F3;
    }

    QLabel {
        color: #424242;
    }

    QStatusBar {
        background-color: #f5f5f5;
        border-top: 1px solid #e0e0e0;
    }

    QScrollBar:vertical {
        border: none;
        background-color: #f5f5f5;
        width: 12px;
        margin: 0;
    }

    QScrollBar::handle:vertical {
        background-color: #BDBDBD;
        border-radius: 6px;
        min-height: 20px;
    }

    QScrollBar::handle:vertical:hover {
        background-color: #9E9E9E;
    }

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    """

    DARK_THEME = """
    QMainWindow {
        background-color: #1e1e1e;
        color: #e0e0e0;
    }

    QWidget {
        color: #e0e0e0;
    }

    QMenuBar {
        background-color: #2d2d2d;
        border-bottom: 1px solid #3d3d3d;
        color: #e0e0e0;
    }

    QMenu {
        background-color: #2d2d2d;
        border: 1px solid #3d3d3d;
        color: #e0e0e0;
    }

    QMenu::item:selected {
        background-color: #094771;
        color: #ffffff;
    }

    QPushButton {
        background-color: #0d7ec1;
        color: white;
        border: none;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 13px;
    }

    QPushButton:hover {
        background-color: #1a8dd4;
    }

    QPushButton:pressed {
        background-color: #076ba8;
    }

    QPushButton:disabled {
        background-color: #3d3d3d;
        color: #6d6d6d;
    }

    QLineEdit {
        background-color: #2d2d2d;
        border: 1px solid #3d3d3d;
        border-radius: 4px;
        padding: 6px;
        color: #e0e0e0;
        font-size: 13px;
    }

    QLineEdit:focus {
        border: 2px solid #0d7ec1;
    }

    QTreeWidget {
        background-color: #2d2d2d;
        border: 1px solid #3d3d3d;
        border-radius: 4px;
        alternate-background-color: #252525;
        color: #e0e0e0;
    }

    QTreeWidget::item:selected {
        background-color: #094771;
        color: #ffffff;
    }

    QTreeWidget::item:hover {
        background-color: #3d3d3d;
    }

    QHeaderView::section {
        background-color: #2d2d2d;
        padding: 6px;
        border: none;
        border-bottom: 2px solid #0d7ec1;
        color: #e0e0e0;
        font-weight: bold;
    }

    QProgressBar {
        border: 1px solid #3d3d3d;
        border-radius: 4px;
        text-align: center;
        background-color: #2d2d2d;
        color: #e0e0e0;
    }

    QProgressBar::chunk {
        background-color: #0d7ec1;
        border-radius: 3px;
    }

    QTextEdit {
        background-color: #2d2d2d;
        border: 1px solid #3d3d3d;
        border-radius: 4px;
        color: #e0e0e0;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 12px;
    }

    QGroupBox {
        border: 1px solid #3d3d3d;
        border-radius: 6px;
        margin-top: 12px;
        font-weight: bold;
        padding-top: 10px;
        color: #e0e0e0;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        background-color: #1e1e1e;
        color: #0d7ec1;
    }

    QLabel {
        color: #e0e0e0;
    }

    QStatusBar {
        background-color: #2d2d2d;
        border-top: 1px solid #3d3d3d;
        color: #e0e0e0;
    }

    QScrollBar:vertical {
        border: none;
        background-color: #2d2d2d;
        width: 12px;
        margin: 0;
    }

    QScrollBar::handle:vertical {
        background-color: #4d4d4d;
        border-radius: 6px;
        min-height: 20px;
    }

    QScrollBar::handle:vertical:hover {
        background-color: #5d5d5d;
    }

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }

    QCheckBox {
        color: #e0e0e0;
    }

    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #3d3d3d;
        border-radius: 3px;
        background-color: #2d2d2d;
    }

    QCheckBox::indicator:checked {
        background-color: #0d7ec1;
        border: 1px solid #0d7ec1;
    }
    """

    def __init__(self):
        """Initialize theme manager"""
        self.themes = {
            'light': self.LIGHT_THEME,
            'dark': self.DARK_THEME
        }

    def get_theme(self, theme_name: str) -> str:
        """Get theme stylesheet by name"""
        return self.themes.get(theme_name, self.LIGHT_THEME)

    def get_available_themes(self) -> list:
        """Get list of available theme names"""
        return list(self.themes.keys())
