@echo off
REM ============================================================
REM  TARS — Mission Agent (Windows Launcher)
REM  Double-click this file to start TARS.
REM  Opens automatically at http://localhost:4321
REM ============================================================

cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║         TARS — Mission Agent          ║
echo  ║      The Pauli Effect Studios         ║
echo  ╚══════════════════════════════════════╝
echo.

REM Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.10+ from python.org
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

REM Check if this is first run — install dependencies
if not exist ".deps_installed" (
    echo  First run — installing dependencies...
    echo.
    pip install pyautogui mss Pillow PyQt6 --quiet
    if errorlevel 1 (
        echo  [WARNING] Some dependencies failed to install.
        echo  TARS will run but screen takeover and desktop monolith may not work.
        echo  Core features (chat, voice, missions) will still function.
        echo.
    )
    echo done > .deps_installed
    echo.
)

REM Check config exists
if not exist "config.json" (
    if exist "config.example.json" (
        echo  [SETUP] No config.json found. Copying from config.example.json...
        copy config.example.json config.json >nul
        echo  [SETUP] Edit config.json and add your API keys, then re-run.
        echo.
    )
)

echo  Starting TARS...
echo  Browser will open automatically at http://localhost:4321
echo  Press Ctrl+C to stop.
echo.

python server.py

pause
