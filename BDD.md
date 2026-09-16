# 行為驅動規格書 (Behavior Driven Development - BDD.md)
## 天工會議紀錄：多模態視訊會議理解驗收場景

---

## 1. 規範參數定義 (Parameters)

```yaml
parameters:
  system_under_test: "天工會議紀錄系統 (Multimodal Vision & Audio Edition)"
  test_environment:
    os: "Windows 11"
    python_env: "uv run (Python 3.10+)"
  vlm_endpoints:
    vllm_url: "http://192.168.1.100:8000/v1"
    default_model: "auto"
  supported_video_formats:
    - ".mp4"
    - ".mkv"
    - ".mov"
    - ".webm"
    - ".avi"
```

---

## 2. 核心行為驗收場景 (Gherkin Scenarios)

### 場景 1：視訊會議關鍵幀智慧擷取與簡報換頁偵測
* **Given** 使用者上傳了一個包含簡報投影片展示的會議錄影檔案 (`meeting.mp4`)
* **When** 系統啟動關鍵幀擷取器 (`KeyframeExtractor`)
* **Then** 系統 **MUST** 透過 FFmpeg 場景切換演算法自動識別出簡報切換的時間點
* **And** 擷取之影像幀 **MUST** 縮放為標準尺寸 (`1280x720`) 以兼顧辨識率與推論效率
* **And** 擷取數量 **MUST NOT** 超過設定之最大上限 (預設 30 張)，每張畫面均帶有對應之會議時間戳

### 場景 2：多模態 VLM 萃取投影片核心數據與決策標記
* **Given** 關鍵幀擷取器成功抽取出多張投影片 JPEG 畫面
* **When** 系統調用多模態 VLM 客戶端 (`VLMClient`) 向 `http://192.168.1.100:11434` 發送分析請求
* **Then** 模型 **MUST** 辨識出畫面上的投影片標題、關鍵業績數字 (如 KPI, 預算, 達成率) 與圖表趨勢
* **And** 輸出結構化為包含時間標記的視覺時間軸文字摘要 (`VisualTimeline`)

### 場景 3：音視雙模態融合生成高階商務會議筆記
* **Given** 語音轉錄管線已產出 ASR 逐字稿，且視覺管線已產出時間軸簡報摘要
* **When** 提煉引擎將語音逐字稿與視覺摘要共同傳入 LLM 會議記錄模型
* **Then** 模型 **MUST** 對照投影片上的專有名詞修正語音同音錯別字
* **And** 產出之會議記錄【會議核心摘要 (Highlights)】與【議題討論紀要】中，**MUST** 包含投影片展示之具體數據結論（即使發言人口頭未逐字提及）
* **And** 產出之 Markdown 文件 **MUST** 嚴格遵循 `skills/video-to-notes` 的 Obsidian PKM YAML Frontmatter 格式

### 場景 4：零截圖純淨排版與看完即忘清理機制 (Zero-screenshot & Ephemeral)
* **Given** 視覺理解管線已完成所有關鍵幀的多模態推論與摘要整理
* **When** 系統完成 Obsidian Markdown 會議筆記寫入
* **Then** 系統 **MUST** 立即清空並刪除暫存目錄下的所有截圖檔案
* **And** 產出之 Markdown 檔案中 **MUST NOT** 包含任何圖片語法 (`![]()`)，維持純淨文字商務排版
* **And** 檔案最末端 **MUST** 正確收錄 `# 參考資料` 並標註原始影片來源

### 場景 5：純音訊或多模態服務異常時的平滑自適應降級 (Graceful Fallback)
* **Given** 使用者上傳了一個純音訊檔案 (`audio.mp3`)，或視訊檔案的影像軌損壞，或 VLM 伺服器暫時斷線
* **When** 系統偵測到無法提取影像畫面或呼叫 VLM 遭遇逾時
* **Then** 系統 **MUST** 捕捉例外並記錄友善日誌，自動平滑降級至純語音轉錄流程
* **And** 任務狀態 **MUST NOT** 崩潰為 `failed`，最終仍順利產出完整的會議記錄

---

## 3. SOP 驗證流程 (Verification Protocol)

```yaml
parameters:
  inputs:
    - test_suite: "tests/unit/test_keyframe_extractor.py"
    - test_suite_vlm: "tests/unit/test_vlm_client.py"
    - test_suite_multimodal: "tests/unit/test_multimodal_minutes.py"
  outputs:
    - test_report: "pytest_results.xml"
```

#### Steps (RFC2119 關鍵字)
1. 測試套件 **MUST** 在單元測試中模擬 FFmpeg 輸出，驗證關鍵幀擷取與時間戳計算正確性。
2. 測試套件 **MUST** 模擬 VLM 回傳結構化視覺文字，驗證 VisualTimeline 解析無誤。
3. 測試套件 **MUST** 驗證多模態 Prompt 注入後，生成的會議筆記滿足 video-to-notes 規範。
4. 測試套件 **MUST** 驗證清理函式在成功與失敗兩種情況下均能確實抹除暫存截圖。

#### Error Handling (異常與邊界處理)

| 編號 | 異常條件 (Criteria) | 系統行動 (Action) |
| :--- | :--- | :--- |
| **EH-01** | VLM 服務回應格式非 JSON 或缺少預期欄位 | 系統 **MUST** 採取防禦性字串清洗，降級為純文字解析，**MUST NOT** 造成反序列化崩潰。 |
| **EH-02** | 視訊時間軸長度異常 (0 秒或負數) | 擷取器 **MUST** 拒絕處理並回傳空清單，觸發平滑降級。 |
| **EH-03** | 暫存目錄權限不足無法刪除 | 清理模組 **MUST** 捕捉 `PermissionError`，記錄警示並於下一次啟動時標記待清理，**MUST NOT** 阻斷主流程完成。 |
