# Build Instructions

## Building Executable

### Prerequisites
- Python 3.11+
- All dependencies from `requirements.txt`
- PyInstaller

### Quick Build

Simply run the build script:
```bash
build.bat
```

Or manually:
```bash
# Install dependencies
pip install -r requirements.txt

# Install PyInstaller (if not already installed)
pip install pyinstaller

# Clean previous build
rmdir /s /q build dist

# Build
python -m PyInstaller dbibackend.spec --clean
```

### Build Output

The executable will be created at:
```
dist\dbibackend-qt.exe
```

This is a single-file executable with all dependencies bundled (around 50-100MB).

## Build Configuration

The build is configured in `dbibackend.spec`:

- **Console mode**: `console=True` - Shows console window for debugging USB issues. Set to `False` for production to hide console.
- **UPX compression**: `upx=True` - Compresses the executable (requires UPX to be installed)
- **Icon**: Currently set to `None`. Add `icon='icon.ico'` if you create an icon file.

### Adding an Icon

1. Create or download a `.ico` file
2. Save it as `icon.ico` in the project root
3. In `dbibackend.spec`, change:
   ```python
   icon=None,
   ```
   to:
   ```python
   icon='icon.ico',
   ```

### Adding Version Information

1. Create a `version_info.txt` file with version details
2. In `dbibackend.spec`, add to the EXE section:
   ```python
   version='version_info.txt',
   ```

## Distribution

The `dist\dbibackend-qt.exe` file is fully portable and can be:
- Copied to any Windows machine
- Run without Python installed
- Distributed to users

**Note**: Users will still need libusb drivers installed for Nintendo Switch (VID: 057E, PID: 3000). Use Zadig to install WinUSB driver.

## Troubleshooting

### Build fails with module not found
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check that all `src/*.py` files are present

### Executable doesn't start
- Run with console enabled (`console=True`) to see error messages
- Check that libusb drivers are installed on target machine
- Verify all PyQt6 dependencies are included

### Executable is too large
- Set `upx=True` and install UPX compressor
- Remove unnecessary files from `datas` in spec file
- Consider using `--exclude-module` for unused modules
