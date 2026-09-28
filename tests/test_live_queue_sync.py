"""
End-to-End Live USB Queue Verification Suite for DBI Backend Qt:
1. Empty start and subsequent addition
2. Reordering two future packages
3. Removing a future package
4. Immutability of active/completed prefix
5. Changing target (SD / NAND / Auto)
6. Re-adding removed file
7. Legacy DBI / SPHA compatibility (no revision prefix, clean fallback)
8. Duplicate basename conflict detection and active file protection
9. Confirmation of applied revision via CMD_TYPE_ACK on CMD_ID_LIST
"""

import sys
import struct
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import dbi_protocol
from src.usb_handler import USBHandler
from src.queue_manager import QueueManager, STATUS_DONE, STATUS_QUEUED


class MockInEp:
    def __init__(self, packets=None):
        self.packets = list(packets) if packets else []

    def read(self, size, timeout=None):
        if self.packets:
            return self.packets.pop(0)
        return b''


class MockOutEp:
    def __init__(self):
        self.sent_buffers = []

    def write(self, data, timeout=None):
        self.sent_buffers.append(bytes(data))
        return len(data)


def create_handler(files_dict=None, initial_checked=None, initial_targets=None):
    handler = USBHandler(files_dict or {}, initial_checked=initial_checked, initial_targets=initial_targets)
    handler.in_ep = MockInEp()
    handler.out_ep = MockOutEp()
    return handler


def parse_sphq_payload(payload_bytes: bytes):
    text = payload_bytes.decode('utf-8')
    lines = [line for line in text.split('\n') if line]
    rev = 0
    items = []
    for line in lines:
        if line.startswith(dbi_protocol.SPHQ_REV_PREFIX):
            parts = line.split('|')
            rev = int(parts[1]) if len(parts) > 1 else int(parts[0].replace(dbi_protocol.SPHQ_REV_PREFIX, ''))
            continue
        parts = line.split('|')
        if len(parts) >= 4:
            items.append({
                'name': parts[0],
                'size': int(parts[1]),
                'selected': int(parts[2]),
                'target': int(parts[3])
            })
    return rev, items


# 1. Empty start and subsequent addition
def test_scenario_1_empty_start_and_subsequent_addition():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'Z' * 300)
        p1 = Path(f1.name)

    try:
        handler = create_handler({})
        # Empty queue list request -> must return ::SPHQ::\n marker
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 9))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        assert handler.out_ep.sent_buffers[1] == dbi_protocol.SPHQ_EMPTY_MARKER.encode('utf-8')

        # Add file after start
        handler.update_file_registry({p1.name: p1}, {p1.name}, {p1.name: dbi_protocol.TARGET_SD})
        assert handler.queue_revision > 0
        handler.out_ep.sent_buffers.clear()

        # Next SPHQ request receives file and revision
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)

        rev, items = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        assert rev == handler.queue_revision
        assert len(items) == 1
        assert items[0]['name'] == p1.name
        assert items[0]['size'] == 300
        assert items[0]['selected'] == 1
        assert items[0]['target'] == dbi_protocol.TARGET_SD
    finally:
        p1.unlink(missing_ok=True)


# 2. Reordering two future packages
def test_scenario_2_reordering_future_packages():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsz', delete=False) as f2:
        f1.write(b'1' * 100)
        f2.write(b'2' * 200)
        p1, p2 = Path(f1.name), Path(f2.name)

    try:
        # Initial order: p1, then p2
        handler = create_handler({p1.name: p1, p2.name: p2}, {p1.name, p2.name})
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        _, items1 = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        assert [i['name'] for i in items1] == [p1.name, p2.name]

        # Reorder: p2, then p1
        init_rev = handler.queue_revision
        handler.update_file_registry({p2.name: p2, p1.name: p1}, {p1.name, p2.name})
        assert handler.queue_revision > init_rev

        handler.out_ep.sent_buffers.clear()
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        _, items2 = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        assert [i['name'] for i in items2] == [p2.name, p1.name]
    finally:
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)


# 3. Removing a future package
def test_scenario_3_removing_future_package():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f2, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f3:
        p1, p2, p3 = Path(f1.name), Path(f2.name), Path(f3.name)

    try:
        handler = create_handler({p1.name: p1, p2.name: p2, p3.name: p3}, {p1.name, p2.name, p3.name})
        # Remove p2
        handler.update_file_registry({p1.name: p1, p3.name: p3}, {p1.name, p3.name})

        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        _, items = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        names = [i['name'] for i in items]
        assert p2.name not in names
        assert names == [p1.name, p3.name]
    finally:
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)
        p3.unlink(missing_ok=True)


# 4. Immutability of active/completed prefix
def test_scenario_4_immutability_of_active_completed_prefix():
    qm = QueueManager()
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f2, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f3:
        p1, p2, p3 = Path(f1.name), Path(f2.name), Path(f3.name)

    try:
        qm.add_flat_files([p1, p2, p3])

        # Mark first file as completed
        qm.files[p1.resolve()].status = STATUS_DONE
        assert qm.files[p1.resolve()].status == STATUS_DONE

        # Move/reorder future files p2 and p3
        qm.move_item(p3, -1)  # p3 before p2
        assert qm.order == [p1.resolve(), p3.resolve(), p2.resolve()]

        # File p1 status is still DONE and remains at top
        assert qm.files[p1.resolve()].status == STATUS_DONE
        assert qm.order[0] == p1.resolve()
    finally:
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)
        p3.unlink(missing_ok=True)


# 5. Changing target (SD / NAND / Auto)
def test_scenario_5_changing_target():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'T' * 100)
        p1 = Path(f1.name)

    try:
        handler = create_handler({p1.name: p1}, {p1.name}, {p1.name: dbi_protocol.TARGET_SD})
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        _, items = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        assert items[0]['target'] == dbi_protocol.TARGET_SD

        # Change target to NAND
        handler.update_file_registry({p1.name: p1}, {p1.name}, {p1.name: dbi_protocol.TARGET_NAND})
        handler.out_ep.sent_buffers.clear()
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        _, items = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        assert items[0]['target'] == dbi_protocol.TARGET_NAND

        # Change target to Auto (0)
        handler.update_file_registry({p1.name: p1}, {p1.name}, {p1.name: dbi_protocol.TARGET_AUTO})
        handler.out_ep.sent_buffers.clear()
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        _, items = parse_sphq_payload(handler.out_ep.sent_buffers[1])
        assert items[0]['target'] == dbi_protocol.TARGET_AUTO
    finally:
        p1.unlink(missing_ok=True)


# 6. Re-adding removed file
def test_scenario_6_readding_removed_file():
    qm = QueueManager()
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        p1 = Path(f1.name)

    try:
        qm.add_flat_files([p1])
        assert p1.resolve() in qm.files
        qm.remove_path(p1)
        assert p1.resolve() not in qm.files

        # Re-add
        added = qm.add_flat_files([p1])
        assert added == 1
        rec = qm.files[p1.resolve()]
        assert rec.status == 'Queued'
        assert not rec.in_conflict
        assert p1.resolve() in qm.order
    finally:
        p1.unlink(missing_ok=True)


# 7. Legacy DBI / SPHA compatibility
def test_scenario_7_legacy_compatibility():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f2:
        f1.write(b'A' * 64)
        f2.write(b'B' * 64)
        p1, p2 = Path(f1.name), Path(f2.name)

    try:
        # p1 is checked, p2 is unchecked
        handler = create_handler({p1.name: p1, p2.name: p2}, {p1.name})

        # Legacy DBI (ext == 0): returns only checked files, newline separated, NO SPHQ_REV prefix
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 50))
        handler.process_list_command(0)
        legacy_payload = handler.out_ep.sent_buffers[1].decode('utf-8')
        assert legacy_payload == f"{p1.name}\n"
        assert dbi_protocol.SPHQ_REV_PREFIX not in legacy_payload
        assert p2.name not in legacy_payload

        # SPHA (ext == LIST_EXT_SPHA): returns name|size\n for selected files, NO SPHQ_REV prefix
        handler.out_ep.sent_buffers.clear()
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHA)
        spha_payload = handler.out_ep.sent_buffers[1].decode('utf-8')
        assert dbi_protocol.SPHQ_REV_PREFIX not in spha_payload
        lines = [l for l in spha_payload.split('\n') if l]
        assert len(lines) == 1
        parts = lines[0].split('|')
        assert len(parts) == 2
        assert parts[0] == p1.name
        assert int(parts[1]) == 64
    finally:
        p1.unlink(missing_ok=True)
        p2.unlink(missing_ok=True)


# 8. Duplicate basename conflict detection and active file protection
def test_scenario_8_conflict_detection_and_active_protection():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        p1 = Path(d1) / "same_name.nsp"
        p2 = Path(d2) / "same_name.nsp"
        p1.write_bytes(b'D1' * 50)
        p2.write_bytes(b'D2' * 50)

        # 8a: QueueManager conflict detection
        qm = QueueManager()
        qm.add_flat_files([p1, p2])
        conflicts = qm.recompute_conflicts()
        assert "same_name.nsp" in conflicts
        assert qm.files[p1.resolve()].in_conflict is True
        assert qm.files[p2.resolve()].in_conflict is True
        # Transfer list excludes conflicts
        assert "same_name.nsp" not in qm.get_transfer_file_list()

        # 8b: USBHandler active transfer protection: silent replacement blocked
        handler = create_handler({"same_name.nsp": p1}, {"same_name.nsp"})
        handler.current_transfer_file = "same_name.nsp"

        # Attempt to swap path for current_transfer_file
        handler.update_file_registry({"same_name.nsp": p2}, {"same_name.nsp"})
        # New path is never advertised; the active old path stays readable.
        assert "same_name.nsp" not in handler.file_list
        assert handler._retained_active_files["same_name.nsp"].resolve() == p1.resolve()


# 9. Confirmation of applied revision via CMD_TYPE_ACK on CMD_ID_LIST
def test_scenario_9_revision_ack_confirmation():
    handler = create_handler({})
    handler.queue_revision = 4
    handler.last_sent_revision = 4

    confirmed = []
    handler.queue_sync_confirmed.connect(lambda rev: confirmed.append(rev))

    # Simulate client sending CmdType::Ack for CmdId::List with data_size = 4, followed by exit to break poll
    ack_packet = struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 4)
    exit_packet = struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_REQUEST, dbi_protocol.CMD_ID_EXIT, 0)
    handler.in_ep.packets.extend([ack_packet, exit_packet])

    handler.is_running = True
    handler.poll_commands()

    assert handler.confirmed_revision == 4
    assert confirmed == [4]


# 10. Regression: Empty queue after removing last file includes revision and is ACKed
def test_empty_queue_after_last_file_removed_includes_revision_and_can_be_acked():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'E' * 256)
        p1 = Path(f1.name)

    try:
        handler = create_handler({p1.name: p1}, {p1.name})
        assert handler.queue_revision == 1

        # User removes the only file
        handler.update_file_registry({}, set())
        assert handler.queue_revision == 2

        # Console requests live queue
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)

        payload_bytes = handler.out_ep.sent_buffers[1]
        rev, items = parse_sphq_payload(payload_bytes)
        assert rev == 2
        assert items == []
        assert dbi_protocol.SPHQ_REV_PREFIX in payload_bytes.decode('utf-8')
        assert dbi_protocol.SPHQ_EMPTY_MARKER in payload_bytes.decode('utf-8')

        # Console confirms rev 2
        handler.process_list_ack(2)
        assert handler.confirmed_revision == 2
    finally:
        p1.unlink(missing_ok=True)


# 11. Regression: Active file retained across deletion until terminal status
def test_active_file_retained_across_deletion_until_terminal_status():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'A' * 4096)
        p1 = Path(f1.name)

    try:
        handler = create_handler({p1.name: p1}, {p1.name})
        handler.current_transfer_file = p1.name

        # User deletes file while it is actively transferring
        handler.update_file_registry({}, set())
        assert p1.name not in handler.file_list
        assert p1.name in handler._retained_active_files

        # Console requests a range for this file
        name_bytes = p1.name.encode('utf-8')
        range_header = struct.pack('<IQI', 1024, 0, len(name_bytes)) + name_bytes
        handler.in_ep.packets.append(range_header)
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_FILE_RANGE, 1024))

        # process_file_range_command must succeed without raising USBError
        handler.process_file_range_command(len(range_header))

        # Terminal status arrived from console
        status_header = struct.pack('<III', dbi_protocol.STATUS_INSTALLED, 0, len(name_bytes)) + name_bytes
        handler.in_ep.packets.append(status_header)
        handler.process_package_status_command(len(status_header))

        # Active retained file is now cleaned up
        assert p1.name not in handler._retained_active_files
    finally:
        if handler.cached_file_handle:
            try:
                handler.cached_file_handle.close()
            except Exception:
                pass
        p1.unlink(missing_ok=True)


# 12. Regression: Session-locked basename replacement rejected even after file is processed
def test_session_locked_basename_replacement_rejected():
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        p1 = Path(d1) / "title.nsp"
        p2 = Path(d2) / "title.nsp"
        p1.write_bytes(b'V1' * 20)
        p2.write_bytes(b'V2' * 20)

        handler = create_handler({"title.nsp": p1}, {"title.nsp"})
        # File is completed
        handler.progress_tracker.completed_files_set.add("title.nsp")

        # User tries to re-add title.nsp pointing to p2 in same session
        handler.update_file_registry({"title.nsp": p2}, {"title.nsp"})
        assert "title.nsp" not in handler.file_list
        assert "title.nsp" not in handler._retained_active_files


# 13. Regression: Strict ACK validation rejects non-positive, stale, future, and unsent revisions
def test_strict_ack_validation():
    handler = create_handler({})
    handler.queue_revision = 5
    handler.last_sent_revision = 3  # last sent to console was rev 3
    handler.confirmed_revision = 2  # console previously confirmed rev 2

    confirmed = []
    handler.queue_sync_confirmed.connect(lambda r: confirmed.append(r))

    # Reject zero / negative
    handler.process_list_ack(0)
    handler.process_list_ack(-1)
    assert handler.confirmed_revision == 2
    assert confirmed == []

    # Reject stale (<= confirmed_revision)
    handler.process_list_ack(1)
    handler.process_list_ack(2)
    assert handler.confirmed_revision == 2
    assert confirmed == []

    # Reject future / unsent (> last_sent_revision)
    handler.process_list_ack(4)
    handler.process_list_ack(5)
    handler.process_list_ack(99)
    assert handler.confirmed_revision == 2
    assert confirmed == []

    # Accept valid matching sent revision (3)
    handler.process_list_ack(3)
    assert handler.confirmed_revision == 3
    assert confirmed == [3]
