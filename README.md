# taigi-asr

**台灣台語語音轉錄與 AI 智導會議紀錄系統 / Taiwanese Hokkien ASR & AI Meeting Assistant**

以 [MediaTek **Breeze-ASR-26**](https://huggingface.co/MediaTek-Research/Breeze-ASR-26) 為語音轉寫核心，整合外部 LLM API（預設 `http://192.168.1.100:8002/v1`）提供二階段**語意錯別字校正**，並深度參考 `skills/video-to-notes` 技能規範，讓使用者**無論何種形式的會議（純語音錄音、實體會議錄音、Teams/Zoom/Meet 線上視訊錄影 MP4/MKV/MOV/WEBM 等、瀏覽器麥克風收音）**，都能一鍵轉錄並自動產出 **Obsidian PKM Markdown (`.md`) 會議記錄筆記**（無需轉 Word 檔，維持輕量純淨）！

---

## 🚀 核心功能特色

1. **全形式會議支援 (音訊與視訊錄影)**：
   - 支援純音訊 (`.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg` 等)。
   - 支援線上視訊會議錄影 (`.mp4`, `.mkv`, `.mov`, `.webm`, `.avi` 等)，自動透過 FFmpeg 分離提取音訊並標準化。
   - 支援網頁端直接麥克風錄音收音。
2. **ASR 語音轉錄與講者分離**：透過 Breeze-ASR-26 與 Pyannote 進行長音檔轉錄與講者辨識。
3. **語意錯別字校正 (LLM 8002/v1)**：自動將逐字稿送至 `http://192.168.1.100:8002/v1` 模型，根據前後文語意修復錯別字、同音異字與專有名詞，同時完整保留講者代號與時間戳記。
4. **符合 video-to-notes 規格之結構化會議記錄 (.md)**：
   - 不論語音或影片轉出的會議記錄，皆產出標準 `.md` 檔案。
   - 開頭宣告 Obsidian PKM YAML Frontmatter。
   - 文末 `# 參考資料` 標記原始影音檔案來源。
   - 六大商務結構：基本資訊、核心摘要 (Highlights)、關鍵決策事項 (Decisions Made 表格)、待辦事項清單 (Action Items / Todo List 表格)、各議題討論紀要 (Agenda & Discussions，標註【發言人】)、下次會議追蹤項目 (Next Meeting Follow-ups 表格)。
5. **雙重執行入口**：
   - 獨立 Script 命令列工具 (`scripts/transcribe_and_summarize.py`)。
   - 現代化 Web 介面 (Next.js + FastAPI)，支援影音線上播放、Markdown 結構化預覽與 `.md` 一鍵下載。
6. **上傳失敗影音雙重保全機制**：網頁錄音或檔案上傳遭遇網路中斷或伺服器異常時，前端自動保全影音，提供「一鍵重試」與「下載影音備份」按鈕，防止寶貴會議影音意外遺失。
7. **KM Wiki raw 資料夾自動同步**：可將處理完成之檔案自動同步複製至指定的 KM Wiki raw 目錄中。

---

## 🛠️ 命令列腳本使用指南 (CLI Script)

您可透過獨立 Python 腳本在終端機直接執行轉換：

### 1. 傳入視訊或音訊檔案（自動執行音訊提取 + ASR + 錯別字校正 + 會議記錄生成）
```powershell
# 視訊會議錄影檔 (MP4, MKV, MOV 等)
uv run python scripts/transcribe_and_summarize.py --audio "path/to/meeting.mp4"

# 純音訊檔 (MP3, WAV 等)
uv run python scripts/transcribe_and_summarize.py --audio "path/to/meeting.mp3"
```

### 2. 傳入既有逐字稿（跳過 ASR，直接進行 錯別字校正 + 會議記錄生成）
```powershell
uv run python scripts/transcribe_and_summarize.py --transcript "path/to/raw_transcript.txt"
```

### 3. 進階選項（自訂輸出目錄、指定端點與模型）
```powershell
uv run python scripts/transcribe_and_summarize.py \
  --audio "meeting.mp4" \
  --output-dir "output/my_meetings" \
  --url "http://192.168.1.100:8002/v1" \
  --model "auto"
```

📁 **輸出成果：**
處理完成後，系統會自動在指定目錄（預設 `output/YYYY-MM-DD/`）產出兩份 Markdown 檔案：
- `[會議名稱]_逐字稿.md`：校正後的完整逐字稿（保留講者時間戳）。
- `[會議名稱]_會議紀錄與摘要.md`：符合 Obsidian PKM 格式之 Markdown 會議記錄。

---

## ⚙️ 環境設定 (.env 與 config.ini)

請於 `.env` 設定 LLM 與相關環境變數：
```env
# =============== LLM 設定 (錯別字校正與摘要生成) ===============
LLM_CORRECTION_URL=http://192.168.1.100:8002/v1
LLM_CORRECTION_MODEL=auto

LLM_URL=http://192.168.1.100:8002/v1
LLM_MODEL=auto

# =============== KM Wiki 自動同步設定 ===============
KM_WIKI_ENABLED=true
KM_WIKI_RAW_DIR=D:/km_wiki/raw
```

亦可在 `config.ini` 中進行細部參數調整：
```ini
[Correction]
correction_url = http://192.168.1.100:8002/v1
correction_model = auto

[MeetingMinutes]
minutes_url = http://192.168.1.100:8002/v1
minutes_model = auto

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
開啟瀏覽器前往 [http://localhost:3002](http://localhost:3002) 即可開始上傳視訊或音訊檔案。
產出完成後，可直接於網頁檢視並點擊「下載 .md」下載會議記錄。
