"""
Tests for Sphaira-style dual storage capacity bars, ETA synchronization, and clean Target rendering.
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QTreeWidget, QComboBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utility_functions import format_sphaira_eta
from src.storage_widget import StorageBarRow, SwitchStorageWidget
from src.main_window import MainWindow
from src.theme_manager import ThemeManager
from src.tree_item_builder import build_file_row
from src.queue_manager import FileRecord


def test_format_sphaira_eta_units():
    """Verify format_sphaira_eta adheres to Sphaira's FormatEta contract."""
    # Zero or negative seconds
    assert format_sphaira_eta(0) == ""
    assert format_sphaira_eta(-10) == ""

    # Less than 1 minute
    assert format_sphaira_eta(45) == "0m 45s"

    # Minutes and seconds
    assert format_sphaira_eta(75) == "1m 15s"
    assert format_sphaira_eta(860) == "14m 20s"

    # Exactly 1 hour
    assert format_sphaira_eta(3600) == "1h 0m"

    # Hours and minutes
    assert format_sphaira_eta(3665) == "1h 1m"
    assert format_sphaira_eta(7881) == "2h 11m"


def test_storage_bar_row_and_widget_state():
    """Verify SwitchStorageWidget updates storage capacities, install progress, and paint rendering."""
    app = QApplication.instance() or QApplication(sys.argv)
    tm = ThemeManager()

    widget = SwitchStorageWidget()
    widget.resize(300, 34)

    # Initial empty state
    assert widget.sd_row.total_bytes == 0
    assert widget.nand_row.total_bytes == 0
    assert "Waiting for console storage info" in widget.toolTip()

    # Receive storage info (119.2 GB SD, 27.0 GB NAND)
    nand_total = 29_000_000_000
    nand_free = 12_000_000_000
    sd_total = 128_000_000_000
    sd_free = 25_000_000_000

    widget.set_storage_info(nand_free, nand_total, sd_free, sd_total)
    assert widget.nand_row.free_bytes == nand_free
    assert widget.nand_row.total_bytes == nand_total
    assert widget.sd_row.free_bytes == sd_free
    assert widget.sd_row.total_bytes == sd_total
    assert "microSD:" in widget.toolTip()
    assert "NAND:" in widget.toolTip()

    # Dynamic install progress on microSD: 1.5 GB written of 16.5 GB
    widget.set_install_progress(
        target='sd',
        focus_bytes=1_500_000_000,
        highlight_bytes=16_500_000_000
    )
    assert widget.sd_row.focus_bytes == 1_500_000_000
    assert widget.sd_row.highlight_bytes == 16_500_000_000
    assert widget.nand_row.highlight_bytes == 0
    assert "Installing to microSD:" in widget.toolTip()

    # Render in both dark and light themes without error
    for theme in ('dark', 'light'):
        app.setStyleSheet(tm.get_theme(theme))
        pix = QPixmap(widget.size())
        pix.fill(Qt.GlobalColor.transparent)
        widget.render(pix)
        assert not pix.isNull()

    # Clear install progress
    widget.clear_install_progress()
    assert widget.sd_row.highlight_bytes == 0
    assert widget.sd_row.focus_bytes == 0
    assert "Installing to" not in widget.toolTip()


def test_target_column_has_no_double_text():
    """Verify Target column item has empty text so no text is rendered underneath QComboBox."""
    app = QApplication.instance() or QApplication(sys.argv)
    tree = QTreeWidget()
    tree.setColumnCount(6)
    tree.setHeaderLabels(['', 'Filename', 'Size', 'Target', 'Status', 'Path'])

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
        lambda p, idx: None
    )

    # Item text in column 3 must be empty to avoid ghosting under QComboBox
    assert item.text(3) == "", f"Expected empty text in Target item cell, got: '{item.text(3)}'"
    assert item.data(3, Qt.ItemDataRole.UserRole) == 0

    # Combo widget must be cleanly configured
    combo = tree.itemWidget(item, 3)
    assert isinstance(combo, QComboBox)
    assert combo.currentIndex() == 0
    assert combo.currentText() == "Auto"


def test_sphaira_synchronized_eta_in_coordinator():
    """Verify SessionCoordinator computes dual-format ETA matching Sphaira."""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    sc = win.server_manager.session

    # Case 1: Multiple files with active transfer
    # total 10 GiB, transferred 2 GiB, speed 20 MiB/s -> total remaining 8192 MiB = 409 sec -> 6m 49s
    # current file 2 GiB, transferred 1 GiB -> file remaining 1024 MiB = 51 sec -> 0m 51s
    total_req = 10 * 1024 * 1024 * 1024
    transferred = 2 * 1024 * 1024 * 1024
    cur_size = 2 * 1024 * 1024 * 1024
    cur_bytes = 1 * 1024 * 1024 * 1024
    speed = 20.0  # MB/s

    sc._update_overall_progress_ui(
        transferred=transferred,
        total_req_size=total_req,
        speed=speed,
        completed=0,
        total_files=5,
        cur_bytes=cur_bytes,
        cur_size=cur_size
    )
    # Dual ETA format: file / total
    assert win.eta_label.text() == "ETA: 0m 51s / 6m 49s"

    # Case 2: Terminal Done
    sc._update_overall_progress_ui(
        transferred=total_req,
        total_req_size=total_req,
        speed=speed,
        completed=5,
        total_files=5
    )
    assert win.eta_label.text() == "ETA: Done"

    win.close()
