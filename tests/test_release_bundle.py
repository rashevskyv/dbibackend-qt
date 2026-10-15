"""SD bundles: the tar made on the fly reads back as a valid tar in any chunk sizes."""
import io
import random
import tarfile
from pathlib import Path

from src import release_choice as rc
from src.release_analyzer import analyze
from src.release_bundle import SUFFIX, BundlePath, archive_rules, bundles

BASE = 'Game [0100B7C00933A000][v0].nsp'
TID = 0x0100B7C00933A000


def read_all(b: BundlePath) -> bytes:
    rnd = random.Random(1)
    out = bytearray()
    with b.open('rb') as f:
        off = 0
        while off < b.size:
            n = rnd.choice([1, 7, 511, 512, 513, 4096, 100000])
            f.seek(off)
            chunk = f.read(n)
            assert chunk
            out += chunk
            off += len(chunk)
    return bytes(out)


def test_rules_cut_equal_tails_and_keep_renames():
    assert archive_rules([('sdcard/switch/p/a.nro', 'switch/p/a.nro'), ('sdcard/switch/p/d/b', 'switch/p/d/b')]) \
        == [('sdcard/switch/', 'switch/')]
    assert archive_rules([('font.pak_duckbill', 'atmosphere/contents/X/romfs/Paks/p.pak')]) \
        == [('font.pak_duckbill', 'atmosphere/contents/X/romfs/Paks/p.pak')]
    assert archive_rules([('a\\b.bin', 'atmosphere/contents/X/romfs/a/b.bin')]) == [('a/', 'atmosphere/contents/X/romfs/a/')]
    assert archive_rules([('switch/p/a.nro', 'switch/p/a.nro')]) == [('switch/', 'switch/')]   # never '' -> ''


def test_loose_files_and_archive_bundle(tmp_path):
    files = {
        BASE: b'nsp',
        'Mod/atmosphere/contents/0100B7C00933A000/romfs/Привіт.bin': b'A' * 1000,
        'Mod/atmosphere/contents/0100B7C00933A000/romfs/' + 'd' * 120 + '/b.bin': b'B' * 512,
        'switch (v0.4) [ENG].7z': b'7z-bytes',
    }
    for r, data in files.items():
        (tmp_path / r).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / r).write_bytes(data)
    rel = analyze(list(files), lambda p: ['switch/port/port.nro', 'switch/port/data/x'] if p.endswith('.7z') else None)
    choice = rc.defaults(rel)
    out = bundles(rel, choice, tmp_path)
    assert [b.name.endswith(SUFFIX) for b in out] == [True, True]
    for b in out:
        assert b.exists() and b.stat().st_size == b.size and b == Path(str(b)) and b.size % 512 == 0
    by_name = {b.name: b for b in out}
    mod = next(b for n, b in by_name.items() if 'Mod' in n)
    with tarfile.open(fileobj=io.BytesIO(read_all(mod))) as t:
        got = {m.name: t.extractfile(m).read() for m in t.getmembers()}
    assert got == {
        'atmosphere/contents/0100B7C00933A000/romfs/Привіт.bin': b'A' * 1000,
        'atmosphere/contents/0100B7C00933A000/romfs/' + 'd' * 120 + '/b.bin': b'B' * 512,
    }
    port = next(b for n, b in by_name.items() if 'switch' in n)
    with tarfile.open(fileobj=io.BytesIO(read_all(port))) as t:
        names = [m.name for m in t.getmembers()]
        assert names == ['.kefir/rules', '.kefir/switch (v0.4) [ENG].7z']
        assert t.extractfile('.kefir/rules').read() == b'switch/\tswitch/\n'
        assert t.extractfile(names[1]).read() == b'7z-bytes'
