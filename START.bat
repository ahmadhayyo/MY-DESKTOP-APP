@echo off
chcp 65001 >nul 2>&1
title HAYO AI Agent — Starting...
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║     🤖  HAYO AI Agent — وكيل ذكي خارق القدرات            ║
echo  ║        Starting server — please wait...                  ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

:: Move to the project folder (works from any location)
cd /d "%~dp0"

:: ── Create venv if missing ────────────────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo  [..] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment. Install Python 3.10+ and add to PATH.
        pause
        exit /b 1
    )
)

:: Activate the virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] Could not activate virtual environment.
    pause
    exit /b 1
)
echo  [OK] Virtual environment activated.

:: ── Install dependencies ONLY on first run (marker file) ──────────────────
::    Subsequent launches skip this and start in seconds. Delete
::    venv\.deps_ok (or run FIX.bat) to force a reinstall after updating deps.
if not exist "venv\.deps_ok" (
    echo  [..] First-time setup: installing dependencies (5-10 min, one time only)...
    pip install -r requirements.txt --exists-action i --progress-bar on
    if errorlevel 1 (
        echo  [ERROR] Failed to install dependencies. Check your internet connection.
        pause
        exit /b 1
    )
    echo  [..] Installing Playwright browser (one time)...
    python -m playwright install chromium --with-deps
    echo done> "venv\.deps_ok"
    echo  [OK] Setup complete.
) else (
    echo  [OK] Dependencies already installed — starting fast.
)

:: ── Ensure .env exists ────────────────────────────────────────────────────
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
    )
    echo  [!] Created .env — edit it to set MODEL_PROVIDER and API keys.
)

echo.
echo  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   🌐 The browser will open automatically once the server is READY.
echo   Press CTRL+C here (or run STOP.bat) to stop the server.
echo  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

:: ── Background waiter: opens the browser ONLY after port 8000 is listening ──
::    (Fixes the old bug where the browser opened before the server was up and
::     showed "site can't be reached".)
start "" /b powershell -NoProfile -WindowStyle Hidden -Command ^
  "$u='http://localhost:8000'; for($i=0;$i -lt 90;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8000); $c.Close(); Start-Process $u; break }catch{ Start-Sleep -Milliseconds 700 } }"

:: ── Foreground server (closing this window / CTRL+C stops it) ──────────────
chainlit run app.py --port 8000 --headless

echo.
echo  [!] Server stopped.
pause
