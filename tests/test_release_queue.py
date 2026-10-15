"""A release folder through the real add pipeline, the queue row action and presets."""
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QFileDialog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main_window import MainWindow
from src.folder_dialog import FolderModeDialog
from src.release_dialog import ReleaseDialog
from src import release_queue

BASE = 'Game [0100B7C00933A000][v0].nsp'
UPD4 = 'Game [0100B7C00933A800][v262144].nsp'
UPD2 = 'Game [0100B7C00933A800][v131072].nsp'
TID = 0x0100B7C00933A000
MOD = 'Russian Translation'


def make_release(root: Path) -> Path:
    rel = root / 'Pikmin'
    for r in (BASE, UPD4, f'{MOD}/{UPD2}', f'{MOD}/atmosphere/contents/0100B7C00933A000/romfs/a.bin'):
        (rel / r).parent.mkdir(parents=True, exist_ok=True)
        (rel / r).write_bytes(b'x' * 64)
    return rel


def names(fm, folder):
    return [p.name for p in fm.queue.folders[folder.resolve()].files]


def test_release_add_edit_and_preset(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    folder = make_release(tmp_path)
    asked = []

    def fake_ask(rel, choice, title, parent=None, allow_plain=True):
        asked.append(allow_plain)
        return ReleaseDialog.SMART, choice

    monkeypatch.setattr(ReleaseDialog, 'ask', fake_ask)
    monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('old dialog')))
    fm.ingest_paths([folder])
    # one mod: ticked by default, so its update replaces the newer one; its files follow as one tar
    bundle = f'Game - {MOD}.kefir-sd.tar'
    assert names(fm, folder) == [BASE, UPD2, bundle]
    with fm.file_list[bundle].open('rb') as f:   # what the USB handler serves
        assert f.read(512)[:len('atmosphere/')] in (b'atmosphere/', b'./PaxHeade')
    assert fm.file_list[bundle].stat().st_size % 512 == 0
    assert fm.file_targets[bundle] == 1   # SD card

    assert release_queue.can_edit(fm, folder.resolve())
    monkeypatch.setattr(ReleaseDialog, 'ask', lambda rel, choice, *a, **kw: (ReleaseDialog.SMART, {TID: set(), 0: set()}))
    release_queue.edit(fm, folder.resolve())
    assert names(fm, folder) == [BASE, UPD4]
    assert set(fm.file_list) == {BASE, UPD4}   # the tree and the transfer list follow

    preset = tmp_path / 'p.dbi'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(preset), ''))
    fm.save_preset()
    fm.clear_file_list()
    fm.load_preset(preset)
    assert names(fm, folder) == [BASE, UPD4]
    assert fm.queue.folders[folder.resolve()].choice[TID] == set()
    assert asked == [True]


def test_plain_folder_and_only_packages_use_the_old_path(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    fm = win.file_manager
    plain = tmp_path / 'plain'
    plain.mkdir()
    (plain / BASE).write_bytes(b'x')
    folder = make_release(tmp_path)
    monkeypatch.setattr(FolderModeDialog, 'ask_mode', lambda *a, **kw: (FolderModeDialog.MODE_FOLDER, False))
    monkeypatch.setattr(ReleaseDialog, 'ask', lambda rel, choice, *a, **kw: (ReleaseDialog.PLAIN, choice))
    fm.ingest_paths([plain, folder])
    assert names(fm, plain) == [BASE]
    assert sorted(names(fm, folder)) == sorted([BASE, UPD4, UPD2])   # every package, as before
    assert fm.queue.folders[folder.resolve()].release is None

    monkeypatch.setattr(ReleaseDialog, 'ask', lambda *a, **kw: (None, {}))
    fm.clear_file_list()
    fm.ingest_paths([folder])
    assert folder.resolve() not in fm.queue.folders
