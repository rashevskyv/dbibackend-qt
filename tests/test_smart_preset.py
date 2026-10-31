"""Smart preset entry {"path": library, "game": name}: one game's files out of a library folder."""
import json
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QInputDialog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main_window import MainWindow
from src.release_analyzer import match_paths, skip_for_preset

LIB = ['Animal Crossing New Horizons [01006F8002326000][v0].nsp',
       'Animal Crossing New Horizons [01006F8002326800][v131072].nsp',
       'Animal Crossing New Horizons [01006F8002326800][v262144].nsp',
       'Animal Crossing NH Happy Home Paradise [01006F8002327001][v0].nsp',
       'Pocket Camp DLC [01006F8002327002][v0].nsp',   # other name, same game by title ID
       'Animal Well [010020D01AD24000][v0].nsp']


def queued(fm):
    return sorted(p.name for p in fm.queue.files)


def test_match_paths():
    assert sorted(match_paths(LIB, 'animal-crossing')) == sorted(LIB[:5])


def test_tagged_update_is_asked():
    upd = ['G [0100A280121F6000][v0].nsp', 'G [0100A280121F6800][v131072].nsp', 'G [0100A280121F6800][v65536][UKR].nsp']
    asked = []
    assert skip_for_preset(upd, lambda t, names: asked.append(names) or names.index(upd[2])) == [upd[1]]
    assert len(asked) == 1 and len(asked[0]) == 2
    # "Rush" in a title is no Russian tag: newest update, nobody asked
    rush = ['Kingdom Rush [0100A280121F6800][v65536].nsp', 'Kingdom Rush [0100A280121F6800][v131072].nsp']
    assert skip_for_preset(rush, lambda *a: 1 / 0) == []


def test_smart_preset_newest_update_repack_and_resume(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication(sys.argv)
    lib = tmp_path / 'games'
    lib.mkdir()
    for n in LIB:
        (lib / n).write_bytes(b'x' * 64)
    preset = tmp_path / 'p.dbi'
    preset.write_text(json.dumps({'files': [{'path': str(lib), 'game': 'Animal Crossing'}]}), encoding='utf-8')
    win = MainWindow()
    fm = win.file_manager

    fm.load_preset(preset)
    assert queued(fm) == sorted([LIB[0], LIB[2], LIB[3], LIB[4]])   # base, newest update, both DLC

    # two repacks: the user picks one; it replaces the base and the updates, and the DLC it names
    for n in ('Animal Crossing [01006F8002326000][v262144][UKR+REPACK].nsp',
              'Animal Crossing [01006F8002326000][RePack + U + 3DLC].nsz'):
        (lib / n).write_bytes(b'x' * 64)
    asked = []
    monkeypatch.setattr(QInputDialog, 'getItem', lambda parent, t, label, names, *a: (asked.append(names), (names[1], True))[1])
    fm.load_preset(preset)
    assert len(asked[0]) == 2
    picked = asked[0][1]
    assert queued(fm) == ([picked] if 'DLC' in picked else sorted([picked, LIB[3], LIB[4]]))

    # resume keeps that pick and asks nothing, and does not pull the whole library
    pm = fm.preset_manager
    monkeypatch.setattr(type(pm), 'resume_path', property(lambda self: tmp_path / 'resume.dbi'))
    before = queued(fm)
    pm.autosave()
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *a: (_ for _ in ()).throw(AssertionError('asked again')))
    fm.load_preset(pm.resume_path)
    assert queued(fm) == before
    assert len(fm.queue.folders) == 1 and not [p for p in fm.queue.order if p in fm.queue.files]
