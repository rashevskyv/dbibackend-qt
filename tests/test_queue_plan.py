"""Queue plan from the console (CMD_ID_QUEUE_PLAN): wire parsing and the storage projection it drives."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import dbi_protocol  # noqa: E402
from src.storage_widget import projection_geometry  # noqa: E402


def build(revision, records):
    out = struct.pack(dbi_protocol.QUEUE_PLAN_HEADER, len(records), revision)
    for selected, target, planned, flags, size, name in records:
        raw = name.encode('utf-8')
        out += struct.pack(dbi_protocol.QUEUE_PLAN_RECORD, selected, target, planned, flags, size, len(raw)) + raw
    return out


def test_parse_roundtrip():
    payload = build(7, [
        (1, 0, 1, 1, 5 * 2**30, 'Game A.nsp'),
        (0, 2, 2, 1, 2**30, 'Гра Б.nsz'),
        (1, 1, 1, 3, 123, 'installed.nsp'),
        (1, 0, 2, 0, 0, 'broken.nsp'),
    ])
    revision, items = dbi_protocol.parse_queue_plan(payload)
    assert revision == 7
    assert [i['name'] for i in items] == ['Game A.nsp', 'Гра Б.nsz', 'installed.nsp', 'broken.nsp']
    assert items[0] == {'name': 'Game A.nsp', 'selected': True, 'target': 0, 'planned_sd': True,
                        'install_size': 5 * 2**30, 'analysis_ok': True, 'already_installed': False,
                        'no_space': False, 'no_base': False}
    assert items[1]['selected'] is False and items[1]['planned_sd'] is False and items[1]['target'] == 2
    assert items[2]['already_installed'] is True
    assert items[3]['analysis_ok'] is False


def test_parse_truncated_raises():
    payload = build(1, [(1, 0, 1, 1, 10, 'x.nsp')])
    with pytest.raises(ValueError):
        dbi_protocol.parse_queue_plan(payload[:-1])
    with pytest.raises(ValueError):
        dbi_protocol.parse_queue_plan(b'\x01')
    assert dbi_protocol.parse_queue_plan(build(0, [])) == (0, [])


def test_projection_sums_like_the_hub():
    _, items = dbi_protocol.parse_queue_plan(build(1, [
        (1, 0, 1, 1, 100, 'a'),   # SD, counted
        (1, 0, 1, 1, 50, 'b'),    # SD, counted, hovered
        (1, 2, 2, 1, 30, 'c'),    # NAND, counted
        (0, 0, 1, 1, 999, 'd'),   # unticked
        (1, 0, 2, 7, 999, 'e'),   # installed and will be skipped: takes no space
        (1, 0, 2, 3, 20, 'g'),    # installed but reinstalled: counted (NAND)
        (1, 0, 1, 0, 999, 'f'),   # analysis failed
    ]))
    assert dbi_protocol.plan_projection(items, 'b') == (50, 150, 0, 50)
    assert dbi_protocol.plan_projection(items, None) == (50, 150, 0, 0)


def test_list_carries_skip_mode_in_revision_line():
    data = dbi_protocol.build_list_payload([], set(), {}, dbi_protocol.LIST_EXT_SPHQ, 5, dbi_protocol.SKIP_MODE_SKIP)
    assert data.decode().splitlines()[0] == '::SPHQ_REV::|5|2|0'
    # default leaves it to the console, like older backends ('|0|0')
    data = dbi_protocol.build_list_payload([], set(), {}, dbi_protocol.LIST_EXT_SPHQ, 5)
    assert data.decode().splitlines()[0] == '::SPHQ_REV::|5|0|0'


def test_projection_geometry_clamps_to_free_space():
    # 1000 px bar, 100 GB total, 20 GB free, 80 GB used (800 px): 10 GB planned = 100 px, fits.
    assert projection_geometry(1000, 100, 20, 800, 10, 4) == (100, 40, True)
    # 50 GB planned does not fit: segment clamped to the free 200 px, red.
    assert projection_geometry(1000, 100, 20, 800, 50, 0) == (200, 0, False)
    # nothing planned draws nothing.
    assert projection_geometry(1000, 100, 20, 800, 0, 0) == (0, 0, True)


def test_installed_rows_are_unticked_once(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from src.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    paths = []
    for n in ('old.nsp', 'new.nsp'):
        (tmp_path / n).write_bytes(b'X' * 64)
        paths.append(tmp_path / n)
    fm.ingest_paths(paths)
    plan = lambda: dbi_protocol.parse_queue_plan(build(1, [
        (1, 0, 1, 7, 10, 'old.nsp'),   # installed, will be skipped
        (1, 0, 1, 1, 10, 'new.nsp'),
    ]))[1]
    checked = lambda: {it.text(1) for it in fm.iter_checked_items()}

    win.server_manager.session.on_queue_plan_received(1, plan())
    assert checked() == {'new.nsp'}
    assert fm.item_map['old.nsp'].text(4) == '📦 Installed'

    fm.set_item_checked(fm.item_map['old.nsp'], True)  # the user wants it back
    win.server_manager.session.on_queue_plan_received(1, plan())
    assert checked() == {'old.nsp', 'new.nsp'}
