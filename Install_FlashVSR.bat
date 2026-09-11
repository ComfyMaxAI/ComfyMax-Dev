@echo off
setlocal
cd /d "%~dp0"
py -3.11 engines\flashvsr\installer.py %*
if errorlevel 1 (
    echo FlashVSR setup failed. Check the messages above. Python 3.11 is required.
    pause
    exit /b 1
)
echo FlashVSR is ready.
pause
