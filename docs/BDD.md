# 行為驅動開發規範 (Behavior-Driven Development, BDD)

本文件定義視訊會議錄影與音訊檔案轉錄、透過 LLM (`192.168.1.100:8002/v1`) 進行錯別字語意校正、遵循 `skills/video-to-notes` 規範產出結構化 Markdown (`.md`) 會議記錄，以及網頁端與獨立腳本（Script）執行的驗收測試場景。檔案格式統一以 `.md` 產出，不需要轉為 Word 檔。

---

## 核心業務邏輯測試場景 (Happy Path)

### 功能 1：視訊會議檔案音訊分離與 ASR 轉錄
```gherkin
功能: 視訊會議錄影音訊提取與語音轉錄
  作為 一名會議參與者
  我希望 系統能夠直接接收視訊會議錄影檔 (如 .mp4, .mkv, .mov, .webm)
  並且 自動提取音訊、標準化並進行高精準度台語/華語轉錄與講者辨識
  以利後續產出會議記錄

  場景 1.1: 傳入 MP4 視訊會議檔案執行轉錄
    假設 終端機或前端存在會議視訊錄影檔 "meeting_20260916.mp4"
    當 系統啟動轉錄流程
    則 系統應透過 ffmpeg 自動提取音軌並轉換為 16kHz mono WAV 與 128k MP3
    並且 Breeze-ASR-26 應順利完成語音辨識與講者標記
    並且 產出標註時間戳與發言人的原始逐字稿
```

### 功能 2：ASR 逐字稿語意錯別字校正
```gherkin
功能: ASR 轉錄後語意錯別字校正
  作為 一名會議紀錄使用者
  我希望 系統在 ASR 轉錄出原始逐字稿後，自動發送至 LLM (192.168.1.100:8002/v1) 修正同音錯別字與專有名詞
  以獲得 高品質且通順的校正逐字稿

  場景 2.1: 成功校正 ASR 轉錄稿中的錯別字
    假設 語音轉寫服務已完成音檔轉寫，產生原始逐字稿:
      "[00:00:05] 講者 A: 我們今天要討論 Breeze ASR 與 Ollama 模形整合。"
    當 系統發送校正請求至 "http://192.168.1.100:8002/v1/chat/completions"
    則 校正後內容應修正為:
      "[00:00:05] 講者 A: 我們今天要討論 Breeze ASR 與 Ollama 模型整合。"
    並且 保留原始時間戳與講者代號

  場景 2.2: 透過 /v1/models 動態查詢伺服器運行之模型名稱
    假設 伺服器 "http://192.168.1.100:8002/v1/models" 運行的模型清單包含 "nvidia/Qwen3.6-35B-A3B-NVFP4"
    當 系統初始化 LLMClient 或未指定模型名稱時
    則 系統應自動發送 GET 請求至 "/v1/models"
    並且 解析出當前可用的第一個模型 ID 作為後續請求之 model 參數
    並且 若伺服器查詢失敗則優雅回退至設定檔之備援模型名稱
```

### 功能 3：產出符合 video-to-notes 規範之結構化會議記錄 (.md)
```gherkin
功能: 無論語音或影片均提煉符合 video-to-notes 規格之會議記錄 Markdown (.md)
  作為 一名企業主管或專案經理
  我希望 不管是語音轉的還是影片轉的會議紀錄，皆產出標準 Obsidian PKM 格式之 .md 檔案（無需 Word 檔）
  以便於 匯入知識管理系統並進行跨專案追蹤

  場景 3.1: 影片轉會議記錄產出相容 video-to-notes 規範之 Markdown
    假設 已取得校正後之逐字稿，原始影片檔名為 "quarterly_review.mp4"
    當 系統提煉會議記錄 Markdown
    則 產出檔案格式必須為 ".md"
    並且 Markdown 開頭必須包含標準 Obsidian PKM YAML frontmatter:
      """
      ---
      title : [會議標題]
      description : 
      date : YYYY-MM-DD HH:MM
      aliases : []
      status : inbox
      tags : 
      Topics : 
      Type : 
        - 📝/✨
      ---
      """
    並且 frontmatter 中嚴格禁止寫入影片來源路徑
    並且 內文必須包含以下結構化區塊：
      - "# [會議標題]"
      - "## 1. 會議基本資訊" (時間、地點、主席、記錄、出席、請假)
      - "## 2. 會議核心摘要 (Highlights)" (3~5 點要點)
      - "## 3. 關鍵決策事項 (Decisions Made)" (Markdown 表格)
      - "## 4. 待辦事項清單 (Action Items / Todo List)" (Markdown 表格)
      - "## 5. 各議題討論紀要 (Agenda & Discussions)" (標註【發言人】)
      - "## 6. 下次會議追蹤項目 (Next Meeting Follow-ups)" (Markdown 表格)
    並且 文件最末端必須包含 "# 參考資料" 章節，格式為:
      "- [quarterly_review.mp4]"

  場景 3.2: 純語音轉會議記錄亦產出相容 video-to-notes 規範之 Markdown
    假設 已取得校正後之逐字稿，原始音訊檔名為 "weekly_standup.mp3"
    當 系統提煉會議記錄 Markdown
    則 產出檔案格式同樣為 ".md"
    並且 遵循完全相同的 Obsidian PKM frontmatter 與六大結構化商務區塊
    並且 文末包含 "# 參考資料" 章節:
      "- [weekly_standup.mp3]"
```

### 功能 4：獨立 Script 與網頁前端整合支援
```gherkin
功能: 雙重入口支援視訊與音訊檔案並下載 .md 會議記錄
  作為 使用者
  我希望 在命令列與網頁端都能輕鬆使用上述功能

  場景 4.1: 透過獨立 CLI 腳本傳入視訊檔並自動產出 .md 檔案
    假設 終端機存在視訊檔案 "team_sync.mp4"
    當 使用者執行 "uv run python scripts/transcribe_and_summarize.py --audio team_sync.mp4"
    則 系統應完成音訊分離、轉錄、校正與摘要提煉
    並且 產出 "team_sync_逐字稿.md" 與 "team_sync_會議紀錄與摘要.md" 於 output 目錄
    並且 終端機印出產出檔案路徑

  場景 4.2: 網頁端選取視訊或音訊檔案、完成後預覽與下載 .md
    假設 使用者開啟前端網頁介面
    當 使用者拖曳視訊檔案 "meeting.mp4" 至上傳卡片並點擊開始轉錄
    則 上傳元件應支援該視訊格式並顯示視訊名稱與檔案大小
    並且 轉錄完成後前端呈現逐字稿與會議記錄 Markdown 渲染預覽
    並且 提供「下載 .md」按鈕下載符合 video-to-notes 規格之會議記錄
```

---

## 異常與邊界條件場景 (Edge Cases & Unhappy Path)

### 場景 5：視訊檔案無有效音軌 (Edge Case)
```gherkin
  場景: 上傳之視訊檔案為靜音或無音軌串流
    假設 使用者上傳一個未包含音訊軌道的視訊檔 "silent_video.mp4"
    當 ffmpeg 嘗試提取音訊失敗時
    則 系統應捕捉 ffmpeg 錯誤例外
    並且 任務狀態應標記為 "failed"
    並且 錯誤訊息應提示「該視訊檔案未包含有效音軌或格式已損毀」
    並且 伺服器進程不得崩潰
```

### 場景 6：視訊或音訊檔案上傳失敗時之本地保全 (Unhappy Path)
```gherkin
  場景: 大檔案視訊上傳遭遇網路中斷
    假設 使用者選取 800MB 視訊檔 "all_hands.mp4" 點擊上傳
    當 網路斷線或後端暫時無回應導致上傳請求失敗
    則 前端狀態切換為 "failed"
    並且 前端不得清空或丟失已選取之視訊 File 物件
    並且 錯誤畫面中應呈現「重試一次」與「下載影音」按鈕
    並且 點擊「下載影音」應順利觸發瀏覽器下載本地視訊檔案備份
```

### 場景 7：會議內容無具體決策或待辦事項 (Edge Case)
```gherkin
  場景: 溝通型會議無任何表決決策與指派任務
    假設 會議為日常狀態交流或團隊閒聊，逐字稿中無任何具體決策或待辦
    當 系統提煉會議記錄 Markdown
    則 系統不應報錯崩潰
    並且 決策與待辦區塊應優雅提示「本會議為資訊同步會議，無新增表決決策與待辦追蹤項目」
```
