"""Release analyser: what a dropped Switch release holds and what to install from it.

Pure logic, no Qt: the input is the list of file paths inside the release
(relative, '/' or '\\' separators) and a callback that lists an archive's files.
`scan_path()` builds that input from a real folder or archive (7-Zip lists .7z/.zip/.rar).

Model:
- Game: one title, joined by title ID (TID) read from the file name. The Hub
  re-reads the real TID and version from the cnmt when it installs.
- Option: files for the microSD card, from a folder or an archive:
  'port' (an NRO and its folder), 'data' (files a port needs, often one per
  language), 'mod' (LayeredFS, atmosphere/contents/<TID>). A mod may carry its own
  update NSP: when the mod is chosen, that update is installed instead of the
  release's own (newer) update, which would break the mod.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

PACKAGE_EXT = ('.nsp', '.nsz', '.xci', '.xcz')
ARCHIVE_EXT = ('.7z', '.zip', '.rar')
SKIP_EXT = ('.exe', '.msi', '.dll', '.bat', '.cmd', '.sh', '.lnk', '.url')
PARTIAL_EXT = ('.!qb', '.part', '.crdownload', '.!ut', '.aria2')
SD_ANCHORS = ('switch', 'atmosphere')

_HEX16 = re.compile(r'^[0-9A-Fa-f]{16}$')
_TID = re.compile(r'(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])')
_VERSION = re.compile(r'[\[\]]v(0x[0-9A-Fa-f]+|\d+)\]')
_SKIP_NAME = re.compile(r'firmware|(?<![a-z])keys?(?![a-z])|switchemu', re.I)
_MOD_WORD = re.compile(r'(?<![a-z])mod(?![a-z])', re.I)
# "Homebrew Update (v0.6.1)", "Updated videos": a later layer over the port, copied last
_UPDATE_WORD = re.compile(r'(?<![a-z])updat', re.I)
_MOD_TID = re.compile(r'^atmosphere/(?:contents|titles)/([0-9A-Fa-f]{16})/', re.I)
_LANGS = (
    ('ru', re.compile(r'(?<![a-z])rus|рус')),
    ('uk', re.compile(r'(?<![a-z])ukr|укр')),
    ('en', re.compile(r'(?<![a-z])eng|англ')),
)
KIND_ORDER = {'port': 0, 'data': 1, 'mod': 2}

ListArchive = Callable[[str], Optional[List[str]]]


@dataclass(frozen=True)
class Package:
    path: str
    tid: Optional[int]
    version: int = 0

    @property
    def kind(self) -> str:
        if self.tid is None:
            return 'unknown'
        low = self.tid & 0xFFF
        if low == 0x800:
            return 'update'
        # DLC ends in 001..7FF; any other ending is a homebrew stub with a random title ID
        return 'dlc' if 0 < low < 0x800 else 'base'

    @property
    def game_tid(self) -> Optional[int]:
        if self.tid is None:
            return None
        if self.kind == 'dlc':
            return (self.tid & ~0xFFF) - 0x1000
        return self.tid & ~0xFFF

    @property
    def name(self) -> str:
        return self.path.rsplit('/', 1)[-1]


@dataclass
class Option:
    key: str                      # stable id: the folder or archive path inside the release
    name: str
    kind: str                     # 'port' | 'data' | 'mod'
    home: str                     # folder the option lives in
    files: List[Tuple[str, str]]  # (source, SD destination); source is inside `archive` when set
    archive: Optional[str] = None
    tids: Set[int] = field(default_factory=set)
    updates: List[Package] = field(default_factory=list)
    lang: Optional[str] = None
    tid_mismatch: bool = False    # mod for a TID that is not in this release, joined by folder
    incomplete: bool = False      # a file in its folder is still downloading
    parent: Optional[str] = None  # add-on: key of the mod it needs (Phoenix Wright 'Addon - ...')


@dataclass
class Game:
    tid: int
    root: str
    base: Optional[Package] = None
    updates: List[Package] = field(default_factory=list)
    dlcs: List[Package] = field(default_factory=list)
    options: List[Option] = field(default_factory=list)

    @property
    def name(self) -> str:
        packages = [self.base] if self.base else self.updates + self.dlcs
        if not packages:   # mod-only: the Hub shows the installed title's name
            return f'{self.tid:016X}'
        pkg = packages[0]
        return re.split(r'\s*[\[(]', pkg.name, maxsplit=1)[0].strip() or pkg.name


@dataclass
class Release:
    games: List[Game] = field(default_factory=list)
    orphans: List[Option] = field(default_factory=list)   # options no game claims: ask the user
    unknown: List[str] = field(default_factory=list)      # packages without a TID in the name
    skipped: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class Plan:
    packages: List[Package]
    sd_files: List[Tuple[Option, str, str]]  # (option, source, SD destination), copy in this order
    conflicts: List[str]


def parse_package(path: str) -> Package:
    name = path.rsplit('/', 1)[-1]
    m = _TID.search(name)
    if not m:
        return Package(path, None)
    v = _VERSION.search(name, m.end())
    version = int(v.group(1), 0) if v else 0
    return Package(path, int(m.group(1), 16), version)


def detect_lang(name: str) -> Optional[str]:
    low = name.lower()
    for lang, rx in _LANGS:
        if rx.search(low):
            return lang
    return None


def _parent(path: str) -> str:
    return path.rsplit('/', 1)[0] if '/' in path else ''


def _basename(path: str) -> str:
    return path.rsplit('/', 1)[-1]


def _is_under(path: str, folder: str) -> bool:
    return folder == '' or path == folder or path.startswith(folder + '/')


def _sd_split(parts: Sequence[str]) -> Optional[Tuple[int, str]]:
    """Where the microSD tree starts in a path: (index, SD destination) or None."""
    for i, comp in enumerate(parts[:-1]):
        if comp.lower() in SD_ANCHORS:
            return i, '/'.join([comp.lower()] + list(parts[i + 1:]))
        # bare LayeredFS folder: <TID>/romfs or <TID>/exefs, without atmosphere/contents above it
        if _HEX16.match(comp) and i + 2 < len(parts) and parts[i + 1].lower() in ('romfs', 'exefs'):
            return i, 'atmosphere/contents/' + '/'.join(parts[i:])
    return None


def _classify(files: List[Tuple[str, str]]) -> Tuple[str, Set[int]]:
    tids = set()
    has_nro = False
    for _, dst in files:
        # a game's romfs holds .nro modules too (Yakuza Kiwami); a port's NRO lives under switch/
        if dst.lower().endswith('.nro') and dst.lower().startswith('switch/'):
            has_nro = True
        m = _MOD_TID.match(dst)
        if m:
            tids.add(int(m.group(1), 16))
    return ('port' if has_nro else 'mod' if tids else 'data'), tids


def analyze(paths: Sequence[str], list_archive: Optional[ListArchive] = None) -> Release:
    rel = Release()
    files = []
    for raw in paths:
        p = raw.replace('\\', '/').strip('/')
        if p.startswith('./'):
            p = p[2:]
        if p:
            files.append(p)

    packages: List[Package] = []
    units: Dict[str, List[Tuple[str, str]]] = {}   # unit root -> [(source, dst)]
    archives: List[str] = []
    loose: List[str] = []
    for p in files:
        parts = p.split('/')
        low = p.lower()
        if any(_SKIP_NAME.search(c) for c in parts) or low.endswith(SKIP_EXT):
            rel.skipped.append((p, 'not for the console'))
            continue
        if low.endswith(PARTIAL_EXT):
            rel.skipped.append((p, 'download not finished'))
            continue
        sd = _sd_split(parts)
        if sd:
            units.setdefault('/'.join(parts[:sd[0]]), []).append((p, sd[1]))
        elif low.endswith(PACKAGE_EXT):
            packages.append(parse_package(p))
        elif low.endswith(ARCHIVE_EXT):
            archives.append(p)
        else:
            loose.append(p)

    # a port folder without switch/ above it (defjamx/defjamx.nro): copy it to switch/<folder>/
    package_dirs = {_parent(pkg.path) for pkg in packages}
    port_dirs = sorted({_parent(p) for p in loose if p.lower().endswith('.nro') and _parent(p) not in package_dirs})
    for d in port_dirs:
        if any(_is_under(d, other) and d != other for other in port_dirs):
            continue
        name = _basename(d)
        units[d] = [(p, f'switch/{name}/' + p[len(d) + 1:]) for p in loose if _is_under(p, d) and p != d]

    options: List[Option] = []
    for root, ufiles in units.items():
        kind, tids = _classify(ufiles)
        name = _basename(root) or 'SD card files'
        options.append(Option(root or '.', name, kind, root, ufiles, tids=tids, lang=detect_lang(name)))
    # a file still downloading marks only the folder unit it belongs to, not its neighbours
    partial_roots = set()
    for p, why in rel.skipped:
        if why != 'download not finished':
            continue
        parts = p.split('/')
        sd = _sd_split(parts)
        if sd:
            partial_roots.add('/'.join(parts[:sd[0]]))
        partial_roots.update(d for d in port_dirs if d and _is_under(p, d))
    for o in options:
        o.incomplete = o.home in partial_roots
    port_names = {dst.split('/')[1].lower() for o in options if o.kind == 'port'
                  for _, dst in o.files if dst.lower().startswith('switch/') and dst.count('/') >= 2}
    # a mod's file names by folder: an archive of bare files with the same names replaces them
    mod_names: Dict[str, Dict[str, str]] = {}
    for o in options:
        if o.kind == 'mod':
            for _, dst in o.files:
                mod_names.setdefault(o.home, {})[_basename(dst).lower()] = dst

    for a in archives:
        members = list_archive(a) if list_archive else None
        if members is None:
            rel.skipped.append((a, 'cannot read the archive (7-Zip not found?)'))
            continue
        afiles = []
        bad = None
        for m in members:
            m = m.replace('\\', '/').strip('/')
            parts = m.split('/')
            if m.lower().endswith(PACKAGE_EXT):
                bad = 'a package inside an archive: extract it first'
                continue
            sd = _sd_split(parts)
            if sd:
                afiles.append((m, sd[1]))
            elif len(parts) > 1 and parts[0].lower() in port_names:
                afiles.append((m, 'switch/' + m))   # dusk/texture_replacements/... for the dusk port
            elif parts[-1].lower() in mod_names.get(_parent(a), {}):
                # DQ XI: better_russian_font_...zip holds another pakchunk0-Switch_p.pak for the mod
                afiles.append((m, mod_names[_parent(a)][parts[-1].lower()]))
        if not afiles:
            rel.skipped.append((a, bad or 'unknown layout'))
            continue
        kind, tids = _classify(afiles)
        home = _parent(a)
        stem = _basename(a).rsplit('.', 1)[0]
        options.append(Option(a, stem, kind, home, afiles, archive=a, tids=tids,
                              lang=detect_lang(stem) or detect_lang(_basename(home))))

    for o in options:
        if o.kind != 'mod':
            continue
        above = [x for x in options if x.kind == 'mod' and x is not o and (
            (x.home != o.home and _is_under(o.home, x.home)) or
            (x.home == o.home and x.archive is None and o.archive is not None))]
        if above:
            o.parent = max(above, key=lambda x: len(x.home)).key

    # an update in a mod's folder belongs to that mod and to the add-on mods in folders below it
    by_game: Dict[int, Game] = {}
    base_dirs = {_parent(pkg.path) for pkg in packages if pkg.kind == 'base'}
    mod_homes = {o.home for o in options if o.kind == 'mod'}
    for pkg in packages:
        if pkg.tid is None:
            rel.unknown.append(pkg.path)
            continue
        d = _parent(pkg.path)
        if pkg.kind == 'update' and d not in base_dirs and d in mod_homes:
            for o in options:
                if o.kind == 'mod' and _is_under(o.home, d):
                    o.updates.append(pkg)
            continue
        g = by_game.get(pkg.game_tid)
        if g is None:
            g = by_game[pkg.game_tid] = Game(pkg.game_tid, d)
        if pkg.kind == 'base':
            g.base = pkg
            g.root = d
        elif pkg.kind == 'update':
            g.updates.append(pkg)
        else:
            g.dlcs.append(pkg)
    # several archives in one mod folder: name them by file; a lone archive takes the folder name
    for o in options:
        if o.archive and o.home not in base_dirs and o.home and \
                sum(1 for x in options if x.home == o.home) == 1:
            o.name = _basename(o.home)
            o.lang = o.lang or detect_lang(o.name)

    games = sorted(by_game.values(), key=lambda g: (g.root, g.tid))
    for o in options:
        targets = [g for g in games if g.tid in o.tids] if o.kind == 'mod' else []
        if targets:
            for g in targets:
                g.options.append(_for_game(o, g, len(targets) > 1))
            continue
        near = _nearest(games, o.home)
        if near is None and o.kind == 'mod':
            # a mod-only release (the game is already on the console): one entry per title
            for tid in sorted(o.tids):
                g = Game(tid, o.home)
                games.append(g)
                g.options.append(_for_game(o, g, len(o.tids) > 1))
            continue
        if near is None:
            # files for several games in one folder (Donkey Kong Country 1-3): one option per
            # switch/<port>/ folder; MTP copies all of them, the dialog asks which
            rel.orphans.extend(_split_ports(o))
            continue
        if o.kind == 'mod':
            o.tid_mismatch = True
        near.options.append(o)

    for g in games:
        # copy order: untagged files first, then English, then other languages, then "Update" layers; mods, then add-ons last
        g.options.sort(key=lambda o: (o.kind == 'mod', o.parent is not None, bool(_UPDATE_WORD.search(o.name)),
                                      o.lang is not None, o.lang != 'en', KIND_ORDER[o.kind], o.key))
        g.updates.sort(key=lambda p: p.version)
    rel.games = games
    return rel


def _for_game(o: Option, g: Game, shared: bool) -> Option:
    """A mod for several games (one folder for Scarlet and Violet): keep this game's part."""
    if not shared:
        o.updates = [u for u in o.updates if u.game_tid == g.tid]
        return o
    other = {t for t in o.tids if t != g.tid}
    files = [(s, d) for s, d in o.files
             if not (_MOD_TID.match(d) and int(_MOD_TID.match(d).group(1), 16) in other)]
    return Option(o.key, o.name, o.kind, o.home, files, o.archive, {g.tid},
                  [u for u in o.updates if u.game_tid == g.tid], o.lang, parent=o.parent)


def _split_ports(o: Option) -> List[Option]:
    groups: Dict[str, List[Tuple[str, str]]] = {}
    for src, dst in o.files:
        parts = dst.split('/')
        top = '/'.join(parts[:2]) if parts[0].lower() == 'switch' and len(parts) > 2 else ''
        groups.setdefault(top, []).append((src, dst))
    if len(groups) < 2 or '' in groups:
        return [o]
    return [Option(f'{o.key}::{top}', top.split('/')[1], o.kind if any(d.lower().endswith('.nro') for _, d in f) else 'data',
                   o.home, f, o.archive, lang=o.lang, incomplete=o.incomplete)
            for top, f in sorted(groups.items())]


def _nearest(games: List[Game], home: str) -> Optional[Game]:
    """The game whose folder holds `home` most closely; None when two games tie."""
    best: List[Game] = []
    depth = -1
    for g in games:
        if _is_under(home, g.root):
            d = len(g.root.split('/')) if g.root else 0
            if d > depth:
                best, depth = [g], d
            elif d == depth:
                best.append(g)
    return best[0] if len(best) == 1 else None


def default_choice(game: Game, lang: str = 'en') -> Set[str]:
    """Option keys to install when nobody asks the user (MTP) and to pre-tick in the dialog.
    Ports and their files: every option without a language in its name ("Optional ..." left out),
    plus the ones in `lang`, else in English, else (when nothing untagged is there) the first
    language found (a port's only data must not be left out); an untagged option whose files
    the chosen language set writes in full is dropped. Mods: only when the game has exactly one
    and its title ID matches; add-ons stay off. Options still downloading are never chosen."""
    files = [o for o in game.options if o.kind != 'mod' and not o.incomplete]
    # port files named "... Mod" (Simpsons voice mods) are alternatives, like LayeredFS mods
    named = [o for o in files if _MOD_WORD.search(o.name)]
    files = [o for o in files if o not in named]
    untagged = [o for o in files if o.lang is None and 'optional' not in o.name.lower()]
    tagged = [o for o in files if o.lang is not None]
    pick = [o for o in tagged if o.lang == lang] or [o for o in tagged if o.lang == 'en']
    if not pick and tagged and not any(o.kind == 'data' for o in untagged):
        pick = [o for o in tagged if o.lang == tagged[0].lang]
    covered = {d.lower() for o in pick for _, d in o.files}
    chosen = {o.key for o in untagged
              if _UPDATE_WORD.search(o.name) or not (pick and {d.lower() for _, d in o.files} <= covered)}
    chosen.update(o.key for o in pick)
    langs = {lang, 'en', None} if not any(o.lang == lang for o in named) else {lang, None}
    if len(named) == 1 and named[0].lang in langs:
        chosen.add(named[0].key)
    mods = [o for o in game.options if o.kind == 'mod' and o.parent is None]
    if len(mods) == 1 and not mods[0].incomplete and not mods[0].tid_mismatch:
        chosen.add(mods[0].key)
    return chosen


def plan(game: Game, chosen: Set[str]) -> Plan:
    """What to install for `game` with the options in `chosen`."""
    picked = [o for o in game.options if o.key in chosen]
    conflicts = []
    mod_updates = {u.version: u for o in picked for u in o.updates}
    if len(mod_updates) > 1:
        names = ', '.join(o.name for o in picked if o.updates)
        conflicts.append(f'mods need different updates ({names}): choose one')
    for o in picked:
        if o.incomplete:
            conflicts.append(f'{o.name}: a file is still downloading')
        if o.tid_mismatch:
            conflicts.append(f'{o.name}: made for another title ID, confirm it')
        if o.parent and o.parent not in chosen:
            need = next((x.name for x in game.options if x.key == o.parent), o.parent)
            conflicts.append(f'{o.name}: an add-on, needs {need}')
    packages = [game.base] if game.base else []
    if mod_updates:
        packages.append(mod_updates[min(mod_updates)])
    elif game.updates:
        packages.append(game.updates[-1])
    packages += game.dlcs
    seen: Dict[str, int] = {}
    sd: List[Tuple[Option, str, str]] = []
    for o in picked:
        for src, dst in o.files:
            k = dst.lower()
            if k in seen:
                sd[seen[k]] = None  # a later option writes the same file
            seen[k] = len(sd)
            sd.append((o, src, dst))
    return Plan(packages, [x for x in sd if x is not None], conflicts)


# ---- disk side -------------------------------------------------------------

def find_7zip() -> Optional[str]:
    found = shutil.which('7z') or shutil.which('7za')
    if found:
        return found
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base and Path(base, '7-Zip', '7z.exe').is_file():
            return str(Path(base, '7-Zip', '7z.exe'))
    return None


def parse_7z_listing(text: str) -> List[str]:
    """File paths from `7z l -slt -ba` output; folders are left out."""
    out = []
    for block in text.replace('\r\n', '\n').split('\n\n'):
        rec = dict(line.split(' = ', 1) for line in block.split('\n') if ' = ' in line)
        path = rec.get('Path')
        if path and 'D' not in rec.get('Attributes', '') and rec.get('Folder') != '+':
            out.append(path)
    return out


def scan_path(path: Path, seven_zip: Optional[str] = None) -> Tuple[Path, Release]:
    """Analyse a dropped folder or archive. Returns (base folder, release); paths in
    the release are relative to the base folder."""
    path = Path(path)
    seven_zip = seven_zip or find_7zip()
    if path.is_dir():
        base = path
        paths = [str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()]
    else:
        base = path.parent
        paths = [path.name]

    def list_archive(rel: str) -> Optional[List[str]]:
        if not seven_zip:
            return None
        try:
            res = subprocess.run([seven_zip, 'l', '-slt', '-ba', '-sccUTF-8', str(base / rel)],
                                 capture_output=True, timeout=120,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            return None
        if res.returncode != 0:
            return None
        return parse_7z_listing(res.stdout.decode('utf-8', errors='replace'))

    return base, analyze(paths, list_archive)


def describe(release: Release, lang: str = 'en') -> str:
    """Human-readable summary (CLI and logs)."""
    lines = []
    for g in release.games:
        lines.append(f'{g.name} [{g.tid:016X}]  root: {g.root or "."}')
        if g.base:
            lines.append(f'  base     {g.base.name}')
        for u in g.updates:
            lines.append(f'  update   v{u.version >> 16} {u.name}')
        if g.dlcs:
            lines.append(f'  dlc      {len(g.dlcs)} file(s)')
        default = default_choice(g, lang)
        for o in g.options:
            mark = '*' if o.key in default else ' '
            extra = ''.join([f' [{o.lang}]' if o.lang else '',
                             ''.join(f' +update v{u.version >> 16}' for u in o.updates),
                             ' TID MISMATCH' if o.tid_mismatch else '',
                             ' INCOMPLETE' if o.incomplete else ''])
            lines.append(f'  {mark}{"addon" if o.parent else o.kind:<7} {o.name}  ({len(o.files)} files){extra}')
        p = plan(g, default)
        for c in p.conflicts:
            lines.append(f'  ! {c}')
    for o in release.orphans:
        lines.append(f'+ shared {o.kind} (any game of the release): {o.name}')
    for u in release.unknown:
        lines.append(f'? no title ID in the name: {u}')
    for path, why in release.skipped:
        lines.append(f'- skip {path}: {why}')
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    for arg in sys.argv[1:]:
        _, r = scan_path(Path(arg))
        print(f'== {arg}\n{describe(r, os.environ.get("HUB_LANG", "en"))}\n')
