"""
Queue sorting by column (header click), row drag from the real mouse path,
the drag handle, and Set as Next. Mouse events go through the tree viewport.
"""
import sys
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QDropEvent, QMouseEvent
from PyQt6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.main_window import MainWindow
from src import tree_item_builder, widgets
from src.queue_manager import QueueManager, STATUS_DONE, STATUS_FAILED


def create_pkg(dir_path: Path, name: str, size: int = 10) -> Path:
    p = dir_path / name
    p.write_bytes(b'Z' * size)
    return p


def name_cell(tree, item):
    return tree.visualRect(tree.indexFromItem(item, 1)).center()


def send_mouse(widget, kind, pos, buttons):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(pos), Qt.MouseButton.LeftButton, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)


class RecordingDrag:
    """Stands in for QDrag: runs the drag enter, move and drop that the OS would send."""
    created = []
    drop_row = 2
    marker_seen = None

    def __init__(self, source):
        self.source = source
        self.mime = None
        RecordingDrag.created.append(self)

    def setMimeData(self, mime): self.mime = mime
    def setPixmap(self, pixmap): pass
    def setHotSpot(self, point): pass

    def exec(self, *actions):
        tree = self.source
        assert self.mime is not None  # without mime QDrag.exec() drops nothing
        target = tree.visualItemRect(tree.topLevelItem(RecordingDrag.drop_row))
        pos = QPointF(target.center().x(), target.bottom() - 1)
        tree.dragEnterEvent(QDropEvent(pos, Qt.DropAction.MoveAction, self.mime,
                                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        tree.dragMoveEvent(QDropEvent(pos, Qt.DropAction.MoveAction, self.mime,
                                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        RecordingDrag.marker_seen = tree.drop_marker.isVisible()
        drop = QDropEvent(pos, Qt.DropAction.MoveAction, self.mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        tree.dropEvent(drop)
        assert drop.isAccepted()


def make_window(tmp_dir, names):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    paths = [create_pkg(Path(tmp_dir), n) for n in names]
    win.file_manager.ingest_paths(paths)
    win.show()  # the tree needs a real layout for mouse hit tests
    app.processEvents()
    return app, win, paths


def test_sort_by_keeps_frozen_prefix_and_sorts_folder_children(tmp_path):
    q = QueueManager()
    done = create_pkg(tmp_path, 'zz_done.nsp', 50)
    big = create_pkg(tmp_path, 'b_big.nsp', 300)
    small = create_pkg(tmp_path, 'c_small.nsp', 10)
    failed = create_pkg(tmp_path, 'a_failed.nsp', 100)
    q.add_flat_files([done, big, small, failed])
    folder = tmp_path / 'f'
    folder.mkdir()
    kids = [create_pkg(folder, 'y.nsp', 1), create_pkg(folder, 'x.nsp', 2)]
    q.add_folder_hierarchical(folder, kids)
    q.files[done.resolve()].status_code = STATUS_DONE
    q.files[failed.resolve()].status_code = STATUS_FAILED
    r = lambda *ps: [p.resolve() for p in ps]

    assert q.sort_by('name')
    assert q.order == r(done, failed, big, small, folder)  # the done row stays first
    assert q.folders[folder.resolve()].files == r(kids[1], kids[0])

    assert q.sort_by('size', descending=True)
    assert q.order == r(done, big, failed, small, folder)  # folder total is 3 bytes

    assert q.sort_by('status')
    assert q.order[:2] == r(done, big) and q.order[-1] == failed.resolve()
    assert not q.sort_by('status')  # already sorted: nothing to sync


def test_drag_from_row_name_cell_reorders_queue(monkeypatch):
    RecordingDrag.created = []
    RecordingDrag.drop_row = 2
    monkeypatch.setattr(widgets, 'QDrag', RecordingDrag)
    with tempfile.TemporaryDirectory() as tmp_dir:
        app, win, paths = make_window(tmp_dir, ('a.nsp', 'b.nsp', 'c.nsp'))
        tree = win.file_tree
        press = name_cell(tree, tree.topLevelItem(0))
        far = QPoint(press.x(), press.y() + 40)
        QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press)
        send_mouse(tree.viewport(), QMouseEvent.Type.MouseMove, far, Qt.MouseButton.LeftButton)
        assert len(RecordingDrag.created) == 1
        assert RecordingDrag.marker_seen is True  # blue drop line shown during the drag
        assert not tree.drop_marker.isVisible()  # hidden after the drop
        assert win.file_manager.queue.order == [p.resolve() for p in (paths[1], paths[2], paths[0])]
        win.close()


def test_small_move_is_a_click_not_a_drag(monkeypatch):
    RecordingDrag.created = []
    monkeypatch.setattr(widgets, 'QDrag', RecordingDrag)
    with tempfile.TemporaryDirectory() as tmp_dir:
        app, win, paths = make_window(tmp_dir, ('a.nsp', 'b.nsp', 'c.nsp'))
        tree = win.file_tree
        press = name_cell(tree, tree.topLevelItem(0))
        near = QPoint(press.x() + 1, press.y() + 1)
        QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press)
        send_mouse(tree.viewport(), QMouseEvent.Type.MouseMove, near, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, near)
        assert RecordingDrag.created == []
        assert tree.selectedItems() == [tree.topLevelItem(0)]
        assert win.file_manager.queue.order == [p.resolve() for p in paths]
        win.close()


def test_ctrl_click_still_extends_selection(monkeypatch):
    RecordingDrag.created = []
    monkeypatch.setattr(widgets, 'QDrag', RecordingDrag)
    with tempfile.TemporaryDirectory() as tmp_dir:
        app, win, paths = make_window(tmp_dir, ('a.nsp', 'b.nsp', 'c.nsp'))
        tree = win.file_tree
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         name_cell(tree, tree.topLevelItem(0)))
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                         name_cell(tree, tree.topLevelItem(2)))
        assert len(tree.selectedItems()) == 2
        assert RecordingDrag.created == []
        win.close()


def test_done_row_does_not_start_a_row_drag(monkeypatch):
    RecordingDrag.created = []
    monkeypatch.setattr(widgets, 'QDrag', RecordingDrag)
    with tempfile.TemporaryDirectory() as tmp_dir:
        app, win, paths = make_window(tmp_dir, ('a.nsp', 'b.nsp', 'c.nsp'))
        tree = win.file_tree
        win.file_manager.set_file_status('a.nsp', 'done')
        press = name_cell(tree, tree.topLevelItem(0))
        far = QPoint(press.x(), press.y() + 40)
        QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press)
        send_mouse(tree.viewport(), QMouseEvent.Type.MouseMove, far, Qt.MouseButton.LeftButton)
        assert RecordingDrag.created == []
        win.close()


def test_drag_handle_hands_its_mime_to_the_drop(monkeypatch):
    RecordingDrag.created = []
    RecordingDrag.drop_row = 2
    monkeypatch.setattr(widgets, 'QDrag', RecordingDrag)
    with tempfile.TemporaryDirectory() as tmp_dir:
        app, win, paths = make_window(tmp_dir, ('a.nsp', 'b.nsp', 'c.nsp'))
        tree = win.file_tree
        handle = tree.itemWidget(tree.topLevelItem(0), 0).findChild(tree_item_builder.DragHandle)
        start = QPointF(handle.rect().center())
        far = QPointF(start.x(), start.y() + 40)
        handle.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, start, start,
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                           Qt.KeyboardModifier.NoModifier))
        handle.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, far, far,
                                          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.NoModifier))
        assert len(RecordingDrag.created) == 1
        assert win.file_manager.queue.order == [p.resolve() for p in (paths[1], paths[2], paths[0])]
        win.close()


def test_set_as_next_still_moves_selected_row():
    with tempfile.TemporaryDirectory() as tmp_dir:
        app, win, paths = make_window(tmp_dir, ('a.nsp', 'b.nsp', 'c.nsp'))
        tree = win.file_tree
        tree.clearSelection()
        tree.topLevelItem(2).setSelected(True)
        win.move_selected_next()
        assert win.file_manager.queue.order == [p.resolve() for p in (paths[2], paths[0], paths[1])]
        win.close()


def test_header_click_sorts_queue_and_keeps_statuses():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        sizes = {'d_done.nsp': 5, 'b.nsp': 20, 'a_fail.nsp': 30, 'c.nsp': 10, 'e_off.nsp': 40}
        paths = [create_pkg(tmp, n, s) for n, s in sizes.items()]
        fm.ingest_paths(paths)
        fm.set_file_status('d_done.nsp', 'done')
        fm.set_file_status('a_fail.nsp', 'failed')
        fm.set_item_checked(fm.item_map['e_off.nsp'], False)
        tree = win.file_tree
        win.show()
        app.processEvents()
        header = tree.header()
        names = lambda: [tree.topLevelItem(i).text(1) for i in range(tree.topLevelItemCount())]

        def click(section):
            x = header.sectionViewportPosition(section) + header.sectionSize(section) // 2
            QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(x, header.height() // 2))
            app.processEvents()

        click(2)
        assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (2, Qt.SortOrder.AscendingOrder)
        assert names() == ['d_done.nsp', 'c.nsp', 'b.nsp', 'a_fail.nsp', 'e_off.nsp']
        click(2)
        assert names() == ['d_done.nsp', 'e_off.nsp', 'a_fail.nsp', 'b.nsp', 'c.nsp']
        assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (2, Qt.SortOrder.DescendingOrder)
        click(1)
        assert names() == ['d_done.nsp', 'a_fail.nsp', 'b.nsp', 'c.nsp', 'e_off.nsp']
        click(4)  # Queued checked, Queued unchecked, Failed
        assert names() == ['d_done.nsp', 'b.nsp', 'c.nsp', 'e_off.nsp', 'a_fail.nsp']
        click(0)  # select-all column: no sort, indicator stays
        assert header.sortIndicatorSection() == 4

        done = fm.item_map['d_done.nsp']
        assert done.text(4) == '✅ Done' and fm.item_map['a_fail.nsp'].text(4) == '❌ Failed'
        assert not tree.itemWidget(done, 0).findChild(tree_item_builder.DragHandle).is_draggable()
    win.close()
