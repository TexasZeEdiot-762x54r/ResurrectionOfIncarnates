@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\play.ps1"
if errorlevel 1 (
    echo Game launch failed. Review the error above and tools\logs\play.log.
    pause
    exit /b 1
)

