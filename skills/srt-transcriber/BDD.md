# 行為驅動驗收文件 (Behavior-Driven Development - BDD)
## 專案名稱：SRT Transcriber 旗艦版 (三合一整合影音轉逐字稿技能)

---

## 核心驗收情境 (Acceptance Scenarios - Gherkin Syntax)

### 情境 1: 影音轉錄標準 SRT 字幕產出 (Happy Path)
```gherkin
場景: 使用者傳入標準 mp4 檔案並產出符合規範之 SRT 字幕檔
  假設 輸入檔案為合法的影片檔案 `video.mp4`
  並且 影片中包含繁體中文語音說明
  當 執行 `uv run scripts/transcribe.py "video.mp4"`
  那麼 系統 MUST 成功產出同名之 `video.srt` 檔案
  並且 字幕內容 MUST 包含自 1 開始遞增之整數序號
  並且 時間戳格式 MUST 嚴格符合 `HH:MM:SS,mmm --> HH:MM:SS,mmm` 格式
```

### 情境 2: MediaTek Breeze-ASR 核心台語與繁體中文特化轉錄 (Taigi & Traditional Chinese Mode)
```gherkin
場景: 當指定模型為 breeze-asr 或語言為 zh-TW 時，系統自動採用 MediaTek Breeze-ASR-26 模型並注入台語專用 Prompt
  假設 輸入檔案包含台灣在地口白、台語與中英文混用之會議或操作對白
  當 執行腳本傳入參數 `--model breeze-asr` 或 `--language zh-TW`
  那麼 系統 MUST 自動解析模型權重為 `paulpengtw/faster-whisper-Breeze-ASR-26-ct2`
  並且 引擎內部 MUST 將語言設定正規化為 `zh`
  並且 初始提示詞 (Initial Prompt) MUST 自動注入台灣繁中與台語專用語意引導字串
  並且 輸出的逐字稿文本中 MUST 以繁體中文呈現，精準還原台語工程口語
```

### 情境 3: 多格式同步輸出 (Multi-Format Export)
```gherkin
場景: 同時輸出 SRT, VTT, TXT 與 JSON 格式
  假設 使用者指定 `--format srt,vtt,txt,json`
  當 轉錄推論完成時
  那麼 磁碟中 MUST 同時產生對應之 `.srt`、`.vtt`、`.txt` 與 `.json` 四種檔案
  並且 `.vtt` 檔案開頭 MUST 具備 `WEBVTT` 標頭
  並且 `.txt` 檔案 MUST 為連續之純文字逐字稿
  並且 `.json` 檔案 MUST 可被成功解析為包含段落與時間戳之合法 JSON 物件
```

### 情境 4: 運算裝置自適應降級與顯存容錯 (Hardware Adaptive Fallback)
```gherkin
場景: 當環境未配置 GPU 或 CUDA 不可用時，自動平滑降級為 CPU 推論
  假設 執行環境為純 CPU 電腦或 CUDA 驅動缺失
  當 執行轉錄任務時
  那麼 系統 MUST NOT 拋出 CUDA 例外而中止
  並且 系統 SHOULD 自動將 device 設置為 `cpu`，計算精度降級為 `int8`
  並且 終端機印出明確友善之 CPU 運算提示訊息
```

### 情境 5: 異常邊界處理 (Edge Cases & Resilience)
```gherkin
場景 5.1: 輸入不支援之非影音格式或檔案不存在
  假設 使用者傳入不存在之檔案路徑或 `.exe` 檔案
  當 腳本啟動執行時
  那麼 系統 MUST 於預檢階段攔截並拋出清晰中文錯誤提示
  並且 程式退出代碼 (Exit Code) MUST 為非 0

場景 5.2: 影片包含長段靜音或環境背景雜音
  假設 使用者啟用 `--vad-filter` 參數
  當 引擎處理無人聲之靜音區間時
  那麼 系統 MUST 自動過濾無聲片段，避免產生重複文字之 Whisper 幻覺現象
```
