@echo off
chcp 65001 >nul 2>&1
REM sync_to_team.bat — 薄入口（内网 Windows 实际运行；开发环境测试用 sync_to_team.sh）
REM 核心逻辑在 sync_to_team.py。双击 = 交互菜单；带参数 = 原样透传。
set "SCRIPT=%~dp0sync_to_team.py"

if "%~1"=="" (
    python "%SCRIPT%" --menu
) else (
    python "%SCRIPT%" %*
)
if errorlevel 9009 goto :fallback
set "EC=%errorlevel%"
goto :end

:fallback
if "%~1"=="" (
    py -3 "%SCRIPT%" --menu
) else (
    py -3 "%SCRIPT%" %*
)
set "EC=%errorlevel%"

:end
echo.
pause
exit /b %EC%
