"""
What the user chose from an analysed release: option keys per game.
Qt-free so it can be tested; the dialog (release_dialog.py) is a view over it.
Orphan options (shared by every game of the release) are kept under the key 0.
"""
from pathlib import Path
from typing import Dict, List, Optional, Set

from .release_analyzer import Option, Release, default_choice, plan

Choice = Dict[int, Set[str]]
ORPHANS = 0


def is_smart(rel: Release) -> bool:
    """True when the release has anything besides packages (ports, data, mods)."""
    return bool(rel.orphans) or any(g.options for g in rel.games)


def defaults(rel: Release, lang: str = 'en') -> Choice:
    choice = {g.tid: default_choice(g, lang) for g in rel.games}
    # shared ports (Donkey Kong Country: one switch/ for three stubs): all of them, the dialog lets the user untick
    choice[ORPHANS] = {o.key for o in rel.orphans if o.kind != 'mod' and not o.incomplete}
    return choice


def options(rel: Release, tid: int) -> List[Option]:
    if tid == ORPHANS:
        return rel.orphans
    return next((g.options for g in rel.games if g.tid == tid), [])


def toggle(rel: Release, choice: Choice, tid: int, key: str, on: bool) -> None:
    """Tick or untick one option. An add-on pulls its mod in; unticking a mod drops its add-ons."""
    chosen = choice.setdefault(tid, set())
    opts = options(rel, tid)
    if on:
        chosen.add(key)
        opt = next((o for o in opts if o.key == key), None)
        if opt and opt.parent:
            chosen.add(opt.parent)
    else:
        chosen.discard(key)
        chosen.difference_update(o.key for o in opts if o.parent == key)


def packages(rel: Release, choice: Choice, base: Path) -> List[Path]:
    """Packages to queue, in install order: per game base, the update the chosen mods need, DLC;
    then packages without a title ID in the name (the console reads their header)."""
    out: List[Path] = []
    for g in rel.games:
        out += [base / p.path for p in plan(g, choice.get(g.tid, set())).packages]
    out += [base / u for u in rel.unknown]
    seen: Set[Path] = set()
    return [p for p in out if p.is_file() and not (p in seen or seen.add(p))]


def sd_file_count(rel: Release, choice: Choice) -> int:
    n = sum(len(plan(g, choice.get(g.tid, set())).sd_files) for g in rel.games)
    return n + sum(len(o.files) for o in rel.orphans if o.key in choice.get(ORPHANS, set()))


def conflicts(rel: Release, choice: Choice) -> List[str]:
    out = []
    for g in rel.games:
        out += [f'{g.name}: {c}' for c in plan(g, choice.get(g.tid, set())).conflicts]
    return out


def summary(rel: Release, choice: Choice) -> str:
    """Short text for the queue row, e.g. 'port, mod: Russian translation'."""
    names = [o.name for g in rel.games for o in g.options if o.key in choice.get(g.tid, set())]
    names += [o.name for o in rel.orphans if o.key in choice.get(ORPHANS, set())]
    return ', '.join(names)


def to_preset(choice: Choice) -> Dict[str, List[str]]:
    return {f'{tid:016X}': sorted(keys) for tid, keys in choice.items()}


def from_preset(rel: Release, data: Optional[dict], lang: str = 'en') -> Choice:
    """Choice saved in a preset; keys no longer in the release are dropped. Option keys are paths
    relative to the release folder, so they hold while the folder keeps its layout."""
    choice = defaults(rel, lang)
    if not isinstance(data, dict):
        return choice
    for tid_hex, keys in data.items():
        try:
            tid = int(tid_hex, 16)
        except (TypeError, ValueError):
            continue
        known = {o.key for o in options(rel, tid)}
        if tid in choice and isinstance(keys, list):
            choice[tid] = {k for k in keys if k in known}
    return choice
