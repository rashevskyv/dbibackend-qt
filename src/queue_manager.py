"""
Queue Data Model and Conflict Resolution for DBI Backend.
Tracks folders, files, selections, and detects duplicate base name collisions.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


SUPPORTED_EXTENSIONS = {'.nsp', '.nsz', '.xci', '.xcz'}

# Status codes
STATUS_QUEUED = 0
STATUS_PROCESS = 1
STATUS_DONE = 2
STATUS_FAILED = 3
STATUS_SKIPPED = 4
STATUS_MISSING = 5
STATUS_CONFLICT = 6


@dataclass
class FileRecord:
    path: Path
    name: str
    size: int
    folder_path: Optional[Path] = None
    target: int = 0
    checked: bool = True
    status: str = "Queued"
    status_code: int = STATUS_QUEUED
    in_conflict: bool = False


@dataclass
class FolderRecord:
    path: Path
    name: str
    files: List[Path] = field(default_factory=list)
    target: int = 0
    checked: bool = True
    status: str = "Queued"
    status_code: int = STATUS_QUEUED

class QueueManager:
    """Manages queue state, folder hierarchy, explicit ordering, and name collision detection."""

    def __init__(self):
        self.folders: Dict[Path, FolderRecord] = {}
        self.files: Dict[Path, FileRecord] = {}
        self.conflicts: Set[str] = set()
        self.order: List[Path] = []

    @staticmethod
    def scan_folder(folder_path: Path, supported_exts: Optional[Set[str]] = None) -> List[Path]:
        """Recursively scan a directory for supported Switch package files."""
        if supported_exts is None:
            supported_exts = SUPPORTED_EXTENSIONS
        found = []
        try:
            for item in folder_path.rglob('*'):
                if item.is_file() and item.suffix.lower() in supported_exts:
                    found.append(item.resolve())
        except Exception:
            pass
        return sorted(found, key=lambda p: p.name.lower())

    def add_flat_files(self, paths: List[Path]) -> int:
        """Add individual files directly as top-level queue entries."""
        added = 0
        for p in paths:
            res = p.resolve()
            if res in self.files:
                continue
            try:
                size = res.stat().st_size if res.exists() else 0
            except Exception:
                size = 0
            rec = FileRecord(path=res, name=res.name, size=size, folder_path=None)
            self.files[res] = rec
            if res not in self.order:
                self.order.append(res)
            added += 1
        return added

    def add_folder_hierarchical(self, folder_path: Path, child_paths: List[Path]) -> int:
        """Add a folder and its child files as a hierarchical queue entry."""
        folder_res = folder_path.resolve()
        if folder_res not in self.folders:
            self.folders[folder_res] = FolderRecord(path=folder_res, name=folder_res.name)
        if folder_res not in self.order:
            self.order.append(folder_res)

        folder_rec = self.folders[folder_res]
        added = 0
        for cp in child_paths:
            c_res = cp.resolve()
            existing = self.files.get(c_res)
            if existing and existing.folder_path not in (None, folder_res):
                continue
            if c_res not in folder_rec.files:
                folder_rec.files.append(c_res)
            if existing:
                existing.folder_path = folder_res
            else:
                try:
                    size = c_res.stat().st_size if c_res.exists() else 0
                except Exception:
                    size = 0
                rec = FileRecord(path=c_res, name=c_res.name, size=size, folder_path=folder_res)
                self.files[c_res] = rec
                added += 1
        return added

    def remove_path(self, path: Path):
        """Remove a file or folder (and its child files) from the queue."""
        res = path.resolve()
        if res in self.order:
            self.order.remove(res)
        if res in self.folders:
            folder_rec = self.folders.pop(res)
            for cp in folder_rec.files:
                self.files.pop(cp, None)
        elif res in self.files:
            file_rec = self.files.pop(res)
            if file_rec.folder_path and file_rec.folder_path in self.folders:
                folder_rec = self.folders[file_rec.folder_path]
                if res in folder_rec.files:
                    folder_rec.files.remove(res)
                if not folder_rec.files:
                    self.folders.pop(file_rec.folder_path, None)
                    if file_rec.folder_path in self.order:
                        self.order.remove(file_rec.folder_path)

    def move_item(self, path: Path, delta: int) -> bool:
        """Move an item one position, respecting the active/completed prefix."""
        res = path.resolve()
        if res in self.order:
            idx = self.order.index(res)
            return self.reorder_top_level(idx, idx + delta)

        rec = self.files.get(res)
        if rec and rec.folder_path and rec.folder_path in self.folders:
            frec = self.folders[rec.folder_path]
            if res in frec.files:
                idx = frec.files.index(res)
                return self.reorder_child(rec.folder_path, idx, idx + delta)
        return False

    def recompute_conflicts(self) -> Set[str]:
        """
        Detect base name collisions across all active files in the queue.
        Marks conflicting files and returns the set of conflicting file names.
        """
        name_to_paths: Dict[str, Set[Path]] = {}
        for path, rec in self.files.items():
            name_to_paths.setdefault(rec.name, set()).add(path)

        new_conflicts = {name for name, paths in name_to_paths.items() if len(paths) > 1}
        self.conflicts = new_conflicts

        for path, rec in self.files.items():
            if rec.name in new_conflicts:
                rec.in_conflict = True
            else:
                if rec.in_conflict:
                    rec.in_conflict = False

        return self.conflicts

    def get_transfer_file_list(self) -> Dict[str, Path]:
        """
        Returns an ordered mapping of {name: path} for all valid, non-conflicting files.
        Order strictly follows self.order and folder hierarchy.
        Conflicting / ambiguous files are strictly excluded from transfer.
        """
        result: Dict[str, Path] = {}
        for p in self.order:
            if p in self.folders:
                folder_rec = self.folders[p]
                for cp in folder_rec.files:
                    rec = self.files.get(cp)
                    if rec and not rec.in_conflict and rec.path.exists():
                        result[rec.name] = rec.path
            elif p in self.files:
                rec = self.files[p]
                if rec.folder_path is None and not rec.in_conflict and rec.path.exists():
                    result[rec.name] = rec.path

        for rec in self.files.values():
            if rec.name not in result and not rec.in_conflict and rec.path.exists():
                result[rec.name] = rec.path

        return result

    def get_checked_file_list(self) -> Dict[str, Path]:
        """
        Returns an ordered mapping of {name: path} for checked, non-conflicting files.
        Order strictly follows self.order and folder hierarchy.
        """
        result: Dict[str, Path] = {}
        for p in self.order:
            if p in self.folders:
                folder_rec = self.folders[p]
                for cp in folder_rec.files:
                    rec = self.files.get(cp)
                    if rec and rec.checked and not rec.in_conflict and rec.path.exists():
                        result[rec.name] = rec.path
            elif p in self.files:
                rec = self.files[p]
                if rec.folder_path is None and rec.checked and not rec.in_conflict and rec.path.exists():
                    result[rec.name] = rec.path

        for rec in self.files.values():
            if rec.checked and rec.name not in result and not rec.in_conflict and rec.path.exists():
                result[rec.name] = rec.path

        return result

    def clear(self):
        """Clear all folders and files from the queue."""
        self.folders.clear()
        self.files.clear()
        self.conflicts.clear()
        self.order.clear()

    def _is_active_or_done(self, p: Path) -> bool:
        if p in self.files:
            return self.files[p].status_code in (STATUS_PROCESS, STATUS_DONE)
        if p in self.folders:
            folder_rec = self.folders[p]
            return any(
                self.files.get(cp) and self.files[cp].status_code in (STATUS_PROCESS, STATUS_DONE)
                for cp in folder_rec.files
            )
        return False

    def _file_active_or_done(self, p: Path) -> bool:
        rec = self.files.get(p)
        return bool(rec and rec.status_code in (STATUS_PROCESS, STATUS_DONE))

    @staticmethod
    def _frozen_len(seq, is_frozen) -> int:
        """Rows up to the last installing or installed one; nothing is moved into them."""
        return max((k + 1 for k, p in enumerate(seq) if is_frozen(p)), default=0)

    @classmethod
    def _can_move(cls, seq, from_idx: int, to_idx: int, is_frozen) -> bool:
        """A row that is not installing or installed may leave the frozen prefix (a failed
        or skipped game sitting between finished ones) but only to land after it."""
        if is_frozen(seq[from_idx]):
            return False
        frozen = cls._frozen_len(seq, is_frozen)
        if from_idx < frozen:
            frozen -= 1  # the prefix is one row shorter once this row is out of it
        return to_idx >= frozen

    @classmethod
    def _to_next(cls, seq: list, chosen: List[Path], is_frozen) -> bool:
        """Put the chosen rows (queue order kept) right after the frozen prefix."""
        chosen_set = set(chosen)
        movable = [p for p in seq if p in chosen_set and not is_frozen(p)]
        if not movable:
            return False
        rest = [p for p in seq if p not in set(movable)]
        frozen = cls._frozen_len(rest, is_frozen)
        new = rest[:frozen] + movable + rest[frozen:]
        if new == seq:
            return False
        seq[:] = new
        return True

    def reorder_top_level(self, from_idx: int, to_idx: int) -> bool:
        n = len(self.order)
        if from_idx < 0 or from_idx >= n or to_idx < 0 or to_idx >= n:
            return False
        if from_idx == to_idx:
            return False
        if not self._can_move(self.order, from_idx, to_idx, self._is_active_or_done):
            return False
        item = self.order.pop(from_idx)
        self.order.insert(to_idx, item)
        return True

    def reorder_child(self, folder_path: Path, from_idx: int, to_idx: int) -> bool:
        folder = self.folders.get(folder_path.resolve())
        if not folder:
            return False
        files = folder.files
        n = len(files)
        if from_idx < 0 or from_idx >= n or to_idx < 0 or to_idx >= n:
            return False
        if from_idx == to_idx:
            return False
        if not self._can_move(files, from_idx, to_idx, self._file_active_or_done):
            return False
        item = files.pop(from_idx)
        files.insert(to_idx, item)
        return True

    def move_top_level_to_next(self, paths: List[Path]) -> bool:
        """Move specified top-level items to immediately follow active/completed items."""
        return self._to_next(self.order, [p.resolve() for p in paths], self._is_active_or_done)

    def move_child_items_to_next(self, folder_path: Path, child_paths: List[Path]) -> bool:
        """Move specified child items in a folder to immediately follow active/completed items in that folder."""
        folder = self.folders.get(folder_path.resolve())
        if not folder:
            return False
        return self._to_next(folder.files, [p.resolve() for p in child_paths], self._file_active_or_done)

    def reorder_dragged_path(
        self,
        src_path: Path,
        is_child: bool,
        parent_path: Optional[Path],
        tgt_path: Optional[Path],
        after: bool = False
    ) -> bool:
        if is_child:
            if not parent_path or not tgt_path:
                return False
            folder = self.folders.get(parent_path.resolve())
            if not folder:
                return False
            src_res = src_path.resolve()
            tgt_res = tgt_path.resolve()
            if src_res not in folder.files or tgt_res not in folder.files:
                return False
            from_idx = folder.files.index(src_res)
            target_pos = folder.files.index(tgt_res)
            insert_pos = target_pos + 1 if after else target_pos
            if from_idx < insert_pos:
                insert_pos -= 1
            return self.reorder_child(parent_path, from_idx, insert_pos)
        else:
            src_res = src_path.resolve()
            if src_res not in self.order:
                return False
            from_idx = self.order.index(src_res)
            if tgt_path is None:
                insert_pos = len(self.order) - 1
            else:
                tgt_res = tgt_path.resolve()
                if tgt_res not in self.order:
                    return False
                target_pos = self.order.index(tgt_res)
                insert_pos = target_pos + 1 if after else target_pos
                if from_idx < insert_pos:
                    insert_pos -= 1
            return self.reorder_top_level(from_idx, insert_pos)
