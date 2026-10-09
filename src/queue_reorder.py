"""
Queue Reordering helpers for FileManager.
Handles moving selected items up/down and drag-and-drop reordering.
"""
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QTreeWidgetItem
from .widgets import FILE_PATH_ROLE


def move_selected_items(file_manager, delta: int):
    """Move selected items up (delta=-1) or down (delta=+1) in queue order."""
    selected_items = file_manager.main_window.file_tree.selectedItems()
    if not selected_items:
        return

    def item_index(it: QTreeWidgetItem) -> int:
        parent = it.parent()
        if parent:
            return parent.indexOfChild(it)
        return file_manager.main_window.file_tree.indexOfTopLevelItem(it)

    sorted_items = sorted(selected_items, key=item_index, reverse=(delta > 0))

    moved = False
    paths_to_reselect = []
    for it in sorted_items:
        p_str = it.data(5, FILE_PATH_ROLE)
        if p_str:
            p = Path(p_str)
            if file_manager.queue.move_item(p, delta):
                moved = True
                paths_to_reselect.append(p)

    if moved:
        file_manager.update_file_list()
        for p in paths_to_reselect:
            item = file_manager.path_to_item.get(p) or file_manager.folder_items.get(p)
            if item:
                item.setSelected(True)
        sm = getattr(file_manager.main_window, 'server_manager', None)
        if sm and sm.usb_handler and sm.usb_handler.is_running:
            checked_names = {it.text(1) for it in file_manager.iter_checked_items()}
            sm.sync_usb_files(file_manager.file_list, checked_names, file_manager.file_targets)


def move_selected_items_next(file_manager) -> bool:
    """Move selected items to immediately follow active/done items in queue order."""
    selected_items = file_manager.main_window.file_tree.selectedItems()
    if not selected_items:
        return False

    top_level_paths = []
    folder_child_paths = {}
    paths_to_reselect = []

    for it in selected_items:
        p_str = it.data(5, FILE_PATH_ROLE)
        if not p_str:
            continue
        p = Path(p_str)
        paths_to_reselect.append(p)
        parent = it.parent()
        if parent:
            parent_p_str = parent.data(5, FILE_PATH_ROLE)
            if parent_p_str:
                folder_child_paths.setdefault(Path(parent_p_str), []).append(p)
        else:
            top_level_paths.append(p)

    moved = False
    if top_level_paths:
        if file_manager.queue.move_top_level_to_next(top_level_paths):
            moved = True

    for f_path, c_paths in folder_child_paths.items():
        if file_manager.queue.move_child_items_to_next(f_path, c_paths):
            moved = True

    if moved:
        file_manager.update_file_list()
        for p in paths_to_reselect:
            item = file_manager.path_to_item.get(p) or file_manager.folder_items.get(p)
            if item:
                item.setSelected(True)
        sm = getattr(file_manager.main_window, 'server_manager', None)
        if sm and sm.usb_handler and sm.usb_handler.is_running:
            checked_names = {it.text(1) for it in file_manager.iter_checked_items()}
            sm.sync_usb_files(file_manager.file_list, checked_names, file_manager.file_targets)
    return moved


def reorder_dragged_path(file_manager, src_path: Path, tgt_path: Optional[Path], before: bool = True) -> bool:
    """Handle drag-and-drop path reordering within the queue."""
    src_res = src_path.resolve()
    is_child, parent_path = False, None
    for f_path, f_rec in file_manager.queue.folders.items():
        if src_res in f_rec.files:
            is_child, parent_path = True, f_path
            break
    if file_manager.queue.reorder_dragged_path(src_path, is_child, parent_path, tgt_path, not before):
        file_manager.update_file_list()
        item = file_manager.path_to_item.get(src_res) or file_manager.folder_items.get(src_res)
        if item:
            item.setSelected(True)
        sm = getattr(file_manager.main_window, 'server_manager', None)
        if sm and sm.usb_handler and sm.usb_handler.is_running:
            checked_names = {it.text(1) for it in file_manager.iter_checked_items()}
            sm.sync_usb_files(file_manager.file_list, checked_names, file_manager.file_targets)
        return True
    return False
