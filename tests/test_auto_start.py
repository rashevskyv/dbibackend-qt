"""Auto-start of the USB server when a Switch appears on the cable (server_operations.auto_start_decision)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server_operations import auto_start_decision  # noqa: E402


def test_starts_once_when_switch_appears():
    # nothing plugged in: armed, no start
    assert auto_start_decision(True, 'usb', False, False, True) == (False, True)
    # the console shows up: start, and disarm
    assert auto_start_decision(True, 'usb', False, True, True) == (True, False)
    # still plugged in on the next tick: no second start
    assert auto_start_decision(True, 'usb', True, True, False) == (False, False)


def test_manual_stop_does_not_restart_until_unplugged():
    # user stopped the server while the console is still there
    assert auto_start_decision(True, 'usb', False, True, False) == (False, False)
    # unplug re-arms
    assert auto_start_decision(True, 'usb', False, False, False) == (False, True)
    # plug again: starts
    assert auto_start_decision(True, 'usb', False, True, True) == (True, False)


def test_disabled_or_other_mode_never_starts():
    assert auto_start_decision(False, 'usb', False, True, True) == (False, True)
    assert auto_start_decision(True, 'http', False, True, True) == (False, True)
    # a running http server also blocks it
    assert auto_start_decision(True, 'usb', True, True, True) == (False, True)
