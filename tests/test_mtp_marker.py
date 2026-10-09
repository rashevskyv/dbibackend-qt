"""MTP marker that asks Kefir Hub to switch from MTP to PC Install (USB) (src/mtp_marker.py)."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtp_marker import marker_decision, powershell_args, MARKER  # noqa: E402


def test_writes_once_while_server_waits_in_mtp():
    # console not in MTP: armed, nothing to write
    assert marker_decision(True, False, True) == (False, True)
    # server waiting, console appears in MTP: write once, disarm
    assert marker_decision(True, True, True) == (True, False)
    # next tick, still in MTP (user has not answered yet, or said No): no nag
    assert marker_decision(True, True, False) == (False, False)
    # MTP gone (user said yes, or unplugged): re-arm
    assert marker_decision(True, False, False) == (False, True)


def test_no_write_without_a_waiting_server():
    # server not started, or already connected over the install link
    assert marker_decision(False, True, True) == (False, True)
    # server started afterwards while the console still sits in MTP: fires then
    assert marker_decision(True, True, True) == (True, False)


def test_script_targets_the_marker_file():
    args = powershell_args()
    script = base64.b64decode(args[-1]).decode('utf-16-le')
    assert args[0] == 'powershell.exe' and '-EncodedCommand' in args
    assert MARKER == 'kefir-hub.pc-install'  # the name Kefir Hub watches for (App::PC_INSTALL_MARKER)
    assert script.count(f"'{MARKER}'") == 3  # delete old, local temp name, wait for it to appear
    assert "'Nintendo Switch'" in script and "'microSD card'" in script
