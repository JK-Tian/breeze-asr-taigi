import pytest
from fastapi.testclient import TestClient
import sys
import os
from unittest.mock import patch

# 確保可以 import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.main import app

client = TestClient(app)

def test_upload_audio_uses_celery_delay(tmp_path):
    """
    測試上傳音檔時，系統應該呼叫 Celery 的 .delay() 方法，
    而非直接使用 FastAPI 的 BackgroundTasks 執行模型推論。
    """
    test_file = tmp_path / "test.mp3"
    test_file.write_bytes(b"dummy audio content")

    # 我們預期 process_audio_task 已經被裝飾為 Celery Task，因此會有 delay 屬性
    with patch('src.usecases.transcription.process_audio_task.delay') as mock_delay:
        with open(test_file, "rb") as f:
            response = client.post("/api/v1/transcriptions", files={"file": ("test.mp3", f, "audio/mpeg")})
        
        assert response.status_code == 201
        
        # 驗證真的有透過 Celery 佇列發送任務
        mock_delay.assert_called_once()
