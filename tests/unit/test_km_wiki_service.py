"""KM Wiki Minutes 知識庫 raw 檔區同步服務單元測試模組。

驗證：
1. 停用開關時平滑跳過同步 (Feature Toggle)
2. 正常同步：自動建立 YYYY-MM-DD 子目錄並安全複製逐字稿與會議記錄
3. 檔名字元消毒與防路徑遍歷攻擊 (Security)
4. 目標磁碟離線或無權限時之平滑降級 (Graceful Degradation)
5. 服務狀態檢查功能 (Status Inspection)
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import pytest

from taigi_asr.km_wiki import KMWikiService


class TestKMWikiService:
    """測試 KM Wiki Minutes 知識庫 raw 檔區同步服務。"""

    def test_sync_skipped_when_disabled(self, tmp_path):
        """驗證當 enabled=False 時平滑跳過，不寫入任何檔案。"""
        service = KMWikiService(enabled=False, raw_dir=str(tmp_path / "Minutes" / "raw"))
        t_file = tmp_path / "test_transcript.md"
        s_file = tmp_path / "test_summary.md"
        t_file.write_text("逐字稿內容", encoding="utf-8")
        s_file.write_text("會議記錄內容", encoding="utf-8")

        result = service.sync_files(transcript_path=t_file, summary_path=s_file)

        assert result["synced"] is False
        assert result["reason"] == "disabled"
        assert not (tmp_path / "Minutes").exists()

    def test_sync_success_with_date_subfolder(self, tmp_path):
        """驗證正常同步至 Minutes/raw/YYYY-MM-DD 目錄。"""
        raw_dir = tmp_path / "Minutes" / "raw"
        service = KMWikiService(enabled=True, raw_dir=str(raw_dir), date_subfolder=True)

        t_file = tmp_path / "Q3檢討會_逐字稿.md"
        s_file = tmp_path / "Q3檢討會_會議紀錄與摘要.md"
        t_file.write_text("# Q3 逐字稿\n[00:00:01] 講者: 營收達標。", encoding="utf-8")
        s_file.write_text("# 會議名稱：Q3檢討會\n## 【會議重點】\n- 達標。", encoding="utf-8")

        fixed_dt = datetime(2026, 9, 18, 14, 30)
        result = service.sync_files(transcript_path=t_file, summary_path=s_file, dt=fixed_dt)

        assert result["synced"] is True
        target_dir = raw_dir / "2026-09-18"
        assert target_dir.exists()

        synced_t = target_dir / "Q3檢討會_逐字稿.md"
        synced_s = target_dir / "Q3檢討會_會議紀錄與摘要.md"

        assert synced_t.exists()
        assert synced_s.exists()
        assert "營收達標" in synced_t.read_text(encoding="utf-8")
        assert "Q3檢討會" in synced_s.read_text(encoding="utf-8")

    def test_sync_sanitizes_filename_and_prevents_traversal(self, tmp_path):
        """驗證安全防禦：路徑遍歷字元被安全濾除，嚴格封裝在 target_dir 內。"""
        raw_dir = tmp_path / "Minutes" / "raw"
        service = KMWikiService(enabled=True, raw_dir=str(raw_dir), date_subfolder=False)

        bad_t_file = tmp_path / "normal_t.md"
        bad_s_file = tmp_path / "normal_s.md"
        bad_t_file.write_text("t", encoding="utf-8")
        bad_s_file.write_text("s", encoding="utf-8")

        # 模擬呼叫時指定含遍歷路徑的檔名
        result = service.sync_files(
            transcript_path=bad_t_file,
            summary_path=bad_s_file,
            override_title="../../etc/passwd:危險*會議",
        )

        assert result["synced"] is True
        for path_str in result["synced_files"]:
            p = Path(path_str)
            assert ".." not in p.name
            assert ":" not in p.name
            assert "*" not in p.name
            # 確保檔案位於 raw_dir 之內
            assert raw_dir in p.resolve().parents

    def test_graceful_degradation_on_io_error(self, tmp_path):
        """驗證當目標磁碟離線或無權限拋出例外時，優雅降級不崩潰。"""
        service = KMWikiService(enabled=True, raw_dir=str(tmp_path / "Minutes" / "raw"))
        t_file = tmp_path / "test_t.md"
        s_file = tmp_path / "test_s.md"
        t_file.write_text("t", encoding="utf-8")
        s_file.write_text("s", encoding="utf-8")

        # 模擬 copy 時遭遇 PermissionError 或網路中斷 OSError
        with patch("shutil.copy2", side_effect=PermissionError("存取被拒 (網路磁碟離線)")):
            result = service.sync_files(transcript_path=t_file, summary_path=s_file)

            assert result["synced"] is False
            assert "存取被拒" in result["error"]

    def test_check_status(self, tmp_path):
        """驗證 KM Wiki 狀態檢查回傳正確資訊。"""
        raw_dir = tmp_path / "Minutes" / "raw"
        service = KMWikiService(enabled=True, raw_dir=str(raw_dir), date_subfolder=True)

        status = service.check_status()
        assert status["enabled"] is True
        assert status["raw_dir"] == str(raw_dir)
        assert status["date_subfolder"] is True
        assert status["is_writable"] is True
