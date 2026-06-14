# Audit & Refactoring Plan — DBI Backend Qt

> **Project version:** v2.4.9
> **Date:** 14 June 2026
> **Scope:** ~3 000 lines of Python, 18 files/modules, built on PyQt6 + PyUSB.
> **Audit status:** All bugs from the audit have been successfully **fixed** and committed.

---

## 1. Architecture Overview

The project is a modern GUI wrapper for Nintendo Switch file transfer over the DBI protocol. Architecture:

* **UI layer:** PyQt6 — `main.py`, `src/main_window.py`, `src/ui_manager.py`, `src/widgets.py`, styled via `src/theme_manager.py`.
* **File management:** `src/file_operations.py` (`FileManager`).
* **Communication threads:**
  * `USBHandler` (`QThread`) in `src/usb_handler.py` — blocking USB I/O via PyUSB.
  * `HTTPHandler` (`QThread`) in `src/http_handler.py` — runs `ThreadingHTTPServer`.
* **Shared state:**
  * `ProgressTracker` in `src/progress_tracker.py` — speed, ETA, interval merging.
  * `ConfigManager` in `src/config_manager.py` — JSON persistence.
  * `SingleInstanceManager` in `src/single_instance.py` — Named Pipe server, Send-to integration.

---

## 2. Critical Issues 🔴

### 🔴 BUG-01 — Thread-safety race in HTTP file cache (`http_request_handler.py`)

**Status:** ✅ Fixed (v2.4.1)

* **Problem:** `cache_lock` only protects the handle swap (lines 167–174). `f.seek(start)` and the `f.read()` loop (lines 177–196) run **outside the lock**. `ThreadingHTTPServer` spawns one thread per request, so two concurrent range requests can call `seek()` on the same file object simultaneously.
* **Consequences:**
  1. Interleaved `seek()` calls corrupt the read pointer → **silent data corruption** during installation.
  2. If a second thread swaps the cached handle for a different file, the first thread gets `ValueError: I/O operation on closed file`, aborting the transfer.
* **Fix:** Each request handler must own its private file descriptor. Either open a new handle per-request inside `send_file_content`, or use `threading.local()` caching so each OS thread holds its own handle.

---

### 🔴 BUG-02 — UI freezes in "Server Running" state after thread crash (`server_operations.py`)

**Status:** ✅ Fixed (v2.4.2)

* **Problem:**
  1. `start_http_server()` never connects `http_handler.finished` to a UI-reset slot. `on_http_server_stopped` (line 377) is an empty stub.
  2. `start_usb_server()` never connects `usb_handler.finished` to a UI-reset slot.
* **Consequences:** If the HTTP port is busy, `ThreadingHTTPServer.__init__` raises an `OSError`, the thread exits immediately, but the UI stays locked with the Stop button active. The user must manually press Stop to recover.
* **Fix:** Connect `usb_handler.finished` and `http_handler.finished` signals to a slot that calls `_set_server_ui_state(False)` and `file_manager.handle_server_stop()`.

---

### 🔴 BUG-06 — Overall progress jumps to 100% at the start of a new installation session (`server_operations.py`)

**Status:** ✅ Fixed (v2.4.3)

* **Problem:** `on_transfer_reset()` (lines 316–320) resets visual styles but does **not** reset `transfer_stats['completed_files']`, `transfer_stats['skipped_files']`, or `completed_files_set`. When `on_progress_updated()` is next called, `completed >= total_files` is already true, so `is_finished = True` and `overall_pct` jumps to 100% immediately.
* **Additional:** `ProgressTracker.reset()` clears `requested_files` and sets `total_requested_size = 0`, but does **not** re-run the constructor's pre-initialization loop that adds all files to `requested_files` and sums their sizes. After a reset the tracker behaves as if no files were registered.
* **Fix (two parts):**
  1. In `ServerManager.on_transfer_reset()`, reset `transfer_stats['completed_files'] = 0`, `transfer_stats['skipped_files'] = 0`, `completed_files_set.clear()`.
  2. In `ProgressTracker.reset()`, re-run the pre-initialization loop so all files are re-added to `requested_files` with their sizes summed into `total_requested_size`.

---

## 3. Serious Issues 🟡

### 🟡 BUG-03 — Incorrect project root path resolution (`config_manager.py`, `file_operations.py`)

**Status:** ✅ Fixed (v2.4.4)

* **Problem:** Both files use `Path(__file__).parent.parent.parent` to locate the project root.
  * `src/config_manager.py` → `.parent` = `src/` → `.parent.parent` = `dbibackend-qt/` (correct) → `.parent.parent.parent` = parent folder of the project (**wrong**).
  * The `if app_dir.name == 'src': app_dir = app_dir.parent` guard on the next line never triggers because by this point `app_dir` is already two levels too high.
* **Consequences:** `config.json` and `presets/` are created one directory above the project root (e.g., `E:\Switch\` instead of `E:\Switch\dbibackend-qt\`).
* **Fix:** Replace `.parent.parent.parent` with `.parent.parent`. The `if app_dir.name == 'src':` guard then becomes a correct safety net.

---

### 🟡 BUG-07 — `None` dereference in `on_installation_begun` for HTTP mode (`server_operations.py:348`)

**Status:** ✅ Fixed (v2.4.5)

* **Problem:** The last log line in `on_installation_begun` is:
  ```python
  self.main_window.log('info', f'Progress recalculated. New target: {format_size(self.usb_handler.progress_tracker.total_requested_size) if self.usb_handler else "N/A"}')
  ```
  This is safe, but earlier in the same method (line 340–346) the loop `for filename in checked: if filename not in requested_set: self.on_file_skipped(filename, size)` runs unconditionally. `on_installation_begun` is connected **only** from `USBHandler.installation_begun` signal, so in HTTP mode this slot is never called. However, if it were ever called in HTTP mode (e.g., future refactor), `self.usb_handler` would be `None` and the attribute access `self.usb_handler.progress_tracker` at line 346 and in the log at 348 would raise `AttributeError`.
* **Risk:** Low for now, but creates a fragile implicit coupling between the signal source and the handler implementation.
* **Fix:** Add an explicit guard at the top of `on_installation_begun`: `if not self.usb_handler: return`.

---

### 🟡 BUG-08 — `.seconds` instead of `.total_seconds()` causes wrong elapsed time for sessions > 1 hour (`server_operations.py:237, 363`)

**Status:** ✅ Fixed (v2.4.6)

* **Problem:** `(datetime.now() - self.transfer_stats['start_time']).seconds` returns the `seconds` component of a `timedelta` (0–59 within each minute). For a session lasting 1 hour 5 minutes, `.seconds` returns 300 (5 minutes), not 3900. The same bug appears in `on_all_transfers_complete` (line 363).
* **Consequences:** Reported speed (MB/s calculated from `elapsed`) and session time in the summary dialog will be wrong for transfers lasting more than 1 hour.
* **Fix:** Replace `.seconds` with `int(.total_seconds())` at both locations.

---

## 4. Minor Issues 🔵

### 🔵 BUG-04 — `log.txt` always empty (`main_window.py`)

**Status:** ✅ Fixed (v2.4.7)

* **Problem:** `_init_log_file()` creates `log.txt` with a header line. `log()` (line 230–237) writes only to the console and the `QTextEdit` widget. No write to `log.txt`.
* **Fix:** Add `with open("log.txt", 'a', encoding='utf-8') as f: f.write(f"[{t}] [{level.upper()}] {message}\n")` inside `log()`.

---

### 🔵 BUG-05 — "Floating" progress bar on horizontal scroll (`widgets.py:226`)

**Status:** ✅ Fixed (v2.4.8)

* **Problem:** `ProgressDelegate.paint()` draws the progress rectangle at `x=0` relative to the viewport. If the tree is scrolled horizontally, the bar stays pinned to the left edge of the window instead of scrolling with the columns.
* **Fix:** Offset `x` by `self.tree_widget.header().offset()` when constructing `progress_rect`.

---

### 🔵 BUG-09 — Icon lookup uses a relative path (`main_window.py:93`)

**Status:** ✅ Fixed (v2.4.9)

* **Problem:** `Path('icons/icon.png')` is resolved relative to the process's current working directory (CWD). If the app is launched from a directory other than the project root, the icon is not found.
* **Fix:** Use `Path(__file__).parent.parent / 'icons' / 'icon.png'` for a CWD-independent path.

---

## 5. Priority Task List (TODO)

| ID | Description | Priority | Files |
|---|---|:---:|---|
| **BUG-01** | Replace shared HTTP file handle cache with per-request or `thread-local` handles. | 🔴 Critical | [http_request_handler.py](file:///E:/Switch/dbibackend-qt/src/http_request_handler.py) |
| **BUG-02** | Connect `finished()` signal of `usb_handler` / `http_handler` to a UI-reset slot. | 🔴 Critical | [server_operations.py](file:///E:/Switch/dbibackend-qt/src/server_operations.py) |
| **BUG-06** | Reset `transfer_stats` counters and `completed_files_set` in `on_transfer_reset()`; fix `ProgressTracker.reset()` to re-initialize file list. | 🔴 Critical | [server_operations.py](file:///E:/Switch/dbibackend-qt/src/server_operations.py), [progress_tracker.py](file:///E:/Switch/dbibackend-qt/src/progress_tracker.py) |
| **BUG-03** | Replace `parent.parent.parent` with `parent.parent` in path resolution. | 🟡 High | [config_manager.py](file:///E:/Switch/dbibackend-qt/src/config_manager.py), [file_operations.py](file:///E:/Switch/dbibackend-qt/src/file_operations.py) |
| **BUG-07** | Add `if not self.usb_handler: return` guard at the top of `on_installation_begun()`. | 🟡 High | [server_operations.py](file:///E:/Switch/dbibackend-qt/src/server_operations.py) |
| **BUG-08** | Replace `.seconds` with `.total_seconds()` in elapsed-time calculations. | 🟡 High | [server_operations.py](file:///E:/Switch/dbibackend-qt/src/server_operations.py) |
| **BUG-04** | Write log entries to `log.txt` inside `MainWindow.log()`. | 🔵 Low | [main_window.py](file:///E:/Switch/dbibackend-qt/src/main_window.py) |
| **BUG-05** | Offset progress-bar `x` by `header().offset()` to fix horizontal scroll visual glitch. | 🔵 Low | [widgets.py](file:///E:/Switch/dbibackend-qt/src/widgets.py) |
| **BUG-09** | Use `Path(__file__)`-relative path for the window icon. | 🔵 Low | [main_window.py](file:///E:/Switch/dbibackend-qt/src/main_window.py) |
