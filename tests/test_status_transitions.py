"""
Runnable regression check for file status transitions and terminal UI progress in ServerManager:
- skipped -> installed
- done -> failed with ProgressTracker.completed_files_set reconciliation
- retry after failure/skip can complete again
- repeated notifications (no double counting)
- moving from one active file to another (no implicit skip)
- Current bar truthful 100% on active file completion
- Non-current file completion does not overwrite active bar
- installation begun exercises actual branch with USB handler attached
- 1 completed + queued at session end: neither bar/text falsely says 100%
- 1 completed + failed at session end: neither bar/text falsely says 100%
- genuinely completed session after throttled 95% update: value and format agree at 100%
- completed-session persistence across server-stop callbacks
- new session after completed session: both values and displayed formats start at 0
- empty or failed session does not display 100%
- manual stop and new-session reset restore default state
- network mode routes skip/unskip/completed through locked handler
"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication
from src.main_window import MainWindow
from src.progress_tracker import ProgressTracker
from src.network_transfer_handler import NetworkTransferHandler
from src import dbi_protocol


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.hibernate_checkbox.setChecked(True)
    sm = win.server_manager
    fm = win.file_manager

    # Setup temporary files
    files = [tempfile.NamedTemporaryFile(delete=False, suffix='.nsp') for _ in range(3)]
    for f in files:
        f.write(b'test' * 100)
        f.close()

    paths = [Path(f.name) for f in files]
    names = [p.name for p in paths]
    f1, f2, f3 = names

    try:
        win.handle_external_files("\n".join(str(p) for p in paths))
        assert len(fm.file_list) == 3, f"Expected 3 files, got {len(fm.file_list)}"

        # Attach fake USB handler with tracker to exercise real branch
        usb_tracker = ProgressTracker(fm.file_list)
        fake_usb = type('FakeUSB', (), {
            'progress_tracker': usb_tracker,
            'is_running': True,
            '_lock': threading.Lock(),
            '_selected_files': set(fm.file_list.keys()),
            'update_file_registry': lambda *a, **k: None,
            'stop': lambda *a, **k: None,
        })()
        sm.usb_handler = fake_usb

        # 1. Skipped -> Installed transition
        sm.on_file_skipped(f1, 400)
        assert f1 in sm.skipped_files_set
        assert sm.transfer_stats['skipped_files'] == 1
        assert fm.get_file_status_code(f1) == 4
        assert f1 in win.progress_delegate.skipped_files
        assert f1 in usb_tracker.skipped_files

        sm.on_package_status_received(f1, dbi_protocol.STATUS_INSTALLED, 0)
        assert f1 not in sm.skipped_files_set, "f1 should be removed from skipped_files_set"
        assert f1 in sm.completed_files_set, "f1 should be in completed_files_set"
        assert sm.transfer_stats['skipped_files'] == 0, "skipped_files counter should decrement"
        assert sm.transfer_stats['completed_files'] == 1, "completed_files counter should increment"
        assert fm.get_file_status_code(f1) == 2, "Status code should be Done (2)"
        assert f1 not in win.progress_delegate.skipped_files, "f1 should not have skipped delegate style"
        assert f1 not in usb_tracker.skipped_files, "f1 should be unskipped in tracker"
        print("PASS: skipped -> installed")

        # 2. Done -> Failed transition & ProgressTracker reconciliation
        usb_tracker.completed_files_set.add(f1)
        sm.on_package_status_received(f1, dbi_protocol.STATUS_FAILED, 0x1234)
        assert f1 not in sm.completed_files_set, "f1 should be removed from completed_files_set"
        assert f1 not in sm.skipped_files_set, "f1 should not be in skipped_files_set"
        assert f1 not in usb_tracker.completed_files_set, "f1 must be removed from tracker completed_files_set"
        assert sm.transfer_stats['completed_files'] == 0, "completed_files counter should decrement"
        assert sm.transfer_stats['skipped_files'] == 0, "skipped_files counter should remain 0"
        assert fm.get_file_status_code(f1) == 3, "Status code should be Failed (3)"
        print("PASS: done -> failed with tracker reconciliation")

        # 3. Retry after failure completes successfully
        usb_tracker.completed_files_set.add(f1)
        sm.on_transfer_complete(f1)
        assert f1 in sm.completed_files_set
        assert sm.transfer_stats['completed_files'] == 1
        assert fm.get_file_status_code(f1) == 2
        print("PASS: retry after failure completes successfully")

        # 4. Repeated notifications (no double counting)
        sm.on_transfer_complete(f2)
        sm.on_transfer_complete(f2)
        assert sm.transfer_stats['completed_files'] == 2, "Repeated complete should not double count"

        sm.on_file_skipped(f3, 400)
        sm.on_file_skipped(f3, 400)
        assert sm.transfer_stats['skipped_files'] == 1, "Repeated skip should not double count"
        print("PASS: repeated notifications idempotency")

        # 5. Moving from one active file to another (no implicit skip)
        sm.current_processing_file = None
        sm.completed_files_set.clear()
        sm.skipped_files_set.clear()
        fm.update_file_status(f1, '')
        fm.update_file_status(f2, '')
        sm.on_progress_updated(f1, 100, 1.0, 1000, 3, 100, 400, 0)
        assert sm.current_processing_file == f1
        assert fm.get_file_status_code(f1) == 1, "f1 should be Process"

        sm.on_progress_updated(f2, 100, 1.0, 1000, 3, 100, 400, 0)
        assert sm.current_processing_file == f2
        assert f1 not in sm.skipped_files_set, "f1 must NOT be implicitly marked skipped"
        print("PASS: moving active file without implicit skip")

        # 6. Current bar reaches 100% with truthful format on active file completion
        sm.current_processing_file = f1
        sm.on_progress_updated(f1, 200, 1.0, 1000, 3, 200, 400, 0)
        assert win.current_progress.value() == 50
        sm.on_transfer_complete(f1)
        assert win.current_progress.value() == 100, "Current progress must reach 100%"
        assert win.current_progress.format() == "100% (400.0 B / 400.0 B)", f"Unexpected format: {win.current_progress.format()}"
        assert win.current_file_label.text() == f1
        print("PASS: Current reaches 100% with truthful format on active file completion")

        # 7. Non-current file completion does not overwrite active file bar
        sm.current_processing_file = f2
        sm.on_progress_updated(f2, 100, 1.0, 1000, 3, 100, 400, 0)
        assert win.current_progress.value() == 25
        assert win.current_file_label.text() == f2
        sm.on_transfer_complete(f1)
        assert sm.current_processing_file == f2, "Active file must not change on other file complete"
        assert win.current_progress.value() == 25, "Active file bar must not be overwritten by other completion"
        assert win.current_file_label.text() == f2
        print("PASS: non-current completion does not overwrite active bar")

        # 8. Installation begun exercises actual branch with USB handler attached
        sm.skipped_files_set.clear()
        sm.transfer_stats['skipped_files'] = 0
        fm.update_file_status(f3, '')
        sm.on_installation_begun([f1])
        assert f3 not in sm.skipped_files_set, "Unrequested f3 must not be marked skipped"
        assert fm.get_file_status_code(f3) == 0, "Unrequested f3 must remain Queued"
        assert sm.transfer_stats['skipped_files'] == 0, "Skipped counter must be 0"
        print("PASS: installation begun exercises actual branch without skipping unrequested")

        # 9a. Session end with 1 completed + queued: neither bar/text falsely says 100%
        sm.completed_files_set.clear()
        sm.transfer_stats['completed_files'] = 0
        sm.transfer_stats['total_files'] = 3
        fm.update_file_status(f1, '')
        fm.update_file_status(f2, '')
        fm.update_file_status(f3, '')
        sm.on_transfer_complete(f1)
        sm.on_all_transfers_complete()
        assert f3 not in sm.completed_files_set
        assert sm.transfer_stats['completed_files'] == 1
        assert win.current_progress.value() < 100, "Current progress must not be 100 on incomplete session"
        assert "100%" not in win.current_progress.format()
        assert win.overall_progress.value() < 100, "Overall progress must not be 100 on incomplete session"
        assert "100%" not in win.overall_progress.format()
        assert win.eta_label.text() != 'ETA: Done'
        assert win.current_file_label.text() != 'Done'
        print("PASS: 1 completed + queued at session end does not falsely say 100%")

        # 9b. Session end with 1 completed + 1 failed: neither bar/text falsely says 100%
        sm.on_package_status_received(f2, dbi_protocol.STATUS_FAILED, 0x123)
        sm.on_all_transfers_complete()
        assert win.current_progress.value() < 100
        assert "100%" not in win.current_progress.format()
        assert win.overall_progress.value() < 100
        assert "100%" not in win.overall_progress.format()
        assert win.eta_label.text() == 'ETA: Failed'
        assert win.current_progress.format() == 'Failed'
        print("PASS: 1 completed + failed at session end does not falsely say 100%")

        # 10. Genuinely completed session after throttled 95% update
        fm.update_file_status(f2, '')
        sm.on_transfer_complete(f2)
        sm.current_processing_file = f3
        sm.on_progress_updated(f3, 380, 1.0, 1200, 3, 380, 400, 0)
        assert win.current_progress.value() == 95
        assert "95%" in win.current_progress.format()
        sm.on_transfer_complete(f3)
        sm.on_all_transfers_complete()
        assert win.current_progress.value() == 100, "Current value must reach 100 on complete session"
        assert "100%" in win.current_progress.format(), "Current format must reach 100% on complete session"
        assert win.overall_progress.value() == 100, "Overall value must reach 100 on complete session"
        assert "100%" in win.overall_progress.format(), "Overall format must reach 100% on complete session"
        assert win.current_file_label.text() == 'Done'
        assert win.eta_label.text() == 'ETA: Done'

        # Trigger on_usb_server_stopped - must persist completed results!
        sm.on_usb_server_stopped()
        assert win.current_progress.value() == 100, "Completed session progress must persist after server stop"
        assert "100%" in win.current_progress.format()
        assert win.overall_progress.value() == 100, "Completed session overall must persist after server stop"
        assert "100%" in win.overall_progress.format()
        assert win.current_file_label.text() == 'Done', "Completed label must persist"
        assert fm.get_file_status_code(f1) == 2, "File status Done must persist"
        print("PASS: genuinely completed session after throttled 95% update agrees at 100%")

        # 11. New session after completed session: both values and displayed formats start at 0
        sm._reset_ui_for_start()
        assert win.current_progress.value() == 0, "New session reset must set Current value to 0"
        assert win.current_progress.format() == "0%", "New session reset must set Current format to 0%"
        assert win.overall_progress.value() == 0, "New session reset must set Overall value to 0"
        assert win.overall_progress.format() == "0%", "New session reset must set Overall format to 0%"
        assert win.speed_label.text() == 'Speed: 0 MB/s'
        assert win.eta_label.text() == 'ETA: --:--:--'
        assert win.current_file_label.text() == 'Waiting for Switch...'
        print("PASS: new session after completed session starts at 0 for values and formats")

        # 12. Empty session does not display 100%
        sm.on_all_transfers_complete()
        assert win.current_progress.value() == 0, "Empty session must not show Current 100%"
        assert win.overall_progress.value() == 0, "Empty session must not show Overall 100%"
        assert win.current_file_label.text() != 'Done', "Empty session label must not be Done"
        print("PASS: empty or failed session does not display 100%")

        # 13. Manual stop and reset restore initial state
        sm.usb_handler = fake_usb
        win.current_progress.setValue(50)
        win.overall_progress.setValue(50)
        sm.stop_usb_server()
        assert sm.manual_stop is True
        sm.on_usb_server_stopped()
        assert win.current_progress.value() == 0, "Manual stop must reset Current"
        assert win.overall_progress.value() == 0, "Manual stop must reset Overall"
        assert win.current_file_label.text() == "No transfer in progress"
        print("PASS: manual stop and reset restore initial state")

        # 14. Network handler locked routing for skip/unskip/completed
        sm.usb_handler = None
        nh = NetworkTransferHandler(fm.file_list, 8080)
        sm.http_handler = nh
        sm.on_file_skipped(f3, 400)
        assert f3 in nh.progress_tracker.skipped_files, "Network skip must update tracker under lock"
        nh.progress_tracker.completed_files_set.add(f3)
        sm.on_package_status_received(f3, dbi_protocol.STATUS_FAILED, 0x1)
        assert f3 not in nh.progress_tracker.completed_files_set, "Network fail must unmark completed"
        assert f3 not in nh.progress_tracker.skipped_files, "Network fail must unmark skipped"
        sm.http_handler = None
        print("PASS: network handler locked routing")

        # 15. Deselecting or removing files during active session preserves truthful counters
        sm._reset_ui_for_start()
        fake_usb._selected_files = {f1, f2, f3}
        fake_usb.file_list = dict(fm.file_list)
        usb_tracker.reset()
        sm.usb_handler = fake_usb
        sm.transfer_stats['total_files'] = 3
        sm.session_active = True

        # Complete f1
        sm.on_transfer_complete(f1)
        assert sm.transfer_stats['completed_files'] == 1
        fake_usb._selected_files.discard(f1)

        # Deselect f2 during session
        def fake_update(files, checked, targets=None):
            fake_usb._selected_files = set(checked)
            fake_usb.file_list = dict(files)
        fake_usb.update_file_registry = fake_update

        sm.sync_usb_files(fake_usb.file_list, {f3}, None)
        assert sm.transfer_stats['total_files'] == 2, "total_files must adjust to completed (1) + planned (1)"
        assert win.overall_label.text() == "2 / 2 files", "overall_label must reflect next index out of 2"

        # Deselect f3 as well
        sm.sync_usb_files(fake_usb.file_list, set(), None)
        assert sm.transfer_stats['total_files'] == 1, "total_files must not fall below completed count"
        assert win.overall_label.text() == "1 / 1 files"
        assert win.overall_progress.value() == 100
        assert win.eta_label.text() == "ETA: Done"

        # Remove completed file f1 from file list while session active
        remaining_files = {f2: fm.file_list[f2], f3: fm.file_list[f3]}
        sm.sync_usb_files(remaining_files, set(), None)
        assert sm.transfer_stats['total_files'] == 1, "completed set retains count even if file removed"
        assert sm.transfer_stats['completed_files'] == 1
        assert win.overall_label.text() == "1 / 1 files"
        print("PASS: deselecting and removing files during active session preserves counters")

        print("ALL 15 STATUS AND PROGRESS REGRESSION CHECKS PASSED")

    finally:
        for p in paths:
            if p.exists():
                p.unlink()


def test_status_transitions():
    main()


if __name__ == '__main__':
    main()
