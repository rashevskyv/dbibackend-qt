"""
Progress Tracker for DBI Backend
"""
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional

class ProgressTracker:
    """Tracks file transfer progress, including intervals."""

    def __init__(self, file_list: Dict[str, Path], initial_checked: Optional[Set[str]] = None):
        self.file_list = file_list
        self.initial_checked = initial_checked
        self.file_intervals: Dict[str, List[Tuple[int, int]]] = {name: [] for name in file_list.keys()}
        self.unique_bytes_transferred = 0
        self.total_requested_size = 0
        self.requested_files: Set[str] = set()
        self.completed_files_set: Set[str] = set()
        self.file_sizes: Dict[str, int] = {}
        self.completed_files = 0
        self.total_files = len(file_list)
        self.file_bytes_sent: Dict[str, int] = {name: 0 for name in file_list.keys()}
        self.skipped_files: Set[str] = set()
        
        self._preinit_totals()

    @property
    def transferred_bytes(self) -> int:
        return self.unique_bytes_transferred

    @transferred_bytes.setter
    def transferred_bytes(self, value: int):
        self.unique_bytes_transferred = value

    def _preinit_totals(self):
        """Pre-initialize with all files in the batch for 'Overall' progress consistency.

        Directory entries are skipped: their stat() size is meaningless, and the
        files inside them register individually (with real sizes) as the client
        requests them.
        """
        for name, path in self.file_list.items():
            try:
                if path.is_dir():
                    continue
            except OSError:
                continue
            if self.initial_checked is not None and name not in self.initial_checked:
                continue
            self.requested_files.add(name)
            self.total_requested_size += self.get_file_size(name)

    def get_file_size(self, filename: str) -> int:
        """Get file size lazily (calculate only when needed)"""
        if filename not in self.file_sizes:
            try:
                file_path = self.file_list[filename]
                size = file_path.stat().st_size
                self.file_sizes[filename] = size
                return size
            except Exception:
                self.file_sizes[filename] = 0
                return 0
        return self.file_sizes[filename]

    def add_interval(self, filename: str, start: int, end: int) -> int:
        """Add a transferred interval and merge overlapping intervals."""
        if filename not in self.file_intervals:
            self.file_intervals[filename] = []

        intervals = self.file_intervals[filename]
        
        # Calculate unique bytes for THIS file before adding new interval
        # We need merged intervals to know how many unique bytes we have
        def get_merged_size(ivs):
            if not ivs: return 0, []
            # Note: ivs must be sorted
            m = []
            for s, e in ivs:
                if m and s <= m[-1][1]:
                    m[-1] = (m[-1][0], max(m[-1][1], e))
                else:
                    m.append((s, e))
            return sum(e - s for s, e in m), m

        old_file_unique, _ = get_merged_size(intervals)
        
        intervals.append((start, end))
        intervals.sort()

        new_file_unique, merged = get_merged_size(intervals)
        self.file_intervals[filename] = merged
        
        # Update global total incrementally
        delta = new_file_unique - old_file_unique
        if delta > 0:
            self.unique_bytes_transferred += delta
            self.file_bytes_sent[filename] = new_file_unique

        return new_file_unique

    def register_file_request(self, filename: str, file_size: int = None):
        # Files served from inside folders are absent from file_list, so their
        # size must be supplied by the caller — get_file_size() alone would
        # cache 0 and the file would never count toward the overall total.
        if file_size is not None and self.file_sizes.get(filename, 0) == 0:
            self.file_sizes[filename] = file_size
        if filename not in self.requested_files:
            self.requested_files.add(filename)
            self.total_requested_size += self.get_file_size(filename)

    def mark_file_skipped(self, filename: str):
        if filename in self.requested_files and filename not in self.skipped_files:
            self.skipped_files.add(filename)
            # Subtract only the remaining part of the file from total size
            # If 30% was transferred, we subtract the 70% that won't be sent.
            bytes_sent = self.file_bytes_sent.get(filename, 0)
            file_size = self.get_file_size(filename)
            old_size = self.total_requested_size
            # Guard against a stale 0 size (bytes_sent > file_size would
            # otherwise inflate the total instead of shrinking it).
            self.total_requested_size -= max(0, file_size - bytes_sent)
            from .utility_functions import format_size
            print(f"[DEBUG] Progress Recalculation: Skipped {filename} ({format_size(file_size)}). Total: {format_size(old_size)} -> {format_size(self.total_requested_size)}")
        else:
            if filename in self.skipped_files:
                pass # Already handled
            else:
                print(f"[DEBUG] Tracker: Skipped {filename} was not in requested_files list.")

    def unmark_file_skipped(self, filename: str):
        """Restore a previously skipped file back into active calculation."""
        if filename in self.skipped_files:
            self.skipped_files.remove(filename)
            bytes_sent = self.file_bytes_sent.get(filename, 0)
            file_size = self.get_file_size(filename)
            self.total_requested_size += max(0, file_size - bytes_sent)
            from .utility_functions import format_size
            print(f"[DEBUG] Progress Recalculation: Unskipped {filename} (+{format_size(file_size - bytes_sent)}). Total: {format_size(self.total_requested_size)}")

    def unmark_file_completed(self, filename: str):
        """Remove a file from completed set so a retry can complete again."""
        self.completed_files_set.discard(filename)

    def add_file(self, filename: str, path: Path, is_checked: bool = True):
        """Register a newly added file into tracking structures."""
        self.file_list[filename] = path
        if filename not in self.file_intervals:
            self.file_intervals[filename] = []
        if filename not in self.file_bytes_sent:
            self.file_bytes_sent[filename] = 0
        if is_checked and filename not in self.requested_files:
            self.register_file_request(filename)

    def reset(self):
        """Reset all transfer-related state."""
        self.unique_bytes_transferred = 0
        self.total_requested_size = 0
        self.requested_files = set()
        self.completed_files_set = set()
        self.completed_files = 0
        self.file_bytes_sent = {name: 0 for name in self.file_list.keys()}
        self.skipped_files = set()
        self.file_intervals = {name: [] for name in self.file_list.keys()}

        self._preinit_totals()
