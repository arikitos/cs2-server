@echo off
setlocal
cd /d "%~dp0"
title CS2 Control Panel Setup

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo Windows PowerShell was not found.
    echo Install or repair PowerShell, then run this installer again.
    pause
    exit /b 1
)

echo Starting the panel installer. Game files are installed later from the dashboard.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "setup_exit_code=%ERRORLEVEL%"

echo.
if not "%setup_exit_code%"=="0" (
    echo Installation failed with exit code %setup_exit_code%.
    echo Review the error above, then run run-setup.cmd again.
    pause
    exit /b %setup_exit_code%
)

echo Panel installation completed successfully.
echo Use Maintenance ^> Install server in the dashboard to install game files.
echo The dashboard address is shown above.
pause
exit /b 0
