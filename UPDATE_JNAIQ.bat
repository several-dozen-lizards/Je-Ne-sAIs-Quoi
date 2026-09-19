@echo off
setlocal EnableExtensions
title Je Ne sAIs Quoi - update
cd /d "%~dp0"

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo Je Ne sAIs Quoi needs Windows PowerShell to check for updates.
  echo.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPDATE_JNAIQ.ps1" %*
set "JNAIQ_UPDATE_RESULT=%ERRORLEVEL%"

echo.
if "%JNAIQ_UPDATE_RESULT%"=="0" (
  echo Update check finished.
) else (
  echo The update did not finish. The explanation above says what needs attention.
)

if not "%JNAIQ_UPDATE_NO_PAUSE%"=="1" pause
exit /b %JNAIQ_UPDATE_RESULT%
