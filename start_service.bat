@echo off
setlocal enabledelayedexpansion
title 天工會議紀錄 - 服務啟動入口
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_service.ps1"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [警告] 服務啟動過程返回代碼: %ERRORLEVEL%
)
pause
