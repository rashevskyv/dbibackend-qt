"""
Hibernation safeguard: the PC hibernates by itself only when nobody is at it.
Someone using the mouse or keyboard gets a button instead of a countdown.
"""
import ctypes
import sys
from typing import Optional, Tuple

USER_AWAY_SECONDS = 120     # no mouse/keyboard input for this long = nobody at the PC
COUNTDOWN_SECONDS = 180     # warning shown this long before hibernating by itself


def user_idle_seconds() -> Optional[float]:
    """Seconds since the last mouse or keyboard input on this PC; None where unknown."""
    if sys.platform != 'win32':
        return None

    class LastInputInfo(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    get_tick = ctypes.windll.kernel32.GetTickCount
    get_tick.restype = ctypes.c_uint
    return ((get_tick() - info.dwTime) & 0xFFFFFFFF) / 1000.0  # both wrap after 49 days


def countdown_step(user_idle: Optional[float], seconds_left: Optional[int]) -> Tuple[Optional[int], bool]:
    """One second of the warning. Returns (seconds left or None when someone is at the
    PC and only the button is offered, hibernate now). The countdown starts over each
    time the PC is left alone again; an unknown idle time counts as someone there."""
    if user_idle is None or user_idle < USER_AWAY_SECONDS:
        return None, False
    left = COUNTDOWN_SECONDS if seconds_left is None else seconds_left - 1
    return left, left <= 0
