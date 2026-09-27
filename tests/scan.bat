@echo off
cd /d "%~dp0"
echo.
echo =================================================
echo Financial AI - Scan and re-index reports
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup is required. Starting update.bat...
  call update.bat
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "from config import PARSER_VERSION; print('Parser version:', PARSER_VERSION)"
echo =================================================
".venv\Scripts\python.exe" -c "from engine import db; from engine.scanner import scan; db.init_db(); r=scan(); print(r)"
echo.
pause
