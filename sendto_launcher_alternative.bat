@echo off
REM DBI Backend Qt - Alternative Silent Launcher
REM Uses PowerShell to launch without console window

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0

REM Build arguments string
set ARGS=%*

REM Launch via PowerShell (hidden window)
powershell -WindowStyle Hidden -Command "& {$process = Start-Process -FilePath 'pythonw' -ArgumentList '\"%SCRIPT_DIR%main.py\" %ARGS%' -WorkingDirectory '%SCRIPT_DIR%' -WindowStyle Hidden -PassThru; exit}"

REM Exit immediately
exit
