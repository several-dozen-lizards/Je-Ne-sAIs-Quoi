@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m shell.comfyui_service --stop
) else (
  py -3 -m shell.comfyui_service --stop
)
