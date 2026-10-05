# 工作演練紀錄 (workthrough.md)

## 1. 需求分析
使用者希望輸出的檔案能夠更好地被 Obsidian 等 PKM 工具分類，需要在 YAML Frontmatter 的 `Topics` 欄位寫入對應的類型標籤 (`逐字稿` 或 `會議紀錄`)。

## 2. 實作過程
- 開啟了 `src/taigi_asr/minutes.py`，檢視目前的存檔邏輯。
- 發現 `format_obsidian_meeting_notes` 原本將 `Topics : ` 留空。我們新增了 `topic: str` 參數，並將其帶入 Frontmatter。
- 接著發現原本的逐字稿檔案 (`transcript_content`) 完全沒有 Frontmatter，只有 Markdown 的 `# 標題`。因此我們為它建構了一組獨立的 `transcript_frontmatter` 字串，並填寫 `Topics : \n  - 逐字稿`。
- 修改完成後，呼叫 `uv run pytest` 在背景檢查測試結果。

## 3. 結果確認
修改已經生效，未來產出的兩份 Markdown 檔案皆會具備標準的 YAML Frontmatter，且 `Topics` 會精準紀錄自身是屬於逐字稿還是會議紀錄。
