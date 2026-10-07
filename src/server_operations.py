"""
Server Operations for DBI Backend
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QSpinBox,
    QDialogButtonBox,
    QComboBox,
)

from . import __version__
from .usb_driver import usb_backends, switch_present
from .usb_handler import USBHandler, ConnectionStatus
from .http_handler import HTTPHandler
from .ftp_handler import FTPHandler
from .network_transfer_handler import NetworkTransferHandler
from .session_coordinator import SessionCoordinator


def auto_start_decision(enabled: bool, mode: str, server_active: bool, present: bool, armed: bool):
    """Whether to start the USB server for a Switch that just appeared on the cable.

    Returns (start, armed). The trigger is armed while no Switch is plugged in and
    fires once when one appears; it stays disarmed until the console goes away, so a
    server the user stopped by hand is not restarted while the same console sits there."""
    if not present:
        return False, True
    if not enabled or mode != 'usb' or server_active or not armed:
        return False, armed
    return True, False


class ServerManager:
    """Manages starting, stopping, and handling events for USB, HTTP, and FTP servers."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.session = SessionCoordinator(main_window, self)
        self.usb_handler = None
        self.http_handler = None
        self.ftp_handler = None
        self.reconnect_timer = QTimer()
        # Kefir Hub opens its USB install link for a few seconds when a PC is
        # plugged in and waits for a backend to answer; check_connection() starts
        # the server as soon as the console shows up, no button press needed.
        self._probe_backends = usb_backends()
        self._auto_start_armed = True

    # Session State Properties (forwarded to session coordinator)
    @property
    def transfer_stats(self) -> Dict:
        return self.session.transfer_stats

    @transfer_stats.setter
    def transfer_stats(self, value: Dict):
        self.session.transfer_stats = value

    @property
    def completed_files_set(self) -> Set[str]:
        return self.session.completed_files_set

    @completed_files_set.setter
    def completed_files_set(self, value: Set[str]):
        self.session.completed_files_set = value

    @property
    def skipped_files_set(self) -> Set[str]:
        return self.session.skipped_files_set

    @skipped_files_set.setter
    def skipped_files_set(self, value: Set[str]):
        self.session.skipped_files_set = value

    @property
    def current_processing_file(self) -> Optional[str]:
        return self.session.current_processing_file

    @current_processing_file.setter
    def current_processing_file(self, value: Optional[str]):
        self.session.current_processing_file = value

    @property
    def last_speed(self) -> float:
        return self.session.last_speed

    @last_speed.setter
    def last_speed(self, value: float):
        self.session.last_speed = value

    @property
    def session_active(self) -> bool:
        return self.session.session_active

    @session_active.setter
    def session_active(self, value: bool):
        self.session.session_active = value

    @property
    def session_ended(self) -> bool:
        return self.session.session_ended

    @session_ended.setter
    def session_ended(self, value: bool):
        self.session.session_ended = value

    @property
    def manual_stop(self) -> bool:
        return self.session.manual_stop

    @manual_stop.setter
    def manual_stop(self, value: bool):
        self.session.manual_stop = value

    @property
    def last_activity_time(self) -> Optional[float]:
        return self.session.last_activity_time

    @last_activity_time.setter
    def last_activity_time(self, value: Optional[float]):
        self.session.last_activity_time = value

    @property
    def has_communicated(self) -> bool:
        return self.session.has_communicated

    @has_communicated.setter
    def has_communicated(self, value: bool):
        self.session.has_communicated = value

    # Server handler queries
    def get_active_handler(self):
        for h in (self.usb_handler, self.http_handler, self.ftp_handler):
            if h and getattr(h, 'is_running', False):
                return h
        return None

    # Inactivity management
    def get_inactivity_seconds(self) -> Optional[float]:
        return self.session.get_inactivity_seconds()

    def snooze_inactivity(self):
        self.session.snooze_inactivity()

    def reset_inactivity(self):
        self.session.reset_inactivity()

    # Server UI & Mode Toggle
    def toggle_server(self):
        mode = self.main_window.mode_switch.mode()
        active = self.get_active_handler()
        if not active:
            getattr(self, f'start_{mode}_server')()
        elif QMessageBox.question(
            self.main_window,
            'Stop Server',
            'Stop the current server?'
        ) == QMessageBox.StandardButton.Yes:
            if active is self.usb_handler:
                self.stop_usb_server()
            elif active is self.http_handler:
                self.stop_http_server()
            else:
                self.stop_ftp_server()

    def get_checked_files(self) -> Dict[str, Path]:
        fm = self.main_window.file_manager
        return {
            item.text(1): fm.file_list[item.text(1)]
            for item in fm.iter_checked_items()
            if item.text(1) in fm.file_list
        }

    def _reset_ui_for_start(self):
        self.session.reset_ui_for_start()

    # USB Server Lifecycle
    def start_usb_server(self):
        checked_files = self.get_checked_files()
        self.session.prepare_session_start(len(checked_files))
        if not checked_files:
            self.main_window.log('info', 'Starting USB server with empty queue (waiting for Switch and files)...')
        else:
            self.main_window.log('info', f'Starting USB server with {len(checked_files)} files')
        self.main_window.file_manager.handle_server_start()

        uh = self.usb_handler = USBHandler(
            self.main_window.file_manager.file_list,
            initial_checked=set(checked_files.keys()),
            initial_targets=self.main_window.file_manager.file_targets,
        )
        uh.connection_changed.connect(self.on_connection_changed)
        uh.log_message.connect(self.main_window.log)
        uh.progress_updated.connect(self.on_progress_updated)
        uh.file_progress.connect(self.on_file_progress)
        uh.transfer_complete.connect(self.on_transfer_complete)
        uh.file_skipped.connect(self.on_file_skipped)
        uh.transfer_reset.connect(self.on_transfer_reset)
        uh.all_transfers_complete.connect(self.on_all_transfers_complete)
        uh.installation_begun.connect(self.on_installation_begun)
        uh.package_status_received.connect(self.on_package_status_received)
        uh.storage_info_received.connect(self.on_storage_info_received)
        uh.queue_sync_confirmed.connect(self.on_queue_sync_confirmed)
        uh.driver_problem.connect(self.main_window.offer_usb_driver_install)
        uh.finished.connect(self.on_usb_server_stopped)
        uh.start()
        self.session.session_active = True

        self.main_window.setWindowTitle(f"DBI Backend Qt v{__version__} | USB Mode Active")
        self._set_server_ui_state(True)

    def stop_usb_server(self):
        self._stop_server('usb_handler')

    def on_usb_server_stopped(self):
        self._handle_server_stopped('usb_handler', 'USB Server')
        self.main_window.connection_status.setText('🔴 Not connected')

    def sync_usb_files(
        self, all_files: Dict[str, Path], checked_names: Set[str], targets: Optional[Dict[str, int]] = None
    ):
        self.session.sync_usb_files(all_files, checked_names, targets)

    # Network Server Lifecycle (HTTP / FTP)
    def _prompt_network_settings(self, title: str, ip_key: str, port_key: str, default_port: int):
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        ip_combo = QComboBox()
        local_ips = NetworkTransferHandler.get_local_ips()
        ip_combo.addItems(local_ips)
        saved_ip = self.main_window.config.get(ip_key, '')
        if saved_ip in local_ips:
            ip_combo.setCurrentText(saved_ip)
        form.addRow("Switch URL IP:", ip_combo)

        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        port_spin.setValue(self.main_window.config.get(port_key, default_port))
        form.addRow("Port:", port_spin)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        selected_ip, selected_port = ip_combo.currentText(), port_spin.value()
        self.main_window.config.set(ip_key, selected_ip)
        self.main_window.config.set(port_key, selected_port)
        self.main_window.config.save()
        return selected_ip, selected_port

    def _connect_network_handler(self, handler, started_slot, stopped_slot):
        handler.log_message.connect(self.main_window.log)
        handler.server_started.connect(started_slot)
        handler.server_stopped.connect(stopped_slot)
        handler.progress_updated.connect(self.on_progress_updated)
        handler.file_progress.connect(self.on_file_progress)
        handler.transfer_complete.connect(self.on_transfer_complete)
        handler.file_skipped.connect(self.on_file_skipped)
        handler.all_transfers_complete.connect(self.on_all_transfers_complete)
        handler.finished.connect(stopped_slot)

    def _start_network_server(
        self, protocol: str, handler_cls, handler_attr: str, ip_key: str, port_key: str,
        default_port: int, started_slot, stopped_slot
    ):
        checked_files = self.get_checked_files()
        if not checked_files:
            self.main_window.log('warning', 'No files selected!')
            return

        settings = self._prompt_network_settings(f"Start {protocol} Server", ip_key, port_key, default_port)
        if settings is None:
            return

        selected_ip, selected_port = settings
        self.session.prepare_session_start(len(checked_files))

        handler = handler_cls(checked_files, port=selected_port, display_ip=selected_ip)
        setattr(self, handler_attr, handler)
        self._connect_network_handler(handler, started_slot, stopped_slot)
        handler.start()
        self.session.session_active = True

        self.main_window.setWindowTitle(
            f"DBI Backend Qt v{__version__} | {protocol} Server: {protocol.lower()}://{selected_ip}:{selected_port}/"
        )
        self._set_server_ui_state(True)

    def start_http_server(self):
        self._start_network_server(
            "HTTP",
            HTTPHandler,
            "http_handler",
            "http_ip",
            "http_port",
            8080,
            self.on_http_server_started,
            self.on_http_server_stopped,
        )

    def stop_http_server(self):
        self._stop_server('http_handler')

    def start_ftp_server(self):
        self._start_network_server(
            "FTP",
            FTPHandler,
            "ftp_handler",
            "ftp_ip",
            "ftp_port",
            2121,
            self.on_ftp_server_started,
            self.on_ftp_server_stopped,
        )

    def stop_ftp_server(self):
        self._stop_server('ftp_handler')

    def on_http_server_started(self, ip, port):
        self.main_window.log('info', f'HTTP Server started: http://{ip}:{port}/')

    def on_ftp_server_started(self, ip, port):
        self.main_window.log('info', f'FTP Server started: ftp://{ip}:{port}/')

    def on_http_server_stopped(self):
        self._handle_server_stopped('http_handler', 'HTTP Server')

    def on_ftp_server_stopped(self):
        self._handle_server_stopped('ftp_handler', 'FTP Server')

    # Common Server Stop Handling
    def _stop_server(self, handler_attr: str):
        self.session.manual_stop = True
        self.session.session_active = False
        self.session.session_ended = False
        handler = getattr(self, handler_attr, None)
        if handler:
            handler.stop()

    def _handle_server_stopped(self, handler_attr: str, name: str):
        handler = getattr(self, handler_attr, None)
        if handler is None:
            return
        if getattr(handler, 'has_communicated', False):
            self.session.has_communicated = True
            self.session.last_activity_time = getattr(handler, 'last_activity_time', None) or time.time()
        setattr(self, handler_attr, None)
        self._set_server_ui_state(False)
        if self.session.manual_stop or not self.session.session_ended:
            self.main_window.file_manager.handle_server_stop()
        self.main_window.log('info', f'{name} stopped')

    # UI Server State & Controls
    def _set_server_ui_state(self, running: bool):
        btn = self.main_window.start_server_btn
        mode = self.main_window.mode_switch.mode()
        if running:
            btn.setText('⏹')
            btn.setStyleSheet(
                'QPushButton { background-color: #f44336; color: white; font-size: 32px; } '
                'QPushButton:hover { background-color: #da190b; }'
            )
            self.main_window.server_label.setText('Stop Server')
            self.main_window.mode_switch.setEnabled(False)
            self.main_window.add_files_btn.setEnabled(mode == 'usb')
            self.main_window.clear_list_btn.setEnabled(False)
        else:
            btn.setText('▶')
            if mode == 'http':
                btn.setStyleSheet(self.main_window._get_btn_style("#2196F3", "#1976D2"))
                self.main_window.server_label.setText('Start HTTP')
            elif mode == 'ftp':
                btn.setStyleSheet(self.main_window._get_btn_style("#FFC107", "#FFB300"))
                self.main_window.server_label.setText('Start FTP')
            else:
                btn.setStyleSheet(self.main_window._get_btn_style("#4CAF50", "#45a049"))
                self.main_window.server_label.setText('Start USB')

            self.main_window.mode_switch.setEnabled(True)
            self.main_window.add_files_btn.setEnabled(True)
            self.main_window.clear_list_btn.setEnabled(True)

    def check_connection(self):
        mode = self.main_window.mode_switch.mode()
        if mode == 'usb':
            if self.usb_handler is None and self.main_window.file_tree.topLevelItemCount() > 0:
                self.main_window.start_server_btn.setEnabled(True)

        start, self._auto_start_armed = auto_start_decision(
            bool(self.main_window.config.get('auto_connect', True)),
            mode,
            self.get_active_handler() is not None,
            switch_present(self._probe_backends),
            self._auto_start_armed,
        )
        if start:
            self.main_window.log('info', 'Switch detected on USB — starting USB server')
            self.start_usb_server()

    def on_auto_connect_toggled(self, checked: bool):
        self.main_window.config.set('auto_connect', checked)
        self.main_window.config.save()
        self._auto_start_armed = True
        self.main_window.log('info', f"Auto-start on Switch connect {'enabled' if checked else 'disabled'}")

    def on_connection_changed(self, status):
        if status == ConnectionStatus.CONNECTED:
            self.main_window.connection_status.setText('🟢 Connected')
        elif status == ConnectionStatus.CONNECTING:
            self.main_window.connection_status.setText('🟡 Connecting...')
        else:
            self.main_window.connection_status.setText('🔴 Not connected')
            if self.usb_handler and not self.usb_handler.is_running:
                self._set_server_ui_state(False)

    # Session & Progress Signal Callbacks
    def _active_network_handler(self):
        return self.session.active_network_handler()

    def _active_tracker(self):
        return self.session.active_tracker()

    def _route_tracker(self, action: str, filename: str):
        self.session.route_tracker(action, filename)

    def on_progress_updated(
        self, filename: str, transferred: int, speed: float, total_req_size: int,
        num_files: int, cur_bytes: int, cur_size: int, _unused: int
    ):
        self.session.on_progress_updated(
            filename, transferred, speed, total_req_size, num_files, cur_bytes, cur_size, _unused
        )

    def on_file_progress(self, filename: str, progress: int):
        self.session.on_file_progress(filename, progress)

    def on_transfer_complete(self, filename: str):
        self.session.on_transfer_complete(filename)

    def on_file_skipped(self, filename: str, size: int):
        self.session.on_file_skipped(filename, size)

    def on_transfer_reset(self):
        self.session.on_transfer_reset()

    def on_installation_begun(self, requested_filenames):
        self.session.on_installation_begun(requested_filenames)

    def on_package_status_received(self, filename: str, status: int, result_code: int):
        self.session.on_package_status_received(filename, status, result_code)

    def on_storage_info_received(self, nand_free: int, nand_total: int, sd_free: int, sd_total: int):
        self.session.on_storage_info_received(nand_free, nand_total, sd_free, sd_total)

    def on_all_transfers_complete(self):
        self.session.on_all_transfers_complete()

    def on_queue_sync_confirmed(self, revision: int):
        self.session.on_queue_sync_confirmed(revision)
