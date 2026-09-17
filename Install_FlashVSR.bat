@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1

echo ==========================================
echo ComfyMax - FlashVSR runtime setup
echo ==========================================
echo.
echo This installs or repairs the isolated FlashVSR runtime only.
echo FlashVSR model files are installed separately with:
echo Download_FlashVSR_Models.bat
echo.

if not exist "engines\flashvsr\installer.py" goto missing_files
if not exist "engines\flashvsr\requirements.lock.txt" goto missing_files
if not exist "engines\flashvsr\check_install.py" goto missing_files
if not exist "engines\flashvsr\flashvsr_worker.py" goto missing_files

py -3.11 -c "import struct, sys; sys.exit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto missing_python

py -3.11 "engines\flashvsr\installer.py" %*
set "FLASHVSR_EXIT=%ERRORLEVEL%"
if not "%FLASHVSR_EXIT%"=="0" goto setup_failed

echo.
echo FlashVSR runtime is ready.
echo To install the optional model files, run Download_FlashVSR_Models.bat.
popd
pause
exit /b 0

:missing_files
echo [ERROR] FlashVSR engine files are missing.
echo Place this script in the complete ComfyMax project folder beside App.py.
set "FLASHVSR_EXIT=1"
goto failed

:missing_python
echo [ERROR] 64-bit Python 3.11 and the Windows Python launcher are required.
echo Install Python 3.11 with its launcher, then run this script again.
set "FLASHVSR_EXIT=1"
goto failed

:setup_failed
echo [ERROR] FlashVSR runtime setup or verification failed. Review the messages above.

:failed
popd
pause
exit /b %FLASHVSR_EXIT%
