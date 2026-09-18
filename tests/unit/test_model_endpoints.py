"""AI 模型端點獨立解耦單元測試模組。

驗證：
1. 語意錯別字校正客戶端 (Correction) 專屬端點 (預設 8001)
2. 結構化會議記錄生成客戶端 (Minutes) 專屬端點 (預設 8002)
3. 多模態視覺客戶端 (Vision / VLM) 專屬端點 (預設 8000)
4. 驗證當兩者同時設定時，Correction 端點絕不會遮蔽 Minutes 端點 (Bug 根除驗證)
"""

import os
import sys
from unittest.mock import patch
import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from src.usecases.transcription import (
    get_correction_llm_client,
    get_minutes_llm_client,
    get_vlm_client,
)


class TestModelEndpointsDecoupling:
    """測試三模型端點獨立解析與互不干擾特性。"""

    def test_correction_client_defaults_to_8001(self, monkeypatch):
        """驗證校正模型預設連線至 8001。"""
        monkeypatch.delenv("LLM_CORRECTION_URL", raising=False)
        monkeypatch.delenv("LLM_URL", raising=False)

        client = get_correction_llm_client()
        assert "8001" in client.base_url

    def test_minutes_client_defaults_to_8002(self, monkeypatch):
        """驗證會議記錄模型預設連線至 8002。"""
        monkeypatch.delenv("LLM_CORRECTION_URL", raising=False)
        monkeypatch.delenv("LLM_URL", raising=False)
        monkeypatch.delenv("LLM_MINUTES_URL", raising=False)

        client = get_minutes_llm_client()
        assert "8002" in client.base_url

    def test_vlm_client_defaults_to_8000(self, monkeypatch):
        """驗證視覺模型預設連線至 8000。"""
        monkeypatch.delenv("VLM_URL", raising=False)

        client = get_vlm_client()
        assert "8000" in client.base_url

    def test_correction_does_not_mask_minutes_url(self, monkeypatch):
        """核心防禦測試：當同時指定 LLM_CORRECTION_URL 與 LLM_URL 時，Minutes 端點絕不可被 Correction 覆蓋。"""
        monkeypatch.setenv("LLM_CORRECTION_URL", "http://custom-correction-host:8001/v1")
        monkeypatch.setenv("LLM_URL", "http://custom-minutes-host:8002/v1")

        corr_client = get_correction_llm_client()
        min_client = get_minutes_llm_client()

        assert corr_client.base_url == "http://custom-correction-host:8001/v1"
        assert min_client.base_url == "http://custom-minutes-host:8002/v1"
        assert min_client.base_url != corr_client.base_url

    def test_fallback_behavior_when_only_llm_url_is_set(self, monkeypatch):
        """當使用者只配置了通用 LLM_URL 時，校正端點平滑回退使用 LLM_URL。"""
        monkeypatch.delenv("LLM_CORRECTION_URL", raising=False)
        monkeypatch.setenv("LLM_URL", "http://single-llm-host:8002/v1")

        corr_client = get_correction_llm_client()
        min_client = get_minutes_llm_client()

        assert min_client.base_url == "http://single-llm-host:8002/v1"
        assert corr_client.base_url == "http://single-llm-host:8002/v1"
