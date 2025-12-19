"""
File Operations Manager for DBI Backend
Handles file list management, adding/removing files, and UI updates for the file tree.
"""
import sys
import json
from pathlib import Path
from typing import Dict, Set

from PyQt6.QtWidgets import QFileDialog, QTreeWidgetItem, QMessageBox, QMenu
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QDesktopServices

from .widgets import FileTreeWidgetItem
from .utility_functions import format_size

class FileManager:
    """Manages file lists and interactions with the file tree widget"""

    # Supported file extensions
    SUPPORTED_EXTENSIONS = {'.nsp', '.nsz', '.xci', '.xcz'}

    def __init__(self, main_window):
        self.main_window = main_window
        self.file_list: Dict[str, Path] = {}
        self.presets_dir = self._get_presets_directory()

    def _get_presets_directory(self) -> Path:
        """Ensure and return the presets directory"""
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).parent.parent.parent # src -> parent -> root
        
        # Fallback if running from src directly
        if base_dir.name == 'src':
             base_dir = base_dir.parent

        presets_dir = base_dir / 'presets'
        presets_dir.mkdir(exist_ok=True)
        return presets_dir

    def is_supported_file(self, path: Path) -> bool:
        """Check if file extension is supported"""
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def add_files(self):
        """Open dialog to add files"""
        files, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Files",
            self.main_window.config.get('last_directory', ''),
            "Switch Files (*.nsp *.nsz *.xci *.xcz);;All Files (*)"
        )

        if files:
            current_checked = self._get_current_checked_state()
            path_obj = Path(files[0])
            self.main_window.config.set('last_directory', str(path_obj.parent))
            
            added_count = 0
            for f in files:
                path = Path(f)
                if self.is_supported_file(path):
                    self.file_list[path.name] = path.resolve()
                    added_count += 1
            
            if added_count > 0:
                self.update_file_list(current_checked)
                self.main_window.log('info', f'Added {added_count} files')

    def add_folder(self):
        """Open dialog to add a folder"""
        folder = QFileDialog.getExistingDirectory(
            self.main_window,
            "Select Folder",
            self.main_window.config.get('last_directory', '')
        )

        if folder:
            current_checked = self._get_current_checked_state()
            folder_path = Path(folder)
            self.main_window.config.set('last_directory', str(folder_path))
            
            added_count = 0
            for path in folder_path.rglob('*'):
                if path.is_file() and self.is_supported_file(path):
                    self.file_list[path.name] = path.resolve()
                    added_count += 1
            
            if added_count > 0:
                self.update_file_list(current_checked)
                self.main_window.log('info', f'Added {added_count} files from folder')
            else:
                self.main_window.log('warning', 'No supported files found in folder')

    def clear_file_list(self):
        """Clear all files from the list"""
        self.file_list.clear()
        self.main_window.file_tree.clear()
        self.update_count_label()
        self.main_window.header_checkbox.setChecked(False)
        self.main_window.log('info', 'File list cleared')

    def _get_current_checked_state(self) -> Set[str]:
        """Remember which files are currently checked"""
        checked = set()
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            checkbox = self.main_window.file_tree.itemWidget(item, 0)
            if checkbox and checkbox.isChecked():
                checked.add(item.text(1))
        return checked

    def update_file_list(self, previously_checked: Set[str] = None):
        """Re-populate the tree widget from self.file_list"""
        self.main_window.file_tree.clear()
        
        # Block signals to prevent massive header checkbox toggling logic during build
        self.main_window.header_checkbox.blockSignals(True)
        
        for name, path in self.file_list.items():
            try:
                size = path.stat().st_size
                item = FileTreeWidgetItem(self.main_window.file_tree)
                
                # Checkbox setup
                from PyQt6.QtWidgets import QCheckBox, QWidget, QHBoxLayout
                checkbox = QCheckBox()
                # Check if it was checked before (or default to checked if new)
                should_check = True
                if previously_checked is not None:
                    should_check = name in previously_checked
                
                checkbox.setChecked(should_check)
                checkbox.stateChanged.connect(self.main_window.on_item_checked)
                
                # Center checkbox
                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.addWidget(checkbox)
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.setContentsMargins(0,0,0,0)
                widget.setLayout(layout)
                
                self.main_window.file_tree.setItemWidget(item, 0, checkbox)
                
                # Set data
                item.setText(1, name)
                
                item.setText(2, format_size(size))
                item.setData(2, Qt.ItemDataRole.UserRole, size) # For sorting
                
                item.setText(3, "Queued")
                item.setData(3, Qt.ItemDataRole.UserRole, 0) # 0=Queued, 1=Process, 2=Done
                
                item.setText(4, str(path))
                
            except FileNotFoundError:
                continue

        self.main_window.header_checkbox.blockSignals(False)
        self.update_count_label()
        
        # Re-apply filter if search is active
        if self.main_window.search_box.text():
            self.filter_files(self.main_window.search_box.text())

    def update_count_label(self):
        """Update the label showing file count and total size"""
        total_size = 0
        count = 0
        for path in self.file_list.values():
            try:
                total_size += path.stat().st_size
                count += 1
            except:
                pass
        self.main_window.file_count_label.setText(f'{count} files, {format_size(total_size)} total')

    def update_file_status(self, filename: str, status: str):
        """Update status column for a specific file"""
        # Iterate items to find the file (Dict lookup doesn't map to TreeItem directly easily without aux map)
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            if item.text(1) == filename:
                if status == 'process':
                    item.setText(3, '🔄 Process')
                    item.setForeground(3, QColor('#2196F3'))
                    item.setData(3, Qt.ItemDataRole.UserRole, 1)
                elif status == 'done':
                    item.setText(3, '✅ Done')
                    item.setForeground(3, QColor('#4CAF50'))
                    item.setData(3, Qt.ItemDataRole.UserRole, 2)
                elif status == 'failed':
                    item.setText(3, '❌ Failed')
                    item.setForeground(3, QColor('#F44336'))
                    item.setData(3, Qt.ItemDataRole.UserRole, 3)
                else:
                    item.setText(3, 'Queued')
                    item.setForeground(3, QColor(self.main_window.palette().text().color()))
                    item.setData(3, Qt.ItemDataRole.UserRole, 0)
                break

    def get_file_status(self, filename: str) -> str:
        """Get the text status of a file"""
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            if item.text(1) == filename:
                return item.text(3)
        return ""

    def invert_selected_files(self):
        """Invert selection of highlighted rows (spacebar action)"""
        selected_items = self.main_window.file_tree.selectedItems()
        for item in selected_items:
            checkbox = self.main_window.file_tree.itemWidget(item, 0)
            if isinstance(checkbox, QCheckBox): # It's wrapped in a widget, need to find the child
                # The widget set via setItemWidget is the container
                container = checkbox
                real_checkbox = container.findChild(QCheckBox)
                if real_checkbox:
                    real_checkbox.setChecked(not real_checkbox.isChecked())
        self.main_window.on_item_checked() # Update header state

    def filter_files(self, text: str):
        """Filter the tree view based on search text"""
        search_text = text.lower()
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            filename = item.text(1).lower()
            item.setHidden(search_text not in filename)

    # --- Presets & Batches ---

    def save_file_list_as_batch(self):
        """Save current list as a .bat file for DBI CLI"""
        if not self.file_list:
            QMessageBox.warning(self.main_window, "Empty List", "No files to save.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save Batch File", "", "Batch Files (*.bat)"
        )
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('dbi_backend.exe -- files ^\n')
                    for p in self.file_list.values():
                        f.write(f'"{p}" ^\n')
                self.main_window.log('success', f'Saved batch file to {path}')
            except Exception as e:
                self.main_window.log('error', f'Failed to save batch: {e}')

    def save_preset(self):
        """Save current file list as a JSON preset"""
        if not self.file_list:
            QMessageBox.warning(self.main_window, "Empty List", "No files to save.")
            return

        name_dialog = QFileDialog(self.main_window)
        path, _ = name_dialog.getSaveFileName(
            self.main_window, "Save Preset", str(self.presets_dir), "JSON Files (*.json)"
        )

        if path:
            data = {name: str(p) for name, p in self.file_list.items()}
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                self.main_window.update_presets_menu()
                self.main_window.log('success', f'Preset saved: {Path(path).name}')
            except Exception as e:
                self.main_window.log('error', f'Failed to save preset: {e}')

    def load_preset(self, path: Path = None):
        """Load a preset from file"""
        if not path:
            file_dialog = QFileDialog(self.main_window)
            path_str, _ = file_dialog.getOpenFileName(
                self.main_window, "Load Preset", str(self.presets_dir), "JSON Files (*.json)"
            )
            if path_str:
                path = Path(path_str)
        
        if path and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.file_list.clear()
                for name, p_str in data.items():
                    p = Path(p_str)
                    if p.exists():
                        self.file_list[name] = p
                
                self.update_file_list()
                self.main_window.log('info', f'Loaded preset: {path.name}')
            except Exception as e:
                self.main_window.log('error', f'Failed to load preset: {e}')

    def delete_preset(self):
        """Delete an existing preset"""
        path_str, _ = QFileDialog.getOpenFileName(
            self.main_window, "Delete Preset", str(self.presets_dir), "JSON Files (*.json)"
        )
        if path_str:
            try:
                Path(path_str).unlink()
                self.main_window.update_presets_menu()
                self.main_window.log('info', f'Deleted preset: {Path(path_str).name}')
            except Exception as e:
                self.main_window.log('error', f'Failed to delete preset: {e}')