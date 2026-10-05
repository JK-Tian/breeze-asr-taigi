# 實作計畫 (implementation_plan.md)

## 步驟 1: 擴充 `format_obsidian_meeting_notes` 函數
- **檔案**: `src/taigi_asr/minutes.py`
- **動作**: 在 `format_obsidian_meeting_notes` 加入 `topic` 參數（預設值 `"會議紀錄"`）。並在組裝 `frontmatter` 字串時將該參數插入到 `Topics : ` 底下。

## 步驟 2: 修改 `save_meeting_outputs` 產出邏輯
- **檔案**: `src/taigi_asr/minutes.py`
- **動作**: 
  - 針對生成的「逐字稿」，補上相同結構的 YAML Frontmatter 字串，並在裡面指定 `Topics : \n  - 逐字稿`。
  - 針對生成的「會議紀錄」，在呼叫 `format_obsidian_meeting_notes` 時，傳入 `topic="會議紀錄"`。

## 步驟 3: 驗證功能
- **動作**: 執行 `uv run pytest` 確認單元測試不受影響。
