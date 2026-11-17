@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat on this PC first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe phone_fleet.py
if errorlevel 1 pause
