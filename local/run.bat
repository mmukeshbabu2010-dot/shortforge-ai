@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Creating ShortForge local bridge environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Could not create the Python environment. Install Python 3.11+ and try again.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Starting ShortForge Local YouTube Bridge...
echo Keep this window open while using ShortForge.
echo.
python agent.py
pause
