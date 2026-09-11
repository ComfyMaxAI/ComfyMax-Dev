@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo ComfyMax is ready. Run Start_ComfyMax.bat.
exit /b 0
:failed
echo Setup failed. Install Python 3.11 with the Python launcher and retry.
pause
exit /b 1
