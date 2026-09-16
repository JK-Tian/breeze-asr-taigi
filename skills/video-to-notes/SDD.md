# 系統設計文件 (System Design Document - SDD)
## 專案名稱：Video to Notes (視訊會議轉會議記錄技能)

---

## 1. 系統脈絡與架構選型 (System Context & Technology Stack)

### 1.1 系統脈絡圖 (System Context Diagram)
```mermaid
flowchart LR
    User[與會人員 / 專案主管] -->|提供會議錄影與指令| VideoToNotes["Video to Notes 技能\n(.agent/skills/video-to-notes)"]
    
    subgraph CoreEngine["技能處理核心"]
        VideoToNotes --> ViewTool["AI 視覺畫面預檢 (view_file / 截圖)\n捕捉 PPT / 白板 / 姓名標籤"]
        VideoToNotes --> Transcriber["ASR 語音轉錄\nsrt-transcriber"]
        ViewTool & Transcriber --> Proofreader["語意審核與錯別字校正層\n(Semantic Proofreader)"]
        Proofreader --> Extractor["會議核心資訊提煉引擎\n(重點/決策/Todo/下次追蹤)"]
        Extractor --> DocxGen["全自動 Word 生成腳本\nscripts/generate_notes_docx.py"]
    end
    
    DocxGen --> WordDoc[("正式會議記錄 Word (.docx)\n(無截圖純淨排版)")]
    Extractor --> MarkdownDoc[("Obsidian PKM Markdown\n([會議名稱]_notes.md)")]
    WordDoc & MarkdownDoc --> User
```

### 1.2 技術選型與環境約束
| 構件維度 | 選型方案 | 決策考量與優勢 |
|---|---|---|
| **作業系統環境** | Windows 11 (PowerShell) | 與現行工程開發及主管作業環境完全一致。 |
| **Python 套件管理** | [uv](https://github.com/astral-sh/uv) | 高效虛擬環境隔離與極速套件解析，杜絕環境污染。 |
| **文件渲染核心** | `python-docx` + `pyyaml` | 純本地處理，可高度控制中英文字體、階層字級與表格邊框樣式。 |
| **語音轉錄核心** | `faster-whisper` (本地執行) | 離線轉錄保證會議隱私不外洩，具備時間戳記與語音片段對齊。 |
| **影像視覺處理** | `view_file` (唯讀預檢，不持久化) | 僅作為 AI 理解 PPT 簡報、螢幕展示數據與與會者姓名之認知輔助，不輸出圖片。 |

---

## 2. 關鍵流程圖 (Key Workflow Diagram)

```mermaid
sequenceDiagram
    autonumber
    actor User as 使用者 / Agent
    participant Vid as 原始會議錄影 (.mp4)
    participant Vision as 視覺分析 (PPT/畫面)
    participant ASR as 語音辨識 (srt-transcriber)
    participant Engine as 語意校對與提煉引擎
    participant Cleanup as 暫存清理腳本
    participant Docx as generate_notes_docx.py
    participant Out as 產出檔案

    User->>Vid: 提供會議錄影檔案
    par 雙軌輸入分析
        User->>Vision: 執行畫面預檢，捕捉投影片大綱、白板圖表與與會者標籤
        User->>ASR: 調用語音轉錄腳本產生逐字稿 (.srt)
    end
    Vision-->>Engine: 提供簡報文字與視覺數據上下文
    ASR-->>Engine: 提供原始 ASR 逐字稿片段
    Note over Engine: 逐段 Review 逐字稿：<br/>1. 結合 PPT 上下文修正同音錯別字<br/>2. 識別發言人身分標籤<br/>3. 提煉重點、決策、Todo、下次追蹤
    Engine->>User: 產出結構化 Markdown ([會議名稱]_notes.md)
    User->>Cleanup: 執行 cleanup_temp.py 釋放暫存影音
    User->>Docx: 呼叫腳本解析 Markdown
    Docx->>Docx: 套用商務排版 (Noto Sans TC、深藍決策框、Todo核取方塊)
    Docx->>Out: 輸出 Word 文件 (無圖片嵌入)
```

---

## 3. 資料模型與類別設計 (Data Models & Class Diagram)

### 3.1 核心資料模型 (Data Models)
```mermaid
classDiagram
    class MeetingNotesData {
        +str parameters_yaml
        +str title
        +str meeting_date
        +str location
        +str chairperson
        +str minute_taker
        +List~str~ attendees
        +List~str~ highlights
        +List~DecisionItem~ decisions
        +List~TodoItem~ todos
        +List~AgendaSection~ agenda_discussions
        +List~FollowUpItem~ next_meeting_followups
        +List~str~ references
    }

    class DecisionItem {
        +str id
        +str topic
        +str decision_content
        +str owner_or_proposer
        +str effective_date
    }

    class TodoItem {
        +str task
        +str owner
        +str due_date
        +str status
    }

    class AgendaSection {
        +str topic_title
        +List~SpeakerDiscussion~ discussions
    }

    class SpeakerDiscussion {
        +str speaker_name
        +str statement_summary
    }

    class FollowUpItem {
        +str item_title
        +str responsible_person
        +str expected_outcome
    }

    MeetingNotesData "1" *-- "*" DecisionItem
    MeetingNotesData "1" *-- "*" TodoItem
    MeetingNotesData "1" *-- "*" AgendaSection
    AgendaSection "1" *-- "*" SpeakerDiscussion
    MeetingNotesData "1" *-- "*" FollowUpItem
```

### 3.2 S.O.L.I.D. 腳本類別架構 (Class Diagram)
```mermaid
classDiagram
    class MeetingNotesParser {
        +parse(text: str) MeetingNotesData
        -_parse_yaml(text: str) str
        -_parse_metadata(text: str) dict
        -_parse_highlights(text: str) List~str~
        -_parse_decisions(text: str) List~DecisionItem~
        -_parse_todos(text: str) List~TodoItem~
        -_parse_discussions(text: str) List~AgendaSection~
        -_parse_next_followups(text: str) List~FollowUpItem~
        -_parse_references(text: str) List~str~
    }

    class NotesStyleManager {
        +set_font(run, font_chinese, font_ascii, size_pt, bold, color)
        +add_heading(doc, text, level)
        +format_table(table, header_bg, alt_row_bg)
        +add_callout_box(doc, text, box_type)
    }

    class NotesDocxBuilder {
        -doc: Document
        -data: MeetingNotesData
        +build() Document
        -_build_header()
        -_build_metadata_table()
        -_build_highlights()
        -_build_decisions_table()
        -_build_todos_table()
        -_build_discussions()
        -_build_next_meeting_followups()
        -_build_references()
    }

    MeetingNotesParser ..> MeetingNotesData : 產出
    NotesDocxBuilder o-- MeetingNotesData : 注入
    NotesDocxBuilder ..> NotesStyleManager : 套用樣式
```

---

## 4. 關鍵機制實作說明

### 4.1 ASR 逐字稿語意校對機制 (Semantic Proofreading)
1. **輸入**：原始語音辨識片段（含時間戳記）+ 視覺預檢所記錄之投影片文字與專有名詞。
2. **校對原則**：
   - 針對常見同音異字（如「換模/換膜」、「公差/工差」、「導流板/導流版」）進行自動校對。
   - 專有名詞、機台型號與與會者姓名強制依據簡報文字修正。
   - 保留口白原意，去除贅字（如「那個」、「然後」），提煉為清晰書面語。

### 4.2 發言人 / 與會者辨識與標記原則
- 於議題討論章節中，格式定義為：
  - `【發言人姓名/職稱】發言要點摘要`（如：`【張處長】要求各組於週五前提交初版報告。`）
  - 若無法確認具體姓名，則標記討論角色（如：`【研發代表】`、`【品質代表】`）。

### 4.3 下次會議追蹤項目 (Next Meeting Follow-ups)
- 專門設置於會議記錄文末前之重點 Highlight 表格，欄位包括：
  - **追蹤事項** (Item)
  - **預計報告人/負責人** (Presenter/Owner)
  - **預期產出/查核標準** (Expected Deliverable)

### 4.4 零截圖輸出保證 (Zero-screenshot Assurance)
- `generate_notes_docx.py` 內部完全不包含 `add_picture` 調用，也不依賴任何外部圖片檔案。
- 專注於高階商務純文字與表格排版（中文字型 `Noto Sans TC`，英文字型 `Calibri`，決策與 Todo 強調色）。
