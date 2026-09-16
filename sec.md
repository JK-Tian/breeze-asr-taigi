# 系統架構與安全規範 (Security & Architecture Document)

## 專案概述
本專案為一個基於 MediaTek Research Breeze ASR 26 模型的智導會議紀錄系統，支援非同步 Web 介面與命令列腳本（Script）雙重執行入口。系統支援處理任何形式的會議（純語音錄音、實體會議錄音、線上視訊會議錄影 MP4/MKV/MOV/WEBM 等），具備講者辨識 (Speaker Diarization) 功能，整合外部 LLM API (預設 `http://192.168.1.100:8002/v1`) 進行二階段語義錯別字校正，並深度參考 `skills/video-to-notes` 技能規範，統一產出符合 **Obsidian PKM YAML Frontmatter 格式之 Markdown (`.md`) 結構化會議筆記**，無需轉為 Word 檔，並支援自動同步輸出檔案至外部 KM Wiki 的 raw 資料夾。

## 系統架構與 pipeline
本系統支援兩種執行入口：
1. **獨立命令列腳本 (CLI Script / scripts/transcribe_and_summarize.py)**:
   - 專為自動化排程、批次處理與本機工程人員設計。
   - 支援直接傳入視訊檔案 (MP4, MKV 等) 或音訊檔案或現有逐字稿，自動提取音訊並調用 Breeze ASR 與共用 `LLMClient` 進行兩階段處理，自動產出校正逐字稿 `.md` 與 video-to-notes 規格會議筆記 `.md` 至 `output/YYYY-MM-DD/`。
2. **前後端微服務 (Web Application)**:
   - **Frontend**: Next.js / React 網頁介面，支援音訊與視訊檔案拖曳選取、即時麥克風錄音、上傳失敗影音雙重保全、任務進度檢視、音訊線上播放、Markdown 結構化預覽及 `.md` 檔案一鍵下載。
   - **Backend**: FastAPI + Celery + SQLite/PostgreSQL，非同步處理長影音任務，提供 RESTful API。

## 核心處理 Pipeline (四階段)
1. **階段 1 (音視訊分離與標準化)**: 接收各類影音輸入，透過 `ffmpeg` 分離音訊並標準化為 16kHz mono WAV (ASR 辨識) 及 128k MP3 (供前端播放)，處理後即時釋放巨大 WAV 暫存。
2. **階段 2 (ASR 轉寫與講者辨識)**: 轉寫音訊並進行講者分離，產出帶時間戳與講者代號之原始逐字稿。
3. **階段 3 (LLM 錯別字校正)**: 發送原始逐字稿至 `http://192.168.1.100:8002/v1`，根據前後文語意修復錯別字與同音異字，完整保留時間戳與講者標記。
4. **階段 4 (提煉符合 video-to-notes 規範之 .md 筆記與成果歸檔)**: 發送校正後逐字稿至 `http://192.168.1.100:8002/v1`，提煉符合 `skills/video-to-notes` 規範（Obsidian PKM YAML Frontmatter、基本資訊、Highlights、決策表格、Todo 表格、發言人討論、下次會議追蹤項目表格、文末 `# 參考資料` 影音檔名）之 Markdown 會議記錄，儲存至 `output/YYYY-MM-DD/`，並在啟用時同步複製至 `KM_WIKI_RAW_DIR`。

## 安全性與容錯考量 (Security & Resilience)
1. **路徑與輸入安全 (Path Traversal Prevention)**:
   - 嚴格校驗傳入檔案副檔名，防範上傳危險執行檔。
   - 檔名消毒：調用 `sanitize_filename` 消除非法字元 (`\ / : * ? " < > |`)，嚴禁任意跳脫目錄寫入。
2. **視訊大檔案與磁碟資源保護 (Disk & Media Resource Protection)**:
   - 視訊檔案體積較大，轉換提取出 16kHz WAV 供 ASR 辨識完畢後，暫存之大型 WAV 檔立即安全刪除，避免磁碟空間耗盡。
   - 後端設有自動清理超過 30 天舊音檔之背景清理任務。
3. **LLM 服務降級與連線容錯 (Graceful Degradation)**:
   - LLM 服務連線設定 1800 秒連線超時與例外捕捉機制。
   - 若 LLM 錯別字校正連線失敗或超時，系統自動降級採用原始 ASR 逐字稿，確保流程不中斷崩潰。
4. **思考模型標籤過濾 (Think Tag Sanitization)**:
   - 外部推理模型若輸出 `<think>...</think>` 推理區塊，核心服務自動解析並徹底過濾，僅保留乾淨正式內容，防止內部推理過程洩漏。
5. **前端影音記憶體保全與防遺失 (Client Media Resilience & Leak Prevention)**:
   - 網頁端選取或錄製之影音暫存於瀏覽器記憶體中。
   - 上傳失敗時，前端嚴格禁止銷毀 File 物件，提供一鍵重試及 Blob 本機下載功能，確保使用者寶貴影音不遺失。
   - 點擊下載時透過 `URL.createObjectURL` 建立臨時連結，並在觸發下載後立即調用 `URL.revokeObjectURL` 釋放瀏覽器記憶體資源，防止長時間使用產生 Memory Leak。
6. **機密資料保護 (Secret Management)**:
   - 所有重要帳號、伺服器 IP、金鑰與 token 均存放於 `.env` 檔案中，並加入 `.gitignore` 嚴格禁止提交至版本控制庫。
   - 一般功能設定（如端點、模型名稱、KM Wiki 目錄）放置於 `config.ini`。
