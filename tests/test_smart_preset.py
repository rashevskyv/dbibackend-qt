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


def test_plain_save_smart_load(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication(sys.argv)
    lib = tmp_path / 'games'
    lib.mkdir()
    for n in LIB + ['Bayonetta [010076F0049A2000][v0].nsp', 'Bayonetta 2 [01007960049A0000][v0].nsp']:
        (lib / n).write_bytes(b'x' * 64)
    win = MainWindow()
    fm = win.file_manager
    saved = [LIB[0], LIB[1], LIB[3], LIB[5], 'Bayonetta [010076F0049A2000][v0].nsp']
    fm.ingest_paths([lib / n for n in saved])
    out = tmp_path / 's.dbi'
    monkeypatch.setattr('src.preset_manager.QFileDialog.getSaveFileName', lambda *a, **kw: (str(out), ''))
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *a: (_ for _ in ()).throw(AssertionError('asked')))
    fm.save_preset()
    assert [e['name'] for e in json.loads(out.read_text(encoding='utf-8'))['files']] == saved   # plain files

    win.config.set('smart_preset_load', False)
    fm.load_preset(out)
    assert queued(fm) == sorted(saved)

    # smart loading: the newest update and the other DLC join; Bayonetta 2 does not
    win.config.set('smart_preset_load', True)
    fm.load_preset(out)
    assert queued(fm) == sorted([LIB[0], LIB[2], LIB[3], LIB[4], LIB[5], 'Bayonetta [010076F0049A2000][v0].nsp'])

    # a repack appears: the saved clean base still wins, with its newest update
    (lib / 'Animal Crossing [01006F8002326000][v262144][UKR+REPACK].nsp').write_bytes(b'x' * 64)
    fm.load_preset(out)
    assert LIB[0] in queued(fm) and LIB[2] in queued(fm)

    # an unticked row loads that game as files
    fm.clear_file_list()
    fm.ingest_paths([lib / LIB[0], lib / LIB[1]])
    fm.queue.files[(lib / LIB[1]).resolve()].checked = False
    fm.update_file_list()
    fm.save_preset()
    fm.load_preset(out)
    assert queued(fm) == sorted([LIB[0], LIB[1]])
    win.config.set('smart_preset_load', False)


def test_only_update_saved_adds_no_base():
    assert match_paths(['B [0100A280121F6000][v0].nsp', 'B 2 [0100A280121F7000][v0].nsp'], 'B', 0x0100A280121F6000) \
        == ['B [0100A280121F6000][v0].nsp']
    from src.release_analyzer import keep_parts
    assert keep_parts(['G [0100A280121F6000][v0].nsp', 'G [0100A280121F6800][v65536].nsp', 'x.nsp'], ['update']) \
        == ['G [0100A280121F6800][v65536].nsp', 'x.nsp']
