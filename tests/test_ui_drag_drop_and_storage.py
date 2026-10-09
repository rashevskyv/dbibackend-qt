"""
Unit and regression tests for:
- Mouse drag-and-drop queue reordering (drag handle, top-level, child, active/done protection)
- Table header column 0 3-state checkbox
- Header bar compact Switch storage display (ElidingLabel)
- Keyboard shortcuts Alt+Up / Alt+Down
"""
import sys
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QMimeData
from PyQt6.QtGui import QCursor, QDropEvent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main_window import MainWindow
from src.folder_dialog import FolderModeDialog
from src.widgets import CheckBoxHeaderView, ElidingLabel, FILE_PATH_ROLE, IS_FOLDER_ROLE
from src.tree_item_builder import DragHandle
from src.queue_manager import STATUS_PROCESS, STATUS_DONE


def create_pkg(dir_path: Path, name: str, size: int = 1024) -> Path:
    p = dir_path / name
    p.write_bytes(b'Z' * size)
    return p


def test_drag_handle_properties_and_active_protection(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p1 = create_pkg(tmp, "p1.nsp")
        p2 = create_pkg(tmp, "p2.nsp")
        p3 = create_pkg(tmp, "p3.nsp")

        fm.ingest_paths([p1, p2, p3])

        tree = win.file_tree
        assert tree.topLevelItemCount() == 3

        item1 = tree.topLevelItem(0)
        widget1 = tree.itemWidget(item1, 0)
        assert widget1 is not None

        handle1 = widget1.findChild(DragHandle)
        assert handle1 is not None
        assert handle1.cursor().shape() == Qt.CursorShape.SizeAllCursor
        assert handle1.is_draggable() is True

        # Mark item1 as STATUS_PROCESS -> cannot be dragged
        fm.set_file_status(p1.name, STATUS_PROCESS)
        assert handle1.is_draggable() is False

        # Mark item2 as STATUS_DONE -> cannot be dragged
        item2 = tree.topLevelItem(1)
        widget2 = tree.itemWidget(item2, 0)
        handle2 = widget2.findChild(DragHandle)
        fm.set_file_status(p2.name, STATUS_DONE)
        assert handle2.is_draggable() is False

        # Item3 remains pending -> can be dragged
        item3 = tree.topLevelItem(2)
        widget3 = tree.itemWidget(item3, 0)
        handle3 = widget3.findChild(DragHandle)
        assert handle3.is_draggable() is True


def test_reorder_top_level_and_active_prefix():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        f1 = create_pkg(tmp, "a_file1.nsp")
        f2 = create_pkg(tmp, "b_file2.nsp")
        f3 = create_pkg(tmp, "c_file3.nsp")
        f4 = create_pkg(tmp, "d_file4.nsp")

        fm.ingest_paths([f1, f2, f3, f4])

        r1 = f1.resolve()
        r2 = f2.resolve()
        r3 = f3.resolve()
        r4 = f4.resolve()

        assert fm.queue.order == [r1, r2, r3, r4]

        # Freeze f1 (done) and f2 (in-process)
        fm.set_file_status(f1.name, STATUS_DONE)
        fm.set_file_status(f2.name, STATUS_PROCESS)

        # Attempt to move f4 before f1 (index 0) -> forbidden!
        moved = fm.queue.reorder_top_level(3, 0)
        assert moved is False
        assert fm.queue.order == [r1, r2, r3, r4]

        # Attempt to move f4 before f2 (index 1) -> forbidden!
        moved = fm.queue.reorder_top_level(3, 1)
        assert moved is False
        assert fm.queue.order == [r1, r2, r3, r4]

        # Attempt to move f1 or f2 -> forbidden!
        assert fm.queue.reorder_top_level(0, 3) is False
        assert fm.queue.reorder_top_level(1, 3) is False
        assert fm.queue.move_item(r2, 1) is False  # Alt+Down shares the same guard.
        assert fm.queue.move_item(r3, -1) is False

        # Move f4 before f3 (index 2) with active usb_handler -> allowed and syncs files!
        import threading
        from unittest.mock import MagicMock
        mock_usb = MagicMock()
        mock_usb.is_running = True
        mock_usb.queue_revision = 2
        mock_usb.confirmed_revision = 1
        mock_usb._selected_files = set()
        mock_usb._lock = threading.Lock()
        mock_usb.progress_tracker.transferred_bytes = 0
        mock_usb.progress_tracker.total_requested_size = 0
        win.server_manager.usb_handler = mock_usb
        moved = fm.reorder_dragged_path(r4, r3, before=True)
        assert moved is True
        assert fm.queue.order == [r1, r2, r4, r3]
        mock_usb.update_file_registry.assert_called()

        # Tree view matches
        assert win.file_tree.topLevelItem(0).data(5, FILE_PATH_ROLE) == str(r1)
        assert win.file_tree.topLevelItem(1).data(5, FILE_PATH_ROLE) == str(r2)
        assert win.file_tree.topLevelItem(2).data(5, FILE_PATH_ROLE) == str(r4)
        assert win.file_tree.topLevelItem(3).data(5, FILE_PATH_ROLE) == str(r3)


def test_tree_drop_routes_through_queue_and_accepts_move():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        paths = [create_pkg(tmp, f"{name}.nsp") for name in ("a", "b", "c")]
        win.file_manager.ingest_paths(paths)
        tree = win.file_tree
        tree.show()
        app.processEvents()
        target = tree.visualItemRect(tree.topLevelItem(0))
        mime = QMimeData()
        mime.setData("application/x-dbibackend-drag-path", str(paths[2].resolve()).encode())
        mime.setData("application/x-dbibackend-drag-kind", b"top")
        event = QDropEvent(QPointF(target.center().x(), target.top() + 1),
                           Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)
        tree.dropEvent(event)
        assert event.isAccepted()
        assert win.file_manager.queue.order == [p.resolve() for p in (paths[2], paths[0], paths[1])]
    win.close()


def test_child_reordering_within_folder_and_isolation(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        folder = tmp / "GameFolder"
        folder.mkdir()
        c1 = create_pkg(folder, "c1.nsp")
        c2 = create_pkg(folder, "c2.nsp")
        c3 = create_pkg(folder, "c3.nsp")
        standalone = create_pkg(tmp, "standalone.nsp")

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *a, **k: (FolderModeDialog.MODE_FOLDER, True))
        fm.ingest_paths([folder, standalone])

        folder_obj = fm.queue.folders[folder.resolve()]
        r1, r2, r3 = c1.resolve(), c2.resolve(), c3.resolve()
        assert folder_obj.files == [r1, r2, r3]

        # Reorder c3 before c2 inside the folder
        moved = fm.reorder_dragged_path(r3, r2, before=True)
        assert moved is True
        assert folder_obj.files == [r1, r3, r2]

        # Attempt to drag child c3 before standalone top-level -> forbidden!
        assert fm.reorder_dragged_path(r3, standalone.resolve(), before=True) is False
        assert folder_obj.files == [r1, r3, r2]

        # Attempt to drag standalone into child position -> forbidden!
        assert fm.reorder_dragged_path(standalone.resolve(), r2, before=True) is False

        # Mark c1 as in-process -> cannot move c2 before c1
        fm.set_file_status(c1.name, STATUS_PROCESS)
        assert fm.reorder_dragged_path(r2, r1, before=True) is False


def test_header_checkbox_tristate_and_file_counting(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        folder = tmp / "FolderA"
        folder.mkdir()
        f1 = create_pkg(folder, "f1.nsp")
        f2 = create_pkg(folder, "f2.nsp")
        f3 = create_pkg(tmp, "f3.nsp")

        monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *a, **k: (FolderModeDialog.MODE_FOLDER, True))
        fm.ingest_paths([folder, f3])

        # Header view is CheckBoxHeaderView
        header = win.file_tree.header()
        assert isinstance(header, CheckBoxHeaderView)
        assert header.checkbox is not None

        # All 3 files initially checked
        assert header.checkbox.checkState() == Qt.CheckState.Checked

        # Uncheck 1 file -> Tristate PartiallyChecked
        item_f3 = fm.path_to_item[f3.resolve()]
        fm.set_item_checked(item_f3, False)
        assert header.checkbox.checkState() == Qt.CheckState.PartiallyChecked

        # Uncheck remaining 2 files -> Unchecked
        item_f1 = fm.path_to_item[f1.resolve()]
        item_f2 = fm.path_to_item[f2.resolve()]
        fm.set_item_checked(item_f1, False)
        fm.set_item_checked(item_f2, False)
        assert header.checkbox.checkState() == Qt.CheckState.Unchecked

        # Trigger header toggle -> all become checked
        win.on_header_checkbox_changed(Qt.CheckState.Checked.value)
        assert fm.queue.files[f1.resolve()].checked is True
        assert fm.queue.files[f2.resolve()].checked is True
        assert fm.queue.files[f3.resolve()].checked is True
        assert header.checkbox.checkState() == Qt.CheckState.Checked


def test_switch_storage_compact_display_and_narrow_window():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()

    label = win.ui_manager.switch_storage_label
    assert isinstance(label, ElidingLabel)
    # Storage label is in header_widget before mode switch
    assert label.parentWidget() is win.ui_manager.header_widget

    # Status bar does not contain a duplicate switch_storage_label
    sb = win.statusBar
    assert sb.findChild(ElidingLabel, "switch_storage_label") is None

    # Before receiving data, label does not invent fake numbers
    assert "25." not in label.text()

    # Receive storage info
    win.server_manager.on_storage_info_received(
        nand_free=12_000_000_000,
        nand_total=29_000_000_000,
        sd_free=25_000_000_000,
        sd_total=128_000_000_000
    )
    win.resize(1100, 760)
    win.show()
    app.processEvents()

    text = label.text()
    assert "🎮 SD:" in text
    assert "NAND:" in text
    assert "·" in text
    assert label.width() > 0

    # Narrow window test: ElidingLabel with width=50px does not crash
    label.resize(50, 20)
    assert label.minimumWidth() == 0


def test_alt_up_down_shortcuts_retained_and_toolbar_cleaned():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()

    # Move Up / Down toolbar buttons were removed
    assert not hasattr(win, 'move_up_btn')
    assert not hasattr(win, 'move_down_btn')

    # Keyboard shortcuts Alt+Up / Alt+Down still exist on MainWindow shortcuts
    assert win.shortcut_move_up.key().toString() == "Alt+Up"
    assert win.shortcut_move_down.key().toString() == "Alt+Down"


def test_move_selected_next_in_queue_and_context_menu(tmp_path, monkeypatch):
    """Verify 'Set as Next in Queue' moves selected items right after active/completed items."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager

    # Create dummy nsp files
    f1 = tmp_path / "game1.nsp"
    f2 = tmp_path / "game2.nsp"
    f3 = tmp_path / "game3.nsp"
    f4 = tmp_path / "game4.nsp"
    f5 = tmp_path / "game5.nsp"
    for f in (f1, f2, f3, f4, f5):
        f.write_bytes(b"\x00" * 1024)

    fm.ingest_paths([f1, f2, f3, f4, f5])
    r1, r2, r3, r4, r5 = f1.resolve(), f2.resolve(), f3.resolve(), f4.resolve(), f5.resolve()
    assert fm.queue.order == [r1, r2, r3, r4, r5]

    # Freeze r1 (done) and r2 (in process) -> frozen_len = 2
    from src.queue_manager import STATUS_DONE, STATUS_PROCESS
    fm.queue.files[r1].status_code = STATUS_DONE
    fm.queue.files[r2].status_code = STATUS_PROCESS

    # Select r5 and trigger move_selected_next
    win.file_tree.clearSelection()
    item5 = fm.path_to_item[r5]
    item5.setSelected(True)

    moved = fm.move_selected_next()
    assert moved is True
    # r5 should now be immediately after active items (at index 2)
    assert fm.queue.order == [r1, r2, r5, r3, r4]

    # Try moving already done r1 -> cannot be moved
    win.file_tree.clearSelection()
    item1 = fm.path_to_item[r1]
    item1.setSelected(True)
    moved_done = fm.move_selected_next()
    assert moved_done is False
    assert fm.queue.order == [r1, r2, r5, r3, r4]

    # Folder child test
    folder = tmp_path / "subfolder"
    folder.mkdir()
    c1 = folder / "child1.nsp"
    c2 = folder / "child2.nsp"
    c3 = folder / "child3.nsp"
    for c in (c1, c2, c3):
        c.write_bytes(b"\x00" * 512)

    fm.ingest_paths([folder], default_folder_mode="folder")
    rc1, rc2, rc3 = c1.resolve(), c2.resolve(), c3.resolve()
    f_res = folder.resolve()
    assert fm.queue.folders[f_res].files == [rc1, rc2, rc3]

    # Freeze rc1
    fm.queue.files[rc1].status_code = STATUS_DONE

    # Select rc3 inside folder
    win.file_tree.clearSelection()
    item_c3 = fm.path_to_item[rc3]
    item_c3.setSelected(True)
    moved_child = fm.move_selected_next()
    assert moved_child is True
    assert fm.queue.folders[f_res].files == [rc1, rc3, rc2]

    # Context menu test: verify 'Set as Next in Queue' exists
    from PyQt6.QtWidgets import QMenu
    menu_actions = []
    orig_exec = QMenu.exec
    monkeypatch.setattr(QMenu, "exec", lambda self, *args: menu_actions.extend([a.text() for a in self.actions()]))
    from PyQt6.QtCore import QPoint
    win.show_context_menu(QPoint(10, 10))
    assert "Set as Next in Queue" in menu_actions
    assert "Move Up (Alt+Up)" in menu_actions
    assert "Move Down (Alt+Down)" in menu_actions
    win.close()

