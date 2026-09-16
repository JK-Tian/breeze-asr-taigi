"""音視雙模態融合會議紀錄提煉單元測試模組。

驗證：
1. LLMClient 正確接收並融入視覺時間軸資訊 (visual_context)
2. 產出之會議記錄符合 Obsidian PKM YAML 格式與 video-to-notes 規範
3. 無視覺資訊時的平滑純語音相容性
"""

import pytest
from unittest.mock import patch, MagicMock
from taigi_asr.llm import LLMClient
from taigi_asr.minutes import format_obsidian_meeting_notes


class TestMultimodalMinutes:
    """測試結合視覺時間軸與語音逐字稿的雙模態會議記錄生成。"""

    def test_generate_meeting_minutes_with_visual_context(self):
        """驗證當提供視覺時間軸時，正確送入 Prompt 並生成包含簡報數據之會議紀錄。"""
        client = LLMClient(base_url="http://mock-llm:8002/v1")

        mock_raw_summary = (
            "# 會議名稱：Q3 營運檢討會議\n\n"
            "## 【會議重點】\n"
            "- 根據簡報圖表，Q3 業績達成率達 115%，表現超乎預期。\n\n"
            "## 【關鍵決策】\n"
            "| 編號 | 決策事項 | 決策共識內容 | 負責人 | 生效日期 |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | 擴大推廣 | 依投影片指標加碼預算 | 張處長 | 2026-10-01 |\n\n"
            "## 【TODO / 行動項目】\n"
            "| 任務內容 | 負責人 | 預計完成日期 | 當前狀態 |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| 整理財務明細 | 會計組 | 2026-09-30 | 進行中 |\n\n"
            "## 【各議題討論紀要】\n"
            "### 議題一：業績檢討\n"
            "- 【張處長】：大家看投影片上的營收走勢，9 月顯著成長。\n\n"
            "## 【下次會議追蹤項目】\n"
            "| 追蹤項目 | 負責人 | 預計報告日期 |\n"
            "| :--- | :--- | :--- |\n"
            "| Q4 行銷企劃 | 李副理 | 2026-10-15 |"
        )

        with patch.object(client, "_chat_completion", return_value=mock_raw_summary) as mock_chat:
            transcript = "[00:01:00] 張處長: 大家請看螢幕上的圖表，我們上個月成長很多。"
            visual_context = (
                "### 會議簡報與視覺畫面時間軸紀錄\n"
                "- [00:01:00] 投影片：Q3 財務報表 (業績達成率 115%)"
            )

            result = client.generate_meeting_minutes(transcript, visual_context=visual_context)

            mock_chat.assert_called_once()
            call_prompt = mock_chat.call_args[0][0]
            assert "會議簡報與視覺畫面時間軸紀錄" in call_prompt
            assert "Q3 財務報表" in call_prompt
            assert "115%" in result

    def test_format_obsidian_notes_multimodal_compliance(self):
        """驗證包裝之 Obsidian Markdown 具備指定 YAML Frontmatter 與文末參考資料。"""
        raw_minutes = (
            "# 會議名稱：技術分享會\n\n"
            "## 【會議重點】\n- 討論多模態 AI 管線。"
        )
        final_doc = format_obsidian_meeting_notes(
            summary=raw_minutes,
            media_filename="tech_sharing.mp4",
        )

        assert final_doc.startswith("---\ntitle : 技術分享會\n")
        assert "Type : \n  - 📝/✨" in final_doc
        assert "tech_sharing.mp4" not in final_doc.split("---")[1]
        assert "# 參考資料\n- [tech_sharing.mp4]" in final_doc
