@echo off
title JNSQ Household - shutdown
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 shell\boot.py --stop
) else (
  python -X utf8 shell\boot.py --stop
)
echo.
pause
