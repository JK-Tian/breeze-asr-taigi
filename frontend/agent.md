# Frontend Developer Agent Guidance (前端 Agent 開發規範)

## 1. 框架與套件管理
- 使用 `pnpm` 管理 JavaScript / TypeScript 套件與相依性。
- 使用 Next.js (App Router) + React + Tailwind CSS 構建現代化 Web 介面。

## 2. API 通訊與成果展示規範
- 前端透過 `NEXT_PUBLIC_API_BASE` (預設 `/api/v1`) 通訊。
- 支援任務狀態輪詢 (`GET /api/v1/transcriptions/{task_id}`)。
- 支援顯示校正後逐字稿與結構化會議記錄。
- 提供一鍵重新生成摘要按鈕 (`POST /api/v1/transcriptions/{task_id}/resummarize`)。
- **會議記錄下載規範**：
  - 會議記錄無論語音或影片來源，均以 `.md` 檔案儲存與下載（相容 Obsidian PKM 格式）。
  - 會議記錄卡片右上角提供「下載 .md」按鈕，觸發瀏覽器下載 UTF-8 編碼之 Markdown 筆記。

## 3. 影音全格式支援與 UI/UX 規範
- 支援使用者上傳任何形式的會議影音（純語音錄音、視訊會議錄影如 MP4, MKV, MOV, WEBM, AVI 等、網頁麥克風錄音）。
- `<input type="file" accept="audio/*,video/*,.mp4,.mkv,.mov,.avi,.webm">`。
- 上傳卡片視覺強化：動態辨識為視訊或音訊，顯示對應圖示（`FileVideo` 或 `FileAudio`），提示文案清楚標明支援視訊會議錄影與音訊檔。

## 4. 影音生命週期與上傳容錯規範 (Media Resilience)
- **影音防丟失原則**：使用者選取或錄製之 `File` 物件，在上傳請求未確認成功前，嚴禁清空或銷毀。
- **上傳失敗處理**：當發送 `POST /transcriptions` 失敗時，前端狀態切換為 `failed`，保留當前 `file` 物件，並在畫面錯誤卡片中提供：
  1. **「重試一次」按鈕**：直接重新觸發 `handleUpload()`，免去使用者重新選取大型視訊檔案或重新錄音。
  2. **「下載影音」按鈕**：直接透過 `URL.createObjectURL(file)` 下載本機影音備份至磁碟。
  3. **「重新選擇」按鈕**：允許使用者清除狀態並返回首頁。
- **記憶體釋放**：建立 Object URL 後，必須在觸發下載後調用 `URL.revokeObjectURL`，避免長期運行產生 Memory Leak。
