@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First-time setup is required. Starting update.bat...
  call update.bat
  if errorlevel 1 exit /b 1
)

echo Starting SolvAI at http://127.0.0.1:5000
start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
pause
