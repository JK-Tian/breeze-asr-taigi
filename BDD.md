# 行為驅動開發規格書 (Behavior-Driven Development - BDD.md)
## 天工會議紀錄：KM Wiki Minutes 知識庫 raw 檔區同步驗收場景

---

### Scenario 1: 音視會議轉錄完成後自動同步至 KM Wiki Minutes 知識庫 raw 檔區 (Happy Path)
- **Given**: 系統組態設定 `[KMWiki] enabled = true`，且目標路徑為 `D:/km_wiki/Minutes/raw`，`date_subfolder = true`
- **And**: 使用者上傳會議錄音或視訊，後端完成語音辨識、LLM 校正與 Obsidian 會議記錄提煉
- **When**: 本地存檔模組於 `output/2026-09-17/` 產出 `Q3營運檢討會_逐字稿.md` 與 `Q3營運檢討會_會議紀錄與摘要.md`
- **Then**: 系統自動在 `D:/km_wiki/Minutes/raw/2026-09-17/` 建立對應資料夾
- **And**: 完整複製逐字稿與會議記錄兩份 Markdown 檔案至該目錄
- **And**: 任務資料庫記錄 `km_wiki_synced = True`，前端呈現「已同步至 KM Wiki」標籤。

---

### Scenario 2: 重新生成會議記錄 (Resummarize) 自動同步更新知識庫
- **Given**: 一筆已完成轉錄但先前摘要需要重新調整之會議任務 (ID: `task-123`)
- **When**: 使用者在介面上點擊「重新生成摘要」按鈕
- **Then**: LLM 重新整理出新版結構化會議記錄
- **And**: 系統自動更新本機 `output/YYYY-MM-DD/` 之會議記錄 `.md`
- **And**: 系統自動將最新版會議記錄覆蓋更新至 `D:/km_wiki/Minutes/raw/YYYY-MM-DD/`
- **And**: 保持知識庫檔案與最新會議摘要完全一致。

---

### Scenario 3: KM Wiki 目錄磁碟離線或無寫入權限時之平滑降級 (Edge Case 1 & Graceful Degradation)
- **Given**: 目標路徑 `D:/km_wiki/Minutes/raw` 指向之網路共享硬碟斷線或當前權限不足
- **When**: 後端任務嘗試執行 KM Wiki 檔案複製
- **Then**: `KMWikiService` 捕捉 `OSError` / `PermissionError` 例外並記錄警告日誌
- **And**: 系統將任務之 `km_wiki_synced` 標記為 `False`，並將主任務狀態標記為 `completed`
- **And**: 本地 `output/YYYY-MM-DD/` 檔案完好保留，主語音轉錄流程不中斷崩潰。

---

### Scenario 4: 會議名稱包含特殊字元或路徑遍歷攻擊之防禦 (Security Review)
- **Given**: LLM 生成或使用者輸入之會議主題為 `../../etc/conf/重大決議:會議*報告`
- **When**: 系統準備同步至 KM Wiki raw 檔區
- **Then**: `sanitize_filename` 消毒過濾非法字元，安全轉化為 `重大決議會議報告`
- **And**: 檔案被限制在 `D:/km_wiki/Minutes/raw/{YYYY-MM-DD}/重大決議會議報告_會議紀錄與摘要.md` 內，杜絕任何路徑遍歷漏洞。

---

### Scenario 5: 透過 RESTful API 手動觸發 KM Wiki 同步 (Controller Endpoint)
- **Given**: 某歷史任務先前因網路短暫斷線未能成功同步至 KM Wiki (`km_wiki_synced = False`)
- **When**: 用戶端發送 HTTP `POST /api/v1/transcriptions/{task_id}/sync-km-wiki`
- **Then**: 後端確認該任務存在且本機檔案齊全
- **And**: 重新調用 `KMWikiService` 執行檔案寫入
- **And**: 回傳 HTTP 200 與成功訊息，將該任務更新為 `km_wiki_synced = True`。

---

### Scenario 6: 停用 KM Wiki 同步設定時之平滑跳過 (Feature Toggle)
- **Given**: 系統組態設定 `[KMWiki] enabled = false`
- **When**: 會議轉錄完成並存檔本地
- **Then**: 系統略過 KM Wiki 複製動作，不產生多餘目錄，記錄 `km_wiki_synced = False`，任務正常結束。
