# Backend Developer Agent Guidance (後端 Agent 開發規範)

## 1. 架構原則 (Clean Architecture & SOLID)
- **Domain (`src/domain`)**: 定義 Pydantic Data Models (Entities/DTOs)，不得依賴 ORM 或外部框架。
- **Use Cases (`src/usecases`)**: 實作核心業務邏輯（如 ASR 轉錄、LLM 錯別字校正、會議紀錄生成與檔案歸檔）。
- **Infrastructure (`src/infrastructure`)**: 負責 SQLite/PostgreSQL 資料庫 (SQLAlchemy)、Celery 任務發送與外部 AI/LLM API 通訊。
- **Interfaces (`src/interfaces`)**: 提供 FastAPI RESTful API 路由與 Controller。
- **共用服務層**: 核心 LLMClient 位於 `src/taigi_asr/llm.py`，供後端 usecases 與 `scripts/transcribe_and_summarize.py` 共同複用，確保二階段校正與會議記錄生成邏輯一致。

## 2. LLM 服務整合規範
- 預設端點設定於 `config.ini` 與 `.env` (`LLM_CORRECTION_URL` 與 `LLM_URL`，預設 `http://192.168.1.100:8002/v1`)。
- 端點格式統一遵循 OpenAI / vLLM `/v1/chat/completions` API 規格。
- 必須妥善處理 Reasoning / Think 標籤 (`<think>...</think>`) 的解析與過濾。
- 必須具備逾時 (Timeout = 1800 秒) 與連線異常的自動降級處置機制（保留原始 ASR 逐字稿，不中斷整體任務）。

## 3. 開發與測試 (TDD)
- 使用 `uv` 管理套件。
- 在新增或修正功能前，必須撰寫 `pytest` 單元測試與 Mock 測試，確保 Happy Path 與 Edge Cases 通過。
