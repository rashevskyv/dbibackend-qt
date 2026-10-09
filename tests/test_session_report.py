"""End-of-session report: counts, per-game failure details, updates/DLC without a base game."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import dbi_protocol as p  # noqa: E402
from src.session_report import build_report, describe_result, base_title_id  # noqa: E402

USB_BAD_COUNT = 505 | (84 << 9)


def test_describe_result():
    assert describe_result(USB_BAD_COUNT).startswith('2505-0084 UsbBadCount: The PC did not send')
    assert describe_result(2 | (35 << 9)) == '2002-0035 FS: not enough free space.'
    assert describe_result(5 | (7 << 9)) == '2005-0007 NCM'


def test_base_title_id():
    assert base_title_id(0x0100ABF008968800) == 0x0100ABF008968000  # update
    assert base_title_id(0x01001B300B9BF00A) == 0x01001B300B9BE000  # DLC
    assert base_title_id(0x0100ABF008968000) == 0


def test_report():
    results = {
        'Sword [0100ABF008968000][v0].nsz': (p.STATUS_INSTALLED, 0),
        'Sword [0100ABF008968800][v458752].nsz': (p.STATUS_INSTALLED, 0),     # base came in this session
        'Shield [01008DB008C2C800][v458752].nsz': (p.STATUS_INSTALLED, 0),    # base not on console
        'Old [0100000000010000][v0].nsp': (p.STATUS_ALREADY_INSTALLED, 0),
        'Diablo UK [01001B300B9BF001][v0].nsp': (p.STATUS_FAILED, USB_BAD_COUNT),
    }
    plan = {
        'Sword [0100ABF008968800][v458752].nsz': {'no_base': True},
        'Shield [01008DB008C2C800][v458752].nsz': {'no_base': True},
    }
    summary, text, clean = build_report(
        results, ['Late [0100A00000000000][v0].nsp', 'Diablo UK [01001B300B9BF001][v0].nsp'], plan,
        {'Diablo UK [01001B300B9BF001][v0].nsp': 'Cannot read the file: [Errno 2] No such file'},
        datetime(2026, 10, 9, 1, 0, 0), datetime(2026, 10, 9, 3, 30, 5),
    )
    assert summary == 'Installed 3, already installed 1, failed 1, not reached 1, without base 1'
    assert not clean
    assert 'Time: 02:30:05' in text
    assert '- Diablo UK [01001B300B9BF001][v0].nsp\n    Console: 2505-0084 UsbBadCount' in text
    assert '    PC: Cannot read the file: [Errno 2] No such file' in text
    without = text.split('WITHOUT BASE GAME')[1].split('\n\n')[0]
    assert 'Shield' in without and 'Sword' not in without
    assert 'NOT REACHED\n- Late [0100A00000000000][v0].nsp' in text


def test_clean_report_and_no_plan():
    summary, text, clean = build_report({'A [0100A00000000000][v0].nsp': (p.STATUS_INSTALLED, 0)}, [], {}, {},
                                        None, datetime(2026, 10, 9))
    assert clean and summary.startswith('Installed 1,')
    assert 'unknown (the console sent no queue plan)' in text
