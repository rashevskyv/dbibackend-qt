from src.release_analyzer import Option
from src.release_bundle import BundlePath, _members


def test_reader_keeps_one_member_open(tmp_path):
    files = []
    for i in range(300):
        (tmp_path / f'f{i}.bin').write_bytes(b'x' * 100)
        files.append((f'f{i}.bin', f'sd/f{i}.bin'))
    b = BundlePath(tmp_path / 'x.kefir-sd.tar', members=_members(tmp_path, Option('k', 'm', 'mod', 'h', files)))
    r = b.open()
    got = 0
    while chunk := r.read(4096):
        got += len(chunk)
        assert (1 if r.cur else 0) <= 1
    assert got == b.size
    r.close()
    assert r.cur is None
