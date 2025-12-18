# Build Instructions / Інструкція збірки

## Quick Start / Швидкий старт

### Building Executable / Збірка EXE файлу

**Method 1 (Recommended):**
```bash
build.bat          # Double-click in Windows Explorer / Подвійний клік у Провіднику
```

**Method 2 (Alternative):**
```bash
python build.py    # Run in terminal / Запустити в терміналі
```

Build time: 2-3 minutes / Час збірки: 2-3 хвилини

### Build Output / Результат

```
dist\dbibackend-qt.exe  (~38 MB)
```

✅ Standalone executable - works WITHOUT Python installed!
✅ Standalone executable - працює БЕЗ встановленого Python!

---

## Prerequisites / Вимоги (для збірки)

- Python 3.11+
- PyQt6
- pyusb
- PyInstaller

### Installing dependencies / Установка залежностей:

```bash
pip install -r requirements.txt
pip install pyinstaller
```

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

## Troubleshooting / Вирішення проблем

### Build fails / Збірка не вдалась
- Install dependencies: `pip install -r requirements.txt pyinstaller`
- Встановіть залежності: `pip install -r requirements.txt pyinstaller`
- Delete `build/` and `dist/` folders manually and try again
- Видаліть папки `build/` та `dist/` вручну і спробуйте знову

### build.bat hangs / build.bat зависає
- Use `python build.py` instead
- Використайте `python build.py` замість цього
- Check that Python is in PATH: `python --version`
- Перевірте що Python в PATH: `python --version`

### Executable doesn't start / EXE не запускається
- Run with console enabled (`console=True` in spec) to see errors
- Запустіть з консоллю (`console=True` в spec) щоб побачити помилки
- Check libusb drivers on target machine (Zadig: VID=057E, PID=3000)
- Перевірте драйвери libusb на цільовому ПК (Zadig: VID=057E, PID=3000)
