@echo off
setlocal EnableExtensions
title Je Ne Sais Quoi - update
cd /d "%~dp0"

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo Je Ne Sais Quoi needs Windows PowerShell to check for updates.
  echo.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPDATE_JNSQ.ps1" %*
set "JNSQ_UPDATE_RESULT=%ERRORLEVEL%"

echo.
if "%JNSQ_UPDATE_RESULT%"=="0" (
  echo Update check finished.
) else (
  echo The update did not finish. The explanation above says what needs attention.
)

if not "%JNSQ_UPDATE_NO_PAUSE%"=="1" pause
exit /b %JNSQ_UPDATE_RESULT%
