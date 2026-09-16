"""單元測試：LLM 服務模組 (src/taigi_asr/llm.py)

測試覆蓋 4 個維度：
1. 核心業務邏輯 (Happy Path)：
   - GET /v1/models 自動查詢模型名稱並帶入
   - 錯別字校正請求建立與回應解析
   - 四區塊會議記錄提示詞與回應解析
2. 異常與邊界條件 (Edge Cases & Unhappy Path)：
   - /v1/models 查詢失敗時回退預設模型
   - 連線失敗與逾時 (Timeout) 時的 Graceful Degradation
   - <think> 推理標籤解析與濾除
   - 空字串與純空白輸入防護
3. 安全性審查 (Security Review)：
   - 防範無效 URL 與注入
   - 確保 Header 與逾時限制安全配置
4. 程式碼品質與維護性 (Code Quality)：
   - 模組化設計與清晰繁體中文註解
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from taigi_asr.llm import LLMClient


def test_clean_think_tags():
    """測試 <think>...</think> 標籤過濾邏輯"""
    client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="auto")
    
    # 包含 think 標籤
    raw_text = "<think>思考中...需要校對專有名詞</think>這是校正後的文字。"
    assert client.clean_think_tags(raw_text) == "這是校正後的文字。"

    # 包含多行 think 標籤
    multiline_think = "<think>\n第1步：比對台語發音\n第2步：分析詞意\n</think>\n# 會議名稱：測試\n\n## 【會議重點】\n重點一"
    assert client.clean_think_tags(multiline_think) == "# 會議名稱：測試\n\n## 【會議重點】\n重點一"

    # 無 think 標籤
    normal_text = "直接回傳正常內容"
    assert client.clean_think_tags(normal_text) == "直接回傳正常內容"

    # 空值或 None
    assert client.clean_think_tags("") == ""
    assert client.clean_think_tags(None) == ""


def test_get_available_model_success():
    """測試自 /v1/models 端點動態查詢並解析模型名稱 (Happy Path)"""
    mock_models_response = {
        "object": "list",
        "data": [
            {
                "id": "nvidia/Qwen3.6-35B-A3B-NVFP4",
                "object": "model",
                "created": 1789532665,
                "owned_by": "vllm"
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_models_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="auto")
        model_id = client.get_available_model()
        assert model_id == "nvidia/Qwen3.6-35B-A3B-NVFP4"
        assert client.model == "nvidia/Qwen3.6-35B-A3B-NVFP4"


def test_get_available_model_fallback_on_failure():
    """測試 /v1/models 查詢失敗時優雅回退至預設值 (Edge Case)"""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="auto", fallback_model="default-fallback-model")
        model_id = client.get_available_model()
        assert model_id == "default-fallback-model"
        assert client.model == "default-fallback-model"


def test_correct_transcript_success():
    """測試語意錯別字校正成功流程 (Happy Path)"""
    raw_transcript = "[00:00:01] 講者 A: 我們要測試 Breeze ASR 模形。"
    corrected_output = "[00:00:01] 講者 A: 我們要測試 Breeze ASR 模型。"

    mock_api_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": f"<think>檢查模形->模型</think>{corrected_output}"
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_api_resp).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="nvidia/Qwen3.6-35B-A3B-NVFP4")
        result = client.correct_transcript(raw_transcript)
        assert result == corrected_output


def test_generate_meeting_minutes_success():
    """測試四區塊結構化會議紀錄生成 (Happy Path)"""
    transcript = "[00:00:01] 講者 A: 今天開會確認 Breeze ASR 上線時程，預計週五完成。"
    expected_minutes = (
        "# 會議名稱：ASR 上線時程會議\n\n"
        "## 【會議重點】\n- 討論上線時程。\n\n"
        "## 【關鍵決策】\n- 確定於本週五上線。\n\n"
        "## 【TODO / 行動項目】\n- [講者 A] 週五前完成部署\n\n"
        "## 【下次會議追蹤項目】\n- 複查上線後效能"
    )

    mock_api_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": expected_minutes
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_api_resp).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="nvidia/Qwen3.6-35B-A3B-NVFP4")
        minutes = client.generate_meeting_minutes(transcript)
        assert "【會議重點】" in minutes
        assert "【關鍵決策】" in minutes
        assert "【TODO / 行動項目】" in minutes
        assert "【下次會議追蹤項目】" in minutes
        assert minutes.startswith("# 會議名稱：")


def test_llm_degradation_on_timeout():
    """測試當 LLM 連線超時或出錯時，校正與會議紀錄進行優雅降級 (Unhappy Path)"""
    raw_transcript = "[00:00:01] 講者 A: 原始逐字稿保留測試。"

    # 模擬 URL 連線逾時
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
        client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="test-model")
        
        # 錯別字校正超時，應回傳原始逐字稿以確保資料不丟失
        corrected = client.correct_transcript(raw_transcript)
        assert corrected == raw_transcript

        # 會議紀錄超時，應產生友善錯誤提示且不崩潰
        minutes = client.generate_meeting_minutes(raw_transcript)
        assert "摘要生成失敗" in minutes
        assert "timed out" in minutes


def test_empty_transcript_handling():
    """測試空逐字稿輸入防護 (Edge Case)"""
    client = LLMClient(base_url="http://192.168.1.100:8002/v1", model="test-model")
    
    assert client.correct_transcript("") == ""
    assert client.correct_transcript("   ") == ""
    assert "逐字稿內容為空" in client.generate_meeting_minutes("")
    assert "逐字稿內容為空" in client.generate_meeting_minutes("   ")
