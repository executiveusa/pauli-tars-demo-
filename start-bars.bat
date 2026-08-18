@echo off
REM ============================================================
REM  BARS — Culture DJ + Mission Operator (Windows Launcher)
REM  Double-click this file to start BARS.
REM  Opens automatically at http://localhost:4321
REM ============================================================

cd /d "%~dp0"

echo.
echo  ========================================
echo           BARS - Mission Operator
echo          The Pauli Effect Studios
echo  ========================================
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
        echo  BARS will run, but screen takeover and the desktop character may not work.
        echo  Core chat, voice, and mission features can still function.
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
        echo  [SETUP] Edit config.json and add the provider keys you intend to use, then re-run.
        echo.
    )
)

REM Remote operation is outbound-only and stays disabled unless explicitly configured.
REM Worker auth is deliberately separate from the Terabithia authority key.
if defined TERABITHIA_REMOTE_URL if defined BARS_REMOTE_TOKEN (
    echo  Starting outbound BARS remote bridge...
    start "BARS Remote Bridge" /min python remote_bridge.py
) else (
    echo  Remote bridge disabled - TERABITHIA_REMOTE_URL / BARS_REMOTE_TOKEN not set.
)

echo  Starting BARS...
echo  Browser will open automatically at http://localhost:4321
echo  Press Ctrl+C to stop.
echo.

python server.py

pause
