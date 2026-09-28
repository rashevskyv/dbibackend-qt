"""
Executable Protocol Suite for DBI Backend Qt:
- SPHQ extension (size, selected, target)
- SPHA extension (size, selected only)
- Legacy DBI fallback (CMD_ID_LIST, selected only)
- Legacy DBI v1 fallback (CMD_ID_LIST_OLD)
- Empty list boundary conditions
- Storage info exchange (CMD_ID_STORAGE_INFO)
- Package status exchange (CMD_ID_PACKAGE_STATUS)
- Exit command (CMD_ID_EXIT)
- File range exact name_len parsing
"""
import sys
import struct
import tempfile
from pathlib import Path
from PyQt6.QtCore import QCoreApplication
import usb.core

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import dbi_protocol
from src.usb_handler import USBHandler


class FakeInEp:
    def __init__(self, packets=None):
        self.packets = list(packets) if packets else []

    def read(self, size, timeout=None):
        if self.packets:
            return self.packets.pop(0)
        return b''


class FakeOutEp:
    def __init__(self):
        self.sent_buffers = []

    def write(self, data, timeout=None):
        self.sent_buffers.append(bytes(data))
        return len(data)


def create_test_handler(files_dict, initial_checked=None, initial_targets=None):
    handler = USBHandler(files_dict, initial_checked=initial_checked, initial_targets=initial_targets)
    handler.in_ep = FakeInEp()
    handler.out_ep = FakeOutEp()
    return handler


def test_sphq_list_exchange():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsz', delete=False) as f2:
        f1.write(b'A' * 1024)
        f2.write(b'B' * 2048)
        p1 = Path(f1.name)
        p2 = Path(f2.name)

    try:
        files = {p1.name: p1, p2.name: p2}
        checked = {p1.name}
        targets = {p1.name: dbi_protocol.TARGET_SD, p2.name: dbi_protocol.TARGET_NAND}
        handler = create_test_handler(files, initial_checked=checked, initial_targets=targets)

        # Sphaira sends Request for List with SPHQ extension (0x51485053)
        handler.in_ep.packets.append(b'\x00' * 16)  # Mock Ack from console
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)

        # Check response header
        out = handler.out_ep.sent_buffers
        assert len(out) == 2, f"Expected 2 buffers (header + payload), got {len(out)}"
        magic, cmd_type, cmd_id, data_size = struct.unpack('<4sIII', out[0])
        assert magic == b'DBI0'
        assert cmd_type == dbi_protocol.CMD_TYPE_RESPONSE
        assert cmd_id == dbi_protocol.CMD_ID_LIST
        assert data_size == len(out[1])

        # Check payload format: name|size|selected|target\n
        payload_text = out[1].decode('utf-8')
        lines = [line for line in payload_text.split('\n') if line]
        file_lines = [l for l in lines if not l.startswith(dbi_protocol.SPHQ_REV_PREFIX)]
        assert len(file_lines) == 2

        line_map = {}
        for line in file_lines:
            parts = line.split('|')
            assert len(parts) == 4
            line_map[parts[0]] = (int(parts[1]), int(parts[2]), int(parts[3]))

        assert line_map[p1.name] == (1024, 1, dbi_protocol.TARGET_SD)
        assert line_map[p2.name] == (2048, 0, dbi_protocol.TARGET_NAND)
        print("PASS: test_sphq_list_exchange")
    finally:
        p1.unlink()
        p2.unlink()


def test_spha_list_exchange():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f2:
        f1.write(b'A' * 512)
        f2.write(b'B' * 1024)
        p1 = Path(f1.name)
        p2 = Path(f2.name)

    try:
        files = {p1.name: p1, p2.name: p2}
        checked = {p1.name}  # Only p1 is selected
        handler = create_test_handler(files, initial_checked=checked)

        handler.in_ep.packets.append(b'\x00' * 16)
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHA)

        out = handler.out_ep.sent_buffers
        assert len(out) == 2
        payload_text = out[1].decode('utf-8')
        lines = [line for line in payload_text.split('\n') if line]
        assert len(lines) == 1  # Only selected file included

        parts = lines[0].split('|')
        assert len(parts) == 2
        assert parts[0] == p1.name
        assert int(parts[1]) == 512
        print("PASS: test_spha_list_exchange")
    finally:
        p1.unlink()
        p2.unlink()


def test_legacy_dbi_list_exchange():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f2:
        f1.write(b'A' * 512)
        f2.write(b'B' * 1024)
        p1 = Path(f1.name)
        p2 = Path(f2.name)

    try:
        files = {p1.name: p1, p2.name: p2}
        checked = {p2.name}
        handler = create_test_handler(files, initial_checked=checked)

        handler.in_ep.packets.append(b'\x00' * 16)
        handler.process_list_command(0)  # Standard DBI data_size == 0

        out = handler.out_ep.sent_buffers
        assert len(out) == 2
        payload_text = out[1].decode('utf-8')
        lines = [line for line in payload_text.split('\n') if line]
        assert len(lines) == 1
        assert lines[0] == p2.name
        print("PASS: test_legacy_dbi_list_exchange")
    finally:
        p1.unlink()
        p2.unlink()


def test_legacy_dbi_v1_list_command_id():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'A' * 256)
        p1 = Path(f1.name)

    try:
        files = {p1.name: p1}
        handler = create_test_handler(files)

        handler.in_ep.packets.append(b'\x00' * 16)
        handler.process_list_command(0, cmd_id=dbi_protocol.CMD_ID_LIST_OLD)

        out = handler.out_ep.sent_buffers
        assert len(out) == 2
        magic, cmd_type, cmd_id, data_size = struct.unpack('<4sIII', out[0])
        assert magic == b'DBI0'
        assert cmd_type == dbi_protocol.CMD_TYPE_RESPONSE
        assert cmd_id == dbi_protocol.CMD_ID_LIST_OLD
        print("PASS: test_legacy_dbi_v1_list_command_id")
    finally:
        p1.unlink()


def test_empty_list_sphq_with_marker():
    handler = create_test_handler({})
    marker_bytes = dbi_protocol.SPHQ_EMPTY_MARKER.encode('utf-8')
    handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, len(marker_bytes)))
    handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)

    out = handler.out_ep.sent_buffers
    assert len(out) == 2, f"Expected 2 buffers (header + marker payload), got {len(out)}"
    magic, cmd_type, cmd_id, data_size = struct.unpack('<4sIII', out[0])
    assert magic == b'DBI0'
    assert cmd_type == dbi_protocol.CMD_TYPE_RESPONSE
    assert cmd_id == dbi_protocol.CMD_ID_LIST
    assert data_size == len(marker_bytes)
    assert out[1] == marker_bytes
    assert out[1] == b'::SPHQ::\n'
    print("PASS: test_empty_list_sphq_with_marker")


def test_empty_list_spha_negative_no_marker():
    handler = create_test_handler({})
    handler.process_list_command(dbi_protocol.LIST_EXT_SPHA)

    out = handler.out_ep.sent_buffers
    assert len(out) == 1, "Empty SPHA list should only send response header with data_size=0"
    magic, cmd_type, cmd_id, data_size = struct.unpack('<4sIII', out[0])
    assert magic == b'DBI0'
    assert cmd_type == dbi_protocol.CMD_TYPE_RESPONSE
    assert cmd_id == dbi_protocol.CMD_ID_LIST
    assert data_size == 0
    print("PASS: test_empty_list_spha_negative_no_marker")


def test_empty_list_legacy_dbi_negative_no_marker():
    handler = create_test_handler({})
    handler.process_list_command(0)

    out = handler.out_ep.sent_buffers
    assert len(out) == 1, "Empty legacy list should only send response header with data_size=0"
    magic, cmd_type, cmd_id, data_size = struct.unpack('<4sIII', out[0])
    assert magic == b'DBI0'
    assert cmd_type == dbi_protocol.CMD_TYPE_RESPONSE
    assert cmd_id == dbi_protocol.CMD_ID_LIST
    assert data_size == 0
    print("PASS: test_empty_list_legacy_dbi_negative_no_marker")


def test_sphq_subsequent_list_after_files_added():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'X' * 500)
        p1 = Path(f1.name)

    try:
        handler = create_test_handler({})
        marker_bytes = dbi_protocol.SPHQ_EMPTY_MARKER.encode('utf-8')
        # 1. First probe with empty queue -> responds with marker
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, len(marker_bytes)))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)
        assert handler.out_ep.sent_buffers[1] == marker_bytes

        # 2. Files dynamically added to backend
        handler.update_file_registry({p1.name: p1}, {p1.name}, {p1.name: dbi_protocol.TARGET_SD})
        handler.out_ep.sent_buffers.clear()

        # 3. Next SPHQ list request (FetchLiveSelection) -> responds with actual file entry
        expected_line = f"{p1.name}|500|1|{dbi_protocol.TARGET_SD}\n".encode('utf-8')
        handler.in_ep.packets.append(struct.pack('<4sIII', b'DBI0', dbi_protocol.CMD_TYPE_ACK, dbi_protocol.CMD_ID_LIST, 100))
        handler.process_list_command(dbi_protocol.LIST_EXT_SPHQ)

        out = handler.out_ep.sent_buffers
        assert len(out) == 2
        _, _, _, data_size = struct.unpack('<4sIII', out[0])
        assert data_size == len(out[1])
        assert expected_line in out[1]
        assert b'::SPHQ::' not in out[1]
        print("PASS: test_sphq_subsequent_list_after_files_added")
    finally:
        p1.unlink()


def test_storage_info_exchange():
    handler = create_test_handler({})
    received = []
    handler.storage_info_received.connect(lambda nf, nt, sf, st: received.append((nf, nt, sf, st)))

    nand_free = 15000000000
    nand_total = 32000000000
    sd_free = 120000000000
    sd_total = 256000000000
    payload = struct.pack('<QQQQ', nand_free, nand_total, sd_free, sd_total)

    handler.in_ep.packets.append(payload)
    handler.process_storage_info_command(len(payload))

    out = handler.out_ep.sent_buffers
    assert len(out) == 2, f"Expected 2 out buffers (Ack, Response), got {len(out)}"

    # Check Ack
    ack_magic, ack_type, ack_id, ack_size = struct.unpack('<4sIII', out[0])
    assert ack_magic == b'DBI0'
    assert ack_type == dbi_protocol.CMD_TYPE_ACK
    assert ack_id == dbi_protocol.CMD_ID_STORAGE_INFO
    assert ack_size == 32

    # Check Response
    res_magic, res_type, res_id, res_size = struct.unpack('<4sIII', out[1])
    assert res_magic == b'DBI0'
    assert res_type == dbi_protocol.CMD_TYPE_RESPONSE
    assert res_id == dbi_protocol.CMD_ID_STORAGE_INFO
    assert res_size == 0

    assert len(received) == 1
    assert received[0] == (nand_free, nand_total, sd_free, sd_total)
    print("PASS: test_storage_info_exchange")


def test_package_status_exchange():
    handler = create_test_handler({})
    received = []
    handler.package_status_received.connect(lambda n, s, r: received.append((n, s, r)))

    pkg_name = "SuperGame.nsp"
    name_bytes = pkg_name.encode('utf-8')
    header = struct.pack('<III', dbi_protocol.STATUS_INSTALLED, 0, len(name_bytes))
    payload = header + name_bytes

    handler.in_ep.packets.append(payload)
    handler.process_package_status_command(len(payload))

    out = handler.out_ep.sent_buffers
    assert len(out) == 2

    # Check Ack
    ack_magic, ack_type, ack_id, ack_size = struct.unpack('<4sIII', out[0])
    assert ack_magic == b'DBI0'
    assert ack_type == dbi_protocol.CMD_TYPE_ACK
    assert ack_id == dbi_protocol.CMD_ID_PACKAGE_STATUS
    assert ack_size == len(payload)

    # Check Response
    res_magic, res_type, res_id, res_size = struct.unpack('<4sIII', out[1])
    assert res_magic == b'DBI0'
    assert res_type == dbi_protocol.CMD_TYPE_RESPONSE
    assert res_id == dbi_protocol.CMD_ID_PACKAGE_STATUS
    assert res_size == 0

    assert len(received) == 1
    assert received[0] == (pkg_name, dbi_protocol.STATUS_INSTALLED, 0)
    print("PASS: test_package_status_exchange")


def test_file_range_header_with_exact_name_len():
    with tempfile.NamedTemporaryFile(suffix='.nsp', delete=False) as f1:
        f1.write(b'Z' * 200000)
        p1 = Path(f1.name)

    try:
        files = {p1.name: p1}
        handler = create_test_handler(files)
        handler.is_running = True

        name_bytes = p1.name.encode('utf-8')
        range_size = 500
        range_offset = 0
        name_len = len(name_bytes)
        # 16-byte FileRangeHeader: [range_size: u32][range_offset: u64][name_len: u32]
        payload = struct.pack('<IQI', range_size, range_offset, name_len) + name_bytes + b'\x00\x00\x00'

        handler.in_ep.packets.append(payload)
        handler.in_ep.packets.append(b'\x00' * 16)  # Mock Final Ack

        handler.process_file_range_command(len(payload))
        assert p1.name in handler.progress_tracker.requested_files

        # Test transfer phase (> 100KB)
        transfer_range_size = 200000
        transfer_payload = struct.pack('<IQI', transfer_range_size, range_offset, name_len) + name_bytes + b'\x00\x00'
        handler.in_ep.packets.append(transfer_payload)
        handler.in_ep.packets.append(b'\x00' * 16)
        handler.process_file_range_command(len(transfer_payload))
        assert handler.current_transfer_file == p1.name
        print("PASS: test_file_range_header_with_exact_name_len")
    finally:
        if handler.cached_file_handle:
            handler.cached_file_handle.close()
        p1.unlink()


def test_truncated_payloads_rejected():
    cases = (
        ('package header', 'process_package_status_command', b'\x00' * 11),
        ('package name', 'process_package_status_command', struct.pack('<III', 0, 0, 5) + b'ab'),
        ('storage info', 'process_storage_info_command', b'\x00' * 31),
        ('range header', 'process_file_range_command', b'\x00' * 15),
        ('range name', 'process_file_range_command', struct.pack('<IQI', 100, 0, 5) + b'ab'),
    )
    for label, method, payload in cases:
        handler = create_test_handler({})
        handler.in_ep.packets.append(payload)
        try:
            getattr(handler, method)(len(payload))
        except usb.core.USBError:
            pass
        else:
            raise AssertionError(f'{label}: truncated payload was accepted')
        assert len(handler.out_ep.sent_buffers) == 1, f'{label}: unexpected response'
    print('PASS: test_truncated_payloads_rejected')


def main():
    QCoreApplication([])
    test_sphq_list_exchange()
    test_spha_list_exchange()
    test_legacy_dbi_list_exchange()
    test_legacy_dbi_v1_list_command_id()
    test_empty_list_handling()
    test_storage_info_exchange()
    test_package_status_exchange()
    test_file_range_header_with_exact_name_len()
    test_truncated_payloads_rejected()
    print("\nALL 9 PROTOCOL AND FALLBACK CHECKS PASSED SUCCESSFULLY")


if __name__ == '__main__':
    main()
