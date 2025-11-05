@echo off
REM Build script for DBI Backend Qt
REM Creates a single executable file with all dependencies

echo ========================================
echo DBI Backend Qt - Build Script
echo ========================================
echo.

REM Install dependencies
echo Installing dependencies...
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies!
    pause
    exit /b 1
)

REM Check if PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install PyInstaller!
        pause
        exit /b 1
    )
)

REM Clean previous build
echo Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build single executable
echo.
echo Building single executable...
python -m PyInstaller dbibackend.spec --clean

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo Build completed successfully!
    echo ========================================
    echo.
    echo Executable location: dist\dbibackend-qt.exe
    echo.
    echo You can now run: dist\dbibackend-qt.exe
) else (
    echo.
    echo ========================================
    echo Build FAILED!
    echo ========================================
    exit /b 1
)

pause
