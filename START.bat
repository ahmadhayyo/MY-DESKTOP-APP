@echo off
chcp 65001 >nul 2>&1
title HAYO AI Agent — Starting...
color 0A

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                                                          ║
echo  ║     🤖  HAYO AI Agent — وكيل ذكي خارق القدرات            ║
echo  ║                                                          ║
echo  ║     Starting server — please wait...                     ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

:: Move to the project folder (works from any location)
cd /d "%~dp0"

:: Check if venv exists, create if not
if not exist "venv\Scripts\activate.bat" (
    echo  [..] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        echo  Make sure Python 3.10+ is installed and in PATH.
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created.
)

:: Activate the virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] Could not activate virtual environment.
    pause
    exit /b 1
)
echo  [OK] Virtual environment activated.
echo.

:: Install / update dependencies
echo  [..] Checking dependencies (first run may take 5-10 minutes)...
echo.
pip install -r requirements.txt --exists-action i --progress-bar on
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install some dependencies.
    echo  Check your internet connection and try again.
    pause
    exit /b 1
)
echo.
echo  [OK] Dependencies up to date.
echo.

:: Install Playwright browsers if not already installed
echo  [..] Checking Playwright browsers...
python -m playwright install chromium --with-deps
if errorlevel 1 (
    echo  [WARNING] Playwright browser install failed — browser tools may not work.
    echo  You can try manually: python -m playwright install chromium --with-deps
) else (
    echo  [OK] Browser ready.
)
echo.

:: Check .env file exists
if not exist ".env" (
    echo  [WARNING] .env file not found!
    if exist ".env.example" (
        echo  Copying .env.example to .env ...
        copy /Y ".env.example" ".env" >nul
        echo  [OK] .env created from .env.example
    ) else (
        echo  Creating a default .env file with Ollama ^(free local AI^)...
        echo MODEL_PROVIDER=ollama> .env
        echo OLLAMA_BASE_URL=http://localhost:11434>> .env
        echo OLLAMA_AGENT_MODEL=dolphin3>> .env
        echo OLLAMA_SUMMARIZER_MODEL=dolphin3>> .env
        echo GOOGLE_API_KEY=>> .env
        echo ANTHROPIC_API_KEY=>> .env
        echo OPENAI_API_KEY=>> .env
        echo DEEPSEEK_API_KEY=>> .env
        echo GROQ_API_KEY=>> .env
        echo  [OK] .env created with Ollama as default provider.
    )
    echo.
    echo  [!] Edit .env to configure your preferred AI provider and API keys.
    echo  [!] Default: Ollama ^(free, local^). Make sure Ollama is running: ollama serve
    echo.
)

:: Launch Chainlit
echo  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo  🌐 Opening http://localhost:8000
echo  📋 Model: Check .env for MODEL_PROVIDER setting
echo.
echo  Press CTRL+C to stop the server.
echo  Or double-click STOP.bat to stop from another window.
echo.
echo  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

:: --headless prevents chainlit from auto-opening browser; we open one window ourselves
start "" http://localhost:8000
chainlit run app.py --port 8000 --headless

echo.
echo  [!] Server stopped.
pause
