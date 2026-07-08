#!/bin/bash

echo "=========================================="
echo "   啟動 Breeze ASR Taigi 語音辨識服務"
echo "=========================================="

# 定義清理函數（當按下 Ctrl+C 時觸發）
cleanup() {
    echo ""
    echo "正在關閉服務..."
    kill $BACKEND_PID $CELERY_PID $FRONTEND_PID 2>/dev/null
    exit 0
}

# 捕捉 Ctrl+C 信號
trap cleanup SIGINT SIGTERM

echo "[1/4] 正在啟動 Redis Queue (Docker)..."
docker start breeze-redis 2>/dev/null || docker run -d --name breeze-redis -p 6379:6379 redis:alpine

echo "[2/4] 正在啟動後端 API 伺服器..."
cd backend
uv run uvicorn src.main:app --reload --reload-dir src --port 8787 &
BACKEND_PID=$!

echo "[3/4] 正在啟動 Celery Worker..."
uv run celery -A src.infrastructure.celery_app worker --loglevel=info &
CELERY_PID=$!
cd ..

echo "[4/4] 正在啟動前端網頁伺服器..."
cd frontend
pnpm dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "服務已於背景啟動！"
echo "前端網址: http://localhost:3000"
echo "後端 API: 已由前端代理 (http://localhost:8787 背景執行中)"
echo "請按 Ctrl+C 來同時關閉所有服務。"
echo "=========================================="

# 等待背景程序執行，保持腳本不退出
wait
