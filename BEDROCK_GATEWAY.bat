@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install JNAIQ first with INSTALL_JNAIQ.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\bedrock_gateway.py %*
if errorlevel 1 pause
