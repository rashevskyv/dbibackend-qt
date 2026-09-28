"""
Regression tests for USB transfer session and Target column progress:
1. STATUS_INSTALLED -> repeated metadata FileRange -> List/ACK:
   Done status, 100% progress, and completed files counter are preserved.
2. Repeated and overlapping range requests do not double counted bytes.
3. Real Qt render confirms partial and full progress visibility inside Target combo,
   while target combo selection changes continue to function normally.
"""
import sys
import struct
import tempfile
import threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem, QComboBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import dbi_protocol
from src.main_window import MainWindow
from src.progress_tracker import ProgressTracker
from src.usb_handler import USBHandler
from src.theme_manager import ThemeManager
from src.widgets import ProgressDelegate
from src.tree_item_builder import build_file_row
from src.queue_manager import FileRecord, STATUS_QUEUED, STATUS_DONE


class FakeInEp:
    def __init__(self, responses):
        self.responses = list(responses)

    def read(self, size, timeout=None):
        return self.responses.pop(0) if self.responses else b'\x00' * size


class FakeOutEp:
    def __init__(self, write_fn=None):
        self.write_fn = write_fn

    def write(self, data, timeout=None):
        return self.write_fn(data) if self.write_fn else len(data)


def test_status_installed_survives_metadata_and_list_ack():
    """STATUS_INSTALLED -> repeated metadata FileRange -> List/ACK:
    status Done, 100% progress, and completed files counter are preserved.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    sm = win.server_manager
    fm = win.file_manager

    with tempfile.NamedTemporaryFile(delete=False, suffix='.nsp') as t1, \
         tempfile.NamedTemporaryFile(delete=False, suffix='.nsp') as t2:
        t1.write(b'data1' * 10000)
        t2.write(b'data2' * 10000)
        p1, p2 = Path(t1.name), Path(t2.name)

    usb_handler = None
    try:
        win.handle_external_files(f"{p1}\n{p2}")
        f1, f2 = p1.name, p2.name

        usb_tracker = ProgressTracker(fm.file_list)
        usb_handler = USBHandler(fm.file_list)
        usb_handler.progress_tracker = usb_tracker
        usb_handler.is_running = True
        sm.usb_handler = usb_handler

        # 1. Console confirms f1 installed
        sm.on_package_status_received(f1, dbi_protocol.STATUS_INSTALLED, 0)
        assert f1 in sm.completed_files_set
        assert sm.transfer_stats['completed_files'] == 1
        assert fm.get_file_status_code(f1) == STATUS_DONE
        assert win.progress_delegate.progress_data.get(f1) == 100
        item1 = fm.item_map.get(f1)
        assert item1 is not None
        assert item1.text(4) == "✅ Done"
        assert not fm.is_item_checked(item1)  # Automatically unchecked after install

        # 2. Repeated metadata FileRange request for f1 (range_offset=0, size < 100KB)
        req_meta = struct.pack('<IQ4x', 500, 0) + f1.encode('utf-8')
        usb_handler.in_ep = FakeInEp([req_meta, b'\x00' * 16, b''])
        usb_handler.out_ep = FakeOutEp()
        usb_handler.process_file_range_command(len(req_meta))

        # Status Done, 100% progress, and completed counter must NOT be reset to Queued
        assert fm.get_file_status_code(f1) == STATUS_DONE, "Status must remain Done after metadata request"
        assert item1.text(4) == "✅ Done"
        assert win.progress_delegate.progress_data.get(f1) == 100, "Progress must remain 100%"
        assert sm.transfer_stats['completed_files'] == 1, "Completed files counter must remain 1"
        assert f1 in sm.completed_files_set

        # 3. New List/ACK sequence (live queue revision confirmation)
        usb_handler.queue_revision = 2
        usb_handler.last_sent_revision = 2
        usb_handler.process_list_ack(2)

        assert fm.get_file_status_code(f1) == STATUS_DONE, "Status must remain Done after List ACK"
        assert item1.text(4) == "✅ Done"
        assert sm.transfer_stats['completed_files'] == 1, "Completed files counter must remain 1"
        assert win.progress_delegate.progress_data.get(f1) == 100

        # Also verify dim_unchecked_items does not turn Done into grey
        fm.dim_unchecked_items()
        assert item1.text(4) == "✅ Done"
        assert item1.foreground(4).color().name().lower() == "#4caf50"
    finally:
        if usb_handler and usb_handler.cached_file_handle:
            usb_handler.cached_file_handle.close()
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)


def test_repeated_and_overlapping_ranges_do_not_double_bytes():
    """Repeated and overlapping range requests do not double counted bytes."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.nsp') as tmp:
        tmp.write(b'B' * 1_000_000)
        p = Path(tmp.name)
    fname = p.name

    try:
        tracker = ProgressTracker({fname: p})
        assert tracker.transferred_bytes == 0
        assert tracker.unique_bytes_transferred == 0

        # Request 1: 0..500_000
        u1 = tracker.add_interval(fname, 0, 500_000)
        assert u1 == 500_000
        assert tracker.unique_bytes_transferred == 500_000
        assert tracker.transferred_bytes == 500_000

        # Request 2: duplicate 0..500_000 (must NOT increase bytes)
        u2 = tracker.add_interval(fname, 0, 500_000)
        assert u2 == 500_000
        assert tracker.unique_bytes_transferred == 500_000
        assert tracker.transferred_bytes == 500_000

        # Request 3: overlapping 250_000..750_000 (only adds 250_000 unique bytes)
        u3 = tracker.add_interval(fname, 250_000, 750_000)
        assert u3 == 750_000
        assert tracker.unique_bytes_transferred == 750_000
        assert tracker.transferred_bytes == 750_000

        # Request 4: full range 0..1_000_000
        u4 = tracker.add_interval(fname, 0, 1_000_000)
        assert u4 == 1_000_000
        assert tracker.unique_bytes_transferred == 1_000_000
        assert tracker.transferred_bytes == 1_000_000

        # Request 5: repeated full range
        u5 = tracker.add_interval(fname, 0, 1_000_000)
        assert u5 == 1_000_000
        assert tracker.unique_bytes_transferred == 1_000_000
        assert tracker.transferred_bytes == 1_000_000

        # Now verify USBHandler transfer loop with duplicate range
        handler = USBHandler({fname: p})
        handler.is_running = True
        req_1 = struct.pack('<IQ4x', 400_000, 0) + fname.encode('utf-8')
        handler.in_ep = FakeInEp([req_1, b'\x00' * 16])
        handler.out_ep = FakeOutEp()
        handler.process_file_range_command(len(req_1))
        credited_1 = handler.progress_tracker.unique_bytes_transferred
        assert credited_1 == 400_000
        assert handler.progress_tracker.transferred_bytes == 400_000

        # Send same range again: credited bytes must not double
        req_2 = struct.pack('<IQ4x', 400_000, 0) + fname.encode('utf-8')
        handler.in_ep = FakeInEp([req_2, b'\x00' * 16])
        handler.process_file_range_command(len(req_2))
        credited_2 = handler.progress_tracker.unique_bytes_transferred
        assert credited_2 == 400_000, f"Expected 400000 bytes after duplicate, got {credited_2}"
        assert handler.progress_tracker.transferred_bytes == 400_000

        if handler.cached_file_handle:
            handler.cached_file_handle.close()
    finally:
        p.unlink(missing_ok=True)


def test_target_column_progress_visibility_and_interaction():
    """Real Qt render verifies partial progress is visible inside Target combo,
    and target changes continue to work normally via mouse/keyboard.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    tm = ThemeManager()

    for theme_name in ('dark', 'light'):
        app.setStyleSheet(tm.get_theme(theme_name))

        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(['Check', 'Name', 'Size', 'Target', 'Status'])
        tree.setColumnWidth(0, 50)
        tree.setColumnWidth(1, 150)
        tree.setColumnWidth(2, 80)
        tree.setColumnWidth(3, 100)
        tree.setColumnWidth(4, 100)

        delegate = ProgressDelegate(tree, tree)
        tree.setItemDelegate(delegate)

        target_changes = []
        fake_path = Path("/fake/game.nsp")
        rec = FileRecord(path=fake_path, name="game.nsp", size=1024)
        item = build_file_row(
            tree,
            fake_path,
            rec,
            tree.style().standardIcon(tree.style().StandardPixmap.SP_FileIcon),
            True,
            0,
            lambda it, st: None,
            lambda path, idx: target_changes.append((path, idx)),
        )

        tree.resize(600, 200)
        tree.show()
        app.processEvents()

        combo = tree.itemWidget(item, 3)
        assert isinstance(combo, QComboBox)

        # Verify normal combo interaction
        assert combo.currentIndex() == 0
        assert combo.currentText() == "Auto"
        combo.setCurrentIndex(1)
        assert combo.currentText() == "SD Card"
        assert len(target_changes) == 1
        assert target_changes[-1][1] == 1

        vp_pos = tree.viewport().pos()
        cpos = combo.pos()
        # Sample points inside Target column (combo width: 100px)
        # Point 1 (x_cov): covered at 55%
        # Point 2 (x_uncov): not yet reached at 55%
        x_cov = vp_pos.x() + cpos.x() + 35
        x_uncov = vp_pos.x() + cpos.x() + 75
        py = vp_pos.y() + cpos.y() + 12

        # 0% progress: baseline render
        delegate.set_progress("game.nsp", 0)
        pix0 = QPixmap(tree.size())
        pix0.fill(Qt.GlobalColor.transparent)
        tree.render(pix0)
        img0 = pix0.toImage()

        color_0_cov = img0.pixel(x_cov, py)
        color_0_uncov = img0.pixel(x_uncov, py)

        # Set partial progress (55%) so fill boundary falls directly inside Target combo
        delegate.set_progress("game.nsp", 55)
        tree.viewport().update()
        pix_partial = QPixmap(tree.size())
        pix_partial.fill(Qt.GlobalColor.transparent)
        tree.render(pix_partial)
        img_partial = pix_partial.toImage()

        color_partial_cov = img_partial.pixel(x_cov, py)
        color_partial_uncov = img_partial.pixel(x_uncov, py)

        # Covered point inside combo is filled with progress color
        assert color_partial_cov != color_0_cov, (
            f"Theme {theme_name}: partial progress must be visible inside Target combo left side"
        )
        # Uncovered point beyond progress boundary remains unfilled background
        assert color_partial_uncov == color_0_uncov, (
            f"Theme {theme_name}: area beyond progress boundary in Target combo must not be filled"
        )

        # 100% progress: entire row and Target combo is filled with progress color
        delegate.set_progress("game.nsp", 100)
        pix_full = QPixmap(tree.size())
        pix_full.fill(Qt.GlobalColor.transparent)
        tree.render(pix_full)
        img_full = pix_full.toImage()

        color_full_cov = img_full.pixel(x_cov, py)
        color_full_uncov = img_full.pixel(x_uncov, py)

        assert color_full_cov == color_partial_cov, (
            f"Theme {theme_name}: full progress fill color must match partial fill color"
        )
        assert color_full_uncov != color_0_uncov, (
            f"Theme {theme_name}: full progress must cover previously uncovered point"
        )
        tree.close()
