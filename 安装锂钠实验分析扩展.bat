@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0user_tools\install_multichem.ps1"
if not "%ERRORLEVEL%"=="0" pause
