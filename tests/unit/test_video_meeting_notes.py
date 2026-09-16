"""單元測試：video-to-notes 規格 Markdown 格式化與影音檔名處理 (TDD)。

驗證無論音訊或視訊會議，產出均統一為符合 Obsidian PKM YAML Frontmatter 格式之 .md 檔案，
且文末自動標記 # 參考資料，檔案來源不進入 Frontmatter。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

import pytest

from taigi_asr.llm import LLMClient
from taigi_asr.minutes import (
    format_obsidian_meeting_notes,
    save_meeting_outputs,
    validate_meeting_minutes_sections,
)


SAMPLE_RAW_SUMMARY = """# 技術架構討論會

## 1. 會議基本資訊
- 會議時間: 2026-09-16 14:00 - 15:00
- 會議地點: 線上會議 (Teams)
- 會議主席: 張主管
- 會議記錄: 李秘書
- 出席人員: 王工程師、陳工程師、林設計師
- 請假人員: 無

## 2. 會議核心摘要 (Highlights)
- 完成 Breeze ASR 與 LLM 8002 錯別字校正架構整合作業。
- 確立不論語音或影片均統一以 video-to-notes 之 .md 格式產出。
- 前端完善影音防丟失上傳保全機制。

## 3. 關鍵決策事項 (Decisions Made)
| 編號 | 決策主題 | 決策內容與共識 | 提案人 / 負責人 | 生效日期 |
|---|---|---|---|---|
| D-01 | 格式統一 | 會議記錄統一產出 Obsidian PKM .md，不轉 Word | 張主管 | 2026-09-16 |

## 4. 待辦事項清單 (Action Items / Todo List)
| 待辦任務項目 (Action Item) | 負責人 | 截止期限 | 當前狀態 |
|---|---|---|---|
| 完成前端視訊上傳支援與圖示切換 | 王工程師 | 2026-09-17 | 進行中 |

## 5. 各議題討論紀要 (Agenda & Discussions)
### 議題一: 影音格式相容性
- 【王工程師】 確認 ffmpeg 可自動處理 MP4, MKV, MOV 等音訊分離。
- 【陳工程師】 建議標準化為 16kHz WAV 與 128k MP3。

## 6. 下次會議追蹤項目 (Next Meeting Follow-ups)
| 追蹤項目 (Focus Item) | 預計報告人 / 負責人 | 期望產出 / 查核標準 (Deliverable) |
|---|---|---|
| 影音長檔效能壓力測試 | 王工程師 | 效能評估報告 |
"""


def test_format_obsidian_meeting_notes_with_video_file():
    """測試傳入視訊檔案 (.mp4) 時正確注入指定之新版 Obsidian PKM YAML frontmatter 與文末參考資料。"""
    fixed_dt = datetime(2026, 9, 16, 14, 30)
    result_md = format_obsidian_meeting_notes(
        summary=SAMPLE_RAW_SUMMARY,
        media_filename="executive_meeting.mp4",
        title="技術架構討論會",
        dt=fixed_dt,
    )

    # 1. 驗證開頭為標準 YAML frontmatter
    expected_frontmatter = (
        "---\n"
        "title : 技術架構討論會\n"
        "description : \n"
        "date : 2026-09-16 14:30\n"
        "aliases : []\n"
        "status : inbox\n"
        "tags : \n"
        "Topics : \n"
        "Type : \n"
        "  - 📝/✨\n"
        "---"
    )
    assert result_md.startswith(expected_frontmatter), f"Frontmatter 不符合預期，實際為:\n{result_md[:200]}"

    # 2. 驗證 frontmatter 內部嚴格禁止包含影片路徑或檔名
    frontmatter_part = result_md.split("---")[1]
    assert "executive_meeting.mp4" not in frontmatter_part

    # 3. 驗證文件最末端包含 # 參考資料 且標記 - [executive_meeting.mp4]
    assert "# 參考資料" in result_md
    assert "- [executive_meeting.mp4]" in result_md
    assert result_md.strip().endswith("- [executive_meeting.mp4]")


def test_format_obsidian_meeting_notes_with_audio_file():
    """測試傳入純音訊檔案 (.mp3) 時亦遵循完全相同之 video-to-notes 規範。"""
    fixed_dt = datetime(2026, 9, 16, 10, 15)
    result_md = format_obsidian_meeting_notes(
        summary=SAMPLE_RAW_SUMMARY,
        media_filename="weekly_standup.mp3",
        title="技術架構討論會",
        dt=fixed_dt,
    )

    # 驗證 frontmatter 中的 status 為 inbox 與 Type
    assert "status : inbox" in result_md
    assert "Type :\n  - 📝/✨" in result_md or "Type : \n  - 📝/✨" in result_md

    # 驗證文末標記音訊檔名
    assert "- [weekly_standup.mp3]" in result_md
    assert result_md.strip().endswith("- [weekly_standup.mp3]")


def test_format_obsidian_meeting_notes_deduplicates_existing_references():
    """測試若輸入摘要原本已包含參考資料章節，不會重複堆疊多個章節。"""
    raw_with_ref = SAMPLE_RAW_SUMMARY + "\n\n# 參考資料\n- [old_file.wav]\n"
    result_md = format_obsidian_meeting_notes(
        summary=raw_with_ref,
        media_filename="new_meeting.mkv",
        title="技術架構討論會",
    )

    # 確保只有一個 # 參考資料
    ref_count = len(re.findall(r"^#+\s*參考資料", result_md, re.MULTILINE))
    assert ref_count == 1
    assert "- [new_meeting.mkv]" in result_md


def test_save_meeting_outputs_generates_obsidian_notes(tmp_path: Path):
    """測試 save_meeting_outputs 自動套用 video-to-notes 規格並產生檔案。"""
    t_file, s_file = save_meeting_outputs(
        transcript="[00:01] 主席: 開會。",
        summary=SAMPLE_RAW_SUMMARY,
        output_dir=tmp_path,
        meeting_name="高階決策會議",
        media_filename="board_meeting.mov",
    )

    assert t_file.exists()
    assert s_file.exists()

    content = s_file.read_text(encoding="utf-8")
    assert "status : inbox" in content
    assert "  - 📝/✨" in content
    assert "- [board_meeting.mov]" in content


def test_llm_client_prompt_aligns_with_video_to_notes():
    """測試 LLMClient 的會議記錄系統提示詞與用戶提示詞皆要求 video-to-notes 六大核心結構。"""
    client = LLMClient()
    prompt = client._build_minutes_prompt("測試逐字稿內容")

    # 檢查提示詞中指引之六大區塊關鍵字
    assert "會議基本資訊" in prompt
    assert "會議核心摘要" in prompt
    assert "關鍵決策事項" in prompt
    assert "待辦事項清單" in prompt
    assert "各議題討論紀要" in prompt
    assert "下次會議追蹤項目" in prompt
