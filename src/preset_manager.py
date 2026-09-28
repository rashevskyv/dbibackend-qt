"""
Preset and Batch File Operations for DBI Backend.
Handles saving and loading .dbi JSON presets and .bat batch export.
"""
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import Qt


class PresetManager:
    """Manages preset file loading/saving and batch script generation."""

    def __init__(self, main_window, file_manager):
        self.main_window = main_window
        self.file_manager = file_manager
        self.presets_dir = self._get_presets_directory()

    @staticmethod
    def _get_presets_directory() -> Path:
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys.executable).parent
        else:
            base_dir = Path(__file__).parent.parent
        if base_dir.name == 'src':
            base_dir = base_dir.parent
        presets_dir = base_dir / 'presets'
        presets_dir.mkdir(exist_ok=True)
        return presets_dir

    def save_file_list_as_batch(self):
        fm = self.file_manager
        if not fm.file_list:
            return
        path, _ = QFileDialog.getSaveFileName(self.main_window, "Batch", "", "Batch (*.bat)")
        if path:
            checked = [
                fm.file_list[it.text(1)]
                for it in fm.iter_checked_items()
                if it.text(1) in fm.file_list
            ]
            if not checked:
                QMessageBox.warning(self.main_window, "No Selection", "None checked.")
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('dbi_backend.exe -- files ^\n')
                    for p in checked:
                        f.write(f'"{p}" ^\n')
                self.main_window.log('success', f'Saved batch: {path}')
            except Exception as e:
                self.main_window.log('error', f'Error: {e}')

    def save_preset(self):
        fm = self.file_manager
        if not fm.file_list:
            return
        default_dir = self.main_window.config.get('last_preset_directory', str(self.presets_dir))
        path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save Preset", default_dir, "DBI Presets (*.dbi)"
        )
        if path:
            self.main_window.config.set('last_preset_directory', str(Path(path).parent))
            from .widgets import FILE_PATH_ROLE
            data = []
            for item in fm.iter_file_items():
                name = item.text(1)
                p_str = item.data(5, FILE_PATH_ROLE)
                if p_str:
                    data.append({
                        "name": name,
                        "path": p_str,
                        "checked": fm.is_item_checked(item),
                        "folder": str(fm.queue.files[Path(p_str)].folder_path) if fm.queue.files[Path(p_str)].folder_path else None,
                        "target": item.data(3, Qt.ItemDataRole.UserRole) or 0,
                    })
            blob = {
                "name": Path(path).stem,
                "created_at": datetime.now().isoformat(),
                "files": data
            }
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(blob, f, indent=2)
                self.main_window.update_presets_menu()
                self.main_window.log('success', f'Saved preset: {Path(path).name}')
            except Exception as e:
                self.main_window.log('error', f'Error: {e}')

    def load_preset(self, path: Optional[Path] = None):
        if not path:
            default_dir = self.main_window.config.get('last_preset_directory', str(self.presets_dir))
            s, _ = QFileDialog.getOpenFileName(
                self.main_window, "Load Preset", default_dir, "DBI Presets (*.dbi);;All Files (*)"
            )
            if s:
                path = Path(s)
                self.main_window.config.set('last_preset_directory', str(path.parent))
        if path and path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                raw_files = d["files"] if (isinstance(d, dict) and "files" in d and isinstance(d["files"], list)) else []
                fm = self.file_manager
                fm.clear_file_list()
                for entry in raw_files:
                    if not isinstance(entry, dict):
                        continue
                    raw_path = entry.get("path")
                    if not isinstance(raw_path, str) or not raw_path:
                        continue
                    p = Path(raw_path)
                    if not p.exists():
                        continue
                    p = p.resolve()
                    if p.is_dir():
                        fm.queue.add_folder_hierarchical(p, fm.queue.scan_folder(p))
                        continue
                    folder_value = entry.get("folder")
                    folder = Path(folder_value).resolve() if folder_value else None
                    if folder and folder.is_dir() and p.is_relative_to(folder):
                        fm.queue.add_folder_hierarchical(folder, [p])
                    else:
                        fm.queue.add_flat_files([p])
                    rec = fm.queue.files[p]
                    rec.checked = bool(entry.get("checked", True))
                    target = entry.get("target", 0)
                    rec.target = target if target in (0, 1, 2) else 0
                    fm.file_targets[rec.name] = rec.target
                fm.queue.recompute_conflicts()
                fm.update_file_list()
                fm.preset_loaded = True
                self.main_window.log('info', f'Loaded preset: {path.name}')
            except Exception as e:
                self.main_window.log('error', f'Error loading preset: {e}')

    def delete_preset(self):
        default_dir = self.main_window.config.get('last_preset_directory', str(self.presets_dir))
        s, _ = QFileDialog.getOpenFileName(
            self.main_window, "Delete", default_dir, "DBI Presets (*.dbi)"
        )
        if s:
            try:
                Path(s).unlink()
                self.main_window.update_presets_menu()
                self.main_window.log('info', f'Deleted: {Path(s).name}')
            except Exception as e:
                self.main_window.log('error', f'Error: {e}')
