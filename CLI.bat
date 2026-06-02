@echo off
title HAYO AI AGENT - CLI Mode
color 0B

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   HAYO AI AGENT - CLI Mode                       ║
echo  ║   Terminal interface (no browser needed)         ║
echo  ╚══════════════════════════════════════════════════╝
echo.

cd /d "C:\HAYO AI AGENT"
call venv\Scripts\activate.bat

if errorlevel 1 (
    echo  [ERROR] Could not activate venv. Run: python -m venv venv
    pause
    exit /b 1
)

python main.py %*

if errorlevel 1 pause
