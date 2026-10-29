@echo off
setlocal
set "ROOT=%~dp0"
set "EIS_HPPC=%ROOT%outputs\fangzhen_workbench_eis_hppc_20261029\FangzhenResearch\FangzhenResearch.exe"
set "STANFORD=%ROOT%outputs\fangzhen_workbench_stanford_20261029_v2\FangzhenResearch\FangzhenResearch.exe"
set "COLD=%ROOT%outputs\fangzhen_workbench_cold_20261029\FangzhenResearch\FangzhenResearch.exe"
set "CALB=%ROOT%outputs\fangzhen_workbench_calb_20261029\FangzhenResearch\FangzhenResearch.exe"
set "EIS_BMS=%ROOT%outputs\fangzhen_workbench_eis_bms_20261029\FangzhenResearch\FangzhenResearch.exe"
set "EIS_GRID=%ROOT%outputs\fangzhen_workbench_eis_grid_20261029\FangzhenResearch\FangzhenResearch.exe"
set "HARDCARBON_DFN=%ROOT%outputs\fangzhen_workbench_hardcarbon_dfn_20261029_v2\FangzhenResearch\FangzhenResearch.exe"
set "RESEARCH=%ROOT%outputs\fangzhen_workbench_research_20261029_final\FangzhenResearch\FangzhenResearch.exe"
set "SODIUM_GENERALIZATION=%ROOT%outputs\fangzhen_workbench_sodium_generalization_20261029\FangzhenResearch\FangzhenResearch.exe"
set "SODIUM=%ROOT%outputs\fangzhen_workbench_sodium_20261029_final\FangzhenResearch\FangzhenResearch.exe"
set "MULTICHEM=%ROOT%outputs\fangzhen_workbench_multichem_20261029_release\FangzhenResearch\FangzhenResearch.exe"
set "READY=%ROOT%outputs\fangzhen_workbench_ui_v0314_final\FangzhenResearch\FangzhenResearch.exe"
set "BUILT=%ROOT%outputs\fangzhen_workbench_ui_v0313_release\FangzhenResearch\FangzhenResearch.exe"
if exist "%EIS_HPPC%" (
  start "" "%EIS_HPPC%"
  exit /b 0
)
if exist "%STANFORD%" (
  start "" "%STANFORD%"
  exit /b 0
)
if exist "%COLD%" (
  start "" "%COLD%"
  exit /b 0
)
if exist "%CALB%" (
  start "" "%CALB%"
  exit /b 0
)
if exist "%EIS_BMS%" (
  start "" "%EIS_BMS%"
  exit /b 0
)
if exist "%EIS_GRID%" (
  start "" "%EIS_GRID%"
  exit /b 0
)
if exist "%HARDCARBON_DFN%" (
  start "" "%HARDCARBON_DFN%"
  exit /b 0
)
if exist "%RESEARCH%" (
  start "" "%RESEARCH%"
  exit /b 0
)
if exist "%SODIUM_GENERALIZATION%" (
  start "" "%SODIUM_GENERALIZATION%"
  exit /b 0
)
if exist "%SODIUM%" (
  start "" "%SODIUM%"
  exit /b 0
)
if exist "%MULTICHEM%" (
  start "" "%MULTICHEM%"
  exit /b 0
)
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
