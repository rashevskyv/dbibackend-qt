"""
Asking Kefir Hub to leave MTP for PC Install (USB).

MTP (VID 057E / PID 201D) and the USB install link (PID 3000) are different USB
devices, so a console that sits in MTP cannot be reached by the USB server. The
signal is an MTP write instead: a file named ``kefir-hub.pc-install`` created on
the console's storage makes Kefir Hub (0.14.038+) ask the user to switch to PC
Install (USB). Windows only: the file goes through the Shell (WPD), the same
path Explorer uses; the console's own MTP driver does the rest.
"""
import base64
import subprocess
import sys

from PyQt6.QtCore import QThread, pyqtSignal

MTP_PID = 0x201D
MARKER = 'kefir-hub.pc-install'
SUPPORTED = sys.platform == 'win32'


def marker_decision(server_waiting: bool, mtp_present: bool, armed: bool):
    """Whether to write the marker now.

    Returns (write, armed). Fires once per MTP appearance while the USB server is
    up and still waiting for the console; it stays disarmed until the console
    leaves MTP, so a user who answered "No" on the console is not asked again."""
    if not mtp_present:
        return False, True
    if not server_waiting or not armed:
        return False, armed
    return True, False


# Shell COM over WPD: find the console, prefer its microSD storage, drop the marker in its root.
# 16 + 4 + 1024 = yes to all, no progress UI, no error UI.
_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject Shell.Application
$dev = $shell.NameSpace(17).Items() | Where-Object { $_.Name -eq 'Nintendo Switch' } | Select-Object -First 1
if (-not $dev) { Write-Output 'no MTP device named Nintendo Switch'; exit 2 }
$storages = @($dev.GetFolder.Items())
$storage = $storages | Where-Object { $_.Name -eq 'microSD card' } | Select-Object -First 1
if (-not $storage) { $storage = $storages | Select-Object -First 1 }
if (-not $storage) { Write-Output 'the console exposes no storage'; exit 3 }
$folder = $storage.GetFolder
$folder.Items() | Where-Object { $_.Name -eq 'MARKER' } | ForEach-Object { $_.InvokeVerb('delete') }
$local = Join-Path $env:TEMP 'MARKER'
[IO.File]::WriteAllText($local, "pc-install`n")
$folder.CopyHere($local, 16 + 4 + 1024)
for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Milliseconds 100
    if ($folder.Items() | Where-Object { $_.Name -eq 'MARKER' }) { exit 0 }
}
Write-Output 'the marker did not show up on the console'; exit 4
'''.replace('MARKER', MARKER)


def powershell_args() -> list:
    encoded = base64.b64encode(_SCRIPT.encode('utf-16-le')).decode('ascii')
    return ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded]


def write_marker() -> tuple:
    """Blocking; returns (ok, message)."""
    if not SUPPORTED:
        return False, 'writing the MTP marker needs Windows'
    try:
        r = subprocess.run(powershell_args(), capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        return False, 'the MTP write timed out'
    if r.returncode == 0:
        return True, 'asked Kefir Hub to switch to PC Install (USB) — confirm on the console'
    detail = (r.stdout.strip() or r.stderr.strip()).splitlines()
    return False, f'could not reach the console over MTP: {detail[-1] if detail else r.returncode}'


class MarkerWriteThread(QThread):
    """The Shell copy blocks for up to a few seconds; keep it off the UI thread."""
    done = pyqtSignal(bool, str)

    def run(self):
        try:
            ok, msg = write_marker()
        except Exception as e:
            ok, msg = False, f'MTP marker failed: {e}'
        self.done.emit(ok, msg)
