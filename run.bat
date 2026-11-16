@echo off
rem Clip Studio launcher for Windows: sets everything up the first time, then starts the app.
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3")
if not defined PY (
  where python >nul 2>&1 && (python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python")
)
if not defined PY (
  echo.
  echo   Python 3.11 or newer is needed.
  echo   Install it with:  winget install Python.Python.3.12
  echo   or from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo   Then run this file again.
  echo.
  pause
  exit /b 1
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo.
  echo   ffmpeg not found - install it with:  winget install Gyan.FFmpeg
  echo   then CLOSE this window and run run.bat again ^(so Windows picks up the new PATH^).
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating a private Python environment in .venv ...
  %PY% -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
)
if not exist ".venv\.installed" (
  echo Installing Clip Studio's packages ^(a few minutes the first time^) ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Package install failed - check your internet connection. & pause & exit /b 1)
  echo ok> ".venv\.installed"
) else (
  rem Sites change often; a fresh yt-dlp keeps downloads working.
  ".venv\Scripts\python.exe" -m pip install -q --upgrade "yt-dlp[default]" deno >nul 2>&1
)

".venv\Scripts\python.exe" -m clipstudio %*
if errorlevel 1 pause
