# Breeze ASR 會議紀錄系統 (Frontend)

本目錄包含系統網頁前端的實作，主要功能為：

1. 提供直覺的使用者介面，支援上傳會議音檔。
2. 顯示處理進度與狀態 (Pending -> Processing -> Completed)。
3. 以美觀的方式展示逐字稿，並標記講者與時間軸。

## 技術選型

- 框架：**Next.js (App Router)**
- 樣式：**Tailwind CSS** (搭配現代化 UI 設計、玻璃擬物化風格)
- 套件管理：`pnpm`

## 開發指南

1. 安裝依賴：

   ```bash
   pnpm install
   ```
2. 啟動開發伺服器：

   ```bash
   pnpm dev
   ```
3. 開啟瀏覽器訪問 `http://localhost:3000`。

## 系統互動

前端會透過 RESTful API 與後端溝通：

- 呼叫 `POST /api/v1/transcriptions` 建立上傳任務。
- 定期 (Polling) 呼叫 `GET /api/v1/transcriptions/{id}` 取得任務最新進度。
- 任務完成後將 `result` 欄位解析，並於畫面上優雅渲染。

## 部署與正式版 (Production)

為了讓前端網頁在公司內部能有最快、最順暢的執行速度，並且避免開發模式下不必要的 HMR (WebSocket) 警告，我們提供了一鍵啟動正式版的腳本。

### 1. 編譯正式版 (Build)

當您修改了前端程式碼 (例如 `src/app/page.tsx`) 後，必須先執行打包指令：

```bash
pnpm run build
```

這個指令會將 React 程式碼最佳化為極速的靜態資源。

### 2. 啟動正式版服務

編譯完成後，您可以直接回到「專案最外層目錄」，連按兩下執行我們為您準備好的腳本：
👉 **`start_service.bat`**

此腳本會：

1. 在背景同時啟動後端 FastAPI (Port 8787)。
2. 在背景啟動前端 Next.js 正式版伺服器 (Port 3000)。
3. 使用者（或同事）只要在瀏覽器輸入 `http://<您的區域網路IP>:3000` (或使用 ngrok 網址)，即可享受最高效能的服務體驗。
