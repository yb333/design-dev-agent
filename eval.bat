@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM 设计开发 Agent 评测系统 - 交互式菜单入口
REM 双击此文件即可启动

REM 找 Python（先试 python，再试 py launcher）
python --version >nul 2>&1
if not errorlevel 1 goto run_python

py -3 --version >nul 2>&1
if not errorlevel 1 goto run_py3

echo.
echo ==========================================
echo   未找到 Python 3.10+
echo ==========================================
echo.
echo   请安装: winget install Python.Python.3.12
echo   或 https://www.python.org/downloads/
echo   安装时勾选 "Add Python to PATH"
echo.
pause
exit /b 1

:run_python
python eval-suite\v2\menu.py %*
goto finish

:run_py3
py -3 eval-suite\v2\menu.py %*
goto finish

:finish
REM menu.py 退出后停留窗口看结果
pause
