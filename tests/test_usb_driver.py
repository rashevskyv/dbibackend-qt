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
    assert usb_driver.find_and_reset_switch(['libusb1']) == (None, 'no_access')


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


def test_installer_script_is_valid_powershell():
    if sys.platform != 'win32':
        return
    import subprocess
    script = Path(usb_driver.__file__).with_name('install_winusb.ps1')
    check = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
             f"'{script}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
    out = subprocess.run(['powershell', '-NoProfile', '-Command', check], capture_output=True, text=True)
    assert out.stdout.strip() == '0', out.stdout + out.stderr
