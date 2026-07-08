 

# Breeze ASR 會議紀錄系統 (Backend)

本目錄包含系統後端的實作，主要負責：

1. 提供 RESTful API 供前端上傳音檔與查詢任務狀態。
2. 背景處理長音檔（透過 VAD 截斷）。
3. 執行 Breeze ASR 26 推論將語音轉換為文字。
4. 結合 Pyannote 進行講者辨識。

## 架構設計

採用 **Clean Architecture** 與 **S.O.L.I.D** 原則：

- **Domain (`src/domain/`)**: 定義核心實體 (Entities)，如 `TranscriptionTask`。
- **Use Cases (`src/usecases/`)**: 核心業務邏輯，負責音檔處理流程與狀態更新。
- **Interfaces (`src/interfaces/`)**: FastAPI 控制器 (Controllers)，定義路由與請求/回應模型。
- **Infrastructure (`src/infrastructure/`)**: 與外部系統互動的實作，如 SQLite 資料庫與 ASR 模型的封裝。

## 開發指南

本專案使用 `uv` 進行套件管理。

1. 安裝依賴：
   ```bash
   uv sync
   ```
2. 啟動開發伺服器：
   ```bash
   uv run uvicorn src.main:app --reload --reload-dir src --port 8787
   ```

## REST API 概觀

- `POST /api/v1/transcriptions`: 上傳會議音檔。
- `GET /api/v1/transcriptions`: 取得歷史任務列表。
- `GET /api/v1/transcriptions/{task_id}`: 查詢指定任務的狀態與結果。
- `DELETE /api/v1/transcriptions/{task_id}`: 刪除任務。

