"""
File Operations Manager for DBI Backend.
Handles file queue, folder hierarchies, conflict handling, and UI interactions.
"""
from pathlib import Path
from typing import Dict, Optional, Sequence, Union, List

from PyQt6.QtWidgets import (
    QFileDialog, QTreeWidgetItem, QCheckBox, QStyle
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush

from .widgets import (
    CHECKED_ROLE, IS_FOLDER_ROLE, FILE_PATH_ROLE, IS_CONFLICT_ROLE
)
from .utility_functions import format_size
from .folder_dialog import FolderModeDialog
from .queue_manager import (
    QueueManager, SUPPORTED_EXTENSIONS, STATUS_QUEUED,
    STATUS_PROCESS, STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED
)
from .preset_manager import PresetManager
from .tree_item_builder import (
    build_folder_row, build_file_row,
    update_folder_checkbox_visual, update_folder_aggregate_status
)
from .queue_reorder import (
    move_selected_items as qr_move_selected,
    reorder_dragged_path as qr_reorder_dragged,
)


class FileManager:
    """Manages file queue, folder hierarchy, and interactions with the tree widget."""

    SUPPORTED_EXTENSIONS = SUPPORTED_EXTENSIONS

    def __init__(self, main_window):
        self.main_window = main_window
        self.queue = QueueManager()
        self.preset_manager = PresetManager(main_window, self)
        self.presets_dir = self.preset_manager.presets_dir
        self.preset_loaded = False

        self.file_list: Dict[str, Path] = {}
        self.item_map: Dict[str, QTreeWidgetItem] = {}
        self.path_to_item: Dict[Path, QTreeWidgetItem] = {}
        self.folder_items: Dict[Path, QTreeWidgetItem] = {}
        self.file_targets: Dict[str, int] = {}
        self._updating_checkboxes = False

    def is_supported_file(self, path: Path) -> bool:
        if self.main_window.mode_switch and self.main_window.mode_switch.mode() in ('http', 'ftp'):
            return True
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def ingest_paths(self, paths: Sequence[Union[str, Path]], default_folder_mode: Optional[str] = None):
        """Unified ingestion pipeline for files and folders from UI, D&D, or CLI."""
        resolved_paths: List[Path] = []
        for p in paths:
            try:
                p_obj = Path(p).resolve()
                if p_obj.exists() and p_obj not in resolved_paths:
                    resolved_paths.append(p_obj)
            except Exception:
                continue

        if not resolved_paths:
            return

        batch_folder_mode = default_folder_mode
        added_files = 0
        added_folders = 0

        for path in resolved_paths:
            if path.is_file():
                if self.is_supported_file(path):
                    added_files += self.queue.add_flat_files([path])
            elif path.is_dir():
                found_files = self.queue.scan_folder(path, self.SUPPORTED_EXTENSIONS)
                if not found_files:
                    self.main_window.log('warning', f'No supported files found in folder: {path.name}')
                    continue

                chosen_mode = batch_folder_mode
                if chosen_mode is None:
                    mode, apply_all = FolderModeDialog.ask_mode(path.name, self.main_window)
                    if mode is None:
                        continue
                    if apply_all:
                        batch_folder_mode = mode
                    chosen_mode = mode

                if chosen_mode == FolderModeDialog.MODE_FOLDER:
                    added_files += self.queue.add_folder_hierarchical(path, found_files)
                    added_folders += 1
                elif chosen_mode == FolderModeDialog.MODE_FILES:
                    added_files += self.queue.add_flat_files(found_files)

        conflicts = self.queue.recompute_conflicts()
        for cname in conflicts:
            self.main_window.log('warning', f"Duplicate filename conflict: '{cname}'. Conflicting files cannot be transferred.")

        self.update_file_list()

        if added_folders > 0 or added_files > 0:
            summary = []
            if added_folders > 0:
                summary.append(f"{added_folders} folder(s)")
            if added_files > 0:
                summary.append(f"{added_files} file(s)")
            self.main_window.log('info', f"Added {', '.join(summary)}")

    def add_files(self):
        """Add files using file dialog and route to unified ingestion."""
        self.preset_loaded = False
        files, _ = QFileDialog.getOpenFileNames(
            self.main_window, "Select Files",
            self.main_window.config.get('last_file_directory', ''),
            "Switch Files (*.nsp *.nsz *.xci *.xcz);;All Files (*)"
        )
        if files:
            self.main_window.config.set('last_file_directory', str(Path(files[0]).parent))
            self.ingest_paths([Path(f) for f in files])

    def add_folder(self):
        """Add folder using directory dialog and route to unified ingestion."""
        self.preset_loaded = False
        folder = QFileDialog.getExistingDirectory(
            self.main_window, "Select Folder",
            self.main_window.config.get('last_folder_directory', '')
        )
        if folder:
            self.main_window.config.set('last_folder_directory', folder)
            self.ingest_paths([Path(folder)])

    def clear_file_list(self):
        """Clear all queue state and reset the tree."""
        self.preset_loaded = False
        self.queue.clear()
        self.file_list.clear()
        self.item_map.clear()
        self.path_to_item.clear()
        self.folder_items.clear()
        self.file_targets.clear()
        self.main_window.file_tree.clear()
        self.main_window.progress_delegate.clear_all()
        self.update_count_label()
        self.main_window.header_checkbox.setChecked(False)
        self.main_window.log('info', 'File list cleared')

    def remove_selected_items(self, selected_items: List[QTreeWidgetItem]):
        """Remove selected items (folders or files) and re-evaluate conflicts."""
        for item in selected_items:
            path_str = item.data(5, FILE_PATH_ROLE)
            if path_str:
                self.queue.remove_path(Path(path_str))
        self.queue.recompute_conflicts()
        self.update_file_list()
        self.main_window.log('info', f'Removed {len(selected_items)} item(s)')
        if self.main_window.server_manager.usb_handler and self.main_window.server_manager.usb_handler.is_running:
            checked_names = {it.text(1) for it in self.iter_checked_items()}
            self.main_window.server_manager.sync_usb_files(self.file_list, checked_names, self.file_targets)

    def move_selected_items(self, delta: int):
        """Move selected items up (delta=-1) or down (delta=+1) in queue order."""
        qr_move_selected(self, delta)

    def update_file_list(self):
        """Populate the tree widget reflecting folders and files with accurate icons and states in explicit queue order."""
        self.main_window.file_tree.clear()
        self.item_map.clear()
        self.path_to_item.clear()
        self.folder_items.clear()
        self.main_window.header_checkbox.blockSignals(True)

        folder_icon = self.main_window.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self.main_window.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        # Build entries in explicit queue order
        for item_path in self.queue.order:
            if item_path in self.queue.folders:
                folder_path = item_path
                folder_rec = self.queue.folders[folder_path]
                folder_item = build_folder_row(
                    self.main_window.file_tree, folder_path, folder_rec, folder_icon,
                    self._on_folder_checkbox_toggled, self.on_folder_target_changed
                )

                folder_total_size = 0
                for child_path in folder_rec.files:
                    if child_path not in self.queue.files:
                        continue
                    rec = self.queue.files[child_path]
                    folder_total_size += rec.size

                    should_check = rec.checked
                    cur_target = rec.target
                    child_item = build_file_row(
                        folder_item, child_path, rec, file_icon, should_check, cur_target,
                        self._on_child_checkbox_toggled, self.on_target_changed
                    )

                    if not rec.in_conflict:
                        self.item_map[rec.name] = child_item
                    folder_item.addChild(child_item)
                    self.path_to_item[child_path] = child_item

                folder_item.setText(2, format_size(folder_total_size))
                folder_item.setData(2, Qt.ItemDataRole.UserRole, folder_total_size)
                folder_item.setExpanded(True)
                self.folder_items[folder_path] = folder_item
                update_folder_checkbox_visual(folder_item, self.is_item_checked, self._checkbox_for)
                update_folder_aggregate_status(folder_item)
            elif item_path in self.queue.files:
                file_path = item_path
                rec = self.queue.files[file_path]
                if rec.folder_path is not None:
                    continue

                should_check = rec.checked
                cur_target = rec.target
                item = build_file_row(
                    self.main_window.file_tree, file_path, rec, file_icon, should_check, cur_target,
                    self._on_standalone_checkbox_toggled, self.on_target_changed
                )

                if not rec.in_conflict:
                    self.item_map[rec.name] = item
                self.path_to_item[file_path] = item

        # Fallback for any standalone files not in queue.order
        for file_path, rec in self.queue.files.items():
            if rec.folder_path is not None or file_path in self.path_to_item:
                continue
            should_check = rec.checked
            cur_target = rec.target
            item = build_file_row(
                self.main_window.file_tree, file_path, rec, file_icon, should_check, cur_target,
                self._on_standalone_checkbox_toggled, self.on_target_changed
            )
            if not rec.in_conflict:
                self.item_map[rec.name] = item
            self.path_to_item[file_path] = item

        self.file_list = self.queue.get_transfer_file_list()
        self.file_targets = {
            rec.name: rec.target for rec in self.queue.files.values() if not rec.in_conflict
        }
        for rec in self.queue.files.values():
            if rec.status_code != STATUS_QUEUED and not rec.in_conflict:
                self.update_file_status(rec.name, rec.status)
        self.main_window.header_checkbox.blockSignals(False)
        self.update_count_label()
        self.main_window.on_item_checked()
        if self.main_window.search_box.text():
            self.filter_files(self.main_window.search_box.text())

    def _on_folder_checkbox_toggled(self, folder_item: QTreeWidgetItem, state: int):
        if self._updating_checkboxes:
            return
        self._updating_checkboxes = True
        try:
            is_checked = (state == Qt.CheckState.Checked.value or state == 2)
            folder_item.setData(0, CHECKED_ROLE, is_checked)
            for i in range(folder_item.childCount()):
                child = folder_item.child(i)
                if child.data(0, IS_CONFLICT_ROLE):
                    continue
                child_cb = self._checkbox_for(child)
                if child_cb and child_cb.isEnabled():
                    child_cb.setChecked(is_checked)
                child.setData(0, CHECKED_ROLE, is_checked)
                c_path_str = child.data(5, FILE_PATH_ROLE)
                if c_path_str and Path(c_path_str) in self.queue.files:
                    self.queue.files[Path(c_path_str)].checked = is_checked
        finally:
            self._updating_checkboxes = False
        self.update_count_label()
        self.main_window.on_item_checked()

    def _on_child_checkbox_toggled(self, child_item: QTreeWidgetItem, state: int):
        if self._updating_checkboxes:
            return
        is_checked = (state == Qt.CheckState.Checked.value or state == 2)
        child_item.setData(0, CHECKED_ROLE, is_checked)
        c_path_str = child_item.data(5, FILE_PATH_ROLE)
        if c_path_str and Path(c_path_str) in self.queue.files:
            self.queue.files[Path(c_path_str)].checked = is_checked

        parent = child_item.parent()
        if parent:
            self._updating_checkboxes = True
            try:
                update_folder_checkbox_visual(parent, self.is_item_checked, self._checkbox_for)
            finally:
                self._updating_checkboxes = False
        self.update_count_label()
        self.main_window.on_item_checked()

    def _on_standalone_checkbox_toggled(self, item: QTreeWidgetItem, state: int):
        if self._updating_checkboxes:
            return
        is_checked = (state == Qt.CheckState.Checked.value or state == 2)
        item.setData(0, CHECKED_ROLE, is_checked)
        p_str = item.data(5, FILE_PATH_ROLE)
        if p_str and Path(p_str) in self.queue.files:
            self.queue.files[Path(p_str)].checked = is_checked
        self.update_count_label()
        self.main_window.on_item_checked()

    def iter_top_level_items(self):
        tree = self.main_window.file_tree
        for i in range(tree.topLevelItemCount()):
            yield tree.topLevelItem(i)

    def iter_items(self):
        for top in self.iter_top_level_items():
            yield top
            for c in range(top.childCount()):
                yield top.child(c)

    def iter_file_items(self):
        for top in self.iter_top_level_items():
            if top.data(0, IS_FOLDER_ROLE):
                for c in range(top.childCount()):
                    yield top.child(c)
            else:
                yield top

    def iter_checked_items(self):
        for item in self.iter_file_items():
            if self.is_item_checked(item):
                yield item

    def _checkbox_for(self, item) -> Optional[QCheckBox]:
        w = self.main_window.file_tree.itemWidget(item, 0)
        return w.findChild(QCheckBox) if w else None

    def is_item_checked(self, item) -> bool:
        cached = item.data(0, CHECKED_ROLE)
        if cached is not None:
            return bool(cached)
        cb = self._checkbox_for(item)
        return cb.isChecked() if cb is not None else False

    def set_item_checked(self, item, value: bool):
        if item.data(0, IS_CONFLICT_ROLE):
            return
        cb = self._checkbox_for(item)
        if cb is not None:
            cb.setChecked(value)
        if item.data(0, IS_FOLDER_ROLE):
            self._on_folder_checkbox_toggled(item, Qt.CheckState.Checked.value if value else Qt.CheckState.Unchecked.value)

    def update_count_label(self):
        total_size = 0
        total_count = 0
        selected_size = 0
        selected_count = 0
        for item in self.iter_file_items():
            size = item.data(2, Qt.ItemDataRole.UserRole) or 0
            total_count += 1
            total_size += size
            if self.is_item_checked(item):
                selected_count += 1
                selected_size += size
        text = (f"Selected: {selected_count} / {total_count} files, "
                f"{format_size(selected_size)} / {format_size(total_size)} total")
        self.main_window.file_count_label.setText(text)

    def on_target_changed(self, file_key, target_idx: int):
        item = self.path_to_item.get(file_key) if isinstance(file_key, Path) else self.item_map.get(file_key)
        if item is not None:
            path = Path(item.data(5, FILE_PATH_ROLE))
            rec = self.queue.files[path]
            rec.target = target_idx
            if not rec.in_conflict:
                self.file_targets[rec.name] = target_idx
            item.setText(3, "")
            item.setData(3, Qt.ItemDataRole.UserRole, target_idx)
        if self.main_window.server_manager.usb_handler and self.main_window.server_manager.usb_handler.is_running:
            checked_names = {it.text(1) for it in self.iter_checked_items()}
            self.main_window.server_manager.sync_usb_files(self.file_list, checked_names, self.file_targets)

    def on_folder_target_changed(self, folder_item: QTreeWidgetItem, target_idx: int):
        folder_item.setText(3, "")
        folder_item.setData(3, Qt.ItemDataRole.UserRole, target_idx)
        for i in range(folder_item.childCount()):
            child = folder_item.child(i)
            fname = child.text(1)
            rec = self.queue.files.get(Path(child.data(5, FILE_PATH_ROLE)))
            if rec:
                rec.target = target_idx
                if not rec.in_conflict:
                    self.file_targets[fname] = target_idx
            w = self.main_window.file_tree.itemWidget(child, 3)
            combo = w if isinstance(w, QComboBox) else (w.findChild(QComboBox) if w else None)
            if combo:
                combo.blockSignals(True)
                combo.setCurrentIndex(target_idx)
                combo.blockSignals(False)
            child.setText(3, "")
            child.setData(3, Qt.ItemDataRole.UserRole, target_idx)
        if self.main_window.server_manager.usb_handler and self.main_window.server_manager.usb_handler.is_running:
            checked_names = {it.text(1) for it in self.iter_checked_items()}
            self.main_window.server_manager.sync_usb_files(self.file_list, checked_names, self.file_targets)

    def set_target_for_selected(self, target_idx: int):
        selected = self.main_window.file_tree.selectedItems()
        if not selected:
            return
        for item in selected:
            if item.data(0, IS_FOLDER_ROLE):
                self.on_folder_target_changed(item, target_idx)
            else:
                self.on_target_changed(Path(item.data(5, FILE_PATH_ROLE)), target_idx)

    def update_file_status(self, filename: str, status: str):
        item = self.item_map.get(filename)
        if not item:
            return
        path_str = item.data(5, FILE_PATH_ROLE)
        rec = self.queue.files.get(Path(path_str)) if path_str else None
        if rec:
            rec.status = status
            rec.status_code = {
                'skipped': STATUS_SKIPPED, 'process': STATUS_PROCESS,
                'done': STATUS_DONE, 'failed': STATUS_FAILED
            }.get(status, STATUS_QUEUED)
        if status == 'skipped':
            item.setText(4, '⏭ Skipped')
            item.setForeground(4, QColor('#808080'))
            item.setData(4, Qt.ItemDataRole.UserRole, STATUS_SKIPPED)
            for c in range(self.main_window.file_tree.columnCount()):
                item.setForeground(c, QBrush(QColor('#808080')))
        else:
            for c in range(self.main_window.file_tree.columnCount()):
                item.setForeground(c, QBrush(self.main_window.palette().text().color()))
            if status == 'process':
                item.setText(4, '🔄 Process')
                item.setForeground(4, QColor('#2196F3'))
                item.setData(4, Qt.ItemDataRole.UserRole, STATUS_PROCESS)
            elif status == 'done':
                item.setText(4, '✅ Done')
                item.setForeground(4, QColor('#4CAF50'))
                item.setData(4, Qt.ItemDataRole.UserRole, STATUS_DONE)
            elif status == 'failed':
                item.setText(4, '❌ Failed')
                item.setForeground(4, QColor('#F44336'))
                item.setData(4, Qt.ItemDataRole.UserRole, STATUS_FAILED)
            else:
                item.setText(4, 'Queued')
                item.setData(4, Qt.ItemDataRole.UserRole, STATUS_QUEUED)

        w = self.main_window.file_tree.itemWidget(item, 0)
        if w:
            from .tree_item_builder import DragHandle
            handle = w.findChild(DragHandle)
            if handle:
                handle.set_draggable(status not in ('process', 'done'))

        parent = item.parent()
        if parent:
            update_folder_aggregate_status(parent)

    def set_file_status(self, filename: str, status: Union[str, int]):
        m = {STATUS_PROCESS: 'process', STATUS_DONE: 'done', STATUS_FAILED: 'failed', STATUS_SKIPPED: 'skipped', STATUS_QUEUED: 'queued'}
        self.update_file_status(filename, m.get(status, status) if isinstance(status, int) else status)

    def reorder_dragged_path(self, src_path: Path, tgt_path: Optional[Path], before: bool = True) -> bool:
        return qr_reorder_dragged(self, src_path, tgt_path, before)

    def get_file_status_code(self, filename: str) -> int:
        item = self.item_map.get(filename); return (item.data(4, Qt.ItemDataRole.UserRole) or 0) if item else 0

    def get_file_status(self, filename: str) -> str:
        item = self.item_map.get(filename); return item.text(4) if item else ""

    def invert_selected_files(self):
        selected = self.main_window.file_tree.selectedItems()
        if not selected:
            return
        for item in selected:
            is_folder = item.data(0, IS_FOLDER_ROLE)
            current = self.is_item_checked(item)
            if is_folder:
                self.set_item_checked(item, not current)
            else:
                if not item.data(0, IS_CONFLICT_ROLE):
                    self.set_item_checked(item, not current)
        self.main_window.on_item_checked()

    def filter_files(self, text: str):
        search = text.lower()
        for top in self.iter_top_level_items():
            if top.data(0, IS_FOLDER_ROLE):
                f_match = search in top.text(1).lower()
                c_matches = False
                for c in range(top.childCount()):
                    child = top.child(c)
                    cm = search in child.text(1).lower()
                    child.setHidden(not cm and not f_match)
                    if cm:
                        c_matches = True
                top.setHidden(not f_match and not c_matches)
                if c_matches:
                    top.setExpanded(True)
            else:
                top.setHidden(search not in top.text(1).lower())

    def dim_unchecked_items(self):
        gray, col_count = QBrush(QColor('#808080')), self.main_window.file_tree.columnCount()
        for item in self.iter_items():
            if not self.is_item_checked(item):
                status_code = item.data(4, Qt.ItemDataRole.UserRole)
                if status_code in (STATUS_DONE, STATUS_FAILED):
                    continue
                for c in range(col_count):
                    item.setForeground(c, gray)

    def reset_items_visuals(self):
        brush = QBrush(self.main_window.palette().text().color())
        self.main_window.progress_delegate.clear_all()
        self.main_window.file_tree.viewport().update()
        col_count = self.main_window.file_tree.columnCount()
        for rec in self.queue.files.values():
            rec.status = 'Queued'
            rec.status_code = STATUS_QUEUED
        for item in self.iter_items():
            if item.data(0, IS_CONFLICT_ROLE):
                continue
            for c in range(col_count):
                item.setForeground(c, brush)
            item.setText(4, "Queued")
            item.setData(4, Qt.ItemDataRole.UserRole, STATUS_QUEUED)

    def handle_server_start(self):
        self.dim_unchecked_items()

    def handle_server_stop(self):
        if hasattr(self.main_window, 'server_manager'):
            self.main_window.server_manager.session_ended = False
        self.reset_items_visuals()
        self.main_window.current_progress.setValue(0); self.main_window.current_progress.setFormat("0%")
        self.main_window.overall_progress.setValue(0); self.main_window.overall_progress.setFormat("0%")
        self.main_window.current_file_label.setText("No transfer in progress")
        self.main_window.overall_label.setText("0 / 0 files")
        self.main_window.speed_label.setText("Speed: 0 MB/s")
        self.main_window.eta_label.setText("ETA: --:--:--")
        from . import __version__
        self.main_window.setWindowTitle(f"DBI Backend Qt v{__version__}")
        if self.main_window.taskbar_manager:
            self.main_window.taskbar_manager.hide_progress()

    def save_file_list_as_batch(self): self.preset_manager.save_file_list_as_batch()
    def save_preset(self): self.preset_manager.save_preset()
    def load_preset(self, path: Optional[Path] = None): self.preset_manager.load_preset(path)
    def delete_preset(self): self.preset_manager.delete_preset()
