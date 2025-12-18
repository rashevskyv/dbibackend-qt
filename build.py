#!/usr/bin/env python
"""
Build script for DBI Backend Qt
Creates standalone executable that works without Python installed
"""

import subprocess
import sys
import shutil
from pathlib import Path

def main():
    print("="*50)
    print("DBI Backend Qt - Build Script")
    print("="*50)
    print()

    # Check Python version
    print(f"Python version: {sys.version}")
    print()

    # Clean old build
    print("[1/2] Cleaning old build...")
    for folder in ['build', 'dist']:
        if Path(folder).exists():
            try:
                shutil.rmtree(folder)
                print(f"  Removed {folder}/")
            except Exception as e:
                print(f"  Warning: Could not remove {folder}/ ({e})")
                print(f"  PyInstaller will clean it anyway...")
    print("  Done.")
    print()

    # Build with PyInstaller
    print("[2/2] Building executable...")
    print("  This will take 2-3 minutes, please wait...")
    print()

    try:
        result = subprocess.run(
            [sys.executable, '-m', 'PyInstaller', 'dbibackend.spec', '--clean', '--noconfirm'],
            check=True
        )

        # Check if executable was created
        exe_path = Path('dist/dbibackend-qt.exe')
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print()
            print("="*50)
            print("BUILD SUCCESS!")
            print("="*50)
            print()
            print(f"Created: {exe_path}")
            print(f"Size: {size_mb:.1f} MB")
            print()
            print("This file works on ANY Windows PC")
            print("WITHOUT Python installed!")
            print()
            return 0
        else:
            print()
            print("="*50)
            print("BUILD FAILED - EXE not found!")
            print("="*50)
            return 1

    except subprocess.CalledProcessError as e:
        print()
        print("="*50)
        print("BUILD FAILED!")
        print("="*50)
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print()
        print("="*50)
        print("BUILD ERROR!")
        print("="*50)
        print(f"Error: {e}")
        return 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nBuild cancelled by user")
        sys.exit(1)
