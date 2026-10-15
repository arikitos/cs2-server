@echo off
call "%~dp0server\scripts\run-setup.cmd" %*
exit /b %ERRORLEVEL%
