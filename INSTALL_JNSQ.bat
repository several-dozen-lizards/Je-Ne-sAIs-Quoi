@echo off
setlocal EnableExtensions
title Je Ne Sais Quoi - setup
cd /d "%~dp0"

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo Je Ne Sais Quoi needs Windows PowerShell to run its setup.
  echo PowerShell was not found on this computer.
  echo.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0SETUP_JNSQ.ps1" %*
set "JNSQ_SETUP_RESULT=%ERRORLEVEL%"

echo.
if "%JNSQ_SETUP_RESULT%"=="0" (
  echo Setup finished successfully.
) else (
  echo Setup did not finish. The explanation above says what needs attention.
)

if not "%JNSQ_SETUP_NO_PAUSE%"=="1" pause
exit /b %JNSQ_SETUP_RESULT%
