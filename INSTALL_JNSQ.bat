@echo off
setlocal
title JNSQ - first installation
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer, then run this again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -X utf8 shell\first_run.py
if errorlevel 1 goto :failed
echo.
echo Installation complete. Run START_NEXUS.bat when you are ready.
pause
exit /b 0
:failed
echo.
echo Installation stopped because a command failed. Nothing personal was uploaded.
pause
exit /b 1
