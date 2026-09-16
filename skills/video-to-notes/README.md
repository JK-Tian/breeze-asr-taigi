# Video to Notes (視訊會議轉會議記錄工具)

## 1. 簡介
`video-to-notes` 是一個專門將視訊會議影音檔轉換為結構化會議記錄的自動化技能。
本工具結合了：
- **視覺輔助理解**：透過檢視會議影片畫面與簡報截圖，吸收 PPT 投影片、白板圖表與與會者姓名標籤，深入理解會議上下文。
- **ASR 逐字稿語意校對**：將語音辨識之逐字稿重新 Review，依據會議主題語意修正同音錯別字與專業術語。
- **高階結構化提煉**：自動提煉會議核心摘要、關鍵決策列表、待辦行動清單 (Todo)、發言人討論紀要、以及「下次會議追蹤項目 (重點 Highlight)」。
- **全自動雙格式產出**：產出符合 Obsidian PKM 規格之 Markdown (`_notes.md`) 以及專業排版之商務 Word 文件 (`.docx`)。最終產出嚴格**不包含任何會議畫面截圖**，維持純淨商業風格。

## 2. 系統需求
- 作業系統：Windows 11
- 套件管理：[uv](https://github.com/astral-sh/uv) (>= 0.1.0)
- Python 版本：>= 3.10
- 系統依賴：`ffmpeg` (置於系統 PATH)

## 3. 架構與設計原則 (S.O.L.I.D. & Clean Architecture)
本工具的核心腳本嚴格遵循物件導向與簡潔架構原則：
- **單一職責原則 (SRP)**：
  - `MeetingNotesParser`：專責解析會議 Markdown 文本、YAML frontmatter、發言人標籤、決策項目、Todo 表格與下次會議追蹤章節。
  - `NotesStyleManager`：專責統籌商務會議樣式、中文字體 (`Noto Sans TC`)、英文字體 (`Calibri`)、階層字級與深藍/雅灰專業表格配色。
  - `NotesDocxBuilder`：專責組裝 Word 元素，輸出純淨無圖片之正式會議記錄。
- **零截圖防呆保證 (Zero-screenshot Output Guarantee)**：
  - 產出腳本嚴格排除任何圖片插入邏輯，保證 Word 與 Markdown 文件 100% 保持文字排版。

## 4. 腳本使用方式

### 4.1 自動生成 Word 會議記錄
使用 `uv run` 調用 Word 生成腳本：
```bash
uv run scripts/generate_notes_docx.py \
  --input path/to/[會議名稱]_notes.md \
  --output path/to/[會議名稱].docx
```

**參數說明**：
- `--input` (`-i`)：**[必填]** 結構化會議 Markdown 檔案路徑。
- `--output` (`-o`)：**[選填]** 輸出的 Word (.docx) 檔案路徑。若未指定，預設於同路徑產出同名之 `.docx`。

## 5. 文件撰寫協定遵循
本技能全面遵從 SOP Generation Protocol：
1. **parameters (YAML 屬性)**：標準 Obsidian PKM 欄位 (`title`, `description`, `date`, `aliases`, `status`, `tags`, `Topics`)，影片來源統一置於文末 `# 參考資料`。
2. **Steps (核心步驟流程)**：使用 RFC2119 關鍵字（**MUST / MUST NOT / SHOULD / MAY**）明確執行邊界。
3. **Error Handling (異常與邊界處理)**：包含音訊嘈雜、簡報模糊、發言爭議與檔案鎖定等 Edge Cases 處置策略。
