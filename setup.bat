@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.13 -m venv .venv
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements-model.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-gps.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe main.py check
if errorlevel 1 goto failed
echo Setup complete. Start run_demo.bat.
pause
exit /b 0
:failed
echo Setup did not complete. Read the error above before retrying.
pause
exit /b 1
