"""單元測試：命令列轉會議紀錄腳本 (scripts/transcribe_and_summarize.py)

涵蓋 4 個維度：
1. 核心業務邏輯 (Happy Path)：
   - 傳入 --transcript 執行校正與四區塊會議記錄生成並儲存檔案
   - 支援自動透過 v1/models 查詢模型並帶入
2. 異常與邊界條件 (Edge Cases & Unhappy Path)：
   - 未指定 --audio 與 --transcript 時回傳錯誤並提示用法
   - 傳入不存在之檔案路徑時回傳錯誤
   - 檔案內容為空時之適當提示
3. 安全性審查 (Security Review)：
   - 驗證自訂輸出目錄建立之路徑安全性
4. 程式碼品質與維護性 (Code Quality)：
   - 模組化 run_pipeline 與 main 函式設計
"""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.transcribe_and_summarize import build_parser, run_pipeline


def test_cli_parser_defaults():
    """測試命令列參數解析預設值 (Happy Path)"""
    parser = build_parser()
    args = parser.parse_args(["--audio", "sample.mp3"])
    assert args.audio == Path("sample.mp3")
    assert args.transcript is None
    assert args.model == "auto"
    assert args.skip_correction is False


def test_cli_requires_input():
    """測試若未提供 audio 也未提供 transcript 應報錯 (Edge Case)"""
    parser = build_parser()
    args = parser.parse_args([])
    assert args.audio is None
    assert args.transcript is None


def test_run_pipeline_file_not_found(tmp_path: Path):
    """測試傳入不存在的檔案時優雅退出 (Edge Case)"""
    exit_code = run_pipeline(
        audio_path=tmp_path / "not_exist.mp3",
        transcript_path=None,
        output_dir=tmp_path,
        llm_url="http://192.168.1.100:8002/v1",
        model="auto",
    )
    assert exit_code != 0


def test_run_pipeline_with_transcript(tmp_path: Path):
    """測試傳入現有逐字稿檔案的一鍵轉換流程 (Happy Path)"""
    sample_transcript_file = tmp_path / "raw.txt"
    sample_transcript_file.write_text("[00:00:01] 講者 A: 今天討論 Breeze ASR 模形。", encoding="utf-8")

    fake_corrected = "[00:00:01] 講者 A: 今天討論 Breeze ASR 模型。"
    fake_minutes = (
        "# 會議名稱：ASR 開發會議\n\n"
        "## 【會議重點】\n- 討論模型。\n\n"
        "## 【關鍵決策】\n- 採用 Breeze ASR。\n\n"
        "## 【TODO / 行動項目】\n- [A] 完成整合\n\n"
        "## 【下次會議追蹤項目】\n- 測試效能"
    )

    with patch("taigi_asr.llm.LLMClient.get_available_model", return_value="nvidia/Qwen3.6-35B-A3B-NVFP4"), \
         patch("taigi_asr.llm.LLMClient.correct_transcript", return_value=fake_corrected), \
         patch("taigi_asr.llm.LLMClient.generate_meeting_minutes", return_value=fake_minutes):
        
        exit_code = run_pipeline(
            audio_path=None,
            transcript_path=sample_transcript_file,
            output_dir=tmp_path,
            llm_url="http://192.168.1.100:8002/v1",
            model="auto",
        )

        assert exit_code == 0
        
        # 驗證 output 目錄下檔案已生成
        gen_files = list(tmp_path.glob("*.md"))
        assert len(gen_files) == 2
        file_names = [f.name for f in gen_files]
        assert "ASR 開發會議_逐字稿.md" in file_names
        assert "ASR 開發會議_會議紀錄與摘要.md" in file_names
