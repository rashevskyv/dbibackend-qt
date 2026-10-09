"""
Opening the Switch over USB on every OS, and fixing OS access when it fails.

Windows needs a driver libusb can talk to (WinUSB, libusbK or libusb0) bound to
USB\\VID_057E&PID_3000; a fresh PC has none. Linux needs a udev rule so a normal
user may open the device. macOS needs nothing.
"""
import base64
import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import usb.core
from PyQt6.QtCore import QThread, pyqtSignal

SWITCH_VID, SWITCH_PID = 0x057E, 0x3000
_USABLE_WINDOWS_SERVICES = {'winusb', 'libusbk', 'libusb0'}
UDEV_RULE_PATH = '/etc/udev/rules.d/99-nintendo-switch-dbi.rules'
UDEV_RULE = 'SUBSYSTEM=="usb", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="3000", MODE="0666"'


def usb_backends() -> list:
    """Bundled libusb-1.0 first (works with WinUSB and libusbK), then pyusb's own
    discovery, which finds e.g. a libusb0.dll that Zadig put in System32."""
    backends = []
    try:
        import libusb_package
        backend = libusb_package.get_libusb1_backend()
        if backend is not None:
            backends.append(backend)
    except Exception:
        pass
    backends.append(None)
    return backends


def switch_present(backends: List, pid: int = SWITCH_PID) -> bool:
    """True when a Switch in USB install mode (VID 057E / PID 3000, or another
    PID such as MTP) is plugged in. Only enumerates; never opens or resets the
    device, so it is safe to poll."""
    for backend in backends:
        try:
            if usb.core.find(idVendor=SWITCH_VID, idProduct=pid, backend=backend) is not None:
                return True
        except (usb.core.NoBackendError, usb.core.USBError):
            continue
    return False


def find_and_reset_switch(backends: List) -> Tuple[Optional[object], Optional[str]]:
    """Find the Switch and open it with the first backend that can.

    Returns (device, None) on success, otherwise (None, problem) where problem is
    'no_driver' (Windows: nothing usable bound), 'no_access' (Linux: no udev rule)
    or None (device not plugged in)."""
    problem = None
    for backend in backends:
        try:
            dev = usb.core.find(idVendor=SWITCH_VID, idProduct=SWITCH_PID, backend=backend)
        except usb.core.NoBackendError:
            continue
        if dev is None:
            continue
        try:
            dev.reset()
            return dev, None
        except NotImplementedError:
            problem = 'no_driver'
        except usb.core.USBError as e:
            if e.errno != 13:
                raise
            problem = 'no_access'
    return None, problem


def windows_driver_missing() -> bool:
    """True when Windows has seen the Switch but bound no driver libusb can use.
    A Switch that was never plugged in has nothing to fix yet."""
    if sys.platform != 'win32':
        return False
    import winreg
    key_path = r'SYSTEM\CurrentControlSet\Enum\USB\VID_057E&PID_3000'
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
    except OSError:
        return False
    services = set()
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as inst:
                    services.add(str(winreg.QueryValueEx(inst, 'Service')[0]).lower())
            except OSError:
                pass
    return not services & _USABLE_WINDOWS_SERVICES


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_ulong), ('fMask', ctypes.c_ulong), ('hwnd', ctypes.c_void_p),
        ('lpVerb', ctypes.c_wchar_p), ('lpFile', ctypes.c_wchar_p), ('lpParameters', ctypes.c_wchar_p),
        ('lpDirectory', ctypes.c_wchar_p), ('nShow', ctypes.c_int), ('hInstApp', ctypes.c_void_p),
        ('lpIDList', ctypes.c_void_p), ('lpClass', ctypes.c_wchar_p), ('hkeyClass', ctypes.c_void_p),
        ('dwHotKey', ctypes.c_ulong), ('hIcon', ctypes.c_void_p), ('hProcess', ctypes.c_void_p),
    ]


def elevated_installer_args(log: Path) -> str:
    """PowerShell arguments with the installer passed inline. Running the .ps1 by
    path would let anything that can write to that folder swap the script
    between here and the UAC prompt and get it run as administrator."""
    script = Path(__file__).with_name('install_winusb.ps1').read_text(encoding='utf-8')
    log_literal = str(log).replace("'", "''")
    command = f"& {{\n{script}\n}} -LogPath '{log_literal}'"
    encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
    return f'-NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}'


def _install_windows() -> Tuple[bool, str]:
    log = Path(tempfile.gettempdir()) / 'dbi-winusb-install.log'
    log.unlink(missing_ok=True)
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = 'runas'  # UAC prompt
    info.lpFile = 'powershell.exe'
    info.lpParameters = elevated_installer_args(log)
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.GetLastError() == 1223:  # ERROR_CANCELLED
            return False, ('Administrator permission was not granted, so the driver was not installed.\n'
                           'Run Help > Install USB Driver again and confirm the Windows prompt, '
                           'or ask the administrator of this PC to do it.')
        return False, f'Could not start the driver installer (error {ctypes.GetLastError()}).'
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(ctypes.c_void_p(info.hProcess), 0xFFFFFFFF)
    code = ctypes.c_ulong()
    kernel32.GetExitCodeProcess(ctypes.c_void_p(info.hProcess), ctypes.byref(code))
    kernel32.CloseHandle(ctypes.c_void_p(info.hProcess))
    # Windows PowerShell's Out-File -Encoding utf8 writes a BOM
    details = log.read_text(encoding='utf-8-sig', errors='replace').strip() if log.exists() else ''
    if code.value == 0:
        return True, 'WinUSB driver installed. Replug the console if it does not connect.'
    return False, f'Driver installation failed (code {code.value}).\n\n{details}'.strip()


def _install_linux() -> Tuple[bool, str]:
    cmd = (f"printf '%s\\n' '{UDEV_RULE}' > {UDEV_RULE_PATH}"
           " && udevadm control --reload-rules && udevadm trigger")
    try:
        r = subprocess.run(['pkexec', 'sh', '-c', cmd], capture_output=True, text=True)
    except FileNotFoundError:
        return False, f'pkexec is not available. Run as root:\n\necho \'{UDEV_RULE}\' > {UDEV_RULE_PATH}'
    if r.returncode == 0:
        return True, 'udev rule installed. Replug the console if it does not connect.'
    if r.returncode in (126, 127):
        return False, 'Authorization was cancelled, so the udev rule was not installed.'
    return False, f'Installing the udev rule failed:\n{r.stderr.strip()}'


def can_install_driver() -> bool:
    return sys.platform == 'win32' or sys.platform.startswith('linux')


class DriverInstallThread(QThread):
    """Runs the elevated install off the UI thread; UAC/pkexec may wait on the user."""
    done = pyqtSignal(bool, str)

    def run(self):
        try:
            ok, msg = _install_windows() if sys.platform == 'win32' else _install_linux()
        except Exception as e:
            ok, msg = False, f'Driver installation failed: {e}'
        self.done.emit(ok, msg)
