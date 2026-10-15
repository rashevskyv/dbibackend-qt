"""
Releases in the queue: a dropped folder with ports, mods or language variants is analysed,
the user picks per game in ReleaseDialog, and the folder row holds the packages that choice
needs. The choice stays editable from the row until a package of it starts, and goes into presets.
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QLocale

from . import release_choice as rc
from .release_analyzer import scan_path
from .release_dialog import ReleaseDialog

ADDED, PLAIN, SKIP = 'added', 'plain', 'skip'


def ui_lang() -> str:
    """Default language for translations and port files: the PC's UI language."""
    return QLocale.system().name()[:2].lower() or 'en'


def _apply(fm, folder: Path, rel, choice) -> None:
    q = fm.queue
    q.add_folder_hierarchical(folder, [])
    rec = q.folders[folder]
    rec.release, rec.choice = rel, choice
    q.set_folder_files(folder, rc.packages(rel, choice, folder))


def offer(fm, folder: Path) -> Optional[str]:
    """Called for every dropped folder. None: a plain package folder, add it the old way."""
    try:
        base, rel = scan_path(folder)
    except OSError as e:
        fm.main_window.log('warning', f'Could not analyse {folder.name}: {e}')
        return None
    if not rc.is_smart(rel):
        return None
    mode, choice = ReleaseDialog.ask(rel, rc.defaults(rel, ui_lang()), folder.name, fm.main_window)
    if mode is None:
        return SKIP
    if mode == ReleaseDialog.PLAIN:
        return PLAIN
    _apply(fm, base.resolve(), rel, choice)
    sd = rc.sd_file_count(rel, choice)
    if sd:
        fm.main_window.log('info', f'{folder.name}: {sd} file(s) for the microSD ({rc.summary(rel, choice)})')
    return ADDED


def can_edit(fm, folder: Path) -> bool:
    rec = fm.queue.folders.get(folder)
    return bool(rec and rec.release) and not fm.queue._is_active_or_done(folder)


def edit(fm, folder: Path) -> None:
    """Queue row action: change what to install until the game starts."""
    if not can_edit(fm, folder):
        return
    rec = fm.queue.folders[folder]
    mode, choice = ReleaseDialog.ask(rec.release, rec.choice, folder.name, fm.main_window, allow_plain=False)
    if mode is None:
        return
    _apply(fm, folder, rec.release, choice)
    fm.queue.recompute_conflicts()
    fm.update_file_list()


def to_preset(fm) -> dict:
    return {str(p): rc.to_preset(r.choice) for p, r in fm.queue.folders.items() if r.release}


def restore(fm, data) -> None:
    """Re-analyse each saved release folder and apply its saved choice (preset load, resume)."""
    if not isinstance(data, dict):
        return
    for path_str, saved in data.items():
        folder = Path(path_str)
        if not folder.is_dir():
            continue
        try:
            base, rel = scan_path(folder)
        except OSError:
            continue
        if rc.is_smart(rel):
            _apply(fm, base.resolve(), rel, rc.from_preset(rel, saved, ui_lang()))
