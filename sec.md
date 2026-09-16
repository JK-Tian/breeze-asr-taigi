# 系統架構與安全規範 (Security & Architecture Document)

## 專案概述
本專案為一個基於 MediaTek Research Breeze ASR 26 模型的會議紀錄系統，支援非同步 Web 介面與命令列腳本（Script）雙重執行模式，支援處理長時間音檔，具備講者辨識 (Speaker Diarization) 功能，整合外部 LLM API (預設 `http://192.168.1.100:8002/v1`) 進行二階段語義錯別字校正與結構化會議紀錄整理（包含會議重點、關鍵決策、TODO/行動項目、下次會議追蹤項目），並支援自動同步輸出檔案至外部 KM Wiki 的 raw 資料夾。

## 系統架構與 pipeline
本系統支援兩種執行入口：
1. **獨立命令列腳本 (CLI Script / scripts/transcribe_and_summarize.py)**:
   - 專為自動化排程、批次處理與本機工程人員設計。
   - 支援直接傳入音訊檔案或現有逐字稿，直接調用 Breeze ASR 與共用 `LLMClient` 進行兩階段處理並輸出 Markdown 檔案至 `output/YYYY-MM-DD/`。
2. **前後端微服務 (Web Application)**:
   - **Frontend**: Next.js / React 網頁介面，提供拖曳上傳、任務進度檢視與成果預覽。
   - **Backend**: FastAPI + Celery + SQLite/PostgreSQL，非同步處理長音檔任務。

## 核心處理 Pipeline (四階段)
1. **階段 1 (ASR 轉寫)**: 音檔長度轉換、轉寫與講者辨識，產出帶講者標籤之原始逐字稿。
2. **階段 2 (LLM 錯別字校正)**: 發送原始逐字稿至 `http://192.168.1.100:8002/v1`，根據前後文語意修復錯別字與同音異字，完整保留時間戳與講者代號。
3. **階段 3 (LLM 結構化會議紀錄)**: 發送校正後逐字稿至 `http://192.168.1.100:8002/v1`，整理包含四大重點區塊（會議重點、關鍵決策、TODO/行動項目、下次會議追蹤項目）之 Markdown 會議記錄。
4. **階段 4 (成果歸檔與 KM 同步)**: 自動儲存 Markdown 檔案至本機 `output/YYYY-MM-DD/`，並在啟用時同步複製一份至 `KM_WIKI_RAW_DIR`。

## 安全性與容錯考量 (Security & Resilience)
1. **路徑與輸入安全 (Path Traversal Prevention)**:
   - 腳本與後端接收檔案路徑時，嚴格進行副檔名與路徑有效性驗證。
   - 儲存 Markdown 檔案時，自動由會議標題提煉檔名，並調用 `sanitize_filename` 消除非法字元 (`\ / : * ? " < > |`)，避免路徑遍歷與檔案寫入注入。
2. **LLM 服務降級與連線容錯 (Graceful Degradation)**:
   - LLM 服務預設 URL 設於 `.env` 與 `config.ini` (`http://192.168.1.100:8002/v1`)。
   - 請求設定 1800 秒連線超時與例外捕捉機制。
   - 若 LLM 錯別字校正連線失敗或超時，系統自動降級採用原始 ASR 逐字稿，確保流程不中斷崩潰。
3. **思考模型標籤過濾 (Think Tag Sanitization)**:
   - 外部推理模型若輸出 `<think>...</think>` 推理區塊，核心服務自動解析並徹底過濾，僅保留乾淨正式內容，防止推理過程洩漏至公開會議記錄中。
4. **機密資料保護 (Secret Management)**:
   - 所有重要帳號、伺服器 IP、金鑰與 token 均存放於 `.env` 檔案中，並加入 `.gitignore` 嚴格禁止提交至版本控制庫。
   - 一般可調整參數（如提示詞模板、滑動視窗等）則放置於 `config.ini`。
5. **KM Wiki 同步寫入容錯**:
   - 若指定之 KM Wiki raw 資料夾不可寫入或網路磁碟中斷，系統記錄 Warning Log 且不中斷主要流程。
6. **前端音檔記憶體保全與防遺失 (Client Audio Resilience & Leak Prevention)**:
   - 網頁端麥克風錄音產生之音訊及選取之音檔暫存於瀏覽器記憶體中。
   - 上傳失敗時，前端嚴格禁止自動銷毀 File 物件，必須提供一鍵重試及 Blob 本機下載功能，確保使用者寶貴錄音不遺失。
   - 點擊下載時透過 `URL.createObjectURL` 建立臨時連結，並在觸發下載後立即調用 `URL.revokeObjectURL` 釋放瀏覽器記憶體資源，防止長時間使用產生 Memory Leak。

## 開發規範
- **Python**: 遵循 PEP8 規範，透過 `uv` 管理套件。
- **JavaScript**: 遵循 ESLint 規範，透過 `pnpm` 管理套件。
- **逐字稿校正規範**: 強制調用 `http://192.168.1.100:8002/v1` 模型進行同音字與專有名詞校正。
- **會議紀錄四區塊規範**: 會議紀錄必須包含「會議重點」、「關鍵決策」、「TODO / 行動項目」以及「下次會議追蹤項目」。
