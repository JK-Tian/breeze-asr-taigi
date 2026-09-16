# 行為驅動規格書 (Behavior Driven Development - BDD.md)
## 天工會議紀錄：企業級高併發與端點整合驗收場景

---

## 1. 規範參數定義 (Parameters)

```yaml
parameters:
  system_under_test: "天工會議紀錄系統 (Breeze ASR Taigi - High Concurrency Edition)"
  test_environment:
    os: "Windows 11"
    python_env: "uv run (Python 3.10+)"
    node_env: "pnpm 9+ (Node.js 20+)"
  concurrency_targets:
    api_concurrent_requests: 50
    large_file_uploads: 5
    transcription_queue_capacity: 100
  endpoints:
    secure_frontend: "https://localhost:3001"
    internal_frontend: "http://localhost:3002"
    backend_api: "http://localhost:8787"
```

---

## 2. 核心行為驗收場景 (Gherkin Scenarios)

### 場景 1：多使用者同時上傳影音，API 不阻塞狀態查詢 (Non-blocking I/O)
* **Given** 系統正常啟動，FastAPI 後端以多 Workers 運行，資料庫處於 WAL 模式
* **When** 5 位企業使用者同時發送 500MB 大音視訊檔案上傳請求 (`POST /api/v1/transcriptions`)
* **And** 另有 20 位使用者在此期間持續發送任務狀態查詢請求 (`GET /api/v1/transcriptions/{id}`)
* **Then** 狀態查詢請求 **MUST** 在 50ms 內迅速獲得 HTTP 200 回應，**MUST NOT** 發生 Connection Timeout 或 504 逾時
* **And** 5 筆上傳請求 **MUST** 成功寫入磁碟並回傳 HTTP 201 與 `task_id`，任務依序排入佇列

### 場景 2：GPU 轉錄佇列限流，徹底防止顯存溢位 (Prevent CUDA OOM)
* **Given** Redis 啟用 `gpu_queue` 與 `io_queue` 雙軌佇列，GPU Worker 設定 `concurrency=1`
* **When** 佇列中同時累積了 5 個長達 1 小時之高音質視訊會議任務
* **Then** GPU Worker **MUST** 每次只處理 1 個任務，依序呼叫 Breeze-ASR 模型推論
* **And** GPU 顯存使用率 **MUST NOT** 超出單卡上限，系統 **MUST NOT** 產生 `CUDA Out of Memory` 崩潰
* **And** 當單一任務之 ASR 轉錄完成後，該任務 **MUST** 立即被轉移至 `io_queue`，釋放 GPU 轉入下一個待轉寫任務

### 場景 3：I/O 佇列多並發處理 LLM 錯別字校正與會議摘要
* **Given** 多個任務已完成 ASR 轉錄，處於逐字稿校正與摘要生成階段
* **When** 3 位使用者同時對既有會議點擊「重新生成摘要」(`POST /api/v1/transcriptions/{id}/resummarize`)
* **And** 同時有 2 個新任務進入 LLM 處理階段
* **Then** I/O Worker 透過多執行緒池 (`concurrency=8`) **MUST** 同時向外部 LLM 端點發起並行請求
* **And** 各任務處理進度獨立，互不卡頓，產出符合 `video-to-notes` 規範之 Obsidian Markdown 會議筆記

### 場景 4：單一 HTTPS 入口取用麥克風設備與同源 API 請求
* **Given** 使用者使用瀏覽器開啟 `https://localhost:3001`
* **When** 使用者在網頁上點擊「開始麥克風錄音」按鈕
* **Then** 瀏覽器 **MUST** 成功辨識 Secure Context 並彈出麥克風錄音授權許可，**MUST NOT** 提示「瀏覽器封鎖了麥克風 API」
* **When** 錄音完畢點擊上傳
* **Then** 前端發送相對路徑 `/api/v1/transcriptions` 請求，由 Next.js 伺服器端內網無縫代理至 `8787`
* **And** 瀏覽器 **MUST NOT** 彈出針對 8788 的二次證書警告，上傳流程 **MUST** 一鍵順暢完成

### 場景 5：啟動腳本端口自我清理與相依順序保障
* **Given** 系統背景殘留有先前未釋放的 Node.js 或 Python 進程（例如佔用 port 3002 或 8787）
* **When** 管理員執行 `start_service.bat`
* **Then** 腳本 **MUST** 在啟動前主動釋放殘留連接埠
* **And** 腳本 **MUST** 依序檢查 Redis (PONG) -> Backend (200) -> Celery -> Frontend (3002) -> SSL Proxy (3001)
* **And** 啟動過程中 **MUST NOT** 出現 `listen EADDRINUSE` 或 `ECONNREFUSED` 錯誤

---

## 3. SOP 驗證流程 (Verification Protocol)

```yaml
parameters:
  inputs:
    - test_suite: "tests/test_high_concurrency.py"
    - sample_audio: "tests/fixtures/sample.wav"
  outputs:
    - test_report: "pytest_results.xml"
    - memory_leak_check: "pass"
```

#### Steps (RFC2119 關鍵字)
1. 測試套件 **MUST** 在單元測試中模擬多線程同時向 SQLite WAL 執行讀取與寫入，驗證零鎖定異常。
2. 測試套件 **MUST** 驗證 `api.py` 的檔案上傳端點採用非同步非阻塞方式接收檔案。
3. 測試套件 **MUST** 驗證 Celery 的任務路由表將 ASR 任務導向 `gpu_queue`、將 LLM/Summary 任務導向 `io_queue`。
4. 前端測試 **MUST** 驗證 `getApiBase()` 在任何協定下均統一回傳 `/api/v1`，完全消除 8788。

#### Error Handling (異常與邊界處理)

| 編號 | 異常條件 (Criteria) | 系統行動 (Action) |
| :--- | :--- | :--- |
| **EH-01** | 連線資料庫發生併發交易超時 (`OperationalError`) | 系統 **MUST** 觸發自適應重試機制 (Exponential Backoff, 最大 3 次)，若仍失敗 **MUST** 拋出清楚之交易衝突錯誤並回滾交易。 |
| **EH-02** | 外部 LLM API (8002) 回應超時或掛起 | I/O Worker **MUST** 在 1800 秒連線超時後終止連線，降級使用原始 ASR 逐字稿生成簡化筆記，**MUST NOT** 無限期卡住線程。 |
| **EH-03** | 前端錄音時使用者拒絕麥克風權限 (`NotAllowedError`) | 前端 **MUST** 彈出友善操作提示指導使用者於瀏覽器網址列重新開啟麥克風權限，**MUST NOT** 導致介面進入凍結狀態。 |
