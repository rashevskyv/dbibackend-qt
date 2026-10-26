import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import server_operations
from src.main_window import MainWindow


class Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self):
        if self.callback:
            self.callback()


class FakeUSBHandler:
    def __init__(self, *_args, **_kwargs):
        for name in (
            'connection_changed', 'log_message', 'progress_updated', 'file_progress',
            'transfer_complete', 'file_skipped', 'transfer_reset', 'all_transfers_complete',
            'installation_begun', 'package_status_received', 'storage_info_received',
            'queue_sync_confirmed', 'queue_plan_received', 'driver_problem', 'finished',
        ):
            setattr(self, name, Signal())
        self.is_running = False
        self.has_communicated = False

    def start(self):
        pass


def test_completed_worker_stays_owned_until_finished_and_does_not_restart(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    manager = window.server_manager
    monkeypatch.setattr(server_operations, 'USBHandler', FakeUSBHandler)

    manager._auto_start_armed = True
    manager.start_usb_server()
    handler = manager.usb_handler

    assert handler is not None
    assert not manager._auto_start_armed
    assert server_operations.auto_start_decision(True, 'usb', False, True, manager._auto_start_armed) == (False, False)

    manager.on_all_transfers_complete()
    assert manager.usb_handler is handler, "The completion signal must not drop the live QThread owner"
    assert not window.mode_switch.isEnabled(), "Mode changes wait for the USB thread to release its device"

    handler.finished.emit()
    assert manager.usb_handler is None
    assert window.mode_switch.isEnabled()
    assert app is not None
