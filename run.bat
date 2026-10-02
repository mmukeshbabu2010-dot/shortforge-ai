@echo off
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r app\requirements.txt
where ffmpeg >nul 2>nul
if errorlevel 1 echo [ShortForge] FFmpeg was not found in PATH. Install FFmpeg before processing videos.
python -m uvicorn app.main:app --reload
pause
