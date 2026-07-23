@echo off
chcp 65001 >nul 2>&1
title HAYO AI AGENT
color 0A

echo.
echo   ========================================================
echo      HAYO AI AGENT - starting, please wait...
echo   ========================================================
echo.

cd /d "%~dp0"

:: ---- Free port 8000: kill any stale/previous server so we ALWAYS bind ----
echo   [..] Making sure port 8000 is free...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
taskkill /IM chainlit.exe /F >nul 2>&1

:: ---- Create venv if missing ----
if not exist "venv\Scripts\activate.bat" goto makevenv
goto haveenv

:makevenv
echo   [..] Creating virtual environment...
python -m venv venv
if errorlevel 1 goto venverr
goto haveenv

:venverr
echo   [ERROR] Failed to create venv. Install Python 3.10+ and add it to PATH.
pause
exit /b 1

:haveenv
call venv\Scripts\activate.bat
if errorlevel 1 goto activateerr
echo   [OK] Environment ready.
goto deps

:activateerr
echo   [ERROR] Could not activate the virtual environment.
pause
exit /b 1

:deps
if exist "venv\.deps_ok" goto launch
echo   [..] First-time setup: installing dependencies. This runs once.
pip install -r requirements.txt --exists-action i --progress-bar on
if errorlevel 1 goto deperr
python -m playwright install chromium --with-deps
echo done> "venv\.deps_ok"
echo   [OK] Setup complete.
goto launch

:deperr
echo   [ERROR] Failed to install dependencies. Check your internet connection.
pause
exit /b 1

:launch
if not exist ".env" if exist ".env.example" copy /Y ".env.example" ".env" >nul
echo.
echo   --------------------------------------------------------
echo    The browser opens automatically when the server is READY.
echo    KEEP THIS WINDOW OPEN - it is the server.
echo    To stop: close this window or press CTRL+C.
echo   --------------------------------------------------------
echo.

:: Background waiter: opens the browser only AFTER port 8000 is listening.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 150;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8000);$c.Close();Start-Process 'http://localhost:8000';break}catch{Start-Sleep -Milliseconds 700}}"

:: Foreground server. This window must stay open.
chainlit run app.py --port 8000 --headless

echo.
echo   [!] Server stopped. Press any key to close.
pause
