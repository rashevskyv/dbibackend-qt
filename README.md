# DBI Backend Qt 🚀

**DBI Backend Qt** is a modern, feature-rich graphical user interface (GUI) for the **DBI** installer (Nintendo Switch). Built with Python 3 and PyQt6, this tool provides a superior alternative to traditional CLI backends, offering an advanced file queue, visual feedback, and deep OS integration.

![Version](https://img.shields.io/badge/version-2.3.14-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Key Features

### 📡 Dual Transfer Modes
*   **USB Backend:** Direct installation via USB cable using the MTP/DBI protocol. High-speed and reliable.
*   **HTTP Server:** Turns your PC into a local network repository. Use the "Install from HTTP" menu in DBI to install games over Wi-Fi or LAN.

### 📋 Intelligent File Queue
*   **Supported Formats:** Full support for `.nsp`, `.nsz`, `.xci`, and `.xcz` files.
*   **Drag & Drop:** Easily add files or entire folders by dragging them into the window.
*   **Dynamic Statistics:** Real-time calculation of file count and total size for both the entire list and currently checked items (e.g., `Selected: 5 / 10 files`).
*   **Instant Search:** Filter your long lists instantly using the built-in search bar.

### 💾 Preset System (.dbi)
*   **Custom Format:** Save your carefully selected file lists, including their checkbox states, into `.dbi` files.
*   **Shell Integration:** Supports "Open With..." — double-click any `.dbi` file in Windows Explorer to load your preset directly into the app.
*   **Quick Access:** A dedicated "Presets" menu for rapid switching between different game sets.

### 🎨 Modern UI & UX
*   **Theming:** Includes **Light**, **Dark**, and **Auto** modes (automatically syncs with Windows system theme).
*   **Row-wide Progress Bars:** Instead of a tiny bar in one cell, the progress fills the entire background of the row for maximum visibility.
*   **Smart Sorting (Default):**
    1.  **Active:** The file currently being installed stays at the top.
    2.  **Completed:** Finished files (`Done`) are grouped below, sorted by size (largest first).
    3.  **Pending:** Queued and failed files come next.
    4.  **Inactive:** *(Preset-only)* Unchecked files are moved to the very bottom.
*   **UI Scaling:** Zoom the file list in or out using `Ctrl` + `Mouse Wheel`.

### 🪟 Windows Enhancements
*   **Taskbar Integration:** View the overall installation progress directly on the app's taskbar icon.
*   **Contextual Memory:** The app remembers the last used directory separately for adding files, adding folders, and loading presets.

---

## ⌨️ Controls & Interaction

| Key | Action |
| :--- | :--- |
| **Space** | Toggle checkbox of selected item and move to the next file |
| **Ctrl + O** | Add files to queue |
| **Ctrl + Shift + O** | Add folder to queue |
| **Ctrl + B** | Export list as a `.bat` file for the classic DBI CLI |
| **Ctrl + Wheel** | Change font size of the file list |
| **Double Click** | Collapse/Expand UI sections via splitter handles |

---

## 🚀 Getting Started

### Prerequisites
1.  **Drivers:** Ensure you have the `libusb-win32` driver installed for your Nintendo Switch (usually done via **Zadig**).
2.  **Python 3.11+** (if running from source).

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
