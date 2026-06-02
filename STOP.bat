@echo off
chcp 65001 >nul 2>&1
title HAYO AI Agent — Stopping...
color 0C

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                                                          ║
echo  ║     🛑  HAYO AI Agent — Stopping...                      ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

:: Kill Chainlit and Python processes running on port 8000
echo  [..] Stopping the agent server...

:: Find and kill process on port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo  [..] Killing process PID: %%a
    taskkill /PID %%a /F >nul 2>&1
)

:: Also kill any chainlit processes
taskkill /IM "chainlit.exe" /F >nul 2>&1

echo.
echo  [OK] Agent server stopped successfully!
echo.
pause
