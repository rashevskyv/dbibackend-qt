# DBI Backend Qt 🚀

**DBI Backend Qt** is a modern, feature-rich graphical user interface (GUI) for the **DBI** installer (Nintendo Switch). Built with Python 3 and PyQt6, this tool provides a superior alternative to traditional CLI backends, offering an advanced file queue, visual feedback, and deep OS integration.

![Version](https://img.shields.io/badge/version-2.9.0-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Key Features

### 🔄 Two-Way Sphaira Synchronization & Queue Management
*   **Live Queue Modification & Drag Handles:** Add new files (via Drag & Drop or Add buttons), toggle checkboxes, or reorder unstarted queue items using dedicated drag handles (or `Alt+Up` / `Alt+Down`) at any time during an active USB session. Sphaira dynamically reflects queue changes on the fly without having to restart the installation session, while active and completed files are safely guarded.
*   **Table Header Select-All:** Master checkbox integrated directly into the table header allows selecting or deselecting all items with a single click.
*   **Real-time Status Tracking & Target Progress:** When Sphaira finishes installing a game or skips a package (already installed or user-skipped), it transmits a notification back to the PC. The PC immediately unchecks the item, marks it as **Done** or **Skipped**, and dynamically recalculates remaining bytes, overall progress, and ETA. The Target column uses clean native dropdown styling with transparent cell background, eliminating double text ghosting while ensuring the row-wide progress bar remains fully visible.
*   **Install Location Sync (Target):** Configure where each game should be installed directly from the PC table (`Auto`, `SD Card`, `NAND / System memory`) via dropdowns or right-click context menus. The choice is synced to Sphaira in real time.
*   **Sphaira-Style Dynamic Dual Storage Bars:** Directly inside the File Queue header, two stacked capacity bars show **microSD** and **NAND** status in the authentic style of Sphaira (SFIRE). Each bar dynamically reflects committed disk space, color thresholds (Green <=75%, Amber >75%, Red >90%), free space readout, and an active installation segment (yellow) tracking real-time write progress of the installing title.
*   **SFIRE-Synchronized ETA:** ETA calculation is fully aligned with Sphaira's `FormatEta` (`Xh Ym` / `Xm Ys`) and displays dual progress (`ETA: <file_eta> / <total_eta>`) powered by a smoothed sliding-window speed estimate.

### 🌙 Auto-Hibernation
*   **Hibernate PC when Idle (5 min):** Option to automatically put your Windows PC into hibernation when there has been no communication between the Nintendo Switch console and the server for over 5 minutes (indicating all transfers have finished and the console is no longer waiting for or accepting files). Includes a 30-second countdown prompt with an option to abort if you are still at your computer, and automatically cancels if the console resumes activity.

### 📡 Transfer Modes
*   **USB Backend:** Direct installation via USB cable using the MTP/DBI protocol. High-speed and reliable. Supports only Switch game files (`.nsp`, `.nsz`, `.xci`, `.xcz`). Features unique byte-range interval tracking to avoid duplicating progress when ranges are re-requested.
*   **HTTP Server:** Turns your PC into a local network repository. Use the "Install from HTTP" menu in DBI to install games over Wi-Fi or LAN. Supports adding any folders (as virtual directories) and files of any type.
*   **FTP Server:** Serves your files over a local FTP server. Use the "Install from FTP" network source in DBI or any standard FTP client (like FileZilla). Supports adding folders and files of any type.

### 📁 Virtual File System & Folder Ingestion
*   **Folder Ingestion Modes:** When adding folders via button, drag & drop, or command line, choose between recursively scanning all files or preserving the hierarchical folder structure.
*   **Duplicate Basename Protection:** Files with identical basenames from different locations are flagged with conflict indicators and excluded from transfer to protect the Switch filesystem.
*   **DBI Client Filter:** When accessed via the Switch's DBI program (detected by User-Agent for HTTP, or username/password matching for FTP), the servers automatically present a flat listing containing only compatible installation files (`.nsp`, `.nsz`, `.xci`, `.xcz`) for seamless installation.
*   **Hierarchical Browsing:** When accessed via standard web browsers or standard FTP clients, the servers present the actual nested directory structures, recursive size calculations, and allow downloading all files without extension filtering.

### 📋 Intelligent File Queue
*   **Supported Formats:** Full support for `.nsp`, `.nsz`, `.xci`, and `.xcz` files.
*   **Drag & Drop:** Easily add files or entire folders by dragging them into the window.
*   **Dynamic Statistics:** Real-time calculation of file count and total size for both the entire list and currently checked items (e.g., `Selected: 5 / 10 files`).
*   **Metadata-Aware:** Automatically dims unselected files when the server starts. Marks checked files as "Skipped" if they weren't requested by the Switch during the selection phase.
*   **Progress Correction:** Dynamic recalculation of total transfer size if a file is skipped or interrupted (works for both **USB** and **HTTP** modes), ensuring the progress bar accurately reaches 100%.
*   **Instant Search:** Filter your long lists instantly using the built-in search bar.
*   **Robust Stop:** Fully responsive "Stop" button that breaks blocking USB operations via device reset.

### 💾 Preset System (.dbi)
*   **Custom Format:** Save your carefully selected file lists, including their checkbox states, targets, and folder structures, into `.dbi` files.
*   **Shell Integration:** Supports "Open With..." — double-click any `.dbi` file in Windows Explorer to load your preset directly into the app.
*   **Quick Access:** A dedicated "Presets" menu for rapid switching between different game sets.

### 🎨 Modern UI & UX
*   **Theming:** Includes **Light**, **Dark**, and **Auto** modes (automatically syncs with Windows system theme).
*   **Row-wide Progress Bars:** Instead of a tiny bar in one cell, the progress fills the entire background of the row for maximum visibility.
*   **Smart Sorting (Dynamic during transfer):**
    1.  **Active:** The file currently being installed (**Process**) stays at the absolute top.
    2.  **Failed:** Files with errors are moved next for immediate attention.
    3.  **Active Queue:** **Queued** (checked) files follow, sorted by **size** (largest first) to match DBI's priority.
    4.  **Skipped:** Files that were not requested or explicitly skipped.
    5.  **Completed:** Finished files (**Done**) are listed below, grouped above unchecked files.
    6.  **Unchecked:** Files without a checkbox stay at the absolute bottom.
*   **Performance Optimization:** Features file handle caching and incremental progress tracking ($O(1)$) to ensure zero delay between files even in massive queues.
*   **UI Scaling:** Zoom the file list in or out using `Ctrl` + `Mouse Wheel`.

### 🪟 Windows Enhancements
*   **Taskbar Integration:** View the overall installation progress directly on the app's taskbar icon.
*   **Contextual Memory:** The app remembers the last used directory separately for adding files, adding folders, and loading presets.

---

## ⌨️ Controls & Interaction

| Key | Action |
| :--- | :--- |
| **Space** | Toggle checkbox of selected item and move to the next file |
| **Alt + Up / Down** | Move selected pending queue item up or down |
| **Ctrl + O** | Add files to queue |
| **Ctrl + Shift + O** | Add folder to queue |
| **Ctrl + B** | Export list as a `.bat` file for the classic DBI CLI |
| **Ctrl + Wheel** | Change font size of the file list |
| **Double Click** | Collapse/Expand UI sections via splitter handles |

---

## 🚀 Getting Started

### Prerequisites
1.  **USB driver:** nothing to do by hand.
    *   **Windows:** the first time the console is seen without a driver, the app offers to install **WinUSB** (one administrator prompt). You can also run it any time from **Help > Install USB Driver**. A driver you already installed with Zadig (libusbK, libusb-win32 or WinUSB) keeps working and is left alone.
    *   **Linux:** if your user cannot open the console, the app offers to install a udev rule (`/etc/udev/rules.d/99-nintendo-switch-dbi.rules`) via `pkexec`.
    *   **macOS:** no driver needed.
2.  **Python 3.11+** (if running from source). libusb-1.0 comes with the `libusb-package` dependency.

### Running from Source
```bash
# Clone the repository
git clone https://github.com/your-username/dbibackend-qt.git
cd dbibackend-qt

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### Building the Executable
To create a standalone `.exe` version, run the provided build script:
```bash
.\build.bat
```
The output will be located in the `dist/` directory.

---

## 🛠 Tech Stack
*   **Language:** [Python 3](https://www.python.org/)
*   **GUI Framework:** [PyQt6](https://riverbankcomputing.com/software/pyqt/)
*   **USB Comm:** [PyUSB](https://pyusb.github.io/pyusb/)
*   **Windows API:** [comtypes](https://github.com/enthought/comtypes) (for Taskbar progress)
*   **Packaging:** [PyInstaller](https://pyinstaller.org/)

---

## 📜 License
This project is distributed under the MIT License. See [LICENSE](LICENSE) for details.

---
*Developed with focus on the best possible user experience for the Nintendo Switch community.*
