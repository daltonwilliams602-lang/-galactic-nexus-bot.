@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Nexus.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m nexus.launch
pause
