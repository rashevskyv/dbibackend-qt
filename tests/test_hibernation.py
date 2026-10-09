"""Hibernation safeguard: a countdown only when nobody is at the PC, else just a button.
execute_hibernation is always replaced here: a test must never hibernate the real PC."""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import main_window as mw  # noqa: E402
from src.hibernation import countdown_step, COUNTDOWN_SECONDS, USER_AWAY_SECONDS  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)


def test_countdown_step():
    assert countdown_step(None, None) == (None, False)            # unknown: treat as someone there
    assert countdown_step(5, None) == (None, False)               # someone at the PC
    assert countdown_step(USER_AWAY_SECONDS, None) == (COUNTDOWN_SECONDS, False)
    assert countdown_step(999, 2) == (1, False)
    assert countdown_step(999, 1) == (0, True)
    assert countdown_step(3, 50) == (None, False)                 # they came back: countdown gone


def test_checkbox_is_off_at_start():
    win = mw.MainWindow()
    assert not win.hibernate_checkbox.isChecked()


def test_box_follows_the_person(monkeypatch):
    win = mw.MainWindow()
    slept = []
    monkeypatch.setattr(win, 'execute_hibernation', lambda: slept.append(1))
    idle = [5.0]
    monkeypatch.setattr(mw, 'user_idle_seconds', lambda: idle[0])

    win.offer_hibernation()                       # someone at the PC: button only
    assert 'will not hibernate by itself' in win._hibernate_box.text()
    for _ in range(COUNTDOWN_SECONDS + 5):
        win._hibernation_tick()
    assert not slept

    idle[0] = 999.0                               # they left: countdown starts
    win._hibernation_tick()
    assert 'hibernate in 3:00' in win._hibernate_box.text()
    idle[0] = 1.0                                 # back again: countdown stops
    win._hibernation_tick()
    assert 'will not hibernate by itself' in win._hibernate_box.text()

    idle[0] = 999.0
    for _ in range(COUNTDOWN_SECONDS + 1):
        if win._hibernate_box is None:
            break
        win._hibernation_tick()
    assert slept == [1]


def test_hibernate_now_button(monkeypatch):
    win = mw.MainWindow()
    slept = []
    monkeypatch.setattr(win, 'execute_hibernation', lambda: slept.append(1))
    monkeypatch.setattr(mw, 'user_idle_seconds', lambda: 0.0)
    win.offer_hibernation()
    win._hibernate_now_btn.click()
    assert slept == [1] and win._hibernate_box is None
