# GEMINI Analysis: dbibackend-qt

## Project Overview

This is a desktop GUI application for Windows, built with Python and the PyQt6 framework. Its primary purpose is to provide a user-friendly interface for transferring files (specifically `.nsp`, `.nsz`, `.xci`, `.xcz`) to a Nintendo Switch console via a USB connection. The application appears to be a graphical frontend for the DBI homebrew tool.

The project is set up to be packaged into a standalone `.exe` file using PyInstaller, allowing it to run on Windows systems without requiring a Python installation.

**Key Technologies:**
- **Language:** Python 3
- **GUI Framework:** PyQt6
- **USB Communication:** PyUSB
- **Packaging:** PyInstaller

**Core Features:**
- File queue for managing transfers.
- Drag-and-drop support for adding files and folders.
- Real-time progress tracking for both individual files and overall transfers.
- A theming system (Light/Dark).
- Single-instance management (opening files with the app from Explorer will add them to the existing instance).
- Ability to save and load file lists as presets.

## Building and Running

### 1. Install Dependencies

The project's Python dependencies are listed in `requirements.txt`. You will also need `pyinstaller`.

```bash
# Install application dependencies
pip install -r requirements.txt

# Install PyInstaller for building the executable
pip install pyinstaller
```
*Note: The application also requires the `libusb` driver to be installed on the system for the Nintendo Switch device. This is typically done using a tool like Zadig.*

### 2. Running from Source

A `run.bat` script is provided to execute the application directly from the Python source code.

```bash
# From the project root directory
python main.py
```

### 3. Building the Executable

The project uses PyInstaller, configured by `dbibackend.spec`, to build a standalone executable. A convenience script is provided.

```bash
# Recommended method (uses build.py internally)
build.bat

# Alternative method
python build.py
```

The build process will create `build/` and `dist/` directories. The final, distributable executable will be located at: `dist/dbibackend-qt.exe`.

## Development Conventions

- **Source Code Structure:** All main application source code is located in the `src/` directory. The root directory contains build scripts, configuration, and documentation.
- **Entry Point:** `main.py` is the main entry point for the application. It initializes the PyQt6 application and the main window (`MainWindow` from `src/main_window.py`).
- **Build Configuration:** The PyInstaller build is defined in `dbibackend.spec`. This file controls aspects like the executable name, included files, hidden imports, and whether to show a console window.
- **Single Instance:** The application ensures only one instance is running at a time using the `SingleInstanceManager` class (`src/single_instance.py`). If a new instance is launched with file paths as arguments, it sends the paths to the primary instance and exits.
- **UI and Logic:** The core UI and application logic are heavily concentrated in the `MainWindow` class within `src/main_window.py`. This class manages UI elements, events, and interacts with the `USBHandler`.
- **USB Handling:** The `USBHandler` class (`src/usb_handler.py`) runs in a separate thread (`QThread`) to manage blocking USB I/O without freezing the GUI.
