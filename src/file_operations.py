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

from .widgets import FileTreeWidgetItem, MissingFileDialog
from .utility_functions import format_size

class FileManager:
    """Manages file lists and interactions with the file tree widget"""

    SUPPORTED_EXTENSIONS = {'.nsp', '.nsz', '.xci', '.xcz'}

    def __init__(self, main_window):
        self.main_window = main_window
        self.file_list: Dict[str, Path] = {}
        self.item_map: Dict[str, QTreeWidgetItem] = {} # Map filename -> QTreeWidgetItem for fast lookup
        self.presets_dir = self._get_presets_directory()
        self.preset_loaded = False

    def _get_presets_directory(self) -> Path:
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).parent.parent.parent
        
        if base_dir.name == 'src': base_dir = base_dir.parent
        presets_dir = base_dir / 'presets'
        presets_dir.mkdir(exist_ok=True)
        return presets_dir

    def is_supported_file(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def add_files(self):
        """Add files using the last known files directory"""
        self.preset_loaded = False
        files, _ = QFileDialog.getOpenFileNames(
            self.main_window, "Select Files",
            self.main_window.config.get('last_file_directory', ''),
            "Switch Files (*.nsp *.nsz *.xci *.xcz);;All Files (*)"
        )
        if files:
            current_checked = self._get_current_checked_state()
            selected_dir = str(Path(files[0]).parent)
            self.main_window.config.set('last_file_directory', selected_dir)
            
            added_count = 0
            for f in files:
                p = Path(f)
                if self.is_supported_file(p):
                    self.file_list[p.name] = p.resolve()
                    current_checked.add(p.name)
                    added_count += 1
            if added_count > 0:
                self.update_file_list(current_checked)
                self.main_window.log('info', f'Added {added_count} files')

    def add_folder(self):
        """Add folder using the last known folder directory"""
        self.preset_loaded = False
        folder = QFileDialog.getExistingDirectory(
            self.main_window, "Select Folder",
            self.main_window.config.get('last_folder_directory', '')
        )
        if folder:
            current_checked = self._get_current_checked_state()
            self.main_window.config.set('last_folder_directory', folder)
            added_count = 0
            for p in Path(folder).rglob('*'):
                if p.is_file() and self.is_supported_file(p):
                    self.file_list[p.name] = p.resolve()
                    current_checked.add(p.name)
                    added_count += 1
            if added_count > 0:
                self.update_file_list(current_checked)
                self.main_window.log('info', f'Added {added_count} files from folder')
            else:
                self.main_window.log('warning', 'No supported files found')

    def clear_file_list(self):
        self.preset_loaded = False
        self.file_list.clear()
        self.main_window.file_tree.clear()
        self.main_window.progress_delegate.clear_all()
        self.update_count_label()
        self.main_window.header_checkbox.setChecked(False)
        self.main_window.log('info', 'File list cleared')

    def _get_current_checked_state(self) -> Set[str]:
        checked = set()
        tree = self.main_window.file_tree
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if self.is_item_checked(item):
                checked.add(item.text(1))
        return checked

    def update_file_list(self, previously_checked: Set[str] = None):
        from .widgets import CHECKED_ROLE
        self.main_window.file_tree.clear()
        self.item_map.clear()
        self.main_window.header_checkbox.blockSignals(True)
        for name, path in self.file_list.items():
            try:
                size = path.stat().st_size
                item = FileTreeWidgetItem(self.main_window.file_tree)
                checkbox = QCheckBox()
                should = True
                if previously_checked is not None: should = name in previously_checked
                checkbox.setChecked(should)
                # Cache the checked state on the item so FileTreeWidgetItem.__lt__
                # and update_count_label don't need to walk the widget tree.
                item.setData(0, CHECKED_ROLE, should)
                checkbox.stateChanged.connect(
                    lambda state, it=item: it.setData(0, CHECKED_ROLE, state == Qt.CheckState.Checked.value)
                )
                checkbox.stateChanged.connect(self.main_window.on_item_checked)
                w = QWidget()
                l = QHBoxLayout(w)
                l.addWidget(checkbox)
                l.setAlignment(Qt.AlignmentFlag.AlignCenter)
                l.setContentsMargins(0,0,0,0)
                w.setLayout(l)
                self.main_window.file_tree.setItemWidget(item, 0, w)
                item.setText(1, name)
                item.setText(2, format_size(size))
                item.setData(2, Qt.ItemDataRole.UserRole, size)
                item.setText(3, "Queued")
                item.setData(3, Qt.ItemDataRole.UserRole, 0)
                item.setText(4, str(path))
                self.item_map[name] = item

                if not path.exists():
                    checkbox.setChecked(False)
                    checkbox.setEnabled(False)
                    item.setText(2, "0 B")
                    item.setData(2, Qt.ItemDataRole.UserRole, 0)
                    item.setText(3, "⚠️ Missing")
                    item.setForeground(3, QColor('#F44336'))
                    item.setData(3, Qt.ItemDataRole.UserRole, 5) # New status for missing
                    for c in range(self.main_window.file_tree.columnCount()):
                        item.setForeground(c, QBrush(QColor('#808080')))
            except: continue
        self.main_window.header_checkbox.blockSignals(False)
        self.update_count_label()
        self.main_window.on_item_checked()
        if self.main_window.search_box.text():
            self.filter_files(self.main_window.search_box.text())

    # ---- Tree helpers -------------------------------------------------
    # Iteration / checkbox access used to be inlined in 12+ places; the
    # helpers below centralize the patterns so callers don't have to
    # walk the widget tree themselves.

    def iter_items(self):
        """Yield every top-level item in the file tree."""
        tree = self.main_window.file_tree
        for i in range(tree.topLevelItemCount()):
            yield tree.topLevelItem(i)

    def iter_checked_items(self):
        """Yield only items whose checkbox is currently checked."""
        for item in self.iter_items():
            if self.is_item_checked(item):
                yield item

    def _checkbox_for(self, item):
        """Return the QCheckBox embedded in column 0's widget, or None."""
        w = self.main_window.file_tree.itemWidget(item, 0)
        if w is None:
            return None
        return w.findChild(QCheckBox)

    def is_item_checked(self, item) -> bool:
        """Read the cached checked state for a tree item.

        Falls back to the widget tree only if the cache isn't populated yet
        (e.g. when called before :meth:`update_file_list` had a chance to seed
        it). All hot paths should hit the cached branch.
        """
        from .widgets import CHECKED_ROLE
        cached = item.data(0, CHECKED_ROLE)
        if cached is not None:
            return bool(cached)
        cb = self._checkbox_for(item)
        return cb.isChecked() if cb is not None else False

    def set_item_checked(self, item, value: bool):
        """Set the checkbox for ``item`` to ``value`` (no-op if absent)."""
        cb = self._checkbox_for(item)
        if cb is not None:
            cb.setChecked(value)

    # ------------------------------------------------------------------

    def update_count_label(self):
        total_size = 0
        total_count = 0
        selected_size = 0
        selected_count = 0
        for item in self.iter_items():
            size = item.data(2, Qt.ItemDataRole.UserRole) or 0
            total_count += 1
            total_size += size
            if self.is_item_checked(item):
                selected_count += 1
                selected_size += size
        text = (f"Selected: {selected_count} / {total_count} files, "
                f"{format_size(selected_size)} / {format_size(total_size)} total")
        self.main_window.file_count_label.setText(text)

    def update_file_status(self, filename: str, status: str):
        item = self.item_map.get(filename)
        if item:
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
            elif status == 'skipped':
                item.setText(3, '⏭ Skipped')
                item.setForeground(3, QColor('#808080'))
                item.setData(3, Qt.ItemDataRole.UserRole, 4)
                for c in range(self.main_window.file_tree.columnCount()):
                    item.setForeground(c, QBrush(QColor('#808080')))
            else:
                item.setText(3, 'Queued')
                item.setForeground(3, QColor(self.main_window.palette().text().color()))
                item.setData(3, Qt.ItemDataRole.UserRole, 0)

    def get_file_status_code(self, filename: str) -> int:
        item = self.item_map.get(filename)
        if item is None:
            return 0
        return item.data(3, Qt.ItemDataRole.UserRole) or 0

    def get_file_status(self, filename: str) -> str:
        item = self.item_map.get(filename)
        return item.text(3) if item else ""

    def invert_selected_files(self):
        selected = self.main_window.file_tree.selectedItems()
        if not selected: return
        for item in selected:
            self.set_item_checked(item, not self.is_item_checked(item))
        self.main_window.on_item_checked()
        curr = self.main_window.file_tree.currentItem()
        if curr:
            idx = self.main_window.file_tree.indexOfTopLevelItem(curr)
            next_idx = idx + 1
            if next_idx < self.main_window.file_tree.topLevelItemCount():
                next_item = self.main_window.file_tree.topLevelItem(next_idx)
                self.main_window.file_tree.clearSelection()
                next_item.setSelected(True)
                self.main_window.file_tree.setCurrentItem(next_item)
            elif self.main_window.file_tree.topLevelItemCount() > 0:
                next_item = self.main_window.file_tree.topLevelItem(0)
                self.main_window.file_tree.clearSelection()
                next_item.setSelected(True)
                self.main_window.file_tree.setCurrentItem(next_item)

    def filter_files(self, text: str):
        search = text.lower()
        for item in self.iter_items():
            item.setHidden(search not in item.text(1).lower())

    def dim_unchecked_items(self):
        gray = QBrush(QColor('#808080'))
        column_count = self.main_window.file_tree.columnCount()
        for item in self.iter_items():
            if not self.is_item_checked(item):
                for c in range(column_count):
                    item.setForeground(c, gray)

    def reset_items_visuals(self):
        brush = QBrush(self.main_window.palette().text().color())
        self.main_window.progress_delegate.clear_all()
        self.main_window.file_tree.viewport().update()
        column_count = self.main_window.file_tree.columnCount()
        for item in self.iter_items():
            for c in range(column_count):
                item.setForeground(c, brush)
            item.setText(3, "Queued")
            item.setData(3, Qt.ItemDataRole.UserRole, 0)

    def handle_server_start(self):
        """Called when any server starts. Dims unchecked files."""
        self.dim_unchecked_items()

    def handle_server_stop(self):
        """Called when server stops. Resets visuals."""
        self.reset_items_visuals()
        # Reset progress bars and labels
        self.main_window.current_progress.setValue(0)
        self.main_window.current_progress.setFormat("0%")
        self.main_window.overall_progress.setValue(0)
        self.main_window.overall_progress.setFormat("0%")
        self.main_window.current_file_label.setText("No transfer in progress")
        self.main_window.overall_label.setText("0 / 0 files")
        self.main_window.speed_label.setText("Speed: 0 MB/s")
        self.main_window.eta_label.setText("ETA: --:--:--")
        from . import __version__
        self.main_window.setWindowTitle(f"DBI Backend Qt v{__version__}")
        if self.main_window.taskbar_manager: self.main_window.taskbar_manager.hide_progress()

    def handle_installation_start(self, requested_filenames: list):
        """Called when the first real data request arrives.
        Marks checked but unrequested files as Skipped."""
        requested_set = set(requested_filenames)
        for filename, item in self.item_map.items():
            if self.is_item_checked(item) and filename not in requested_set:
                self.update_file_status(filename, 'skipped')

        # Sort once at the end
        self.main_window.file_tree.sortItems(3, self.main_window.file_tree.header().sortIndicatorOrder())

    # --- Presets & Batches ---

    def save_file_list_as_batch(self):
        if not self.file_list: return
        path, _ = QFileDialog.getSaveFileName(self.main_window, "Batch", "", "Batch (*.bat)")
        if path:
            checked = []
            for item in self.iter_checked_items():
                name = item.text(1)
                if name in self.file_list:
                    checked.append(self.file_list[name])
            if not checked:
                QMessageBox.warning(self.main_window, "No Selection", "None checked.")
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('dbi_backend.exe -- files ^\n')
                    for p in checked: f.write(f'"{p}" ^\n')
                self.main_window.log('success', f'Saved batch: {path}')
            except Exception as e: self.main_window.log('error', f'Error: {e}')

    def save_preset(self):
        """Save preset using the last known preset directory"""
        if not self.file_list: return
        
        default_dir = self.main_window.config.get('last_preset_directory', str(self.presets_dir))
        path, _ = QFileDialog.getSaveFileName(self.main_window, "Save Preset", default_dir, "DBI Presets (*.dbi)")
        
        if path:
            self.main_window.config.set('last_preset_directory', str(Path(path).parent))
            data = []
            for item in self.iter_items():
                name = item.text(1)
                if name in self.file_list:
                    data.append({
                        "name": name,
                        "path": str(self.file_list[name]),
                        "checked": self.is_item_checked(item),
                    })
            
            blob = {"name": Path(path).stem, "created_at": datetime.now().isoformat(), "files": data}
            try:
                with open(path, 'w', encoding='utf-8') as f: json.dump(blob, f, indent=2)
                self.main_window.update_presets_menu()
                self.main_window.log('success', f'Saved preset: {Path(path).name}')
            except Exception as e: self.main_window.log('error', f'Error: {e}')

    def load_preset(self, path: Path = None):
        """Load preset using the last known preset directory"""
        if not path:
            default_dir = self.main_window.config.get('last_preset_directory', str(self.presets_dir))
            s, _ = QFileDialog.getOpenFileName(self.main_window, "Load Preset", default_dir, "DBI Presets (*.dbi);;All Files (*)")
            if s: 
                path = Path(s)
                self.main_window.config.set('last_preset_directory', str(path.parent))
        
        if path and path.exists():
            try:
                self.preset_loaded = True
                with open(path, 'r', encoding='utf-8') as f: d = json.load(f)
                self.file_list.clear()
                to_check = set()
                
                raw_files = []
                if isinstance(d, dict) and "files" in d and isinstance(d["files"], list):
                    raw_files = d["files"]
                else:
                    items = d.items() if isinstance(d, dict) else []
                    for n, p_str in items:
                        raw_files.append({"name": n, "path": p_str, "checked": True})

                bulk_action = None
                cancelled = False
                for e in raw_files:
                    name = e.get("name", "")
                    p_str = e.get("path", "")
                    p = Path(p_str)
                    is_checked = e.get("checked", True)

                    if not p.exists():
                        if bulk_action == MissingFileDialog.CANCEL:
                            # Already cancelled — skip everything
                            cancelled = True
                            break
                        elif bulk_action in (MissingFileDialog.IGNORE, MissingFileDialog.REMOVE):
                            if bulk_action == MissingFileDialog.REMOVE: continue
                            # If IGNORE, we add it but it will be handled by update_file_list
                        else:
                            dlg = MissingFileDialog(name, p_str, self.main_window)
                            dlg.exec()

                            if dlg.result_code == MissingFileDialog.CANCEL:
                                cancelled = True
                                break

                            if dlg.apply_all: bulk_action = dlg.result_code

                            if dlg.result_code == MissingFileDialog.REMOVE:
                                continue
                            elif dlg.result_code == MissingFileDialog.UPDATE:
                                ext_filter = "Switch Files (*.nsp *.nsz *.xci *.xcz);;All Files (*)"
                                new_path, _ = QFileDialog.getOpenFileName(
                                    self.main_window, f"Locate {name}",
                                    str(p.parent), ext_filter
                                )
                                if new_path:
                                    p = Path(new_path)

                    self.file_list[p.name] = p
                    if is_checked and p.exists(): to_check.add(p.name)

                if cancelled:
                    self.file_list.clear()
                    self.preset_loaded = False
                    self.main_window.log('info', 'Preset loading cancelled')
                    return

                self.update_file_list(to_check)
                self.main_window.log('info', f'Loaded preset: {path.name}')
            except Exception as e: self.main_window.log('error', f'Error loading: {e}')

    def delete_preset(self):
        """Delete preset using the last known preset directory"""
        default_dir = self.main_window.config.get('last_preset_directory', str(self.presets_dir))
        s, _ = QFileDialog.getOpenFileName(self.main_window, "Delete", default_dir, "DBI Presets (*.dbi)")
        if s:
            try:
                Path(s).unlink()
                self.main_window.update_presets_menu()
                self.main_window.log('info', f'Deleted: {Path(s).name}')
            except Exception as e: self.main_window.log('error', f'Error: {e}')