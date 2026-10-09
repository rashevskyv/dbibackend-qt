"""
Switch lookup across USB backends and driver-problem detection.
"""
import sys
from pathlib import Path

import usb.core

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import usb_driver


class FakeDev:
    def __init__(self, exc=None):
        self.exc = exc

    def reset(self):
        if self.exc:
            raise self.exc


def _patch_find(monkeypatch, by_backend):
    def fake_find(idVendor, idProduct, backend):
        assert (idVendor, idProduct) == (0x057E, 0x3000)
        value = by_backend[backend]
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(usb_driver.usb.core, 'find', fake_find)


def test_falls_back_to_next_backend_when_driver_unsupported(monkeypatch):
    good = FakeDev()
    _patch_find(monkeypatch, {'libusb1': FakeDev(NotImplementedError()), 'libusb0': good})
    assert usb_driver.find_and_reset_switch(['libusb1', 'libusb0']) == (good, None)


def test_reports_missing_windows_driver(monkeypatch):
    _patch_find(monkeypatch, {'libusb1': FakeDev(NotImplementedError()), 'libusb0': None})
    assert usb_driver.find_and_reset_switch(['libusb1', 'libusb0']) == (None, 'no_driver')


def test_reports_missing_linux_permission(monkeypatch):
    denied = usb.core.USBError('Access denied', errno=13)
    _patch_find(monkeypatch, {'libusb1': FakeDev(denied)})
    monkeypatch.setattr(usb_driver.sys, 'platform', 'linux')
    assert usb_driver.find_and_reset_switch(['libusb1']) == (None, 'no_access')


def test_console_open_elsewhere_on_windows_is_busy_not_a_driver_problem(monkeypatch):
    _patch_find(monkeypatch, {'libusb1': FakeDev(usb.core.USBError('Access denied', errno=13))})
    monkeypatch.setattr(usb_driver.sys, 'platform', 'win32')
    assert usb_driver.find_and_reset_switch(['libusb1']) == (None, 'busy')


def test_absent_console_and_missing_backend_are_not_driver_problems(monkeypatch):
    _patch_find(monkeypatch, {'libusb1': None, 'none': usb.core.NoBackendError('no backend')})
    assert usb_driver.find_and_reset_switch(['libusb1', 'none']) == (None, None)


def test_other_usb_errors_propagate(monkeypatch):
    _patch_find(monkeypatch, {'libusb1': FakeDev(usb.core.USBError('Pipe error', errno=32))})
    try:
        usb_driver.find_and_reset_switch(['libusb1'])
    except usb.core.USBError as e:
        assert e.errno == 32
    else:
        raise AssertionError('USBError was swallowed')


def test_bundled_libusb1_backend_comes_first():
    backends = usb_driver.usb_backends()
    assert backends[-1] is None
    assert len(backends) == 2 and 'libusb1' in type(backends[0]).__module__


def test_elevated_command_is_inline_and_valid_powershell(tmp_path):
    """The elevated installer gets the script inline (no file path to swap) and it parses."""
    if sys.platform != 'win32':
        return
    import base64
    import subprocess
    log = tmp_path / "it's.log"
    args = usb_driver.elevated_installer_args(log)
    assert '-File' not in args and 'install_winusb.ps1' not in args
    command = base64.b64decode(args.split('-EncodedCommand ')[1]).decode('utf-16-le')
    assert command.endswith(f"-LogPath '{str(log).replace(chr(39), chr(39) * 2)}'")
    (tmp_path / 'cmd.ps1').write_text(command, encoding='utf-8-sig')
    check = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
             f"'{tmp_path / 'cmd.ps1'}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
    out = subprocess.run(['powershell', '-NoProfile', '-Command', check], capture_output=True, text=True)
    assert out.stdout.strip() == '0', out.stdout + out.stderr
    assert len(args) < 32767  # CreateProcess command-line limit


def test_reconnect_releases_stale_device_before_searching(monkeypatch):
    """A session that ended without Stop (Switch app exited) must not keep the
    old handle while looking for the next app, or Windows never finds it."""
    from src import usb_handler as uh_mod
    handler = uh_mod.USBHandler({})
    stale = object()
    handler.dev, handler.is_running = stale, True
    disposed = []
    monkeypatch.setattr(uh_mod.usb.util, 'dispose_resources', disposed.append)

    def fake_find(backends):
        assert handler.dev is None and disposed == [stale]
        handler.is_running = False
        return None, None
    monkeypatch.setattr(uh_mod, 'find_and_reset_switch', fake_find)
    monkeypatch.setattr(uh_mod.time, 'sleep', lambda s: None)

    assert handler.connect_to_switch() is False
