# Frontend Developer Agent Guidance (前端 Agent 開發規範)

## 1. 框架與管理
- 使用 `pnpm` 管理 JavaScript / TypeScript 套件與相依性。
- 使用 Next.js (App Router) + React + Vanilla CSS 構建現代化 Web 介面。

## 2. API 通訊規範
- 前端透過 `NEXT_PUBLIC_API_BASE` (預設 `/api/v1`) 通訊。
- 支援任務狀態輪詢 (`GET /api/v1/transcriptions/{task_id}`)。
- 支援顯示二階段處理結果（校正後逐字稿與四區塊會議紀錄）。
- 提供一鍵重新生成摘要/校正按鈕 (`POST /api/v1/transcriptions/{task_id}/resummarize`)。

## 3. UI/UX 與視覺設計
- 採用高對比且簡潔質感之現代 UI 風格。
- Markdown 渲染須支援標頭、待辦事項核取方塊、重點區塊與程式碼區塊高亮。
