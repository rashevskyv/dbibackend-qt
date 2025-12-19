"""
Theme Manager
Provides light and dark themes for the application.
Hardcoded styles ensure independence from Windows System Theme settings.
"""
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

class ThemeManager:
    """Manages application themes"""

    # --- LIGHT THEME (Fixed for Dark Mode Windows) ---
    LIGHT_THEME = """
    QWidget { color: #000000; background-color: #f5f5f5; font-family: "Segoe UI", sans-serif; }
    QMenuBar { background-color: #e0e0e0; color: #000000; border-bottom: 1px solid #cccccc; }
    QMenuBar::item { background-color: transparent; color: #000000; padding: 4px 10px; }
    QMenuBar::item:selected { background-color: #d0d0d0; }
    QMenu { background-color: #ffffff; color: #000000; border: 1px solid #cccccc; }
    QMenu::item { padding: 4px 24px 4px 10px; }
    QMenu::item:selected { background-color: #2196F3; color: #ffffff; }
    QLineEdit, QTextEdit, QPlainTextEdit { background-color: #ffffff; color: #000000; border: 1px solid #c0c0c0; border-radius: 4px; padding: 4px; }
    QTreeWidget, QListWidget, QTableWidget { background-color: #ffffff; color: #000000; border: 1px solid #c0c0c0; alternate-background-color: #f9f9f9; }
    QTreeWidget::item:selected { background-color: #2196F3; color: #ffffff; }
    QHeaderView::section { background-color: #e0e0e0; color: #000000; padding: 4px; border: 1px solid #d0d0d0; }
    QGroupBox { border: 1px solid #cccccc; border-radius: 4px; margin-top: 1.1em; padding-top: 10px; }
    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; color: #333333; left: 10px; }
    
    /* Status Bar Fixes */
    QStatusBar { background-color: #e0e0e0; color: #000000; border-top: 1px solid #cccccc; }
    QStatusBar::item { border: none; }
    QStatusBar QLabel { background: transparent; }
    QSizeGrip { background: transparent; width: 16px; height: 16px; }
    
    /* Transparent splitter background to allow custom grip painting */
    QSplitter::handle { background-color: transparent; }
    """

    # --- DARK THEME ---
    DARK_THEME = """
    QWidget { color: #ffffff; background-color: #1e1e1e; font-family: "Segoe UI", sans-serif; }
    QMenuBar { background-color: #2d2d2d; color: #ffffff; border-bottom: 1px solid #3d3d3d; }
    QMenuBar::item:selected { background-color: #3d3d3d; }
    QMenu { background-color: #2d2d2d; color: #ffffff; border: 1px solid #3d3d3d; }
    QMenu::item:selected { background-color: #2196F3; color: #ffffff; }
    QLineEdit, QTextEdit, QPlainTextEdit { background-color: #2d2d2d; color: #ffffff; border: 1px solid #3d3d3d; border-radius: 4px; padding: 4px; }
    QTreeWidget, QListWidget, QTableWidget { background-color: #252526; color: #cccccc; border: 1px solid #3d3d3d; alternate-background-color: #2d2d2d; }
    QTreeWidget::item:selected { background-color: #37373d; color: #ffffff; border: 1px solid #2196F3; }
    QHeaderView::section { background-color: #2d2d2d; color: #ffffff; padding: 4px; border: 1px solid #3d3d3d; }
    QGroupBox { border: 1px solid #3d3d3d; border-radius: 4px; margin-top: 1.1em; padding-top: 10px; }
    QGroupBox::title { color: #cccccc; subcontrol-origin: margin; left: 10px; }
    
    /* Status Bar Fixes */
    QStatusBar { background-color: #2d2d2d; color: #ffffff; border-top: 1px solid #3d3d3d; }
    QStatusBar::item { border: none; }
    QStatusBar QLabel { background: transparent; }
    QSizeGrip { background: transparent; width: 16px; height: 16px; }

    /* Transparent splitter background to allow custom grip painting */
    QSplitter::handle { background-color: transparent; }
    
    QScrollBar:vertical { border: none; background: #1e1e1e; width: 14px; margin: 0px; }
    QScrollBar::handle:vertical { background: #424242; min-height: 20px; border-radius: 2px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    """

    def __init__(self):
        self.themes = {
            'light': self.LIGHT_THEME,
            'dark': self.DARK_THEME
        }

    def get_theme(self, theme_name: str) -> str:
        return self.themes.get(theme_name, self.LIGHT_THEME)
    
    def get_system_theme(self) -> str:
        """Detect system theme via Qt"""
        if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return 'dark'
        return 'light'