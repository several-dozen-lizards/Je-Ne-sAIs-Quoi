@echo off
rem Legacy filename retained for existing downloads and shortcuts.
call "%~dp0UPDATE_JNAIQ.bat" %*
exit /b %ERRORLEVEL%
