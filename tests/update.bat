@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating the private SolvAI Python environment...
  py -3 -m venv .venv 2>nul
  if errorlevel 1 python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Python 3 could not be found. Install Python 3.11 or newer, then run this file again.
  pause
  exit /b 1
)

echo Updating required packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo Running the SolvAI environment check...
".venv\Scripts\python.exe" diagnose.py
if errorlevel 1 goto :failed

echo.
echo SolvAI is ready. Use run.bat to start it.
pause
exit /b 0

:failed
echo.
echo The update did not complete. Check the message above and your internet or proxy settings.
pause
exit /b 1
