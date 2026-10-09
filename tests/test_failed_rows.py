"""Failed rows: they can leave the finished part of the queue, Retry puts them back next,
a drive they cannot fit on is refused, and the installing row stays pinned on screen."""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.main_window import MainWindow  # noqa: E402
from src import dbi_protocol as p  # noqa: E402
from src.widgets import FILE_PATH_ROLE  # noqa: E402


APP = QApplication.instance() or QApplication(sys.argv)


def make(tmp_path, names):
    win = MainWindow()
    paths = []
    for n in names:
        (tmp_path / n).write_bytes(b'X' * 1024)
        paths.append(tmp_path / n)
    win.file_manager.ingest_paths(paths)
    return win


def order(win):
    fm = win.file_manager
    return [fm.queue.files[q].name for q in fm.queue.order]


def select(win, name):
    win.file_tree.clearSelection()
    win.file_manager.item_map[name].setSelected(True)


def test_failed_row_between_done_rows_moves_next_and_retries(tmp_path):
    win = make(tmp_path, ['a.nsp', 'bad.nsp', 'c.nsp', 'd.nsp'])
    fm, s = win.file_manager, win.server_manager.session
    fm.update_file_status('a.nsp', 'done')
    s.on_package_status_received('bad.nsp', p.STATUS_FAILED, 505 | (84 << 9))
    fm.update_file_status('c.nsp', 'done')
    assert not fm.is_item_checked(fm.item_map['bad.nsp'])  # unticked on failure

    select(win, 'bad.nsp')
    fm.move_selected_next()
    assert order(win) == ['a.nsp', 'c.nsp', 'bad.nsp', 'd.nsp']

    select(win, 'bad.nsp')
    s.retry(['bad.nsp'])
    assert fm.is_item_checked(fm.item_map['bad.nsp'])
    assert fm.get_file_status_code('bad.nsp') == 0
    assert order(win) == ['a.nsp', 'c.nsp', 'bad.nsp', 'd.nsp']


def test_nothing_moves_into_the_finished_part(tmp_path):
    win = make(tmp_path, ['a.nsp', 'b.nsp', 'c.nsp'])
    fm = win.file_manager
    fm.update_file_status('a.nsp', 'done')
    fm.update_file_status('b.nsp', 'done')
    select(win, 'c.nsp')
    fm.move_selected_items(-1)  # Alt+Up into the done rows: refused
    assert order(win) == ['a.nsp', 'b.nsp', 'c.nsp']


def test_target_that_does_not_fit_is_refused(tmp_path):
    win = make(tmp_path, ['big.nsp', 'small.nsp'])
    fm, s = win.file_manager, win.server_manager.session
    s.nand_free, s.nand_total = 7 * 2**30, 8 * 2**30
    s.queue_plan = {'big.nsp': {'analysis_ok': True, 'install_size': 12 * 2**30, 'no_space': False}}
    big, small = fm.item_map['big.nsp'], fm.item_map['small.nsp']

    win.file_tree.itemWidget(big, 3).setCurrentIndex(2)  # NAND
    assert fm.queue.files[Path(big.data(5, FILE_PATH_ROLE))].target == 0
    assert win.file_tree.itemWidget(big, 3).currentIndex() == 0

    win.file_tree.itemWidget(small, 3).setCurrentIndex(2)  # 1 KB fits
    assert fm.file_targets['small.nsp'] == 2


def test_installing_row_is_pinned_when_out_of_view(tmp_path):
    win = make(tmp_path, ['a.nsp', 'b.nsp'])
    fm, s = win.file_manager, win.server_manager.session
    tree = win.file_tree
    tree.refresh_active_banner()
    assert tree.active_banner.isHidden()  # nothing installing

    s.current_processing_file = 'b.nsp'
    fm.update_file_status('b.nsp', 'process')
    tree.refresh_active_banner()  # window not shown: the row is not in view
    assert not tree.active_banner.isHidden()
    assert 'b.nsp' in tree.active_banner.text()

    fm.update_file_status('b.nsp', 'done')
    tree.refresh_active_banner()
    assert tree.active_banner.isHidden()
