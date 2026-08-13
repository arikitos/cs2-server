@echo off
setlocal
cd /d "%~dp0"
title CS2 Server Setup

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo Windows PowerShell was not found.
    echo Install or repair PowerShell, then run this installer again.
    pause
    exit /b 1
)

echo Starting the CS2 server installer.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-on-windows.ps1"
set "setup_exit_code=%ERRORLEVEL%"

echo.
if not "%setup_exit_code%"=="0" (
    echo Installation failed with exit code %setup_exit_code%.
    echo Review the error above, then run install-windows.cmd again.
    pause
    exit /b %setup_exit_code%
)

echo Installation completed successfully.
echo The dashboard address is shown above.
pause
exit /b 0
