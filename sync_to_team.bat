@echo off
chcp 65001 >nul 2>&1
REM sync_to_team.bat — 薄入口（内网 Windows 实际运行；开发环境测试用 sync_to_team.sh）
REM 核心逻辑在 sync_to_team.py，参数原样透传。
set "SCRIPT=%~dp0sync_to_team.py"

python "%SCRIPT%" %*
if errorlevel 9009 goto :fallback
set "EC=%errorlevel%"
goto :end

:fallback
py -3 "%SCRIPT%" %*
set "EC=%errorlevel%"

:end
echo.
pause
exit /b %EC%
