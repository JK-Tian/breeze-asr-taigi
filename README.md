# taigi-asr

**台灣台語語音轉錄與 AI 智導會議紀錄系統 / Taiwanese Hokkien ASR & AI Meeting Assistant**

以 [MediaTek **Breeze-ASR-26**](https://huggingface.co/MediaTek-Research/Breeze-ASR-26) 為語音轉寫核心，整合外部 LLM API（預設 `http://192.168.1.100:8002/v1`）提供二階段**語意錯別字校正**與**四大結構化會議紀錄整理（會議重點、關鍵決策、TODO與下次會議追蹤項目）**，支援獨立 Script 命令列一鍵執行轉會議記錄，並支援將產出結果自動同步至 **KM Wiki 的 raw 資料夾**。

---

## 🚀 核心功能特色

1. **ASR 語音轉錄**：透過 Breeze-ASR-26 進行長音檔轉錄與講者辨識。
2. **語意錯別字校正 (LLM 8002/v1)**：自動將逐字稿送至 `http://192.168.1.100:8002/v1` 模型，根據前後文語意修復錯別字、同音異字與專有名詞，同時完整保留講者代號與時間戳記。
3. **結構化會議紀錄整理 (LLM 8002/v1)**：將校正後逐字稿自動整理為包含以下四大重點區塊的會議紀錄：
   - **【會議重點】**：核心論點與背景討論。
   - **【關鍵決策】**：會議中達成的明確共識與結論。
   - **【TODO / 行動項目】**：具體待辦事項、負責人及預計完成日期。
   - **【下次會議追蹤項目】**：需要於下次會議進行複查或延伸討論的事項。
4. **獨立 Script 命令列執行**：提供 `scripts/transcribe_and_summarize.py` 腳本，可直接於終端機以命令列執行音檔轉寫或既有逐字稿整理。
5. **KM Wiki raw 資料夾自動同步**：可將處理完成之 `.md` 檔案自動同步複製至指定的 KM Wiki raw 目錄中。
6. **上傳失敗音檔雙重保全機制**：網頁錄音或檔案上傳遭遇網路中斷或伺服器異常時，前端自動保全音檔，提供「一鍵重試」與「下載音檔備份」按鈕，防止寶貴會議錄音意外遺失。

---

## 🛠️ 命令列腳本使用指南 (CLI Script)

除了網頁介面之外，您也可以透過獨立 Python 腳本在終端機直接執行轉換：

### 1. 傳入音訊檔案（自動執行 ASR + 錯別字校正 + 會議記錄）
```powershell
uv run python scripts/transcribe_and_summarize.py --audio "path/to/meeting.mp3"
```

### 2. 傳入既有逐字稿（跳過 ASR，直接進行 錯別字校正 + 會議記錄）
```powershell
uv run python scripts/transcribe_and_summarize.py --transcript "path/to/raw_transcript.txt"
```

### 3. 進階選項（自訂輸出目錄、指定端點與模型）
```powershell
uv run python scripts/transcribe_and_summarize.py \
  --audio "meeting.wav" \
  --output-dir "output/my_meetings" \
  --url "http://192.168.1.100:8002/v1" \
  --model "Qwen/Qwen3.8-27B-FP8"
```

📁 **輸出成果：**
處理完成後，系統會自動在指定目錄（預設 `output/YYYY-MM-DD/`）產出兩份 Markdown 檔案：
- `[會議名稱]_逐字稿.md`：校正後的完整逐字稿（保留講者時間戳）。
- `[會議名稱]_會議紀錄與摘要.md`：包含四大區塊之結構化會議記錄。

---

## ⚙️ 環境設定 (.env 與 config.ini)

請於 `.env` 設定 LLM 與相關環境變數：
```env
# =============== LLM 設定 (錯別字校正與摘要生成) ===============
LLM_CORRECTION_URL=http://192.168.1.100:8002/v1
LLM_CORRECTION_MODEL=Qwen/Qwen3.8-27B-FP8

LLM_URL=http://192.168.1.100:8002/v1
LLM_MODEL=Qwen/Qwen3.8-27B-FP8

# =============== KM Wiki 自動同步設定 ===============
KM_WIKI_ENABLED=true
KM_WIKI_RAW_DIR=D:/km_wiki/raw
```

亦可在 `config.ini` 中進行細部參數調整：
```ini
[Correction]
correction_url = http://192.168.1.100:8002/v1
correction_model = Qwen/Qwen3.8-27B-FP8

[MeetingMinutes]
minutes_url = http://192.168.1.100:8002/v1
minutes_model = Qwen/Qwen3.8-27B-FP8

[KMWiki]
enabled = true
raw_dir = D:/km_wiki/raw
```

---

## 🌐 網頁服務啟動教學 (Web Application)

### 步驟 1：啟動後端 API (FastAPI)
```powershell
cd backend
uv run uvicorn src.main:app --reload --port 8000
```

### 步驟 2：啟動前端介面 (Next.js)
```powershell
cd frontend
pnpm dev
```
開啟瀏覽器前往 [http://localhost:3002](http://localhost:3002) 即可開始上傳音檔。

---

## 專案結構

```
backend/             # FastAPI 後端微服務 (Clean Architecture)
  src/
    domain/          # Pydantic Entities / DTOs
    usecases/        # ASR, LLM Correction, Summarization & KM Exporter logic
    infrastructure/  # DB, Celery worker & ML Models
    interfaces/      # FastAPI Controllers / Routers
frontend/            # Next.js 網頁前端
scripts/             # 獨立執行腳本 (transcribe_and_summarize.py)
src/
  taigi_asr/         # Breeze ASR 核心引擎與共用 LLMClient 服務 (llm.py)
output/              # 每日自動歸檔的 Markdown 會議紀錄 (output/YYYY-MM-DD/)
docs/                # SDD.md, BDD.md
```

## License
MIT. See [LICENSE](LICENSE).
