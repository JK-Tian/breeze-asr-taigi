# 行為驅動驗收文件 (Behavior-Driven Development - BDD)
## 專案名稱：Video to Notes (視訊會議轉會議記錄技能)

---

## 核心驗收情境 (Acceptance Scenarios - Gherkin Syntax)

### 情境 1: ASR 逐字稿語意審核與錯別字校正 (Happy Path)
```gherkin
場景: 當語音轉錄產生同音異字或專有名詞誤差時，校對機制能根據簡報與語意修正
  假設 Agent 已取得語音辨識之原始逐字稿，內容包含同音詞「這批導流版工差要控制在一條以內」
  並且 Agent 已透過視覺預檢獲取 PPT 簡報標題為「導流板精密加工公差規範」
  當 Agent 執行語意校對與重點提煉時
  那麼 提煉出的會議重點中 MUST 正確記載為「導流板」與「公差」
  並且 決策與待辦清單中 MUST NOT 出現「導流版」或「工差」之錯別字
```

### 情境 2: 視覺畫面認知輔助與零截圖產出保證 (Visual Context & Zero-Screenshot Output)
```gherkin
場景: AI 閱讀簡報圖表與螢幕展示數據，但最終 Word 會議記錄完全不包含截圖
  假設 視訊會議錄影中包含 15 頁 PPT 投影片與 2 段系統操作展示
  並且 Agent 透過視覺預檢捕捉了關鍵產出數據「良率提升至 99.2%」
  當 Agent 呼叫 generate_notes_docx.py 腳本產出會議記錄 Word 文件時
  那麼 Word 內文之核心摘要 MUST 正確包含數據「良率提升至 99.2%」
  並且 產出之 Word 文件中的 Inline Shapes 與 Picture 數量 MUST 為 0
  並且 生成之 Markdown 內文除了文末參考資料外，MUST NOT 嵌入任何圖片標籤 `![]()`
```

### 情境 3: 發言人 / 與會者身分標記 (Speaker Attribution)
```gherkin
場景: 議題討論紀要中若能辨識發言者則明確標註
  假設 會議錄影中主持人說「請品質部張處長發表看法」，隨後發言者說明檢驗規範
  當 Agent 提煉該段落之討論紀要時
  那麼 議題討論項目中 SHOULD 明確標註發言人為「【張處長】」或「【品質部張處長】」
  並且 條列出其所提之具體觀點與要求
```

### 情境 4: 關鍵決策事項與 Todo 行動清單表格化 (Decisions & Action Items)
```gherkin
場景: 決策與 Todo 事項被精確解析並以專業商務表格呈現
  假設 會議中決議「採購第 2 套導流板治具」並指派「王組長於 10/15 前完成詢價」
  當 產出會議記錄 Markdown 與 Word 文件時
  那麼 決策章節 MUST 呈現決策內容「採購第 2 套導流板治具」
  並且 待辦事項表格 MUST 包含任務「完成詢價」、負責人「王組長」與截止期限「10/15」
  並且 Word 表格中該 Todo 項目開頭 MUST 具備核取方塊符號 `☐`
```

### 情境 5: 下次會議追蹤項目作為重點 Highlight (Next Meeting Follow-ups)
```gherkin
場景: 標示下次會議開場時之回顧重點與報告人
  假設 會議結尾確認下次開會需檢視「新治具試作數據」
  當 產出會議記錄時
  那麼 文件結尾前 MUST 具備「下次會議追蹤項目 (Next Meeting Follow-ups)」專屬章節或表格
  並且 明確列出追蹤項目、預計報告人與期望交付成果
```

### 情境 6: 極端邊界條件容錯處置 (Edge Cases & Resilience)
```gherkin
場景 6.1: 討論型會議未產出任何明確決策 (No Decisions Made)
  假設 該視訊會議為純現況同步會，並未表決或形成任何具體決策事項
  當 腳本解析該 Markdown 文件時
  那麼 決策章節 MUST NOT 拋出異常崩潰
  並且 系統 SHOULD 在決策區塊優雅標註「本會議為資訊同步會議，無新增決策事項」

場景 6.2: 檔案鎖定衝突 (PermissionError)
  假設 使用者已於 Microsoft Word 中開啟該 output.docx
  當 generate_notes_docx.py 嘗試寫入儲存時
  那麼 腳本 MUST 捕捉 PermissionError 並印出清楚中文指引
  並且 自動加上時間戳後綴（如 `output_20260914_2355.docx`）完成安全輸出
```

### 情境 7: 文末影片來源規範 (References Section)
```gherkin
場景: 影片檔案來源置於文件末端
  假設 會議錄影路徑為 `meetings/2026-09-14_週會.mp4`
  當 產出會議記錄 Markdown 與 Word 文件時
  那麼 開頭 YAML parameters 中 MUST NOT 包含影片來源鍵值
  並且 文件最末端 MUST 具備 `# 參考資料` 章節
  並且 內容格式 MUST 包含 `- [meetings/2026-09-14_週會.mp4]`
```
