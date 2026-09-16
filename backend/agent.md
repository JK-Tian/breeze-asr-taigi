# Backend Developer Agent Guidance (後端 Agent 開發規範)

## 1. 架構原則 (Clean Architecture & SOLID)
- **Domain (`src/domain`)**: 定義 Pydantic Data Models (Entities/DTOs)，不得依賴 ORM 或外部框架。
- **Use Cases (`src/usecases`)**: 實作核心業務邏輯（包含各類影音音軌提取、ASR 轉錄、LLM 錯別字校正、符合 `skills/video-to-notes` 規範之結構化 Markdown 會議記錄生成與檔案歸檔）。
- **Infrastructure (`src/infrastructure`)**: 負責 SQLite/PostgreSQL 資料庫 (SQLAlchemy)、Celery 任務排程、外部 AI/LLM API 通訊。
- **Interfaces (`src/interfaces`)**: 提供 FastAPI RESTful API 路由與 Controller。
- **共用服務層**: 核心 LLMClient 位於 `src/taigi_asr/llm.py`，會議記錄格式化位於 `src/taigi_asr/minutes.py`，供後端 usecases 與 `scripts/transcribe_and_summarize.py` 共同複用。

## 2. 視訊會議與 video-to-notes 整合規範
- 支援使用者上傳視訊檔案 (MP4, MKV, MOV, WEBM 等) 與音訊檔案。
- 透過 ffmpeg 分離音軌為 16kHz mono WAV (ASR 辨識) 與 128k MP3 (供前端播放)。
- 不論語音還是視訊會議，會議記錄輸出格式統一為 `.md`（Markdown），不需要轉換為 Word docx 檔案。
- 會議記錄 Markdown 開頭必須宣告標準 Obsidian PKM YAML Frontmatter，文末以 `# 參考資料` 標註影音檔名。

## 3. 開發與測試 (TDD)
- 使用 `uv` 管理套件。
- 在新增或修正功能前，必須撰寫 `pytest` 單元測試與 Mock 測試，確保 Happy Path 與 Edge Cases (如音軌損毀) 通過。
