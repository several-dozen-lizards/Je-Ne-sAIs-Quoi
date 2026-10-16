@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo World publishing needs Node.js. Install it from https://nodejs.org then rerun this installer.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL_JNAIQ.bat in this public installation first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\install_public_3d.py
if errorlevel 1 (
  echo Installation did not complete. Existing creations are preserved.
  pause
  exit /b 1
)
pause
