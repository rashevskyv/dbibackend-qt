@echo off
REM Build script for DBI Backend Qt
REM Creates a single executable file with all dependencies

REM Enable logging
set LOGFILE=build_output.log
echo Build started at %date% %time% > %LOGFILE%

echo ========================================
echo DBI Backend Qt - Build Script
echo ========================================
echo.

REM Install dependencies
echo Installing dependencies...
echo Installing dependencies... >> %LOGFILE%
python -m pip install -r requirements.txt --quiet >> %LOGFILE% 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies!
    echo ERROR: Failed to install dependencies! >> %LOGFILE%
    pause
    exit /b 1
)
echo Dependencies installed successfully >> %LOGFILE%

REM Check if PyInstaller is installed
echo Checking PyInstaller... >> %LOGFILE%
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    echo Installing PyInstaller... >> %LOGFILE%
    python -m pip install pyinstaller >> %LOGFILE% 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install PyInstaller!
        echo ERROR: Failed to install PyInstaller! >> %LOGFILE%
        pause
        exit /b 1
    )
)
echo PyInstaller ready >> %LOGFILE%

REM Clean previous build
echo Cleaning previous build...
echo Cleaning previous build... >> %LOGFILE%
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo Previous build cleaned >> %LOGFILE%

REM Build single executable
echo.
echo Building single executable...
echo Building single executable... >> %LOGFILE%
python -m PyInstaller dbibackend.spec --clean >> %LOGFILE% 2>&1

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo Build completed successfully!
    echo ========================================
    echo Build completed successfully! >> %LOGFILE%
    echo Build finished at %date% %time% >> %LOGFILE%
    echo.
    echo Executable location: dist\dbibackend-qt.exe
    echo.
    echo You can now run: dist\dbibackend-qt.exe
    echo Check build_output.log for detailed build information
) else (
    echo.
    echo ========================================
    echo Build FAILED!
    echo ========================================
    echo Build FAILED at %date% %time% >> %LOGFILE%
    echo Check build_output.log for error details >> %LOGFILE%
    exit /b 1
)

pause
