"""
Releases in the queue: a dropped folder with ports, mods or language variants is analysed,
the user picks per game in ReleaseDialog, and the folder row holds the packages that choice
needs. The choice stays editable from the row until a package of it starts, and goes into presets.
"""
from pathlib import Path
from typing import Optional

import threading

from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtWidgets import QApplication, QInputDialog, QProgressDialog

from . import release_bundle
from . import release_choice as rc
from .release_analyzer import keep_parts, match_paths, scan_path, skip_for_preset
from .release_dialog import ReleaseDialog
from .dbi_protocol import TARGET_SD

ADDED, PLAIN, SKIP = 'added', 'plain', 'skip'


def ui_lang() -> str:
    """Default language for translations and port files: the PC's UI language."""
    return QLocale.system().name()[:2].lower() or 'en'


def _make_bundles(fm, rel, choice, folder: Path) -> list:
    """Building the bundles looks up every file of the chosen options, which takes seconds for
    thousands of files. Say so in the log and show a busy bar; keep the window alive meanwhile."""
    sd = rc.sd_file_count(rel, choice)
    if not sd:
        return release_bundle.bundles(rel, choice, folder)
    fm.main_window.log('info', f'Packing {sd} file(s) for the microSD...')
    box = QProgressDialog(f'Packing {sd} file(s) for the microSD...', None, 0, 0, fm.main_window)
    box.setWindowTitle('Packing')
    box.setWindowModality(Qt.WindowModality.WindowModal)
    box.setMinimumDuration(0)
    box.show()
    out = []
    worker = threading.Thread(target=lambda: out.append(release_bundle.bundles(rel, choice, folder)), daemon=True)
    worker.start()
    while worker.is_alive():
        QApplication.processEvents()
        worker.join(0.03)
    box.close()
    fm.main_window.log('info', 'Packing done.')
    return out[0] if out else []


def _apply(fm, folder: Path, rel, choice, source: Optional[dict] = None) -> None:
    q = fm.queue
    q.add_folder_hierarchical(folder, [])
    rec = q.folders[folder]
    rec.release, rec.choice = rel, choice
    if source:
        rec.source = source
    # a smart preset row is named after the game; its files live in the library folder
    base = Path(rec.source['path']) if rec.source else folder
    # packages first, so each game is on the console before its files reach the microSD
    bundles = _make_bundles(fm, rel, choice, base)
    q.set_folder_files(folder, rc.packages(rel, choice, base) + bundles)
    for b in bundles:   # the Hub books microSD space for them
        q.files[b].target = fm.file_targets[b.name] = TARGET_SD


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
        fm.main_window.log('info', f'{folder.name}: {sd} file(s) for the microSD ({rc.summary(rel, choice)}); '
                                   'USB only, Kefir Hub 0.14.100 or newer')
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


def add_game(fm, library: Path, game: str, saved: Optional[dict] = None,
             entry: Optional[dict] = None) -> Optional[Path]:
    """Smart preset entry {"path": library folder, "game": name}: every file of the game found
    in the library (see release_analyzer.match_paths). Several bases or repacks: ask which one;
    mods or translations: the release dialog. `saved` (a saved preset, resume) asks nothing.
    An entry saved by the app also holds "tid", "parts" and "prefer" (PresetManager._smart):
    it adds no mods and asks nothing while the saved files are still there. Returns the row key."""
    src = saved['_source'] if saved else (entry or {})
    skip = src.get('skip', []) if saved else None
    tid = int(src['tid'], 16) if isinstance(src.get('tid'), str) else None
    parts, prefer = src.get('parts'), src.get('prefer') or ()

    def select(paths):
        nonlocal skip
        paths = keep_parts(match_paths(paths, game, tid), parts)
        if skip is None:
            skip = skip_for_preset(paths, lambda title, names: _ask_base(fm, title, names), prefer)
            if skip is None:
                return []
        return [p for p in paths if p not in skip]

    try:
        base, rel = scan_path(library, select=select)
    except OSError as e:
        fm.main_window.log('warning', f'Could not search {library} for {game}: {e}')
        return None
    if skip is None:
        return None   # the user cancelled the base choice
    if not rel.games and not rel.unknown:
        fm.main_window.log('warning', f'Preset: nothing named "{game}" in {library}')
        return None
    if saved:
        choice = rc.from_preset(rel, saved, ui_lang())
    elif prefer:   # saved from plain package rows: no mods; the row action can add them
        choice = {tid: set() for tid in [g.tid for g in rel.games] + [rc.ORPHANS]}
    elif rc.is_smart(rel):
        mode, choice = ReleaseDialog.ask(rel, rc.defaults(rel, ui_lang()), game, fm.main_window, allow_plain=False)
        if mode is None:
            return None
    else:
        choice = rc.defaults(rel, ui_lang())
    key = (base / game).resolve()
    _apply(fm, key, rel, choice, {'path': str(base.resolve()), 'game': game, 'skip': sorted(skip),
                                  **{k: src[k] for k in ('tid', 'parts', 'prefer') if src.get(k)}})
    return key


def _ask_base(fm, title: str, names: list) -> Optional[int]:
    item, ok = QInputDialog.getItem(fm.main_window, 'Choose a base',
                                    f'{title}: several bases. Which one to install?', names, 0, False)
    return names.index(item) if ok else None


def to_preset(fm) -> dict:
    out = {}
    for p, r in fm.queue.folders.items():
        if r.release:
            out[str(p)] = rc.to_preset(r.choice)
            if r.source:   # rc.from_preset skips keys that are not title IDs
                out[str(p)]['_source'] = r.source
    return out


def restore(fm, data) -> None:
    """Re-analyse each saved release folder and apply its saved choice (preset load, resume)."""
    if not isinstance(data, dict):
        return
    for path_str, saved in data.items():
        source = saved.get('_source') if isinstance(saved, dict) else None
        if isinstance(source, dict) and Path(source.get('path', '')).is_dir() and source.get('game'):
            add_game(fm, Path(source['path']), source['game'], saved)
            continue
        folder = Path(path_str)
        if not folder.is_dir():
            continue
        try:
            base, rel = scan_path(folder)
        except OSError:
            continue
        if rc.is_smart(rel):
            _apply(fm, base.resolve(), rel, rc.from_preset(rel, saved, ui_lang()))
