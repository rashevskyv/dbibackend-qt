"""
Compact regression check for USBHandler process_file_range_command.
Verifies byte accounting, completion signals, and failure/reconnect paths.
"""
import sys
import struct
import tempfile
from pathlib import Path
from PyQt6.QtCore import QCoreApplication
import usb.core

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.usb_handler import USBHandler


class FakeInEp:
    def __init__(self, responses):
        self.responses = list(responses)

    def read(self, size, timeout=None):
        return self.responses.pop(0) if self.responses else b'\x00' * size


class FakeOutEp:
    def __init__(self, write_fn=None):
        self.write_fn = write_fn

    def write(self, data, timeout=None):
        return self.write_fn(data) if self.write_fn else len(data)


def run_range_case(case_name, file_bytes, req_size, write_fn=None, is_running=True):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.nsp') as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    handler = USBHandler({tmp_path.name: tmp_path})
    handler.is_running = is_running
    req_header = struct.pack('<IQ4x', req_size, 0) + tmp_path.name.encode('utf-8')
    handler.in_ep = FakeInEp([req_header, b'\x00' * 16])
    handler.out_ep = FakeOutEp(write_fn=write_fn)

    completed = []
    handler.transfer_complete.connect(lambda n: completed.append(n))
    failure_path = None

    try:
        handler.process_file_range_command(len(req_header))
    except usb.core.USBError as e:
        failure_path = f"USBError: {e}"
    except Exception as e:
        failure_path = f"{type(e).__name__}: {e}"
    finally:
        if handler.cached_file_handle:
            handler.cached_file_handle.close()
        tmp_path.unlink()

    credited = handler.progress_tracker.unique_bytes_transferred
    return {"name": case_name, "failure_path": failure_path, "credited": credited, "completed": completed}


def make_seq_write(returns):
    it = iter(returns)
    ack_count = 0

    def fn(data):
        nonlocal ack_count
        ack_count += 1
        if ack_count <= 2:
            return len(data)
        val = next(it, len(data))
        if isinstance(val, Exception):
            raise val
        return val
    return fn


def main():
    QCoreApplication([])
    chunk_1mib = 1048576
    cases = [
        ("successful_transfer", b'X' * 200000, 200000, None, True, None, 200000, 1),
        ("short_file_read", b'X' * 50000, 200000, None, True, "USBError", 50000, 0),
        ("empty_read", b'', 200000, None, True, "USBError", 0, 0),
        ("short_usb_write", b'X' * 200000, 200000, make_seq_write([30000]), True, "USBError", 30000, 0),
        ("zero_usb_write", b'X' * 200000, 200000, make_seq_write([0]), True, "USBError", 0, 0),
        ("invalid_write_negative", b'X' * 200000, 200000, make_seq_write([-1]), True, "USBError", 0, 0),
        ("invalid_write_overflow", b'X' * 200000, 200000, make_seq_write([999999]), True, "USBError", 0, 0),
        ("invalid_write_none", b'X' * 200000, 200000, make_seq_write([None]), True, "USBError", 0, 0),
        ("invalid_after_partial", b'X' * (chunk_1mib + 50000), chunk_1mib + 50000, make_seq_write([chunk_1mib, -1]), True, "USBError", chunk_1mib, 0),
        ("usb_write_exception", b'X' * 200000, 200000, make_seq_write([usb.core.USBError('Simulated write failure')]), True, "USBError", 0, 0),
        ("manual_stop", b'X' * 200000, 200000, None, False, None, 0, 0),
    ]

    for name, f_bytes, req_sz, w_fn, running, exp_err, exp_credit, exp_comp in cases:
        res = run_range_case(name, f_bytes, req_sz, write_fn=w_fn, is_running=running)
        err = res["failure_path"]
        assert (exp_err is None and err is None) or (exp_err and err and exp_err in err), f"{name}: unexpected path {err}"
        assert res["credited"] == exp_credit, f"{name}: expected {exp_credit} credited, got {res['credited']}"
        assert len(res["completed"]) == exp_comp, f"{name}: expected {exp_comp} completions, got {len(res['completed'])}"
        print(f"PASS: {name:<24} | path={err or 'None (normal)'} | credited={res['credited']} bytes | completed={len(res['completed'])}")

    print(f"ALL {len(cases)} USB RANGE REGRESSION CHECKS PASSED")


def test_usb_range():
    main()


def test_speed_window_is_time_bounded(monkeypatch):
    """The speed window is bounded by time (~30 s), not by a fixed number of chunks."""
    from src import usb_handler as uh_mod
    app = QCoreApplication.instance() or QCoreApplication([])
    clock = [1000.0]

    def fake_time():
        clock[0] += 0.1
        return clock[0]

    monkeypatch.setattr(uh_mod.time, 'time', fake_time)
    monkeypatch.setattr(uh_mod.dbi_protocol, 'BUFFER_SEGMENT_DATA_SIZE', 4096)

    size = 4096 * 250  # 250 chunks, two clock ticks each -> ~50 s of fake transfer
    with tempfile.NamedTemporaryFile(delete=False, suffix='.nsp') as tmp:
        tmp.write(b'X' * size)
        tmp_path = Path(tmp.name)
    handler = USBHandler({tmp_path.name: tmp_path})
    handler.is_running = True
    req_header = struct.pack('<IQ4x', size, 0) + tmp_path.name.encode('utf-8')
    handler.in_ep = FakeInEp([req_header, b'\x00' * 16])
    handler.out_ep = FakeOutEp()
    try:
        handler.process_file_range_command(len(req_header))
    finally:
        if handler.cached_file_handle:
            handler.cached_file_handle.close()
        tmp_path.unlink()

    span = handler._speed_samples[-1][0] - handler._speed_samples[0][0]
    assert 25.0 < span <= 30.0, f"speed window spans {span:.1f}s"


def test_missing_file_answers_zero_size_and_keeps_link():
    """A queued file deleted from disk: reply size 0, no ack read, no USBError (the console skips it)."""
    app = QCoreApplication.instance() or QCoreApplication([])
    gone = Path(tempfile.gettempdir()) / 'dbi_missing_test_file.nsp'
    gone.unlink(missing_ok=True)
    handler = USBHandler({gone.name: gone})
    handler.is_running = True
    req_header = struct.pack('<IQI', 704, 0, len(gone.name)) + gone.name.encode('utf-8')
    handler.in_ep = FakeInEp([req_header])
    written = []
    handler.out_ep = FakeOutEp(write_fn=lambda d: written.append(bytes(d)) or len(d))

    handler.process_file_range_command(len(req_header))  # must not raise

    assert handler.in_ep.responses == []  # header consumed, no ack waited for
    assert len(written) == 2  # ack + response
    assert struct.unpack('<4sIII', written[1]) == (b'DBI0', 1, 2, 0)


if __name__ == '__main__':
    main()
