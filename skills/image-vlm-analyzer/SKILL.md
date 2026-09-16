---
name: image-vlm-analyzer
description: 當使用者提供單張圖片檔案路徑 (.png, .jpg, .webp, .bmp)、多張圖片或包含圖片之資料夾目錄，希望進行圖片內容分析、OCR 文字識別、多圖批次摘要或視覺細節問答時觸發。務必在使用者提及圖片理解、圖片解析、圖表說明、圖片轉文字 (OCR) 或提供圖片路徑時使用本 Skill。本 Skill 自動輪詢 4 個預設 Docker vLLM 端點 (192.168.1.100:8000~8002, 192.168.3.9:8000) 並透過 GET /v1/models 自動查詢模型名稱，執行超大圖 Resize (Max 2048px)、Base64 打包、dHash 相似圖片去重與單圖串流 API 呼叫，即時產出結構化 Markdown 圖片分析日誌報告。
---

# Image VLM Analyzer (圖片多模態預處理、去重與串流解析 Skill)

本 Skill 專門用於解決 **Pi Agent 傳送圖片給 Docker vLLM 時「讀不到圖 (容器隔離)」與「超大圖/多圖顯存爆掉 (OOM / Context Exhaustion)」** 的問題。

---

## 核心機制與技術特色 (Architectural Highlights)

1. **Docker vLLM 端點輪詢與自動模型查詢**：
   - 預設自動輪詢探測 `192.168.1.100:8000`, `192.168.1.100:8001`, `192.168.1.100:8002`, `192.168.3.9:8000` 共 4 個候選端點。
   - 透過 `GET /v1/models` 自動取得當前健康端點運行的模型名稱 (Model ID)。
2. **Base64 Payload 橋接**：在 Host 端將圖片轉為 Base64 Data URL，完全免除 Docker 容器目錄掛載問題。
3. **自動 Resize (防 VRAM OOM)**：圖片邊長 >2048px 時自動縮放。
4. **dHash 相似圖片去重**：過濾相似度 $\ge 95\%$ 的重複圖片 (漢明距離 $\le 4$)。
5. **單圖串流寫入 (Stream Processing)**：一次處理 1 張圖片並即時 Append 寫入 `.md` 報告檔。

---

## Agent 標準執行 SOP

* **單張圖片解析**：
  ```bash
  uv run python skills/image-vlm-analyzer/scripts/analyze_images.py \
    --image "<path/to/image.png>" \
    --output "<path/to/image_report.md>"
  ```

* **圖片資料夾批次解析**：
  ```bash
  uv run python skills/image-vlm-analyzer/scripts/analyze_images.py \
    --dir "<path/to/image_folder>" \
    --output "<path/to/folder_report.md>" \
    --threshold 4
  ```

* **自訂特定焦點解析 (根據使用者提問動態帶入 `--prompt`)**：
  若使用者的提問有特定側重點（如：瑕疵判定、OCR 文字提取、圖表數據分析、SOP 流程說明等），Agent **MUST** 將使用者的具體意圖帶入 `--prompt` 參數傳給腳本：
  ```bash
  uv run python skills/image-vlm-analyzer/scripts/analyze_images.py \
    --image "<path/to/image.png>" \
    --output "<path/to/image_report.md>" \
    --prompt "請詳細檢查這張圖片中是否有表面瑕疵或裂紋，並說明其位置與嚴重程度。"
  ```

*若需手動指定特定的 vLLM API 位址與模型，可附加 `--vllm-url` 或 `--model` 參數。*
