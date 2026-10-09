# DBI Backend Qt 🚀

**DBI Backend Qt** is a modern, feature-rich graphical user interface (GUI) for the **DBI** installer (Nintendo Switch). Built with Python 3 and PyQt6, this tool provides a superior alternative to traditional CLI backends, offering an advanced file queue, visual feedback, and deep OS integration.

![Version](https://img.shields.io/badge/version-2.9.4-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Key Features

### 🔄 Two-Way Sphaira Synchronization & Queue Management
*   **Live Queue Modification & Context Menu "Set as Next in Queue":** Add new files (via Drag & Drop or Add buttons), toggle checkboxes, reorder unstarted queue items using dedicated drag handles (or `Alt+Up` / `Alt+Down`), or right-click any game to select **"Set as Next in Queue"** to immediately position it next in line after active/completed items. Sphaira dynamically reflects queue changes on the fly without restarting the installation session, while active and completed files are safely guarded.
*   **Queue Plan Synchronization & Target Resolution:** When paired with Sphaira/Kefir Hub, the console reports its planned install queue (`CMD_ID_QUEUE_PLAN`). Items in `Auto` mode dynamically display their planned target (`Auto → SD` or `Auto → NAND`), unchecking an item on the console propagates to the PC without getting re-enabled, and packages pinned to drives they cannot fit on are safely reset to Auto.
*   **Dynamic Storage Projection & Cursor Hover:** The storage bars calculate live drive projections based on planned packages (marking green for fitting or red for overflowing), with interactive highlight segments showing the footprint of the package currently hovered under the mouse pointer.
*   **Pinned Active Item Banner:** When scrolling away from the currently installing game in long queues, a pinned header banner stays anchored at the top of the file list, showing the title, target, percentage progress bar, and clickable jump to scroll straight back to the active item.
*   **Table Header Select-All:** Master checkbox integrated directly into the table header allows selecting or deselecting all items with a single click.
*   **Real-time Status Tracking & Target Progress:** When Sphaira finishes installing a game or skips a package (already installed or user-skipped), it transmits a notification back to the PC. The PC immediately unchecks the item, marks it as **Done** or **Skipped**, and dynamically recalculates remaining bytes, overall progress, and ETA. The Target column uses clean native dropdown styling with transparent cell background, eliminating double text ghosting while ensuring the row-wide progress bar remains fully visible.
*   **Install Location Sync (Target):** Configure where each game should be installed directly from the PC table (`Auto`, `SD Card`, `NAND / System memory`) via dropdowns or right-click context menus. The choice is synced to Sphaira in real time.
*   **Already Installed Policy:** Configurable handling for already installed packages (`Console setting`, `Reinstall`, `Skip`, `Prompt`), propagated directly to the console over SPHQ headers.
*   **Sphaira-Style Dynamic Dual Storage Bars:** Directly inside the File Queue header, two stacked capacity bars show **microSD** and **NAND** status in the authentic style of Sphaira (SFIRE). Each bar dynamically reflects committed disk space, color thresholds (Green <=75%, Amber >75%, Red >90%), and during installation displays all three metrics at once in full Sphaira format: `+<written> / <package_size> / <free_space>` (e.g. `+128.8 MB / 162.5 MB / 7.4 GB`), alongside an active installation yellow segment tracking real-time write progress.
*   **SFIRE-Synchronized ETA:** ETA calculation is fully aligned with Sphaira's `FormatEta` (`Xh Ym` / `Xm Ys`) and displays dual progress (`ETA: <file_eta> / <total_eta>`) powered by a smoothed sliding-window speed estimate.

### 🛡️ Crash Resilience & End-of-Session Reporting
*   **Automatic Queue Resume (`resume.dbi`):** The active queue state is atomically mirrored to `resume.dbi` as transfers progress. If the application closes, crashes, or the PC reboots, the next launch prompts to restore unfinished items with a single click.
*   **Comprehensive Session Reports:** Automatically generates an end-of-session summary and text log upon completion or link loss. Categorizes installed, skipped, and failed packages, maps Horizon and Sphaira error codes into clear descriptions (e.g., missing firmware keys, corrupt NCA/NCZ, filesystem out of space), and flags DLC/updates installed without their base game. Saved to `reports/report_YYYYMMDD_HHMMSS.txt`.
*   **Safe Log Rotation:** Existing session logs are rotated to `log.prev.txt` on launch, preventing loss of debug traces after unexpected crashes.

### 🌙 Smart User-Aware Auto-Hibernation
*   **User-Aware Inactivity Guard:** When auto-hibernation is enabled, the system monitors physical mouse and keyboard inputs via Windows `GetLastInputInfo`. If someone is actively using the PC, the system will never hibernate automatically, presenting only a manual button. When the user is away, it displays a 3-minute warning countdown with taskbar notifications before safely putting the computer to sleep once transfers finish. Automatically snoozes if console traffic resumes.

### 📡 Transfer Modes
*   **USB Backend:** Direct installation via USB cable using the MTP/DBI protocol. High-speed and reliable. Supports only Switch game files (`.nsp`, `.nsz`, `.xci`, `.xcz`). Features unique byte-range interval tracking to avoid duplicating progress when ranges are re-requested.
    *   **Automatic MTP Handoff:** If the Switch is connected in MTP mode while the USB server is waiting, the backend writes a trigger to the SD card via Windows Shell COM. Kefir Hub 0.14.038+ detects it and offers to switch seamlessly to PC Install (USB). If declined, it avoids re-prompting.
    *   **Auto-Connect on Cable Plug-in:** Optional auto-start detects when the Switch appears in install mode on the USB cable and begins communication automatically without manual clicks.
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
