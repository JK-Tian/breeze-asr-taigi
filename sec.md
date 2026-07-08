# 系統架構與安全規範 (Security & Architecture Document)

## 專案概述
本專案為一個基於 MediaTek Research Breeze ASR 26 模型的會議紀錄系統，採用前後端分離架構，支援非同步上傳與處理長時間音檔，並具備講者辨識 (Speaker Diarization) 功能。

## 系統架構
本系統分為兩個主要微服務（Monorepo 形式管理）：
1. **Frontend (網頁前端)**: 使用 React (Next.js/Vite) 構建，負責提供使用者介面，包含音檔上傳、進度查詢與結果展示。
2. **Backend (後端 API)**: 使用 FastAPI 構建，基於 Clean Architecture 原則，負責接收音檔、寫入任務狀態至 SQLite，並透過 BackgroundTasks 調用 AI 模型進行處理。

## 資料流與狀態機
任務狀態 (Status) 包含以下生命週期：
- `pending`: 音檔已上傳，等待背景處理。
- `processing`: 音檔正在由 VAD 或 ASR 模型處理中。
- `completed`: 處理完成，已產生帶有講者標籤的逐字稿。
- `failed`: 處理過程中發生錯誤。

## 安全性考量 (Security)
1. **音檔儲存與清理**：
   - 使用者上傳的音檔會暫存於伺服器。為保護會議機密性，系統應於處理完成後 (無論成功或失敗) 主動刪除原始音檔。
   - 上傳介面應限制檔案類型 (僅限 `.mp3`, `.wav`, `.m4a` 等安全格式) 與檔案大小上限。
2. **API 存取限制**：
   - 目前設計為單機本機部署版本 (MVP)，若未來需上線公網，需補齊 JWT 或 OAuth2 驗證機制。
3. **資料庫安全**：
   - 採用 SQLite，不需對外開放 Port。
   - 使用 SQLAlchemy ORM 防止 SQL Injection。

## 開發規範
- **Python**: 遵循 PEP8 規範，透過 `uv` 管理套件。
- **JavaScript**: 遵循 ESLint 規範，透過 `pnpm` 管理套件。
- 所有非同步 I/O 操作 (如檔案讀取、資料庫寫入) 應使用 `async/await` 以不阻塞 Event Loop。
- AI 模型載入屬高成本操作，應於 FastAPI 啟動時 (Lifespan) 或以 Singleton 模式載入，避免每次 Request 重新載入。
