@echo off
REM Build script for DBI Backend Qt
REM This script calls build.py which handles the actual build process

python build.py

if errorlevel 1 (
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo.
echo Press any key to exit...
pause >nul
