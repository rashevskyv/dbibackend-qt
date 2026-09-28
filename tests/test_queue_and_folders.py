"""
Regression test suite for File Queue, Folder Hierarchies, Unified Ingestion,
and Duplicate Base Name Conflict Handling.
"""
import sys
import tempfile
import threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QFileDialog
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main_window import MainWindow
from src.folder_dialog import FolderModeDialog
from src.widgets import IS_FOLDER_ROLE, CHECKED_ROLE, IS_CONFLICT_ROLE, FILE_PATH_ROLE
from src.progress_tracker import ProgressTracker
from src.usb_handler import USBHandler


def create_temp_package(directory: Path, filename: str, size: int = 1024) -> Path:
    p = directory / filename
    p.write_bytes(b'X' * size)
    return p


def test_batch_folder_prompt_and_apply_to_all(monkeypatch):
    """Verify that adding 10 folders in a single batch with apply_all prompts only once."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        folders = []
        for i in range(10):
            fdir = tmp_path / f"batch_folder_{i}"
            fdir.mkdir()
            create_temp_package(fdir, f"game_{i}.nsp", 512)
            folders.append(fdir)

        prompt_count = 0

        def fake_ask_mode(folder_name, parent=None):
            nonlocal prompt_count
            prompt_count += 1
            return FolderModeDialog.MODE_FOLDER, True

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', fake_ask_mode)

        fm.ingest_paths(folders)

        assert prompt_count == 1, f"Expected exactly 1 prompt for batch of 10 folders, got {prompt_count}"
        assert len(fm.queue.folders) == 10
        assert len(fm.file_list) == 10

        # Now test that a subsequent separate addition prompts again
        extra_dir = tmp_path / "extra_folder"
        extra_dir.mkdir()
        create_temp_package(extra_dir, "extra.nsp", 512)

        fm.ingest_paths([extra_dir])
        assert prompt_count == 2, "Expected prompt to be shown again on subsequent separate addition"


def test_folder_hierarchy_and_expandability(monkeypatch):
    """Verify folder item has folder icon, is expandable, and contains child files."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        fdir = tmp_path / "CoolGameFolder"
        fdir.mkdir()
        create_temp_package(fdir, "base.nsp", 1000)
        create_temp_package(fdir, "update.nsz", 2000)

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *args, **kwargs: (FolderModeDialog.MODE_FOLDER, True))

        fm.ingest_paths([fdir])

        tree = win.file_tree
        assert tree.topLevelItemCount() == 1
        folder_item = tree.topLevelItem(0)

        assert folder_item.data(0, IS_FOLDER_ROLE) is True
        assert folder_item.isExpanded() is True
        assert folder_item.childCount() == 2

        child1 = folder_item.child(0)
        child2 = folder_item.child(1)

        assert child1.data(0, IS_FOLDER_ROLE) is False
        assert child2.data(0, IS_FOLDER_ROLE) is False
        assert {child1.text(1), child2.text(1)} == {"base.nsp", "update.nsz"}

        # Size check on folder
        assert folder_item.data(2, Qt.ItemDataRole.UserRole) == 3000

        # Accurate file counting (not counting folder container as a file)
        assert len(list(fm.iter_file_items())) == 2
        assert len(list(fm.iter_checked_items())) == 2
        assert "Selected: 2 / 2 files" in win.file_count_label.text()


def test_checkbox_selection_parent_child_sync(monkeypatch):
    """Verify folder and child checkbox interactions (Checked, Unchecked, Tristate)."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        fdir = tmp_path / "MultiPackage"
        fdir.mkdir()
        create_temp_package(fdir, "game1.nsp", 1000)
        create_temp_package(fdir, "game2.nsp", 1000)

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *args, **kwargs: (FolderModeDialog.MODE_FOLDER, True))
        fm.ingest_paths([fdir])

        tree = win.file_tree
        folder_item = tree.topLevelItem(0)
        child1 = folder_item.child(0)
        child2 = folder_item.child(1)

        # Initially both checked, folder checked
        assert fm.is_item_checked(child1) is True
        assert fm.is_item_checked(child2) is True
        assert fm.is_item_checked(folder_item) is True

        # Uncheck child1 -> folder becomes partially checked
        fm.set_item_checked(child1, False)
        assert fm.is_item_checked(child1) is False
        assert fm.is_item_checked(child2) is True
        folder_cb = fm._checkbox_for(folder_item)
        assert folder_cb.checkState() == Qt.CheckState.PartiallyChecked
        assert len(list(fm.iter_checked_items())) == 1

        # Uncheck child2 -> folder becomes unchecked
        fm.set_item_checked(child2, False)
        assert folder_cb.checkState() == Qt.CheckState.Unchecked
        assert len(list(fm.iter_checked_items())) == 0

        # Check folder -> both children become checked
        fm.set_item_checked(folder_item, True)
        assert fm.is_item_checked(child1) is True
        assert fm.is_item_checked(child2) is True
        assert folder_cb.checkState() == Qt.CheckState.Checked


def test_duplicate_basename_conflict_prevention(monkeypatch):
    """Verify that two files with the same name in different folders do not overwrite each other and are flagged."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dir_a = tmp_path / "DirA"
        dir_b = tmp_path / "DirB"
        dir_a.mkdir()
        dir_b.mkdir()

        create_temp_package(dir_a, "Duplicate.nsp", 1024)
        create_temp_package(dir_b, "Duplicate.nsp", 2048)

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *args, **kwargs: (FolderModeDialog.MODE_FOLDER, True))

        # Ingest both folders
        fm.ingest_paths([dir_a, dir_b])

        # Both files must exist in queue without silent overwrite
        assert len(fm.queue.files) == 2
        assert "Duplicate.nsp" in fm.queue.conflicts

        # Ambiguous file must NOT be in the transfer list
        assert "Duplicate.nsp" not in fm.file_list

        tree = win.file_tree
        assert tree.topLevelItemCount() == 2

        folder_a = tree.topLevelItem(0)
        folder_b = tree.topLevelItem(1)

        child_a = folder_a.child(0)
        child_b = folder_b.child(0)

        assert child_a.data(0, IS_CONFLICT_ROLE) is True
        assert child_b.data(0, IS_CONFLICT_ROLE) is True
        assert "Conflict" in child_a.text(4)
        assert "Conflict" in child_b.text(4)

        # Checkboxes must be disabled to prevent ambiguous selection
        cb_a = fm._checkbox_for(child_a)
        cb_b = fm._checkbox_for(child_b)
        assert cb_a.isEnabled() is False
        assert cb_b.isEnabled() is False

        fm.on_target_changed(Path(child_a.data(5, FILE_PATH_ROLE)), 1)
        fm.on_target_changed(Path(child_b.data(5, FILE_PATH_ROLE)), 2)

        # Now remove one of the duplicate items: conflict must resolve for the remaining one!
        fm.remove_selected_items([child_a])

        assert "Duplicate.nsp" not in fm.queue.conflicts
        assert "Duplicate.nsp" in fm.file_list

        # Remaining item is now Queued and selectable
        assert len(fm.file_list) == 1
        remaining_item = fm.item_map.get("Duplicate.nsp")
        assert remaining_item is not None
        assert remaining_item.text(4) == "Queued"
        assert remaining_item.data(0, IS_CONFLICT_ROLE) is None or remaining_item.data(0, IS_CONFLICT_ROLE) is False
        assert fm.file_targets["Duplicate.nsp"] == 2


def test_active_usb_session_dynamic_sync(monkeypatch):
    """Verify child file uncheck/check dynamically updates active USBHandler session."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    sm = win.server_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        fdir = tmp_path / "ActiveSessionFolder"
        fdir.mkdir()
        p1 = create_temp_package(fdir, "part1.nsp", 2048)
        p2 = create_temp_package(fdir, "part2.nsp", 4096)

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *args, **kwargs: (FolderModeDialog.MODE_FOLDER, True))
        fm.ingest_paths([fdir])

        # Attach fake USB handler
        usb_tracker = ProgressTracker(fm.file_list)
        fake_usb = type('FakeUSB', (), {
            'progress_tracker': usb_tracker,
            'is_running': True,
            '_lock': threading.Lock(),
            '_selected_files': set(fm.file_list.keys()),
            '_file_targets': {},
            'file_list': dict(fm.file_list),
            'update_file_registry': lambda all_files, checked, targets=None: None
        })()
        sm.usb_handler = fake_usb

        def real_update_registry(all_files, checked, targets=None):
            fake_usb._selected_files = set(checked)
            for name in list(fake_usb.file_list.keys()):
                if name not in checked:
                    usb_tracker.mark_file_skipped(name)
                else:
                    if name in usb_tracker.skipped_files:
                        usb_tracker.unmark_file_skipped(name)

        fake_usb.update_file_registry = real_update_registry

        tree = win.file_tree
        folder_item = tree.topLevelItem(0)
        child1 = folder_item.child(0)

        # Uncheck child1 during active session
        fm.set_item_checked(child1, False)
        assert child1.text(1) in usb_tracker.skipped_files

        # Re-check child1 during active session
        fm.set_item_checked(child1, True)
        assert child1.text(1) not in usb_tracker.skipped_files


def test_removed_file_disappears_from_active_usb_registry(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = create_temp_package(Path(tmp_dir), 'removed.nsp')
        fm.ingest_paths([path])
        handler = USBHandler(fm.file_list)
        handler.is_running = True
        win.server_manager.usb_handler = handler
        fm.remove_selected_items([fm.path_to_item[path.resolve()]])
        assert path.name not in handler.file_list
        assert path.name not in handler._selected_files


def test_completed_status_survives_queue_rebuild():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        first = create_temp_package(root, 'finished.nsp')
        second = create_temp_package(root, 'later.nsp')
        fm.ingest_paths([first])
        fm.update_file_status(first.name, 'done')
        fm.ingest_paths([second])
        assert fm.get_file_status_code(first.name) == 2
        assert 'Done' in fm.get_file_status(first.name)


def test_preset_roundtrip_preserves_folder_selection_and_target(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    with tempfile.TemporaryDirectory() as tmp_dir:
        folder = Path(tmp_dir) / 'packages'
        folder.mkdir()
        path = create_temp_package(folder, 'saved.nsp')
        preset = Path(tmp_dir) / 'saved.dbi'
        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *a, **kw: (FolderModeDialog.MODE_FOLDER, True))
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(preset), ''))
        fm.ingest_paths([folder])
        fm.set_item_checked(fm.path_to_item[path.resolve()], False)
        fm.on_target_changed(path.name, 2)
        fm.save_preset()
        fm.clear_file_list()
        fm.load_preset(preset)
        assert folder.resolve() in fm.queue.folders
        assert fm.queue.files[path.resolve()].checked is False
        assert fm.file_targets[path.name] == 2
        assert len(list(fm.iter_checked_items())) == 0


def test_unified_ingestion_equality(monkeypatch):
    """Verify Add Folder, Drag-and-Drop, and handle_external_files follow the identical ingestion pipeline."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        test_dir = tmp_path / "UnifiedTest"
        test_dir.mkdir()
        create_temp_package(test_dir, "pkg1.nsp", 500)
        create_temp_package(test_dir, "pkg2.nsz", 700)

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *args, **kwargs: (FolderModeDialog.MODE_FOLDER, True))

        # External file call
        win.handle_external_files(str(test_dir))
        assert len(fm.file_list) == 2
        assert len(fm.queue.folders) == 1
        fm.clear_file_list()

        # Ingest call (simulating drag and drop)
        fm.ingest_paths([test_dir])
        assert len(fm.file_list) == 2
        assert len(fm.queue.folders) == 1
