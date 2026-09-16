# Docker vLLM 圖片多模態 (Vision VLM) 解析參考文件

本文件記載 Docker vLLM 處理單圖/多圖解析時的 API 規格、預設端點與優化指引。

---

## 1. 預設 4 個 Docker vLLM 端點與自動探測機制

腳本預設會按順序輪詢探測下列 4 個 Docker vLLM 候選端點：

1. `http://192.168.1.100:8000/v1`
2. `http://192.168.1.100:8001/v1`
3. `http://192.168.1.100:8002/v1`
4. `http://192.168.3.9:8000/v1`

### 自動探測與模型獲取流程：
- 腳本啟動時，會自動向上述端點發送 `GET <endpoint>/models` 請求。
- 第一個連線成功的端點將被選為主要端點。
- 腳本會自動讀取 `/v1/models` 回傳 JSON 中的 `data[0].id` 作為當前執行的 Model 名稱。

---

## 2. Base64 傳輸與預處理機制

1. **Base64 打包**：在 Host 端將圖片轉為 `data:image/jpeg;base64,...` 發送，完全擺脫 Docker 容器隔離讀不到圖的問題。
2. **自動 Resize**：圖片任一邊長 > 2048px 時自動等比例縮放，避免超大圖導致 VRAM OOM。
3. **dHash 重複/相似度過濾**：批次處理時過濾相似度 $\ge 95\%$ 的重複圖片 (Hamming Distance $\le 4$)。
