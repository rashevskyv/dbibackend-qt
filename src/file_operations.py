"""
File Operations Manager for DBI Backend
Handles file list management, adding/removing files, and UI updates for the file tree.
"""
import sys
import json
from pathlib import Path
from typing import Dict, Set
from datetime import datetime

from PyQt6.QtWidgets import QFileDialog, QTreeWidgetItem, QMessageBox, QMenu, QCheckBox, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QBrush

from .widgets import FileTreeWidgetItem
from .utility_functions import format_size

class FileManager:
    """Manages file lists and interactions with the file tree widget"""

    # Supported file extensions for Games
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
            # Go up from src/file_operations.py -> src -> root
            base_dir = Path(__file__).parent.parent.parent
        
        # Fallback if running from source directly
        if base_dir.name == 'src':
             base_dir = base_dir.parent

        presets_dir = base_dir / 'presets'
        presets_dir.mkdir(exist_ok=True)
        return presets_dir

    def is_supported_file(self, path: Path) -> bool:
        """Check if file extension is supported (for games)"""
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
        self.main_window.progress_delegate.clear_all() # Reset delegate data
        self.update_count_label()
        self.main_window.header_checkbox.setChecked(False)
        self.main_window.log('info', 'File list cleared')

    def _get_current_checked_state(self) -> Set[str]:
        """Remember which files are currently checked"""
        checked = set()
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            checkbox_widget = self.main_window.file_tree.itemWidget(item, 0)
            if checkbox_widget:
                cb = checkbox_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    checked.add(item.text(1))
        return checked

    def update_file_list(self, previously_checked: Set[str] = None):
        """Re-populate the tree widget from self.file_list"""
        self.main_window.file_tree.clear()
        self.main_window.header_checkbox.blockSignals(True)
        
        for name, path in self.file_list.items():
            try:
                size = path.stat().st_size
                item = FileTreeWidgetItem(self.main_window.file_tree)
                
                # Checkbox setup
                checkbox = QCheckBox()
                should_check = True
                if previously_checked is not None:
                    should_check = name in previously_checked
                
                checkbox.setChecked(should_check)
                checkbox.stateChanged.connect(self.main_window.on_item_checked)
                
                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.addWidget(checkbox)
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.setContentsMargins(0,0,0,0)
                widget.setLayout(layout)
                
                self.main_window.file_tree.setItemWidget(item, 0, widget)
                
                item.setText(1, name)
                item.setText(2, format_size(size))
                item.setData(2, Qt.ItemDataRole.UserRole, size)
                item.setText(3, "Queued")
                item.setData(3, Qt.ItemDataRole.UserRole, 0)
                item.setText(4, str(path))
                
            except FileNotFoundError:
                continue

        self.main_window.header_checkbox.blockSignals(False)
        self.update_count_label()
        self.main_window.on_item_checked()
        
        if self.main_window.search_box.text():
            self.filter_files(self.main_window.search_box.text())

    def update_count_label(self):
        total_size = 0
        count = 0
        for path in self.file_list.values():
            try:
                total_size += path.stat().st_size
                count += 1
            except: pass
        self.main_window.file_count_label.setText(f'{count} files, {format_size(total_size)} total')

    def update_file_status(self, filename: str, status: str):
        """Update status column for a specific file"""
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
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            if item.text(1) == filename:
                return item.text(3)
        return ""

    def invert_selected_files(self):
        """Invert selection of highlighted rows (spacebar action)"""
        selected_items = self.main_window.file_tree.selectedItems()
        if not selected_items: return

        current_item = selected_items[0]
        current_index = self.main_window.file_tree.indexOfTopLevelItem(current_item)

        for item in selected_items:
            widget = self.main_window.file_tree.itemWidget(item, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb: cb.setChecked(not cb.isChecked())
        
        self.main_window.on_item_checked() 

        # Move Selection
        next_index = current_index + 1
        if next_index < self.main_window.file_tree.topLevelItemCount():
            next_item = self.main_window.file_tree.topLevelItem(next_index)
            self.main_window.file_tree.clearSelection()
            next_item.setSelected(True)
            self.main_window.file_tree.setCurrentItem(next_item)
        elif self.main_window.file_tree.topLevelItemCount() > 0:
            next_item = self.main_window.file_tree.topLevelItem(0)
            self.main_window.file_tree.clearSelection()
            next_item.setSelected(True)
            self.main_window.file_tree.setCurrentItem(next_item)

    def filter_files(self, text: str):
        search_text = text.lower()
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            filename = item.text(1).lower()
            item.setHidden(search_text not in filename)

    # --- New Methods for UI State Management ---

    def dim_unchecked_items(self):
        """Gray out items that are not checked/queued for transfer"""
        gray_brush = QBrush(QColor('#808080')) 
        
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            widget = self.main_window.file_tree.itemWidget(item, 0)
            is_checked = False
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb: is_checked = cb.isChecked()
            
            if not is_checked:
                for col in range(self.main_window.file_tree.columnCount()):
                    item.setForeground(col, gray_brush)

    def reset_items_visuals(self):
        """Reset all items to default visual state"""
        default_brush = QBrush(self.main_window.palette().text().color())
        
        self.main_window.progress_delegate.clear_all()
        self.main_window.file_tree.viewport().update()
        
        for i in range(self.main_window.file_tree.topLevelItemCount()):
            item = self.main_window.file_tree.topLevelItem(i)
            for col in range(self.main_window.file_tree.columnCount()):
                item.setForeground(col, default_brush)
            
            item.setText(3, "Queued")
            item.setData(3, Qt.ItemDataRole.UserRole, 0)

    # --- Presets & Batches ---

    def save_file_list_as_batch(self):
        if not self.file_list:
            QMessageBox.warning(self.main_window, "Empty List", "No files to save.")
            return
        path, _ = QFileDialog.getSaveFileName(self.main_window, "Save Batch File", "", "Batch Files (*.bat)")
        if path:
            try:
                checked_files = []
                for i in range(self.main_window.file_tree.topLevelItemCount()):
                    item = self.main_window.file_tree.topLevelItem(i)
                    widget = self.main_window.file_tree.itemWidget(item, 0)
                    if widget and widget.findChild(QCheckBox).isChecked():
                        filename = item.text(1)
                        if filename in self.file_list:
                            checked_files.append(self.file_list[filename])
                if not checked_files:
                    QMessageBox.warning(self.main_window, "No Selection", "No checked files to save.")
                    return
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('dbi_backend.exe -- files ^\n')
                    for p in checked_files:
                        f.write(f'"{p}" ^\n')
                self.main_window.log('success', f'Saved batch file to {path}')
            except Exception as e:
                self.main_window.log('error', f'Failed to save batch: {e}')

    def save_preset(self):
        if not self.file_list:
            QMessageBox.warning(self.main_window, "Empty List", "No files to save.")
            return
        name_dialog = QFileDialog(self.main_window)
        path, _ = name_dialog.getSaveFileName(self.main_window, "Save Preset", str(self.presets_dir), "DBI Presets (*.dbi)")
        if path:
            files_data = []
            for i in range(self.main_window.file_tree.topLevelItemCount()):
                item = self.main_window.file_tree.topLevelItem(i)
                filename = item.text(1)
                is_checked = True
                widget = self.main_window.file_tree.itemWidget(item, 0)
                if widget:
                    cb = widget.findChild(QCheckBox)
                    if cb: is_checked = cb.isChecked()
                if filename in self.file_list:
                    files_data.append({
                        "name": filename,
                        "path": str(self.file_list[filename]),
                        "checked": is_checked
                    })
            preset_data = {
                "name": Path(path).stem,
                "created_at": datetime.now().isoformat(),
                "files": files_data
            }
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(preset_data, f, indent=2)
                self.main_window.update_presets_menu()
                self.main_window.log('success', f'Preset saved: {Path(path).name}')
            except Exception as e:
                self.main_window.log('error', f'Failed to save preset: {e}')

    def load_preset(self, path: Path = None):
        if not path:
            file_dialog = QFileDialog(self.main_window)
            path_str, _ = file_dialog.getOpenFileName(
                self.main_window, "Load Preset", str(self.presets_dir), "DBI Presets (*.dbi);;All Files (*)"
            )
            if path_str: path = Path(path_str)
        if path and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.file_list.clear()
                files_to_check = set()
                if isinstance(data, dict) and "files" in data and isinstance(data["files"], list):
                    for entry in data["files"]:
                        p = Path(entry.get("path", ""))
                        if p.exists():
                            self.file_list[p.name] = p
                            if entry.get("checked", True): files_to_check.add(p.name)
                else:
                    items = data.items() if isinstance(data, dict) else []
                    for name, p_str in items:
                        p = Path(p_str)
                        if p.exists():
                            self.file_list[name] = p
                            files_to_check.add(name)
                self.update_file_list(files_to_check)
                self.main_window.log('info', f'Loaded preset: {path.name}')
            except Exception as e:
                self.main_window.log('error', f'Failed to load preset: {e}')

    def delete_preset(self):
        path_str, _ = QFileDialog.getOpenFileName(self.main_window, "Delete Preset", str(self.presets_dir), "DBI Presets (*.dbi)")
        if path_str:
            try:
                Path(path_str).unlink()
                self.main_window.update_presets_menu()
                self.main_window.log('info', f'Deleted preset: {Path(path_str).name}')
            except Exception as e:
                self.main_window.log('error', f'Failed to delete preset: {e}')