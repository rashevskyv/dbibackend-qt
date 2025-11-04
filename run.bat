@echo off
REM DBI Backend Qt - Quick Launch Script
REM Double-click this file to start the application

echo Starting DBI Backend Qt...

REM Try python3 first, then fall back to python
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start pythonw3 main.py
) else (
    start pythonw main.py
)

REM If the window closes immediately with errors, run with console:
REM python3 main.py
REM pause
