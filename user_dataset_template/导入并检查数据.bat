@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem ===========================================================
rem  第一步：导入并检查数据
rem  把你的数据放进 raw 文件夹、填好 dataset_info.xlsx 后双击本文件
rem ===========================================================

echo.
echo ============================================================
echo   电池数据导入与检查
echo ============================================================
echo.

where wsl.exe >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 WSL。请先确认本机已安装 WSL 与 Ubuntu 发行版。
    echo.
    pause
    exit /b 1
)

set "USERPKG=%~dp0"
set "USERROOT=%~dp0.."
set "WSLENV=USERPKG/p:USERROOT/p"

wsl.exe -d Ubuntu -e bash -lc "source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm && cd \"$USERROOT\" && python -m user_tools.import_dataset --package \"$USERPKG\""
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
    echo ============================================================
    echo   出错了（退出码 %RC%）
    echo.
    echo   常见原因：
    echo     1. raw 文件夹里没有数据文件，或有多个数据文件
    echo     2. dataset_info.xlsx 里必填项没填
    echo     3. column_mapping 里的列名和你的数据文件不一致
    echo     4. 数据里有空值，或电流符号声明填反了
    echo.
    echo   若导入成功但仍有问题，请打开下面的报告：
    echo     outputs\user_datasets\你的数据集名称\validation_report.html
    echo ============================================================
    echo.
    pause
    exit /b %RC%
)

echo ============================================================
echo   完成。请打开报告查看：
echo.
echo     outputs\user_datasets\你的数据集名称\validation_report.html
echo.
echo   报告里显示“仿真：AVAILABLE”时，再双击「运行仿真.bat」。
echo ============================================================
echo.
pause
endlocal
