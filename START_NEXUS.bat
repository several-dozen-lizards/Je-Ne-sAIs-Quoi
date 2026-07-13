@echo off
title JNSQ Household
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 shell\boot.py
) else (
  python -X utf8 shell\boot.py
)
echo.
pause
