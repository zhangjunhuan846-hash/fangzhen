@echo off
setlocal
set "ROOT=%~dp0"
set "READY=%ROOT%outputs\fangzhen_workbench_ui_v0310_ready\FangzhenResearch\FangzhenResearch.exe"
set "BUILT=%ROOT%outputs\fangzhen_workbench_ui_v0310\FangzhenResearch\FangzhenResearch.exe"
if exist "%READY%" (
  start "" "%READY%"
  exit /b 0
)
if exist "%BUILT%" (
  start "" "%BUILT%"
  exit /b 0
)
pushd "%ROOT%"
python -m user_tools.research_workbench
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" pause
exit /b %RESULT%
