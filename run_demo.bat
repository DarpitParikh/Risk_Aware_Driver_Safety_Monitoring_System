@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py demo
) else (
    py -3.13 main.py demo
)
if errorlevel 1 pause
