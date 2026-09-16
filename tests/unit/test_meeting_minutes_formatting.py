"""單元測試：會議紀錄格式化與檔案存檔模組 (src/taigi_asr/minutes.py)

涵蓋 4 個維度：
1. 核心業務邏輯 (Happy Path)：
   - extract_meeting_title 成功自 Markdown 提取會議主題
   - 四大區塊標題結構檢查 (validate_meeting_minutes_sections)
   - save_meeting_outputs 正常輸出 _逐字稿.md 與 _會議紀錄與摘要.md
2. 異常與邊界條件 (Edge Cases & Unhappy Path)：
   - 特殊字元、非法字元及空白檔名
   - 摘要未包含標題時的 fallback 處理
   - 同名檔案自動流水號遞增防覆蓋 (_1, _2...)
3. 安全性審查 (Security Review)：
   - 防範路徑遍歷 (Path Traversal，如 ../ 或 ..\\)
   - 檔名字元消毒 (Sanitize illegal characters)
4. 程式碼品質與維護性 (Code Quality)：
   - 清晰型別註解與繁體中文說明
"""

from __future__ import annotations

from pathlib import Path
import pytest

from taigi_asr.minutes import (
    extract_meeting_title,
    sanitize_filename,
    validate_meeting_minutes_sections,
    save_meeting_outputs,
)


def test_sanitize_filename_security():
    """測試檔名字元消毒與安全性防護 (Security Review & Edge Cases)"""
    # 移除非法字元
    assert sanitize_filename('會議紀錄: 2026/09/16*測試? "重要" <A|B>') == "會議紀錄 20260916測試 重要 AB"
    
    # 防範路徑穿越
    assert ".." not in sanitize_filename("../../etc/passwd")
    
    # 移除前後空白與 Markdown 符號
    assert sanitize_filename("# * 專案進度週會 * #") == "專案進度週會"

    # 空值防護
    assert sanitize_filename("") == ""
    assert sanitize_filename(None) == ""


def test_extract_meeting_title():
    """測試從會議紀錄中提取會議名稱 (Happy Path & Fallback)"""
    summary_with_hash = "# 會議名稱：系統架構技術研討會\n\n## 【會議重點】\n討論模型選型..."
    assert extract_meeting_title(summary_with_hash, fallback="預設會議") == "系統架構技術研討會"

    summary_with_colon = "會議主題：行銷專案對齊會\n\n## 【關鍵決策】\n決策一..."
    assert extract_meeting_title(summary_with_colon, fallback="預設會議") == "行銷專案對齊會"

    # 無明確標題時回退至 fallback
    summary_no_title = "## 【會議重點】\n只有重點沒有標題"
    assert extract_meeting_title(summary_no_title, fallback="2026-09-16_語音轉錄") == "2026-09-16_語音轉錄"


def test_validate_meeting_minutes_sections():
    """測試四區塊結構驗證 (Happy Path & Edge Cases)"""
    good_minutes = (
        "# 會議名稱：測試\n\n"
        "## 【會議重點】\n- 重點 1\n\n"
        "## 【關鍵決策】\n- 決策 1\n\n"
        "## 【TODO / 行動項目】\n- 待辦 1\n\n"
        "## 【下次會議追蹤項目】\n- 追蹤 1\n"
    )
    result = validate_meeting_minutes_sections(good_minutes)
    assert result["is_valid"] is True
    assert result["has_focus"] is True
    assert result["has_decisions"] is True
    assert result["has_todos"] is True
    assert result["has_followups"] is True

    # 缺少 TODO 區塊
    incomplete_minutes = (
        "# 會議名稱：測試\n\n"
        "## 【會議重點】\n- 重點 1\n\n"
        "## 【關鍵決策】\n- 決策 1\n\n"
        "## 【下次會議追蹤項目】\n- 追蹤 1\n"
    )
    res_incomplete = validate_meeting_minutes_sections(incomplete_minutes)
    assert res_incomplete["is_valid"] is False
    assert res_incomplete["has_todos"] is False


def test_save_meeting_outputs(tmp_path: Path):
    """測試產出 Markdown 檔案與流水號防覆蓋機制 (Happy Path & Edge Cases)"""
    transcript = "[00:00:01] 講者 A: 逐字稿測試"
    summary = "# 會議名稱：測試保存檔案\n\n## 【會議重點】\n重點內容"

    # 第一次存檔
    transcript_file, summary_file = save_meeting_outputs(
        transcript=transcript,
        summary=summary,
        output_dir=tmp_path,
        meeting_name="測試保存檔案"
    )

    assert transcript_file.exists()
    assert summary_file.exists()
    assert transcript_file.name == "測試保存檔案_逐字稿.md"
    assert summary_file.name == "測試保存檔案_會議紀錄與摘要.md"
    assert transcript in transcript_file.read_text(encoding="utf-8")
    assert summary in summary_file.read_text(encoding="utf-8")

    # 第二次同名存檔，應自動增加流水號 _1
    t2, s2 = save_meeting_outputs(
        transcript=transcript,
        summary=summary,
        output_dir=tmp_path,
        meeting_name="測試保存檔案"
    )
    assert t2.name == "測試保存檔案_1_逐字稿.md"
    assert s2.name == "測試保存檔案_1_會議紀錄與摘要.md"
