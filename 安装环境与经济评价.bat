@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0user_tools\setup_sustainability.ps1"
pause
