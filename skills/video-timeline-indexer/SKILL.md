---
name: video-timeline-indexer
description: 當使用者提供影片檔案 (.mp4, .mkv, .mov, .avi) 並希望進行影片內容分析、時間軸定位、生成影片章節摘要或詢問影片細節問題時觸發。務必在使用者提及影片理解、長影片分析、影片檢索或傳入影片路徑時使用本 Skill。本 Skill 自動輪詢 4 個預設 Docker vLLM 端點 (192.168.1.100:8000~8002, 192.168.3.9:8000) 並透過 GET /v1/models 自動查詢模型名稱，執行每秒 1 幀採樣 (fps=1)、FFmpeg+dHash 雙重過濾，單幀流式傳送給 Docker vLLM 產出帶時間戳的 Markdown 索引日誌，徹底解決長影片顯存爆掉的問題。
---

# Video Timeline Indexer (影片時間軸雙重過濾與流式索引 Skill)

本 Skill 專門用於解決 **長影片理解 (Long Video Understanding)** 的顯存爆掉與 Context Window 限制問題。

---

## 核心機制與架構 (Architectural Highlights)

1. **Docker vLLM 端點輪詢與自動模型查詢**：
   - 預設自動輪詢探測 `192.168.1.100:8000`, `192.168.1.100:8001`, `192.168.1.100:8002`, `192.168.3.9:8000` 共 4 個候選端點。
   - 透過 `GET /v1/models` 自動取得當前健康端點運行的模型名稱 (Model ID)。
2. **預設採樣頻率**：每 1 秒採樣 1 幀 (`fps=1`)。
3. **雙重過濾機制**：FFmpeg `mpdecimate` 粗篩 + dHash (漢明距離 $\le 4$) 感知哈希精篩 (過濾靜態/手持晃動/噪點)。
4. **單幀流式推論 (Stream Processing)**：一次發送 1 張圖片至 Docker vLLM，即時 Append 寫入 `video_timeline.md` 並刪除圖片暫存檔。

---

## Agent 標準執行 SOP

```bash
uv run python skills/video-timeline-indexer/scripts/index_video.py \
  --video "<path/to/video.mp4>" \
  --output "<path/to/output_timeline.md>" \
  --fps 1.0 \
  --threshold 4
```

*若需手動指定特定的 vLLM API 位址與模型，可附加 `--vllm-url` 或 `--model` 參數。*
