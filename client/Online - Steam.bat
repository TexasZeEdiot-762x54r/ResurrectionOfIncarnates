@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\online.ps1" -Mode public -NoPause
if errorlevel 1 goto failed
call "%~dp0Play Rise of Incarnates.bat"
exit /b %errorlevel%
:failed
pause
exit /b 1

