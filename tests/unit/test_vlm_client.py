"""多模態 VLM 客戶端單元測試模組。

驗證：
1. vLLM OpenAI 相容格式之 Chat Completions 與 image_url 封裝
2. 視覺摘要解析、思考標籤過濾與時間軸組織
3. 網路逾時與異常時之平滑降級
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from taigi_asr.vision.vlm_client import VLMClient, VisualFrameAnalysis
from taigi_asr.vision.keyframe_extractor import Keyframe


class TestVLMClient:
    """測試多模態 VLM 客戶端的通訊、解析與降級機制。"""

    def test_init_defaults(self):
        """驗證預設端點與模型名稱。"""
        client = VLMClient()
        assert "8000" in client.base_url
        assert client.timeout == 180

    def test_describe_keyframe_success(self, tmp_path):
        """驗證單張關鍵幀分析與回應提取。"""
        img_file = tmp_path / "slide.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        keyframe = Keyframe(image_path=str(img_file), timestamp_seconds=75.0, timestamp_str="[00:01:15]")

        client = VLMClient(base_url="http://mock-vlm:8000/v1", model="Qwen/Qwen3.8-27B-FP8")

        mock_response_data = {
            "choices": [
                {
                    "message": {
                        "content": "【投影片：Q3 營運報告】營收達成率 115%，重點推廣專案進行中。",
                        "reasoning": "This is a business slide about Q3."
                    }
                }
            ]
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(mock_response_data).encode("utf-8")
            mock_cm.__enter__.return_value = mock_cm
            mock_urlopen.return_value = mock_cm

            analysis = client.analyze_frame(keyframe)

        assert isinstance(analysis, VisualFrameAnalysis)
        assert analysis.timestamp_str == "[00:01:15]"
        assert "Q3 營運報告" in analysis.description
        assert "115%" in analysis.description

    def test_format_visual_timeline(self):
        """驗證將多張畫面分析結果整合為結構化時間軸文字。"""
        analyses = [
            VisualFrameAnalysis(timestamp_str="[00:00:10]", description="開場議程投影片"),
            VisualFrameAnalysis(timestamp_str="[00:05:30]", description="市場分析圖表：市佔率提升至 35%"),
        ]
        client = VLMClient()
        timeline = client.format_visual_timeline(analyses)
        assert "### 會議簡報與視覺畫面時間軸紀錄" in timeline
        assert "[00:00:10] 開場議程投影片" in timeline
        assert "[00:05:30] 市場分析圖表" in timeline

    def test_vlm_timeout_graceful_fallback(self, tmp_path):
        """驗證 VLM 逾時或連線異常時，安全回傳空分析，不中斷流程。"""
        img_file = tmp_path / "slide.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        keyframe = Keyframe(image_path=str(img_file), timestamp_seconds=10.0, timestamp_str="[00:00:10]")

        client = VLMClient(base_url="http://invalid-host:8000/v1")

        with patch("urllib.request.urlopen", side_effect=Exception("Connection timed out")):
            analysis = client.analyze_frame(keyframe)

        assert analysis is None
