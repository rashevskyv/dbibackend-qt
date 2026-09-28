"""
Session Coordinator for DBI Backend
Manages transfer session state, progress tracking, status transitions, and inactivity monitoring.
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Optional

from PyQt6.QtWidgets import QMessageBox

from . import dbi_protocol
from .utility_functions import format_size, format_time


class SessionCoordinator:
    """Coordinates file transfer progress, status transitions, ETA, and session lifecycle."""

    def __init__(self, main_window, server_manager):
        self.main_window = main_window
        self.server_manager = server_manager

        self.transfer_stats = {
            'total_files': 0,
            'completed_files': 0,
            'skipped_files': 0,
            'start_time': None,
        }
        self.completed_files_set: Set[str] = set()
        self.skipped_files_set: Set[str] = set()
        self.current_processing_file: Optional[str] = None
        self.last_speed: float = 0.0

        # Inactivity & hibernation tracking
        self.session_active: bool = False
        self.session_ended: bool = False
        self.manual_stop: bool = False
        self.last_activity_time: Optional[float] = None
        self.has_communicated: bool = False

    def get_inactivity_seconds(self) -> Optional[float]:
        """
        Returns seconds of client inactivity, or None if:
        - Server was manually stopped
        - No server has run / no communication occurred
        """
        if self.manual_stop:
            return None

        handler = self.server_manager.get_active_handler()
        if handler:
            sec = handler.get_inactivity_seconds()
            if sec is not None:
                self.last_activity_time = getattr(handler, 'last_activity_time', None)
                self.has_communicated = True
            return sec

        if self.session_active and self.has_communicated and self.last_activity_time is not None:
            return max(0.0, time.time() - self.last_activity_time)

        return None

    def snooze_inactivity(self):
        """Reset the inactivity timer (e.g. when user cancels countdown or interacts)."""
        self.last_activity_time = time.time()
        handler = self.server_manager.get_active_handler()
        if handler:
            handler.last_activity_time = time.time()

    def reset_inactivity(self):
        """Completely reset inactivity tracking."""
        self.session_active = False
        self.manual_stop = True
        self.has_communicated = False
        self.last_activity_time = None

    def active_network_handler(self):
        return self.server_manager.http_handler or self.server_manager.ftp_handler

    def active_tracker(self):
        uh = self.server_manager.usb_handler
        return uh.progress_tracker if uh else getattr(self.active_network_handler(), 'progress_tracker', None)

    def route_tracker(self, action: str, filename: str):
        uh = self.server_manager.usb_handler
        target = uh.progress_tracker if uh else self.active_network_handler()
        if target:
            getattr(target, action)(filename)

    def _uncheck_file(self, filename: str):
        item = self.main_window.file_manager.item_map.get(filename)
        if item is not None:
            self.main_window.file_manager.set_item_checked(item, False)
        self.main_window.on_item_checked()

    def _unmark_completed(self, filename: str):
        if filename in self.completed_files_set:
            self.completed_files_set.remove(filename)
            self.transfer_stats['completed_files'] = max(0, self.transfer_stats['completed_files'] - 1)
        self.route_tracker('unmark_file_completed', filename)

    def _unmark_skipped(self, filename: str):
        if filename in self.skipped_files_set:
            self.skipped_files_set.remove(filename)
            self.transfer_stats['skipped_files'] = max(0, self.transfer_stats['skipped_files'] - 1)
            self.route_tracker('unmark_file_skipped', filename)
            self.main_window.progress_delegate.skipped_files.discard(filename)

    def reset_ui_for_start(self):
        self.session_ended = False
        self.manual_stop = False
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear()
        self.skipped_files_set.clear()
        self.current_processing_file = None
        self.main_window.progress_delegate.clear_all()
        for item in self.main_window.file_manager.iter_items():
            self.main_window.file_manager.update_file_status(item.text(1), '')
        self.main_window.current_progress.setValue(0)
        self.main_window.current_progress.setFormat("0%")
        self.main_window.overall_progress.setValue(0)
        self.main_window.overall_progress.setFormat("0%")
        self.main_window.speed_label.setText('Speed: 0 MB/s')
        self.main_window.eta_label.setText('ETA: --:--:--')
        self.main_window.current_file_label.setText('Waiting for Switch...')
        if self.main_window.session_time_label:
            self.main_window.session_time_label.setText('')
        if hasattr(self.main_window, 'queue_sync_status') and self.main_window.queue_sync_status:
            self.main_window.queue_sync_status.setText('')

    def prepare_session_start(self, total_files: int):
        self.reset_ui_for_start()
        self.transfer_stats['total_files'] = total_files
        self.transfer_stats['start_time'] = datetime.now()
        self.manual_stop = False
        self.has_communicated = False
        self.last_activity_time = None
        self.main_window.file_manager.dim_unchecked_items()
        self.main_window.overall_label.setText(f'0 / {total_files} files')
        if self.main_window.taskbar_manager:
            self.main_window.taskbar_manager.show_progress()
            self.main_window.taskbar_manager.set_progress_value(0)

    def _update_overall_progress_ui(
        self, transferred: int, total_req_size: int, speed: float, completed: int, total_files: int
    ):
        if total_req_size > 0:
            raw_pct = (transferred / total_req_size) * 100
            overall_pct = int(raw_pct)
            is_finished = (completed >= total_files and total_files > 0)

            if is_finished or raw_pct >= 99.9:
                overall_pct = 100
                self.main_window.eta_label.setText('ETA: Done')
            elif speed > 0 and total_req_size > transferred:
                remaining_bytes = total_req_size - transferred
                sec = remaining_bytes / (speed * 1024 * 1024)
                self.main_window.eta_label.setText(f'ETA: {format_time(int(sec))}')
            else:
                self.main_window.eta_label.setText('ETA: --:--:--')

            self.main_window.overall_progress.setValue(min(100, overall_pct))
            self.main_window.overall_progress.setFormat(
                f'{overall_pct}% ({format_size(transferred)} / {format_size(total_req_size)})'
            )
            if self.main_window.taskbar_manager:
                self.main_window.taskbar_manager.set_progress_value(min(100, overall_pct))
        else:
            self.main_window.overall_progress.setValue(0)
            self.main_window.overall_progress.setFormat('0% (0 B / 0 B)')
            self.main_window.eta_label.setText('ETA: --:--:--')

    def _update_overall_files_label(self, completed: int, total_files: int):
        display_idx = min(completed + 1, total_files) if total_files > 0 else 0
        if completed >= total_files:
            display_idx = total_files
        self.main_window.overall_label.setText(f'{display_idx} / {total_files} files')

    def sync_usb_files(
        self, all_files: Dict[str, Path], checked_names: Set[str], targets: Optional[Dict[str, int]] = None
    ):
        uh = self.server_manager.usb_handler
        if not uh or not uh.is_running:
            return
        uh.update_file_registry(all_files, checked_names, targets)
        with uh._lock:
            planned_count = len(uh._selected_files | self.completed_files_set | self.skipped_files_set)
            pending_revision = (
                uh.queue_revision if hasattr(uh, 'queue_revision') and uh.queue_revision > uh.confirmed_revision else None
            )
        if pending_revision is not None and getattr(self.main_window, 'queue_sync_status', None):
            self.main_window.queue_sync_status.setText(f'🔄 Queue pending (rev {pending_revision})')
        completed = self.transfer_stats['completed_files'] + self.transfer_stats['skipped_files']
        self.transfer_stats['total_files'] = max(planned_count, completed)
        total_files = self.transfer_stats['total_files']

        self._update_overall_files_label(completed, total_files)

        tracker = uh.progress_tracker
        total_req_size = tracker.total_requested_size
        transferred = tracker.transferred_bytes
        self._update_overall_progress_ui(transferred, total_req_size, self.last_speed, completed, total_files)

    def on_progress_updated(
        self, filename: str, transferred: int, speed: float, total_req_size: int,
        num_files: int, cur_bytes: int, cur_size: int, _unused: int
    ):
        self.main_window.current_file_label.setText(filename)

        if self.current_processing_file != filename:
            self.current_processing_file = filename
            if filename not in self.completed_files_set and filename not in self.skipped_files_set:
                self.main_window.file_manager.update_file_status(filename, 'process')

        if cur_size > 0:
            pct = int((cur_bytes / cur_size) * 100)
            self.main_window.current_progress.setFormat(f'{pct}% ({format_size(cur_bytes)} / {format_size(cur_size)})')
            self.main_window.current_progress.setValue(min(100, pct))
            if hasattr(self.main_window.current_progress, 'step_animation'):
                self.main_window.current_progress.step_animation()
        else:
            self.main_window.current_progress.setValue(0)
            self.main_window.current_progress.setFormat('Starting...')

        self.last_speed = speed
        self.main_window.speed_label.setText(f'Speed: {speed:.1f} MB/s')

        if not self.server_manager.usb_handler and num_files > self.transfer_stats['total_files']:
            self.transfer_stats['total_files'] = num_files

        completed = self.transfer_stats['completed_files'] + self.transfer_stats['skipped_files']
        total_files = self.transfer_stats['total_files']

        self._update_overall_progress_ui(transferred, total_req_size, speed, completed, total_files)
        self._update_overall_files_label(completed, total_files)

        if self.transfer_stats['start_time']:
            elapsed = int((datetime.now() - self.transfer_stats['start_time']).total_seconds())
            self.main_window.session_time_label.setText(f"Time: {format_time(elapsed)}")

    def on_file_progress(self, filename: str, progress: int):
        self.main_window.progress_delegate.set_progress(filename, progress)
        item = self.main_window.file_manager.item_map.get(filename)
        if item is not None:
            rect = self.main_window.file_tree.visualItemRect(item)
            if rect.isValid() and not rect.isNull():
                self.main_window.file_tree.viewport().update(rect)
            else:
                self.main_window.file_tree.viewport().update()
        else:
            self.main_window.file_tree.viewport().update()

    def on_transfer_complete(self, filename: str):
        self._unmark_skipped(filename)

        if filename not in self.completed_files_set:
            self.completed_files_set.add(filename)
            self.transfer_stats['completed_files'] += 1

        self.main_window.file_manager.update_file_status(filename, 'done')
        self.main_window.progress_delegate.set_progress(filename, 100)
        self.main_window.progress_delegate.skipped_files.discard(filename)
        self._uncheck_file(filename)

        path = self.main_window.file_manager.file_list.get(filename)
        fsize = path.stat().st_size if path and path.exists() else 0
        tracker = self.active_tracker()
        if fsize == 0 and tracker:
            fsize = tracker.get_file_size(filename)

        if self.current_processing_file == filename or self.current_processing_file is None:
            self.current_processing_file = filename
            self.main_window.current_file_label.setText(filename)
            self.main_window.current_progress.setValue(100)
            fmt = f"100% ({format_size(fsize)} / {format_size(fsize)})" if fsize > 0 else "100%"
            self.main_window.current_progress.setFormat(fmt)

        prog_fmt = self.main_window.overall_progress.format()
        new_target = format_size(tracker.total_requested_size) if tracker else "N/A"
        print(f"[PROGRESS] Completed: {filename} ({format_size(fsize)}) | Overall: {prog_fmt} / Target: {new_target}")

        total = self.transfer_stats['total_files']
        done = self.transfer_stats['completed_files'] + self.transfer_stats['skipped_files']
        if total > 0 and done >= total:
            self.main_window.overall_progress.setValue(100)
            current_text = self.main_window.overall_progress.text()
            if "(" in current_text:
                sizes_part = current_text.split("(", 1)[1]
                self.main_window.overall_progress.setFormat(f"100% ({sizes_part}")
            else:
                self.main_window.overall_progress.setFormat("100%")
            self.main_window.eta_label.setText('ETA: Done')
            if self.main_window.taskbar_manager:
                self.main_window.taskbar_manager.set_progress_value(100)

    def on_file_skipped(self, filename: str, size: int):
        self._unmark_completed(filename)
        self.route_tracker('mark_file_skipped', filename)

        if filename not in self.skipped_files_set:
            self.skipped_files_set.add(filename)
            self.transfer_stats['skipped_files'] += 1

        self.main_window.file_manager.update_file_status(filename, 'skipped')
        self.main_window.progress_delegate.mark_skipped(filename)
        self.main_window.log('warning', f'Skipped: {filename}')
        self._uncheck_file(filename)

        prog_fmt = self.main_window.overall_progress.format()
        print(f"[PROGRESS] Skipped: {filename} ({format_size(size)}) | Total: {prog_fmt}")

    def on_transfer_reset(self):
        self.main_window.log('info', 'Switch reset sequence.')
        self.transfer_stats['completed_files'] = 0
        self.transfer_stats['skipped_files'] = 0
        self.completed_files_set.clear()
        self.skipped_files_set.clear()
        self.current_processing_file = None
        if self.server_manager.usb_handler:
            self.server_manager.usb_handler.progress_tracker.reset()
        self.main_window.file_manager.handle_server_stop()
        self.main_window.file_manager.handle_server_start()
        self.main_window.on_item_checked()

    def on_installation_begun(self, requested_filenames):
        if not self.server_manager.usb_handler:
            return
        requested_set = {n.rstrip('\x00') for n in requested_filenames}
        self.main_window.log('info', 'Switch initiated installation phase...')
        req_total_size = sum(
            self.main_window.file_manager.file_list[n].stat().st_size
            for n in requested_set
            if n in self.main_window.file_manager.file_list
        )
        print(
            f"[DEBUG] Installation Begun. Requested files by DBI: {len(requested_set)} files, "
            f"Total: {format_size(req_total_size)}"
        )

    def on_package_status_received(self, filename: str, status: int, result_code: int):
        if status == dbi_protocol.STATUS_INSTALLED:
            self.main_window.log('success', f'Console confirmed installed: {filename}')
            self.on_transfer_complete(filename)
        elif status in (dbi_protocol.STATUS_USER_SKIPPED, dbi_protocol.STATUS_ALREADY_INSTALLED):
            reason = "already installed" if status == dbi_protocol.STATUS_ALREADY_INSTALLED else "skipped by user"
            self.main_window.log('warning', f'Console skipped: {filename} ({reason})')
            path = self.main_window.file_manager.file_list.get(filename)
            fsize = path.stat().st_size if path else 0
            self.on_file_skipped(filename, fsize)
        elif status == dbi_protocol.STATUS_FAILED:
            self.main_window.log('error', f'Console install failed: {filename} (Result: 0x{result_code:08X})')
            self._unmark_completed(filename)
            self._unmark_skipped(filename)
            self.main_window.progress_delegate.set_progress(filename, 0)
            self.main_window.file_manager.update_file_status(filename, 'failed')

    def on_storage_info_received(self, nand_free: int, nand_total: int, sd_free: int, sd_total: int):
        storage_text = f"🎮 SD: {format_size(sd_free)} · NAND: {format_size(nand_free)}"
        if getattr(self.main_window, 'switch_storage_label', None):
            self.main_window.switch_storage_label.setText(storage_text)
            self.main_window.switch_storage_label.setToolTip(
                f"microSD: {format_size(sd_free)} free of {format_size(sd_total)}\n"
                f"NAND: {format_size(nand_free)} free of {format_size(nand_total)}"
            )
        self.main_window.log(
            'info',
            f"Switch Storage Info: SD {format_size(sd_free)} free of {format_size(sd_total)}, "
            f"NAND {format_size(nand_free)} free of {format_size(nand_total)}"
        )

    def on_all_transfers_complete(self):
        success = self.transfer_stats['completed_files']
        skipped = self.transfer_stats['skipped_files']
        total = self.transfer_stats['total_files']
        time_taken = "00:00:00"
        if self.transfer_stats['start_time']:
            elapsed = int((datetime.now() - self.transfer_stats['start_time']).total_seconds())
            time_taken = format_time(elapsed)

        if self.main_window.taskbar_manager:
            self.main_window.taskbar_manager.hide_progress()

        self.session_ended = True
        fm = self.main_window.file_manager
        has_failed = any(fm.get_file_status_code(n) == 3 for n in fm.file_list)
        is_fully_complete = (success > 0 and total > 0 and (success + skipped) >= total and not has_failed)

        if is_fully_complete:
            self.main_window.log('success', 'All transfers complete!')
            self.main_window.overall_progress.setValue(100)
            cur_overall = self.main_window.overall_progress.text()
            sizes_part = cur_overall.split("(", 1)[1] if "(" in cur_overall else ""
            self.main_window.overall_progress.setFormat(f"100% ({sizes_part}" if sizes_part else "100%")

            active_file = (
                self.current_processing_file
                if self.current_processing_file in self.completed_files_set
                else next(iter(self.completed_files_set), None)
            )
            path = fm.file_list.get(active_file) if active_file else None
            fsize = path.stat().st_size if path and path.exists() else 0
            if fsize == 0 and active_file:
                tracker = self.active_tracker()
                fsize = tracker.get_file_size(active_file) if tracker else 0
            fmt = f"100% ({format_size(fsize)} / {format_size(fsize)})" if fsize > 0 else "100%"
            self.main_window.current_progress.setValue(100)
            self.main_window.current_progress.setFormat(fmt)
            self.main_window.current_file_label.setText('Done')
            self.main_window.eta_label.setText('ETA: Done')
        else:
            pct = int((success / total) * 100) if total > 0 else 0
            self.main_window.overall_progress.setValue(min(99, pct))
            self.main_window.overall_progress.setFormat(f"{pct}% ({success}/{total} files)" if total > 0 else "0%")
            if has_failed:
                failed_file = next((n for n in fm.file_list if fm.get_file_status_code(n) == 3), 'Failed')
                self.main_window.current_file_label.setText(failed_file)
                self.main_window.current_progress.setValue(0)
                self.main_window.current_progress.setFormat("Failed")
                self.main_window.eta_label.setText('ETA: Failed')
                self.main_window.log('warning', f'Session finished with failures ({success}/{total} installed).')
            else:
                unfinished = next(
                    (n for n in fm.file_list if n not in self.completed_files_set and n not in self.skipped_files_set),
                    None
                )
                self.main_window.current_file_label.setText(
                    unfinished if unfinished else ('Done' if skipped > 0 else 'No transfers')
                )
                self.main_window.current_progress.setValue(0)
                self.main_window.current_progress.setFormat(
                    "Incomplete" if unfinished else ("Skipped" if skipped > 0 else "0%")
                )
                self.main_window.eta_label.setText(
                    'ETA: Incomplete' if unfinished else ('ETA: Skipped' if skipped > 0 else 'ETA: --:--:--')
                )
                self.main_window.log(
                    'warning',
                    f'Session incomplete ({success}/{total} installed).' if unfinished else 'Session ended without completed transfers.'
                )

        self.main_window.speed_label.setText('Speed: 0 MB/s')

        if self.main_window.hibernate_checkbox and self.main_window.hibernate_checkbox.isChecked():
            self.main_window.log(
                'info',
                f"Session complete (Installed: {success}, Skipped: {skipped}, Time: {time_taken}). "
                f"Inactivity monitor active."
            )
        else:
            msg = f"Session Complete!\n\nInstalled: {success}\nSkipped: {skipped}\nTime: {time_taken}"
            QMessageBox.information(self.main_window, "Complete", msg)

        for attr in ('usb_handler', 'http_handler', 'ftp_handler'):
            h = getattr(self.server_manager, attr)
            if h:
                self.last_activity_time = getattr(h, 'last_activity_time', None) or time.time()
                self.has_communicated = True
                setattr(self.server_manager, attr, None)

        self.server_manager._set_server_ui_state(False)

    def on_queue_sync_confirmed(self, revision: int):
        if hasattr(self.main_window, 'queue_sync_status') and self.main_window.queue_sync_status:
            uh = self.server_manager.usb_handler
            if uh and revision == uh.queue_revision:
                self.main_window.queue_sync_status.setText(f'✅ Queue in sync (rev {revision})')
            elif uh and revision < uh.queue_revision:
                self.main_window.queue_sync_status.setText(f'🔄 Queue applied (rev {revision}, pending rev {uh.queue_revision})')
            else:
                self.main_window.queue_sync_status.setText(f'🔄 Queue applied (rev {revision})')
