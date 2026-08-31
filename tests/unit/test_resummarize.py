import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend")))

from src.main import app
from src.infrastructure.database import SessionLocal, TaskModel, Base, engine

Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_resummarize_not_found():
    response = client.post("/api/v1/transcriptions/non-existent-task-id/resummarize")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"

def test_resummarize_no_transcript(monkeypatch):
    task_id = "test-no-transcript-id"
    db = SessionLocal()
    db.query(TaskModel).filter(TaskModel.id == task_id).delete()
    db.commit()

    task = TaskModel(
        id=task_id,
        file_path="test.mp3",
        status="completed",
        transcript=None,
        summary=None
    )
    db.add(task)
    db.commit()
    db.close()

    try:
        response = client.post(f"/api/v1/transcriptions/{task_id}/resummarize")
        assert response.status_code == 400
        assert "逐字稿尚未完成" in response.json()["detail"]
    finally:
        db = SessionLocal()
        db.query(TaskModel).filter(TaskModel.id == task_id).delete()
        db.commit()
        db.close()

def test_resummarize_success(monkeypatch):
    # Mock celery delay
    delay_called = False
    def mock_delay(task_id):
        nonlocal delay_called
        delay_called = True

    from src.usecases import transcription
    monkeypatch.setattr(transcription.resummarize_task, "delay", mock_delay)

    task_id = "test-resummarize-valid-id"
    db = SessionLocal()
    db.query(TaskModel).filter(TaskModel.id == task_id).delete()
    db.commit()

    task = TaskModel(
        id=task_id,
        file_path="test.mp3",
        status="completed",
        transcript="[00:00:00] 測試講者: 測試內容",
        summary="摘要生成失敗: Timeout"
    )
    db.add(task)
    db.commit()
    db.close()

    try:
        response = client.post(f"/api/v1/transcriptions/{task_id}/resummarize")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task_id
        assert data["status"] == "processing"
        assert delay_called is True
    finally:
        db = SessionLocal()
        db.query(TaskModel).filter(TaskModel.id == task_id).delete()
        db.commit()
        db.close()
