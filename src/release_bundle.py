"""
Files for the microSD from one release option, sent to the Hub as one tar made on the fly.
Thousands of small files must not go one by one over FILE_RANGE; the Hub reads the tar as a
stream and writes each member to the microSD. Loose files are members at their SD path. An
archive goes as is: a `.kefir/rules` member (lines "archive prefix<TAB>SD prefix"), then the
archive under `.kefir/`; the Hub extracts it with those rules. Nothing is copied on the PC.
"""
import bisect
import os
import tarfile
from pathlib import Path
from typing import List, Optional, Tuple

from . import release_choice as rc
from .release_analyzer import Option, Release

SUFFIX = '.kefir-sd.tar'
_BLOCK = 512


def _header(name: str, size: int) -> bytes:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = size, 0o644, 0
    return info.tobuf(format=tarfile.PAX_FORMAT, encoding='utf-8')


def archive_rules(files: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """(archive entry, SD path) pairs -> prefix rules. Equal trailing path parts are cut off,
    so a whole folder maps with one rule; a renamed file keeps its own exact rule. Entries
    that no rule matches are not extracted."""
    rules: List[Tuple[str, str]] = []
    for src, dst in files:
        s, d = src.replace('\\', '/').split('/'), dst.split('/')
        n = 0
        # keep the first part of the entry: a rule for '' would also extract the archive's readme etc.
        while n < min(len(s), len(d)) - 1 and s[-1 - n] == d[-1 - n]:
            n += 1
        rule = ('/'.join(s), '/'.join(d)) if n == 0 else ('/'.join(s[:-n] + ['']), '/'.join(d[:-n] + ['']))
        if rule not in rules:
            rules.append(rule)
    return rules


class _Reader:
    def __init__(self, bundle: 'BundlePath'):
        self.b, self.pos = bundle, 0
        self.cur = None   # (path, handle) of the one file open now: thousands of members must not stay open

    def seek(self, off: int, whence: int = 0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.b.size + off
        return self.pos

    def read(self, n: int = -1) -> bytes:
        end = self.b.size if n < 0 else min(self.b.size, self.pos + n)
        out = bytearray()
        while self.pos < end:
            i = bisect.bisect_right(self.b.starts, self.pos) - 1
            start, length, data = self.b.starts[i], self.b.segs[i][0], self.b.segs[i][1]
            take = min(end, start + length) - self.pos
            rel = self.pos - start
            if isinstance(data, bytes):
                out += data[rel:rel + take]
            elif data is None:
                out += bytes(take)   # tar padding and the end blocks
            else:
                f = self._open(data)
                f.seek(rel)
                chunk = f.read(take)
                out += chunk + bytes(take - len(chunk))   # a file that shrank: keep the layout
            self.pos += take
        return bytes(out)

    def _open(self, path: str):
        if self.cur and self.cur[0] == path:
            return self.cur[1]
        self.close()
        self.cur = (path, open(path, 'rb'))
        return self.cur[1]

    def close(self):
        if self.cur:
            self.cur[1].close()
            self.cur = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class BundlePath(type(Path())):
    """A queue path that is not on disk: `<release folder>/<name>.kefir-sd.tar`. Equal to the
    plain Path of the same string, so queue lookups by Path work. open() gives the tar."""

    def __init__(self, *args, members: Optional[List[Tuple[str, object, int]]] = None):
        super().__init__(*args)
        self.segs, self.starts, self.size = [], [], 0
        for name, src, size in members or []:
            self._add(_header(name, size))
            self._add_part(size, src)
            if size % _BLOCK:
                self._add_part(_BLOCK - size % _BLOCK, None)
        if members is not None:
            self._add_part(2 * _BLOCK, None)

    def with_segments(self, *args):
        return Path(*args)   # derived paths (parent, joinpath) are plain paths

    def _add(self, data: bytes):
        self._add_part(len(data), data)

    def _add_part(self, length: int, data):
        if length:
            self.starts.append(self.size)
            self.segs.append((length, data))
            self.size += length

    def exists(self, *a, **kw) -> bool:
        return True

    def is_file(self, *a, **kw) -> bool:
        return True

    def resolve(self, strict: bool = False):
        return self

    def stat(self, *a, **kw):
        return os.stat_result((0o100644, 0, 0, 1, 0, 0, self.size, 0, 0, 0))

    def open(self, mode='rb', *a, **kw):
        return _Reader(self)


def _members(base: Path, o: Option) -> List[Tuple[str, object, int]]:
    def size(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0
    if o.archive:
        rules = ''.join(f'{s}\t{d}\n' for s, d in archive_rules(o.files)).encode('utf-8')
        path = base / o.archive
        return [('.kefir/rules', rules, len(rules)), (f'.kefir/{path.name}', str(path), size(path))]
    return [(dst, str(base / src), size(base / src)) for src, dst in o.files]


def _safe(name: str) -> str:
    return ''.join('_' if c in '\\/:*?"<>|' else c for c in name).strip() or 'files'


def bundles(rel: Release, choice: rc.Choice, base: Path) -> List[BundlePath]:
    """One bundle per chosen option, per game in copy order, then the shared options."""
    out = []
    groups = [(g.name, g.options, choice.get(g.tid, set())) for g in rel.games]
    groups.append(('Shared', rel.orphans, choice.get(rc.ORPHANS, set())))
    for game, opts, chosen in groups:
        for o in opts:
            if o.key in chosen:
                out.append(BundlePath(base / f'{_safe(game)} - {_safe(o.name)}{SUFFIX}', members=_members(base, o)))
    return out
