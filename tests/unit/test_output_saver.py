import os
import sys
import shutil
import pytest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend")))

from src.usecases.transcription import (
    sanitize_filename,
    extract_meeting_title,
    save_output_md_files,
)


def test_sanitize_filename():
    assert sanitize_filename("簡單會議") == "簡單會議"
    assert sanitize_filename("專案討論/會議:1*2?3") == "專案討論會議123"
    assert sanitize_filename("# **重點會議**") == "重點會議**" or sanitize_filename("# **重點會議**") == "重點會議"
    assert sanitize_filename("") == ""


def test_extract_meeting_title():
    summary1 = "# 會議名稱：台語 ASR 開發進度會\n\n## 一、結論\n好"
    assert extract_meeting_title(summary1, "fallback") == "台語 ASR 開發進度會"

    summary2 = "**會議主題**： 產品規劃討論\n\n內容..."
    assert extract_meeting_title(summary2, "fallback") == "產品規劃討論"

    summary3 = "# 專案架構重構會議\n\n無特別標頭"
    assert extract_meeting_title(summary3, "fallback") == "專案架構重構會議"

    summary4 = "一般無標題摘要內容"
    assert extract_meeting_title(summary4, "預設檔名") == "預設檔名"


def test_save_output_md_files(tmp_path, monkeypatch):
    task_id = "test-task-1234"
    original_file = "interview_recording.wav"
    transcript = "[00:00:01] 講者一: 你好"
    summary = "# 會議名稱：系統測試會議\n\n- 討論項目1"

    # 模擬根目錄到 tmp_path
    base_output_dir = tmp_path / "output"
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = base_output_dir / today_str

    # 呼叫 save_output_md_files
    save_output_md_files(task_id, original_file, transcript, summary)

    # 檢查真正的 output/YYYY-MM-DD 目錄
    real_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../output", today_str))
    transcript_path = os.path.join(real_output_dir, "系統測試會議_逐字稿.md")
    summary_path = os.path.join(real_output_dir, "系統測試會議_會議紀錄與摘要.md")

    assert os.path.exists(transcript_path)
    assert os.path.exists(summary_path)

    with open(transcript_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "系統測試會議 - 會議逐字稿" in content
        assert "你好" in content

    with open(summary_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "系統測試會議 - 會議紀錄與摘要" in content
        assert "討論項目1" in content

    # 清理測試留下的檔案
    if os.path.exists(transcript_path):
        os.remove(transcript_path)
    if os.path.exists(summary_path):
        os.remove(summary_path)
