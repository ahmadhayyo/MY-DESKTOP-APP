@echo off
title HAYO AGENT - One-shot fix and restart
color 0E

echo.
echo  ===============================================
echo    HAYO AGENT - Auto Fix and Restart
echo  ===============================================
echo.

cd /d "%~dp0"

echo  [1/5] Stopping any running Python/Chainlit processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1
taskkill /F /IM chainlit.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo  [2/5] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] venv activation failed.
    pause
    exit /b 1
)
echo        OK

echo  [3/5] Installing aiosqlite (fixes the async SqliteSaver error)...
pip install aiosqlite --quiet
if errorlevel 1 (
    echo  [WARN] aiosqlite install reported issues, continuing...
)
echo        OK

echo  [4/5] Backing up old agent_memory.db (if locked, will skip)...
if exist agent_memory.db (
    ren agent_memory.db agent_memory.db.old.%RANDOM% >nul 2>&1
    if errorlevel 1 (
        echo        Could not rename - file is in use. The async saver will reuse it.
    ) else (
        echo        OK - old DB renamed
    )
) else (
    echo        No old DB to back up
)

echo  [5/5] Launching Chainlit on http://localhost:8000 ...
echo.
echo  ===============================================
echo  Server starting. Browser will open shortly.
echo  Press CTRL+C here to stop the server.
echo  ===============================================
echo.

chainlit run app.py --port 8000

pause
