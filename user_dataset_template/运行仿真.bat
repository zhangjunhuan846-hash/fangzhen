@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem ===========================================================
rem  第二步：运行 zero-fit baseline
rem  必须先成功运行「导入并检查数据.bat」
rem ===========================================================

echo.
echo ============================================================
echo   运行 zero-fit baseline
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

wsl.exe -d Ubuntu -e bash -lc "source ~/miniforge3/etc/profile.d/conda.sh && conda activate pybamm && cd \"$USERROOT\" && python -m user_tools.run_baseline --package \"$USERPKG\" --models DFN"
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
    echo ============================================================
    echo   出错了（退出码 %RC%）
    echo.
    echo   常见原因：
    echo     1. 还没有成功运行「导入并检查数据.bat」
    echo     2. 上次导入有严重错误（报告里显示“数据导入：FAIL”）
    echo     3. 数据时间太长，求解器超时
    echo ============================================================
    echo.
    pause
    exit /b %RC%
)

echo ============================================================
echo   完成。
echo.
echo   指标表：outputs\user_datasets\你的数据集名称\baseline_metrics.csv
echo   曲线图：outputs\platform\user_你的数据集名称\baseline\DFN\...
echo.
echo   提醒：这是 zero-fit baseline，没有做任何拟合。
echo        RMSE 只描述差异大小，不代表模型已被验证。
echo ============================================================
echo.
pause
endlocal
