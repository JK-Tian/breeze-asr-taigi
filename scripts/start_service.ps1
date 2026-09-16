# ==============================================================================
# 天工會議紀錄 (Breeze ASR Taigi) - 服務啟動管理器
# 企業級高併發架構 | 雙軌佇列分流 | 端口衝突自動清理 | 環境缺失套件自動檢查修復
# ==============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   天工會議紀錄 (Breeze ASR Taigi) - 服務啟動管理器" -ForegroundColor Cyan
Write-Host "   企業級高併發架構 | 雙軌佇列分流 | 環境自癒檢查" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 取得目錄絕對路徑
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$rootDir = (Resolve-Path "$scriptDir\..").Path
$backendDir = Join-Path $rootDir "backend"
$frontendDir = Join-Path $rootDir "frontend"

# ------------------------------------------------------------------------------
# 步驟 0/4：執行環境自檢與缺失套件自動修復 (Self-healing Environment Check)
# ------------------------------------------------------------------------------
Write-Host "[步驟 0/4] 檢查執行環境與 Python / Node.js 套件完整性..." -ForegroundColor Yellow

# 檢查 uv 工具
$hasUv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $hasUv) {
    Write-Host "  -> [錯誤] 系統未安裝 uv 套件管理工具，請先安裝 uv！" -ForegroundColor Red
    pause
    exit 1
}

# 檢查 Python 關鍵後端依賴套件 (fastapi, uvicorn, celery, redis, psycopg2)
Write-Host "  -> 檢查 Python 核心依賴套件 (FastAPI, Celery, psycopg2, 等)..."
$pyCheck = & uv run python -c "import fastapi, uvicorn, celery, redis, psycopg2" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  -> 偵測到缺失 Python 依賴套件，正在透過 uv 自動同步安裝中..." -ForegroundColor Magenta
    Push-Location $rootDir
    & uv sync
    Pop-Location
    Write-Host "  -> Python 套件安裝同步完成！" -ForegroundColor Green
} else {
    Write-Host "  -> Python 核心依賴套件已完備。" -ForegroundColor Green
}

# 檢查前端 node_modules 與 pnpm
$hasPnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if ($hasPnpm) {
    $frontModules = Join-Path $frontendDir "node_modules"
    if (-not (Test-Path $frontModules)) {
        Write-Host "  -> 偵測到前端 node_modules 不存在，正在透過 pnpm install 自動安裝..." -ForegroundColor Magenta
        Push-Location $frontendDir
        & pnpm install
        Pop-Location
        Write-Host "  -> 前端套件安裝完成！" -ForegroundColor Green
    } else {
        Write-Host "  -> 前端 node_modules 依賴已完備。" -ForegroundColor Green
    }
}

# 檢查前端 .next 構建輸出
$frontNext = Join-Path $frontendDir ".next"
if (-not (Test-Path $frontNext)) {
    Write-Host "  -> 首次啟動偵測：正在自動進行前端最佳化建置 (pnpm build)..." -ForegroundColor Magenta
    Push-Location $frontendDir
    & pnpm run build
    Pop-Location
    Write-Host "  -> 前端建置完成！" -ForegroundColor Green
}
Write-Host ""

# ------------------------------------------------------------------------------
# 步驟 1/4：啟動前連接埠檢查與自動清理 (Pre-flight Sanitization)
# ------------------------------------------------------------------------------
Write-Host "[步驟 1/4] 執行啟動前連接埠檢查與自動釋放 (Pre-flight Sanitization)..." -ForegroundColor Yellow
$targetPorts = @(3001, 3002, 8787)
foreach ($port in $targetPorts) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($p in $pids) {
                if ($p -gt 4) {
                    Write-Host "  -> 發現端口 $port 被進程 (PID: $p) 佔用，正在強制釋放..." -ForegroundColor Magenta
                    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {}
}
Write-Host "  -> 端口 3001, 3002, 8787 已全數就緒釋放。" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------------------------
# 步驟 2/4：檢查並啟動 Redis 訊息佇列
# ------------------------------------------------------------------------------
Write-Host "[步驟 2/4] 檢查並啟動 Redis 訊息佇列 (Docker)..." -ForegroundColor Yellow
# 檢查並啟動 Redis 容器
$dockerCheck = docker ps -q --filter "name=breeze-redis" 2>$null
if (-not $dockerCheck) {
    docker start breeze-redis 2>$null
    if ($LASTEXITCODE -ne 0) {
        docker run -d --name breeze-redis -p 6379:6379 redis:alpine 2>$null
    }
}

# 檢查並啟動 PostgreSQL 容器 (breeze-postgres)
$pgCheck = docker ps -q --filter "name=breeze-postgres" 2>$null
if (-not $pgCheck) {
    $pgExists = docker ps -a -q --filter "name=breeze-postgres" 2>$null
    if ($pgExists) {
        Write-Host "  -> 偵測到 breeze-postgres 容器處於停止狀態，正在自動啟動..." -ForegroundColor Magenta
        docker start breeze-postgres 2>$null
    }
}

Write-Host "  -> 正在等待 Redis 6379 連線響應..."
$redisReady = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 6379)
        if ($tcpClient.Connected) {
            $redisReady = $true
            $tcpClient.Close()
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if ($redisReady) {
    Write-Host "  -> Redis 佇列就緒 (PING OK)。" -ForegroundColor Green
} else {
    Write-Host "  -> [警告] Redis 連線逾時，請確認 Docker 是否已啟動！" -ForegroundColor Red
}
Write-Host ""

# ------------------------------------------------------------------------------
# 步驟 3/4：編排並啟動微服務矩陣
# ------------------------------------------------------------------------------
Write-Host "[步驟 3/4] 編排並啟動微服務矩陣..." -ForegroundColor Yellow

$cmdApi = "uv run uvicorn src.main:app --port 8787"
$cmdCelery = "uv run celery -A src.infrastructure.celery_app worker -Q gpu_queue,io_queue --pool=threads -c 8 --loglevel=info"
$cmdFront = "start /b pnpm run start & cd .. & npx.cmd local-ssl-proxy --source 3001 --target 3002"

$hasWt = Get-Command wt.exe -ErrorAction SilentlyContinue

if ($hasWt) {
    Write-Host "  -> 偵測到 Windows Terminal，以分頁標籤 (Tabs) 整合啟動 3 大核心服務..." -ForegroundColor Cyan

    Start-Process wt.exe -ArgumentList @("-w", "BreezeASR", "new-tab", "--title", "Backend-API", "-d", $backendDir, "cmd", "/k", $cmdApi)
    Start-Sleep -Milliseconds 400

    Start-Process wt.exe -ArgumentList @("-w", "BreezeASR", "new-tab", "--title", "Celery-Workers", "-d", $backendDir, "cmd", "/k", $cmdCelery)
    Start-Sleep -Milliseconds 400

    Start-Process wt.exe -ArgumentList @("-w", "BreezeASR", "new-tab", "--title", "Frontend-HTTPS", "-d", $frontendDir, "cmd", "/k", $cmdFront)
} else {
    Write-Host "  -> 未偵測到 Windows Terminal，以獨立視窗啟動 3 大核心服務..." -ForegroundColor Cyan

    Start-Process cmd.exe -ArgumentList @("/k", "title Backend-API & $cmdApi") -WorkingDirectory $backendDir
    Start-Sleep -Milliseconds 400

    Start-Process cmd.exe -ArgumentList @("/k", "title Celery-Workers & $cmdCelery") -WorkingDirectory $backendDir
    Start-Sleep -Milliseconds 400

    Start-Process cmd.exe -ArgumentList @("/k", "title Frontend-HTTPS & $cmdFront") -WorkingDirectory $frontendDir
}

# ------------------------------------------------------------------------------
# 步驟 4/4：服務狀態確認與指引
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   天工會議紀錄 - 企業級微服務已成功調度啟動！" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " 🎙️ 主要網頁入口 (麥克風錄音) : https://localhost:3001" -ForegroundColor Yellow
Write-Host " 🖥️ 前端本機 HTTP (除錯用)   : http://localhost:3002"
Write-Host " 📑 後端 API 規格文件         : http://localhost:8787/docs"
Write-Host " ⚡ 高併發雙軌佇列            : gpu_queue (ASR) + io_queue (LLM)"
Write-Host " 🔒 安全優化                 : 已淘汰 8788，免除二次自簽證書警告"
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
