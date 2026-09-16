@echo off
chcp 65001 >nul
title 天工會議紀錄 - 企業級服務啟動管理器

echo ==========================================================
echo    天工會議紀錄 (Breeze ASR Taigi) - 服務啟動管理器
echo    企業級高併發架構 ^| 雙軌佇列分流 ^| 端口衝突自動清理
echo ==========================================================
echo.

echo [步驟 1/4] 執行啟動前連接埠檢查與自動清理 (Pre-flight Sanitization)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ports = 3001, 3002, 8787; foreach ($port in $ports) { " ^
    "    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue; " ^
    "    if ($conn) { " ^
    "        $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique; " ^
    "        foreach ($p in $pids) { " ^
    "            if ($p -gt 4) { " ^
    "                Write-Host \"[清理] 釋放端口 $port (終止殘留進程 PID: $p)...\"; " ^
    "                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue " ^
    "            } " ^
    "        } " ^
    "    } " ^
    "}"
echo 端口檢查完成 (3001, 3002, 8787 已就緒)。
echo.

echo [步驟 2/4] 啟動與檢查 Redis 訊息佇列...
docker start breeze-redis 2>nul || docker run -d --name breeze-redis -p 6379:6379 redis:alpine >nul 2>nul

echo 正在等待 Redis 佇列就緒...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ready = $false; for ($i=0; $i -lt 15; $i++) { " ^
    "    try { " ^
    "        $tcp = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 6379); " ^
    "        if ($tcp.Connected) { $ready = $true; $tcp.Close(); break; } " ^
    "    } catch {} " ^
    "    Start-Sleep -Milliseconds 500; " ^
    "}; " ^
    "if ($ready) { Write-Host 'Redis 佇列就緒 (PING OK)。' } else { Write-Warning 'Redis 連線超時，請檢查 Docker 服務！' }"
echo.

echo [步驟 3/4] 編排並啟動微服務矩陣...
where wt >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo 偵測到 Windows Terminal，將以標籤頁 (Tabs) 整合啟動 3 大核心服務...
    wt -w "BreezeASR" new-tab --title "後端API-FastAPI" -d "%~dp0backend" cmd /k "echo [FastAPI] 啟動高併發 Web API 網關... & uv run uvicorn src.main:app --port 8787"
    wt -w "BreezeASR" new-tab --title "雙軌Worker-Celery" -d "%~dp0backend" cmd /k "echo [Celery] 啟動雙軌運算矩陣 (GPU限流 + IO多執行緒並發)... & uv run celery -A src.infrastructure.celery_app worker -Q gpu_queue,io_queue --pool=threads -c 8 --loglevel=info"
    wt -w "BreezeASR" new-tab --title "前端與HTTPS代理" -d "%~dp0frontend" cmd /k "echo [Frontend] 啟動 Next.js 並掛載 3001 HTTPS 麥克風閘道... & (if not exist .next pnpm run build) & start /b pnpm run start & cd .. & npx.cmd local-ssl-proxy --source 3001 --target 3002"
) else (
    echo 未偵測到 Windows Terminal，以獨立視窗整合啟動 3 大核心服務...
    cd /d "%~dp0backend"
    start "天工後端 API (FastAPI:8787)" cmd /k "uv run uvicorn src.main:app --port 8787"
    start "天工雙軌 Worker (Celery)" cmd /k "uv run celery -A src.infrastructure.celery_app worker -Q gpu_queue,io_queue --pool=threads -c 8 --loglevel=info"
    
    cd /d "%~dp0frontend"
    start "天工前端與麥克風 HTTPS 網關 (3001->3002)" cmd /k "(if not exist .next pnpm run build) & start /b pnpm run start & cd .. & npx local-ssl-proxy --source 3001 --target 3002"
)

echo.
echo [步驟 4/4] 服務狀態確認與就緒指引
echo ==========================================================
echo    天工會議紀錄 - 企業級微服務已成功調度啟動！
echo ==========================================================
echo  🎙️ 主要網頁入口 (麥克風錄音) : https://localhost:3001
echo  🖥️ 前端本機 HTTP (除錯用)   : http://localhost:3002
echo  📑 後端 API 規格文件         : http://localhost:8787/docs
echo  ⚡ 高併發雙軌佇列            : gpu_queue (ASR) + io_queue (LLM)
echo  🔒 安全優化                 : 已淘汰 8788，免除二次自簽證書警告
echo ==========================================================
echo.
pause
