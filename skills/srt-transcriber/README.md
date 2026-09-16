# SRT Transcriber (影音轉逐字稿旗艦版)

## 1. 簡介
`srt-transcriber` 是專為影音字幕生成與原音轉寫設計的旗艦版技能，已完整整併原 `srt-transcriber-zh` 與 `srt-faster-whisper` 的所有優勢：
- **核心模型：MediaTek Breeze-ASR-26**：預設採用聯發創新基地 (MediaTek Research) 專為**台灣華語口音、中英混用與台語 (Taigi)** 深度微調之旗艦模型 (`paulpengtw/faster-whisper-Breeze-ASR-26-ct2`)，辨識準確率遠超通用 Whisper。
- **多模型自由切換**：支援 OpenAI Whisper 官方多國模型 (`large-v3`, `medium`, `small`, `base`, `tiny`) 與純英文模型。
- **繁體中文與台灣台語深度優化**：內建台語專用初始提示詞 (Initial Prompt) 與台灣常用科技與機械工程術語，大幅提升中台雙語混用之辨識精準度。
- **極速推論與低記憶體**：基於 `faster-whisper` (CTranslate2) 引擎，推論速度較原生 Whisper 提升 4 倍以上，GPU 支援 4GB VRAM (float16)，CPU 支援 int8 量化。
- **全格式輸出**：支援同時輸出 `srt`、`vtt`、`txt` 與 `json`。
- **VAD 靜音切除**：內建語音活動偵測 (Voice Activity Detection)，自動跳過長段靜音或背景音樂雜音。

## 2. 系統需求
- 作業系統：Windows 11
- 套件管理：[uv](https://github.com/astral-sh/uv) (>= 0.1.0)
- Python 版本：>= 3.10
- 系統依賴：`ffmpeg` (置於系統 PATH)
- 顯存需求：GPU 模式建議 4GB+ VRAM (GTX 1650/RTX 3050 等)；無 GPU 時自動降級為 CPU int8。

## 3. 使用方式 (Script-Driven Pipeline)

### 3.1 核心台語 (Taigi) 與繁體中文模式 (預設使用 Breeze-ASR)
直接執行即可自動載入 Breeze-ASR 繁中/台語模型：
```bash
uv run scripts/transcribe.py "會議錄影.mp4"
```
或顯式指定語言與提示詞：
```bash
uv run scripts/transcribe.py "會議.mp4" --language zh-TW --initial-prompt "這是一場使用台灣繁體中文與台語的工程會議，包含導流板、公差、換模等專業術語"
```

### 3.2 切換通用多國語言旗艦模型 (OpenAI Whisper large-v3)
```bash
uv run scripts/transcribe.py "外語影片.mp4" --model large-v3 --format srt,txt,json --vad-filter
```

### 3.3 批次處理整個資料夾
```bash
uv run scripts/transcribe.py --input-dir "videos/" --format srt,vtt
```

## 4. 參數說明

| 參數 | 簡寫 | 說明 | 預設值 |
|---|---|---|---|
| `audio` | | 輸入檔案路徑（單檔或多檔） | (必填) |
| `--model` | `-m` | 模型名稱 (`breeze-asr`, `large-v3`, `medium`, `small`, `base`, `tiny`) | `breeze-asr` |
| `--language` | `-l` | 語言代碼 (如 `zh-TW`, `zh`, `en`, `ja`) | `zh-TW` (自動注入台語/繁中 Prompt) |
| `--format` | `-f` | 輸出格式，以逗號分隔 (`srt`, `vtt`, `txt`, `json`) | `srt` |
| `--output` | `-o` | 指定單一輸出檔案路徑 | 與輸入同名 |
| `--input-dir` | `-d` | 批次處理指定資料夾下所有影音檔 | 無 |
| `--device` | | 運算裝置 (`auto`, `cuda`, `cpu`) | `auto` |
| `--compute-type` | | 計算精度 (`auto`, `float16`, `int8`, `float32`) | `auto` |
| `--vad-filter` | | 啟用 VAD 語音活動偵測 (過濾靜音/雜音) | 停用 |
| `--initial-prompt` | | 初始提示詞 (引導繁中、台語或專有名詞) | 台灣繁中/台語專用語引導 |
| `--max-words` | | 限制單一字幕片段最大字數 (超長自動拆分) | 無 |
