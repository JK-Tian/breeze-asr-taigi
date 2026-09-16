# 系統架構與安全規範 (Security & Architecture Document)

## 專案概述
本專案為一個基於 MediaTek Research Breeze ASR 26 模型的智導會議紀錄系統，支援企業級高併發非同步 Web 介面與命令列腳本（Script）雙重執行入口。系統支援處理任何形式的會議（純語音錄音、實體會議錄音、線上視訊會議錄影 MP4/MKV/MOV/WEBM 等），具備講者辨識 (Speaker Diarization) 功能，整合外部 LLM API (預設 `http://192.168.1.100:8002/v1`) 進行二階段語義錯別字校正，並深度參考 `skills/video-to-notes` 技能規範，統一產出符合 **Obsidian PKM YAML Frontmatter 格式之 Markdown (`.md`) 結構化會議筆記**，無需轉為 Word 檔，並支援自動同步輸出檔案至外部 KM Wiki 的 raw 資料夾。

## 系統架構與 pipeline (企業級高併發重整)
本系統支援兩種執行入口：
1. **獨立命令列腳本 (CLI Script / scripts/transcribe_and_summarize.py)**:
   - 專為自動化排程、批次處理與本機工程人員設計。
   - 支援直接傳入視訊檔案 (MP4, MKV 等) 或音訊檔案或現有逐字稿，自動提取音訊並調用 Breeze ASR 與共用 `LLMClient` 進行兩階段處理，自動產出校正逐字稿 `.md` 與 video-to-notes 規格會議筆記 `.md` 至 `output/YYYY-MM-DD/`。
2. **前後端微服務 (Web Application - 企業級高併發架構)**:
   - **Frontend**: Next.js / React 網頁介面，支援音訊與視訊檔案拖曳選取、即時麥克風錄音、上傳失敗影音雙重保全、任務進度檢視、音訊線上播放、Markdown 結構化預覽及 `.md` 檔案一鍵下載。
   - **統一 HTTPS 網關 (ProxyFront 3001)**: 單一對外安全入口，全面保全瀏覽器麥克風設備的安全上下文 (Secure Context) 存取；伺服器端內網自動將 `/api/*` 轉發至後端，徹底淘汰冗餘的 8788 代理，杜絕二次證書警告與 Mixed Content 漏洞。
   - **Backend**: FastAPI (支援 Uvicorn 多 Workers 併發) + Celery 雙軌佇列 + PostgreSQL (或 SQLite WAL 讀寫分離)，非同步處理長影音任務，提供高效能 RESTful API。

## 核心處理 Pipeline (雙軌佇列分流)
1. **階段 1 (非同步分塊接收與音視訊分離)**: 透過非同步串流安全接收各類影音輸入，不阻塞主 Event Loop；透過 `ffmpeg` 分離音訊並標準化為 16kHz mono WAV (ASR 辨識) 及 128k MP3 (供前端播放)，處理後即時釋放巨大 WAV 暫存。
2. **階段 2 (GPU 專屬佇列 ASR 轉寫與講者辨識)**: 任務進入 `gpu_queue`，嚴格限制並發數（Concurrency 1-2）並設定 Prefetch=1，轉寫音訊並進行講者分離，防範 GPU CUDA OOM 崩潰，產出帶時間戳與講者代號之原始逐字稿。完成後立即轉移至 I/O 佇列並釋放 GPU。
3. **階段 3 (I/O 佇列 LLM 錯別字校正)**: 任務進入 `io_queue`，利用多線程池 (Threads 8-16) 發送原始逐字稿至 `http://192.168.1.100:8002/v1`，修復錯別字與同音異字，完整保留時間戳與講者標記。
4. **階段 4 (I/O 佇列提煉符合 video-to-notes 規範之 .md 筆記與成果歸檔)**: 發送校正後逐字稿至外部 LLM，提煉符合 `skills/video-to-notes` 規範（Obsidian PKM YAML Frontmatter、基本資訊、Highlights、決策表格、Todo 表格、發言人討論、下次會議追蹤項目表格、文末 `# 參考資料` 影音檔名）之 Markdown 會議記錄，儲存至 `output/YYYY-MM-DD/`，並在啟用時同步複製至 `KM_WIKI_RAW_DIR`。

## 安全性與容錯考量 (Security & Resilience)
1. **單一統一 HTTPS 入口與同源保護 (Unified Ingress & Same-Origin Protection)**:
   - 對外僅開放 `https://localhost:3001`，徹底關閉 8788 後端暴露端口，消除跨網域存取攻擊面與瀏覽器 Mixed Content 阻擋。
   - 前端所有 API 請求均以相對路徑同源發送，由 Next.js 伺服器端內核轉發，兼顧安全與高效。
2. **高併發資料庫鎖防護與連線池 (Database Concurrency & Connection Pooling)**:
   - 正式環境支援 PostgreSQL 連線池 (`QueuePool`, `pool_size=20, max_overflow=10`)，具備資料庫行級鎖 (Row-Level Locking)。
   - 本地單機支援 SQLite WAL 模式 (`PRAGMA journal_mode=WAL;` / `PRAGMA busy_timeout=30000;`)，實現讀寫分離，杜絕高併發寫入時的 `database is locked` 異常。
3. **GPU 顯存防禦與背壓機制 (GPU VRAM Protection & Backpressure)**:
   - GPU 運算與外部 LLM 呼叫實行佇列隔離。限制 GPU 任務併發量為 1 或 2，防止同時載入多個長影音推論引發 CUDA OOM 崩潰。
   - 佇列滿載時實行背壓限流，保障伺服器高負載時仍穩定服務。
4. **非同步串流寫入防 Event Loop 阻塞 (Non-blocking Async Streaming)**:
   - 檔案上傳端點採用非同步分塊串流寫入磁碟，徹底防止多個使用者同時上傳數百 MB 影音時卡死 API 伺服器主線程。
5. **路徑與輸入安全 (Path Traversal Prevention)**:
   - 嚴格校驗傳入檔案副檔名，防範上傳危險執行檔。
   - 檔名消毒：調用 `sanitize_filename` 消除非法字元 (`\ / : * ? " < > |`)，嚴禁任意跳脫目錄寫入。
6. **視訊大檔案與磁碟資源保護 (Disk & Media Resource Protection)**:
   - 視訊檔案體積較大，轉換提取出 16kHz WAV 供 ASR 辨識完畢後，暫存之大型 WAV 檔立即安全刪除，避免磁碟空間耗盡。
   - 後端設有自動清理超過 30 天舊音檔之背景清理任務。
7. **LLM 服務降級與連線容錯 (Graceful Degradation)**:
   - LLM 服務連線設定 1800 秒連線超時與例外捕捉機制。
   - 若 LLM 錯別字校正連線失敗或超時，系統自動降級採用原始 ASR 逐字稿，確保流程不中斷崩潰。
8. **思考模型標籤過濾 (Think Tag Sanitization)**:
   - 外部推理模型若輸出 `<think>...</think>` 推理區塊，核心服務自動解析並徹底過濾，僅保留乾淨正式內容，防止內部推理過程洩漏。
9. **前端影音記憶體保全與防遺失 (Client Media Resilience & Leak Prevention)**:
   - 網頁端選取或錄製之影音暫存於瀏覽器記憶體中。
   - 上傳失敗時，前端嚴格禁止銷毀 File 物件，提供一鍵重試及 Blob 本機下載功能，確保使用者寶貴影音不遺失。
   - 點擊下載時透過 `URL.createObjectURL` 建立臨時連結，並在觸發下載後立即調用 `URL.revokeObjectURL` 釋放瀏覽器記憶體資源，防止長時間使用產生 Memory Leak。
10. **機密資料保護 (Secret Management)**:
    - 所有重要帳號、伺服器 IP、金鑰與 token 均存放於 `.env` 檔案中，並加入 `.gitignore` 嚴格禁止提交至版本控制庫。
    - 一般功能設定（如端點、模型名稱、KM Wiki 目錄）放置於 `config.ini`。
