@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1

echo ==========================================
echo ComfyMax - optional FlashVSR v1.1 setup
echo ==========================================
echo.
REM Keep dependency installation, model hashes and locking in the existing installer.
REM The runtime needs the Wan2GP BF16 conversions, not renamed upstream checkpoints.
echo Runtime: FlashVSR v1.1 Tiny-Long, 2x
echo Model folder: "%CD%\engines\flashvsr\models"
echo Compatible models: https://huggingface.co/DeepBeepMeep/Wan2.1/tree/main/FlashVSR
echo Upstream: https://huggingface.co/JunhaoZhuang/FlashVSR-v1.1
echo.
echo Normal setup installs the isolated environment and downloads missing models.
echo Existing models are checked with SHA-256 and reused when valid.
echo --check verifies the installation without installing or downloading.
echo --models-from "folder" reuses local model files after verification.
echo.

if not exist "engines\flashvsr\installer.py" goto missing_files
if not exist "engines\flashvsr\models.json" goto missing_files
if not exist "engines\flashvsr\requirements.lock.txt" goto missing_files
if not exist "engines\flashvsr\check_install.py" goto missing_files
if not exist "engines\flashvsr\flashvsr_worker.py" goto missing_files

py -3.11 -c "import struct, sys; sys.exit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto missing_python

py -3.11 "engines\flashvsr\installer.py" %*
set "FLASHVSR_EXIT=%ERRORLEVEL%"
if not "%FLASHVSR_EXIT%"=="0" goto setup_failed

echo.
echo FlashVSR command completed successfully.
echo For an installation check, run install_FlashVSR.bat --check.
echo Before upscaling, save your existing ComfyUI output folder in Settings.
echo Upscaled videos will be saved beneath it in videos\upscaled.
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
echo [ERROR] FlashVSR setup or verification failed. Review the messages above.
echo Resolve the reported dependency, download, checksum or GPU error and retry.
echo See README.md for troubleshooting.

:failed
popd
pause
exit /b %FLASHVSR_EXIT%
