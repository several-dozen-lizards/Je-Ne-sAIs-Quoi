@echo off
title JNSQ Household
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 shell\boot.py --session
) else (
  python -X utf8 shell\boot.py --session
)
if errorlevel 1 (
  echo.
  echo JNSQ could not start. The details are above.
  pause
)
