# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DBI Backend Qt is a PyQt6-based GUI application for transferring files to Nintendo Switch via USB using the DBI protocol. It's a modernized rewrite of the original tkinter-based `dbibackend_classic.py` with enhanced features including:

- Visual progress tracking with per-file and overall progress bars
- Dark/Light theme support
- Single-instance management (prevents multiple windows)
- Drag & drop file support
- Windows "Send to" integration via VBScript launchers
- Batch file export for loading file lists
- Detailed file logging to `log.txt`

## Commands

### Running the Application

```bash
# Standard launch (with console output for debugging)
python main.py

# Launch without console (Windows)
pythonw main.py

# Quick launch on Windows
run.bat

# Launch with files pre-loaded
python main.py "path/to/file1.nsp" "path/to/file2.nsp"
```

### Installing Dependencies

```bash
pip install -r requirements.txt
```

**Important for Windows:** You need to install libusb drivers for the Nintendo Switch device (VID: 057E, PID: 3000). Use Zadig to install WinUSB driver or download libusb-win32.

### Development

```bash
# No test suite currently exists
# No linting configuration currently exists

# To debug USB issues, check the generated log.txt file
# Logs include detailed protocol traces, speed measurements, and error traces
```

## Architecture

### High-Level Structure

The application follows a Qt MVC-like pattern with threaded USB handling:

```
main.py (entry point)
  └─ MainWindow (src/main_window.py)
      ├─ USBHandler (src/usb_handler.py) - QThread for USB communication
      ├─ ConfigManager (src/config_manager.py) - JSON-based settings
      ├─ ThemeManager (src/theme_manager.py) - Qt stylesheets
      └─ SingleInstanceManager (src/single_instance.py) - QLocalServer/Socket
```

### DBI Protocol Implementation

**Protocol**: The DBI protocol (implemented in `usb_handler.py`) uses a binary packet format:

```
Header: [Magic: "DBI0"] [CmdType: 4 bytes] [CmdID: 4 bytes] [DataSize: 4 bytes]
```

**Command Types:**
- `CMD_TYPE_REQUEST = 0` - Switch requests from PC
- `CMD_TYPE_RESPONSE = 1` - PC responds to Switch
- `CMD_TYPE_ACK = 2` - Acknowledgment

**Command IDs:**
- `CMD_ID_EXIT = 0` - Switch signals exit
- `CMD_ID_LIST = 3` - Switch requests file list
- `CMD_ID_FILE_RANGE = 2` - Switch requests file data range

**Transfer Flow:**
1. Switch sends `CMD_ID_LIST` -> PC responds with newline-separated filenames
2. Switch sends `CMD_ID_FILE_RANGE` with (offset, size, filename) -> PC sends data in 1MB chunks
3. Switch may request same file multiple times with different ranges (metadata phase, then transfer phase)
4. Switch sends `CMD_ID_EXIT` when done

### Progress Tracking

**Interval-based tracking** (like torrent clients): `usb_handler.py` tracks transferred byte ranges as intervals `[(start, end), ...]` and merges overlapping ranges to calculate unique bytes transferred. This handles:
- Overlapping ranges (Switch re-requests same bytes)
- Out-of-order ranges
- Verification passes

**Two phases:**
- **Metadata phase**: Small requests (<100KB) - Switch reads file headers to determine if files should be installed
- **Transfer phase**: Large requests (1MB) - Actual file data transfer with progress updates

**Progress signals:**
- `progress_updated` - Overall progress (every 10 chunks / 10MB)
- `file_progress` - Per-file progress percentage (for visual feedback in tree widget)
- `transfer_complete` - File transfer completed

### Threading Model

**Main Thread:** Qt event loop, UI updates, user interactions

**USB Thread:** `USBHandler` (QThread) handles all USB I/O:
- Blocking USB reads/writes
- File I/O for transfers
- Protocol state machine
- Emits signals to main thread for UI updates

**Thread Safety:** All UI updates happen via Qt signals/slots (thread-safe by design)

### Single Instance Management

Uses Qt's `QLocalServer`/`QLocalSocket` with named pipe (`"dbibackend_qt_instance"`):
- First instance creates server
- Subsequent instances connect, send file paths, and exit
- Primary instance receives paths and adds them to file list

This enables Windows "Send to" integration where files sent from Explorer are forwarded to the running instance.

### Configuration

`ConfigManager` stores user preferences in JSON at `~/.dbibackend-qt/config.json`:
- Theme preference
- Window geometry (for restore on launch)
- Last directory (file picker memory)
- Auto-connect settings
- Buffer sizes

**No database** - file lists are ephemeral (not persisted between sessions unless explicitly saved as JSON)

### Theme System

`ThemeManager` provides two Qt stylesheets (light/dark) covering:
- Color schemes (backgrounds, text, borders)
- Button styles (hover, pressed, disabled states)
- Progress bar styling
- Tree widget alternating row colors
- Custom scrollbar appearance
- GroupBox styling with colored titles

Themes are applied via `QMainWindow.setStyleSheet()` and persisted via ConfigManager.

### File List Management

**Data Structure:** `Dict[str, Path]` where key is filename (basename) and value is full path
- **Note:** Duplicate filenames (same name, different paths) will overwrite each other
- When adding folders, recursively finds all files via `Path.rglob('*')`
- Files can be checked/unchecked in UI but unchecked files are still sent to Switch (UI-only feature, not protocol-enforced)

### Custom Delegates

`ProgressDelegate` (in `main_window.py`) is a `QStyledItemDelegate` that:
- Paints a green progress bar background behind tree widget items
- Shows darker green for in-progress files, brighter green for completed
- Progress data stored in `delegate.progress_data: Dict[filename, progress%]`
- Triggers repaint via `tree_widget.update(index)` when progress changes

## Key Implementation Details

### USB Communication

**Buffer Size:** `BUFFER_SEGMENT_DATA_SIZE = 0x100000` (1MB) - matches Nintendo's expected chunk size

**Endpoint Detection:** Finds USB bulk endpoints via `usb.util.find_descriptor()` with direction matchers

**Error Recovery:** USB errors trigger reconnection attempts (up to 30 retries with 1s delay)

**Device Reset:** Always calls `dev.reset()` after finding device, waits 1s for reset to complete

### Speed Calculation

Smoothed moving average over last 10 chunks:
```python
self.speed_samples.append(chunk_speed_mbps)
if len(self.speed_samples) > self.max_speed_samples:
    self.speed_samples.pop(0)
avg_speed = sum(self.speed_samples) / len(self.speed_samples)
```

### Logging

**Dual logging:**
1. **UI Log:** HTML-formatted, color-coded, auto-scrolling TextEdit (max 1000 lines)
2. **File Log:** `log.txt` with timestamps (µs precision), detailed protocol traces, exception tracebacks

**Log levels:** `info`, `success`, `warning`, `error` (color-mapped in UI)

### Windows Integration

**Send to Launchers:**
- `sendto_launcher.vbs` - VBScript for silent launch (no console window)
- `sendto_launcher_alternative.bat` - PowerShell-based alternative
- Both forward command-line arguments to `main.py`

**Batch Export:** Saves file list as `.bat` file that launches app with all files as arguments

## Common Pitfalls

1. **USB Driver Issues (Windows):** Most common failure. Ensure WinUSB driver is installed for Switch device. Check Device Manager.

2. **Duplicate Filenames:** If you add files with same basename from different directories, only the last one is kept. Consider warning users or using full path as key.

3. **Progress >100%:** `transferred_bytes` can exceed `total_requested_size` due to overlapping ranges. Always cap display at 99% until completion.

4. **Unchecked Files Still Transfer:** The checkbox UI doesn't filter files sent to Switch. Would need protocol-level filtering in `process_list_command()`.

5. **Single Instance Not Working:** Check for stale QLocalServer socket. Application calls `QLocalServer.removeServer()` on startup to clean up.

6. **File Locking:** On Windows, files being transferred are locked (opened in `rb` mode). Ensure files aren't being written by other processes.

7. **Thread Safety:** Never call USB/file operations from main thread. Always use USBHandler thread. Never update UI widgets from USB thread (use signals).

## Protocol Quirks

- Switch may request the same file range multiple times (verification)
- Metadata requests are unpredictable (can be 16, 96, 3072 bytes)
- No error codes in protocol - errors are detected via USB exceptions
- No resume support - each session starts fresh
- File list order doesn't matter - Switch decides installation order
