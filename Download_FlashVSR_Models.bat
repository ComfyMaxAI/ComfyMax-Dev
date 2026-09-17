@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1

echo ==========================================
echo ComfyMax - FlashVSR model installer
echo ==========================================
echo.
echo This downloads the optional FlashVSR v1.1 BF16 model files.
echo Existing files are reused only when their SHA-256 checksum is valid.
echo Model folder: "%CD%\engines\flashvsr\models"
echo.

if not exist "engines\flashvsr\model_installer.py" goto missing_files
if not exist "engines\flashvsr\models.json" goto missing_files

py -3.11 -c "import struct, sys; sys.exit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto missing_python

py -3.11 "engines\flashvsr\model_installer.py" %*
set "FLASHVSR_EXIT=%ERRORLEVEL%"
if not "%FLASHVSR_EXIT%"=="0" goto setup_failed

echo.
echo FlashVSR models are ready.
popd
pause
exit /b 0

:missing_files
echo [ERROR] FlashVSR model installer files are missing.
set "FLASHVSR_EXIT=1"
goto failed

:missing_python
echo [ERROR] 64-bit Python 3.11 and the Windows Python launcher are required.
set "FLASHVSR_EXIT=1"
goto failed

:setup_failed
echo [ERROR] FlashVSR model installation failed. Review the messages above.
echo You can safely run this BAT again; verified models will be reused.

:failed
popd
pause
exit /b %FLASHVSR_EXIT%
