# Docker vLLM 多模態 (Vision VLM) 端點設定指南

`video-timeline-indexer` 透過標準 OpenAI 相容介面 (`/v1/chat/completions`) 與 Docker 執行的 vLLM 進行對接。

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
- 腳本會自動讀取 `/v1/models` 回傳 JSON 中的 `data[0].id` 作為當前執行的 Model 名稱 (無需手動硬編碼模型名稱)。

---

## 2. 環境變數覆蓋設定

若需強制指定特定的端點或模型名稱，可設定 `.env` 檔案：

```ini
# 強制指定 Docker vLLM API 位址
VLLM_BASE_URL=http://192.168.1.100:8000/v1

# 強制指定載入的模型名稱
VLLM_MODEL_NAME=Qwen/Qwen2-VL-7B-Instruct

# API 金鑰
VLLM_API_KEY=EMPTY
```
