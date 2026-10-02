@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo   ShortForge Local YouTube Bridge
echo ========================================
echo.

set "PYTHON_EXE="
set "USE_PY_LAUNCHER=0"

rem Find Python first.
where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  set "USE_PY_LAUNCHER=1"
)

rem If Python is missing, install it automatically with Windows Package Manager.
if not defined PYTHON_EXE (
  where winget >nul 2>&1
  if errorlevel 1 (
    echo Python was not found and Windows Package Manager is unavailable.
    echo Please install Python 3.11+ from https://www.python.org/downloads/windows/ and run this file again.
    pause
    exit /b 1
  )
  echo Python is not installed. Installing it automatically...
  winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo Python installation did not complete.
    pause
    exit /b 1
  )
  rem The current terminal may not have the refreshed PATH, so locate the new Python directly.
  for /f "delims=" %%P in ('powershell -NoProfile -Command "$p=Get-ChildItem $env:LocalAppData\Programs\Python\Python*\python.exe -ErrorAction SilentlyContinue ^| Sort-Object FullName -Descending ^| Select-Object -First 1 -ExpandProperty FullName; if($p){$p}"') do set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
  echo Could not locate Python after installation.
  echo Close this window, reopen run.bat, and try again.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo Creating the local bridge environment...
  if "%USE_PY_LAUNCHER%"=="1" (
    %PYTHON_EXE% -3 -m venv .venv
  ) else (
    "%PYTHON_EXE%" -m venv .venv
  )
  if errorlevel 1 (
    echo Could not create the Python environment.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --disable-pip-version-check
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo Could not install the local bridge dependencies.
  pause
  exit /b 1
)

echo.
echo Local bridge is starting...
echo Keep this window open while using ShortForge.
echo You can now refresh ShortForge and click Analyze Video.
echo.
python agent.py
pause
