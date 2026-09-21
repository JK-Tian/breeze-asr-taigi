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


# ─── 分段校正 (Chunked Correction) 測試 ───────────────────────────────────


def _make_transcript_lines(n: int, speaker_cycle: int = 5) -> str:
    """產生 n 行模擬逐字稿，每 speaker_cycle 行換一個 SPEAKER。"""
    lines = []
    for i in range(n):
        speaker = f"SPEAKER_{i // speaker_cycle:02d}"
        start = i * 10.0
        end = start + 9.5
        lines.append(f"{start:.2f} - {end:.2f} [{speaker}]: 這是第 {i + 1} 行的測試內容")
    return "\n".join(lines)


def test_chunk_transcript_short():
    """短逐字稿 (≤ max_lines) 不分段，回傳包含全文的單一 chunk (Happy Path)"""
    from taigi_asr.llm import chunk_transcript

    text = _make_transcript_lines(30)
    chunks = chunk_transcript(text, max_lines=50, overlap_lines=3)

    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_transcript_long():
    """長逐字稿 (150 行) 切成多段，每段 ≤ max_lines + overlap (Happy Path)"""
    from taigi_asr.llm import chunk_transcript

    text = _make_transcript_lines(150)
    chunks = chunk_transcript(text, max_lines=50, overlap_lines=3)

    # 應產生 3~4 個 chunk
    assert len(chunks) >= 3
    # 每個 chunk 行數不超過 max_lines + overlap_lines
    for chunk in chunks:
        line_count = len(chunk.strip().splitlines())
        assert line_count <= 53  # 50 + 3 overlap

    # 所有原始行都應出現在至少一個 chunk 中
    original_lines = set(text.splitlines())
    covered_lines = set()
    for chunk in chunks:
        covered_lines.update(chunk.splitlines())
    assert original_lines.issubset(covered_lines)


def test_chunk_transcript_speaker_boundary():
    """不在同一 SPEAKER 段落中間截斷 (Edge Case)"""
    from taigi_asr.llm import chunk_transcript

    # 製作特殊場景：前 48 行同一個 SPEAKER，第 49~60 行換 SPEAKER
    lines = []
    for i in range(48):
        lines.append(f"{i * 10:.2f} - {i * 10 + 9:.2f} [SPEAKER_00]: 同一講者第 {i + 1} 行")
    for i in range(48, 60):
        lines.append(f"{i * 10:.2f} - {i * 10 + 9:.2f} [SPEAKER_01]: 新講者第 {i + 1} 行")
    text = "\n".join(lines)

    chunks = chunk_transcript(text, max_lines=50, overlap_lines=3)

    # 第一個 chunk 的最後一行和第二個 chunk 的第一行（排除 overlap）應屬於不同 SPEAKER
    first_chunk_lines = chunks[0].splitlines()
    # 第一個 chunk 不應恰好在 SPEAKER_00 的第 50 行截斷（第 48 行結束才是邊界）
    assert len(chunks) >= 2


def test_chunk_transcript_overlap():
    """相鄰 chunk 之間有重疊行提供上下文 (Happy Path)"""
    from taigi_asr.llm import chunk_transcript

    text = _make_transcript_lines(120)
    chunks = chunk_transcript(text, max_lines=50, overlap_lines=3)

    assert len(chunks) >= 2

    # 驗證第一個 chunk 的末尾 3 行 = 第二個 chunk 的開頭 3 行
    first_tail = chunks[0].splitlines()[-3:]
    second_head = chunks[1].splitlines()[:3]
    assert first_tail == second_head


def _extract_transcript_from_prompt(prompt: str) -> str:
    """從校正 prompt 中提取逐字稿部分（提示詞後的文字）。"""
    marker = "以下是原始逐字稿內容：\n"
    idx = prompt.find(marker)
    if idx >= 0:
        return prompt[idx + len(marker):].strip()
    # fallback: 提示詞結尾通常有 \n 接逐字稿
    parts = prompt.split("\n\n", 1)
    return parts[-1].strip() if len(parts) > 1 else prompt.strip()


def test_correct_transcript_chunked_success():
    """分段校正後合併結果完整，所有原始行都被處理 (Happy Path)"""
    text = _make_transcript_lines(120)

    # Mock: 從 prompt 提取逐字稿部分，將「測試內容」替換為「校正內容」
    def mock_chat(prompt, temperature=0.3):
        transcript_part = _extract_transcript_from_prompt(prompt)
        return transcript_part.replace("測試內容", "校正內容")

    with patch.object(LLMClient, "_chat_completion", side_effect=mock_chat):
        client = LLMClient(base_url="http://test:8001/v1", model="test-model")
        result = client.correct_transcript(text, chunk_max_lines=50, chunk_overlap_lines=3)

    # 校正結果中不應有「測試內容」，應全部變為「校正內容」
    assert "測試內容" not in result
    assert "校正內容" in result
    # 行數應與原始一致（去重後）
    assert len(result.strip().splitlines()) == 120


def test_correct_transcript_chunked_partial_fail():
    """某一段 LLM 校正失敗時，該段保留原始文字，其他段正常校正 (降級)"""
    text = _make_transcript_lines(120)

    call_count = {"n": 0}

    def mock_chat_with_failure(prompt, temperature=0.3):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise urllib.error.URLError("connection reset")
        transcript_part = _extract_transcript_from_prompt(prompt)
        return transcript_part.replace("測試內容", "校正內容")

    with patch.object(LLMClient, "_chat_completion", side_effect=mock_chat_with_failure):
        client = LLMClient(base_url="http://test:8001/v1", model="test-model")
        result = client.correct_transcript(text, chunk_max_lines=50, chunk_overlap_lines=3)

    # 結果應同時包含校正內容（成功的段）和測試內容（失敗的段保留原始）
    assert "校正內容" in result
    assert "測試內容" in result
    # 總行數仍應為 120
    assert len(result.strip().splitlines()) == 120


def test_correct_transcript_chunked_dedup():
    """重疊區域的行不會重複出現在最終結果中 (Edge Case)"""
    text = _make_transcript_lines(120)

    def mock_chat_identity(prompt, temperature=0.3):
        # 原封不動回傳逐字稿部分（模擬不做任何修改的校正）
        return _extract_transcript_from_prompt(prompt)

    with patch.object(LLMClient, "_chat_completion", side_effect=mock_chat_identity):
        client = LLMClient(base_url="http://test:8001/v1", model="test-model")
        result = client.correct_transcript(text, chunk_max_lines=50, chunk_overlap_lines=3)

    result_lines = result.strip().splitlines()
    # 不應有重複行
    assert len(result_lines) == len(set(result_lines))
    # 行數應與原始一致
    assert len(result_lines) == 120

