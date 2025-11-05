# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

block_cipher = None

# Collect all Python files from src directory
src_path = Path('src')
src_modules = []
for py_file in src_path.rglob('*.py'):
    if py_file.name != '__init__.py':
        module_name = str(py_file.relative_to('.').with_suffix('')).replace(os.sep, '.')
        src_modules.append(module_name)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include the entire src directory as data files to ensure all modules are available
        ('src', 'src'),
    ],
    hiddenimports=[
        # PyQt6 modules
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        # USB modules
        'usb.core',
        'usb.util',
        'usb.backend',
        'usb.backend.libusb1',
        'usb.backend.libusb0',
        'usb.backend.openusb',
        # Application modules
        'src',
        'src.config_manager',
        'src.main_window',
        'src.usb_handler',
        'src.theme_manager',
        'src.single_instance',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='dbibackend-qt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False to hide console window (keep True for debugging USB issues)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path if you have one: icon='icon.ico'
    uac_admin=False,  # Set to True if you need admin privileges
    uac_uiaccess=False,
)
