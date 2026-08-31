@echo off
echo ==========================================
echo    Starting Breeze ASR Taigi Service
echo ==========================================

echo [1/2] Starting Redis Queue...
docker start breeze-redis 2>nul || docker run -d --name breeze-redis -p 6379:6379 redis:alpine

echo [2/2] Launching Services...

where wt >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo Windows Terminal detected. Opening all services in new tabs...
    wt -w "Breeze" new-tab --title BackendAPI -d "%~dp0backend" cmd /k uv run uvicorn src.main:app --reload --reload-dir src --port 8787
    wt -w "Breeze" new-tab --title CeleryWorker -d "%~dp0backend" cmd /k uv run celery -A src.infrastructure.celery_app worker --pool=solo --loglevel=info
    wt -w "Breeze" new-tab --title Frontend -d "%~dp0frontend" cmd /k pnpm run dev
    wt -w "Breeze" new-tab --title ProxyFront -d "%~dp0." cmd /k npx.cmd local-ssl-proxy --source 3001 --target 3002
    wt -w "Breeze" new-tab --title ProxyBack -d "%~dp0." cmd /k npx.cmd local-ssl-proxy --source 8788 --target 8787
) else (
    echo Windows Terminal not found. Falling back to separate windows...
    cd /d "%~dp0backend"
    start "Backend API" cmd /k "uv run uvicorn src.main:app --reload --reload-dir src --port 8787"
    start "Celery Worker" cmd /k "uv run celery -A src.infrastructure.celery_app worker --pool=solo --loglevel=info"
    
    cd /d "%~dp0frontend"
    start "Frontend" cmd /k "pnpm run dev"
    
    cd /d "%~dp0"
    start "Frontend HTTPS Proxy" cmd /k "npx local-ssl-proxy --source 3001 --target 3002"
    start "Backend HTTPS Proxy" cmd /k "npx local-ssl-proxy --source 8788 --target 8787"
)

echo.
echo ==========================================
echo Services have been started!
echo Frontend (HTTP) : http://localhost:3002
echo Frontend (HTTPS): https://localhost:3001  (Please use this for Microphone)
echo Backend API     : Proxied by Frontend (http://localhost:8787 in background)
echo Backend HTTPS   : https://localhost:8788
echo ==========================================
pause
