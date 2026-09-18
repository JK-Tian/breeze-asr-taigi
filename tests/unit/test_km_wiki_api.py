"""KM Wiki Web API 路由與 Use Case 單元測試模組。

驗證：
1. GET /api/v1/km-wiki/status 回傳正確狀態與權限資訊
2. POST /api/v1/transcriptions/{task_id}/sync-km-wiki 任務不存在時回傳 404
3. POST /api/v1/transcriptions/{task_id}/sync-km-wiki 任務無內容時回傳 400
4. POST /api/v1/transcriptions/{task_id}/sync-km-wiki 正常手動同步成功 (Happy Path)
"""

import os
import sys
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from src.main import app
from src.infrastructure.database import Base, SessionLocal, TaskModel, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)


class TestKMWikiAPI:
    """測試 KM Wiki RESTful API。"""

    def test_get_km_wiki_status(self):
        """驗證查詢 KM Wiki 狀態端點。"""
        response = client.get("/api/v1/km-wiki/status")
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "raw_dir" in data
        assert "is_writable" in data
        assert "Minutes" in data["raw_dir"]

    def test_sync_km_wiki_not_found(self):
        """驗證任務不存在時回傳 404。"""
        response = client.post("/api/v1/transcriptions/non-existent-task-id/sync-km-wiki")
        assert response.status_code == 404
        assert response.json()["detail"] == "Task not found"

    def test_sync_km_wiki_no_content(self):
        """驗證任務尚未具備逐字稿或會議記錄時回傳 400。"""
        task_id = "test-km-no-content-id"
        db = SessionLocal()
        db.query(TaskModel).filter(TaskModel.id == task_id).delete()
        db.commit()

        task = TaskModel(
            id=task_id,
            file_path="sample.mp3",
            status="completed",
            transcript=None,
            summary=None,
        )
        db.add(task)
        db.commit()
        db.close()

        try:
            response = client.post(f"/api/v1/transcriptions/{task_id}/sync-km-wiki")
            assert response.status_code == 400
            assert "無法同步至 KM Wiki" in response.json()["detail"]
        finally:
            db = SessionLocal()
            db.query(TaskModel).filter(TaskModel.id == task_id).delete()
            db.commit()
            db.close()

    def test_sync_km_wiki_success(self, tmp_path):
        """驗證手動觸發 KM Wiki 同步成功 (Happy Path)。"""
        task_id = "test-km-valid-sync-id"
        db = SessionLocal()
        db.query(TaskModel).filter(TaskModel.id == task_id).delete()
        db.commit()

        task = TaskModel(
            id=task_id,
            file_path="valid_meeting.mp3",
            status="completed",
            transcript="[00:00:00] 主持人: 測試內容",
            summary="# 會議名稱：KM Wiki 整合測試\n## 【會議重點】\n- 成功測試",
            km_wiki_synced=False,
        )
        db.add(task)
        db.commit()
        db.close()

        # Mock KMWikiService 目錄為 tmp_path
        custom_raw_dir = tmp_path / "Minutes" / "raw"
        with patch.dict(os.environ, {"KM_WIKI_RAW_DIR": str(custom_raw_dir), "KM_WIKI_ENABLED": "true"}):
            try:
                response = client.post(f"/api/v1/transcriptions/{task_id}/sync-km-wiki")
                assert response.status_code == 200
                data = response.json()
                assert data["task_id"] == task_id
                assert data["km_wiki_synced"] is True
                assert "成功同步至 KM Wiki" in data["message"]

                # 驗證資料庫欄位同步更新
                db = SessionLocal()
                updated_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
                assert updated_task.km_wiki_synced is True
                db.close()

                # 驗證查詢 task status 也包含 km_wiki_synced
                status_res = client.get(f"/api/v1/transcriptions/{task_id}")
                assert status_res.status_code == 200
                assert status_res.json()["km_wiki_synced"] is True
            finally:
                db = SessionLocal()
                db.query(TaskModel).filter(TaskModel.id == task_id).delete()
                db.commit()
                db.close()
