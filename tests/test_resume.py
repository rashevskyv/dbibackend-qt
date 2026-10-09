"""Resume after a crash: the live queue is mirrored to resume.dbi; installed rows drop out."""
import sys
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main_window import MainWindow
from src.preset_manager import PresetManager


def test_autosave_keeps_only_unfinished_files(monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        monkeypatch.setattr(PresetManager, 'resume_path', property(lambda s: tmp / 'resume.dbi'))
        win = MainWindow()
        fm, pm = win.file_manager, win.file_manager.preset_manager
        files = []
        for i in range(3):
            p = tmp / f'game_{i}.nsp'
            p.write_bytes(b'X' * 512)
            files.append(p)
        fm.ingest_paths(files)

        win.server_manager.session.on_transfer_complete('game_0.nsp')  # installed -> unchecked
        pm.autosave()
        assert pm.pending_resume_count() == 2

        files[2].unlink()  # moved away overnight: nothing to resume for it
        assert pm.pending_resume_count() == 1

        fm.clear_file_list()
        pm.load_preset(pm.resume_path)
        checked = {it.text(1) for it in fm.iter_checked_items()}
        assert checked == {'game_1.nsp'}
        assert 'game_0.nsp' in fm.file_list  # kept, but not queued again
