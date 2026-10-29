@echo off
setlocal
pushd "%~dp0"
python -m user_tools.install_engineering
set "RESULT=%ERRORLEVEL%"
popd
pause
exit /b %RESULT%
