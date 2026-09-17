@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo ComfyMax setup
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating ComfyMax Python environment...
    py -3.11 -m venv .venv
    if errorlevel 1 goto failed
)

echo Installing ComfyMax dependencies, including Whisper...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Installing or verifying the FlashVSR runtime...
if exist "engines\flashvsr\installer.py" (
    py -3.11 "engines\flashvsr\installer.py"
    if errorlevel 1 goto flashvsr_failed
) else (
    echo [WARNING] FlashVSR engine files were not found. Core ComfyMax setup will continue.
)

echo.
echo ==========================================
echo ComfyMax is ready.
echo ==========================================
echo Whisper is installed with ComfyMax.
echo FlashVSR models are optional and are NOT downloaded by this setup.
echo Run Download_FlashVSR_Models.bat when you want to enable FlashVSR upscaling.
echo.
echo Run Start_ComfyMax.bat to start ComfyMax.
exit /b 0

:flashvsr_failed
echo.
echo [WARNING] Core ComfyMax and Whisper were installed, but FlashVSR runtime setup failed.
echo You can still use ComfyMax and repair FlashVSR later with Install_FlashVSR.bat.
echo.
echo Run Start_ComfyMax.bat to start ComfyMax.
exit /b 0

:failed
echo Setup failed. Install 64-bit Python 3.11 with the Python launcher and retry.
pause
exit /b 1
