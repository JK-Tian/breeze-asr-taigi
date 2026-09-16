# Frontend Developer Agent Guidance (前端 Agent 開發規範)

## 1. 框架與管理
- 使用 `pnpm` 管理 JavaScript / TypeScript 套件與相依性。
- 使用 Next.js (App Router) + React + Tailwind CSS 構建現代化 Web 介面。

## 2. API 通訊規範
- 前端透過 `NEXT_PUBLIC_API_BASE` (預設 `/api/v1`) 通訊。
- 支援任務狀態輪詢 (`GET /api/v1/transcriptions/{task_id}`)。
- 支援顯示二階段處理結果（校正後逐字稿與四區塊會議紀錄）。
- 提供一鍵重新生成摘要/校正按鈕 (`POST /api/v1/transcriptions/{task_id}/resummarize`)。

## 3. UI/UX 與視覺設計
- 採用高對比且簡潔質感之現代 UI 風格。
- Markdown 渲染須支援標頭、待辦事項核取方塊、重點區塊與程式碼區塊高亮。

## 4. 音檔生命週期與上傳容錯規範 (Audio Resilience)
- **音檔防丟失原則**：使用者透過檔案選擇、拖曳或網頁麥克風錄音產生之 `File` 物件，在上傳請求未確認成功前，嚴禁清空或銷毀。
- **上傳失敗處理**：當發送 `POST /transcriptions` 失敗時，前端狀態切換為 `failed`，保留當前 `file` 物件，並在畫面錯誤卡片中提供：
  1. **「重試一次」按鈕**：直接重新觸發 `handleUpload()`，免去使用者重選檔案或重新錄音。
  2. **「下載音檔」按鈕**：直接透過 `URL.createObjectURL(file)` 下載本機音訊至使用者磁碟。
  3. **「重新選擇」按鈕**：允許使用者清除狀態並返回首頁。
- **記憶體釋放**：建立 Object URL 後，必須在觸發下載後調用 `URL.revokeObjectURL`，避免長期運行產生 Memory Leak。
