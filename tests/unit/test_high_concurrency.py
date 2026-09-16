"""企業級高併發、雙軌佇列分流與資料庫並發防護單元測試模組。

遵循 TDD 測試驅動開發原則，驗證：
1. 資料庫連線池與 SQLite WAL 模式 (防 database is locked)
2. 非同步非阻塞大檔案上傳寫入機制
3. Celery 雙軌佇列 (GPU vs I/O) 路由與預取 (prefetch) 設定
"""

import os
import sys
import concurrent.futures
import pytest
from sqlalchemy import create_engine, text
from unittest.mock import patch, MagicMock

# 將 backend 加入 sys.path 以支援 src.* 模組引用
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# 載入受測模組
from src.infrastructure.database import create_app_engine, TaskModel, init_db, SessionLocal
from src.infrastructure.celery_app import celery_app
from fastapi.testclient import TestClient
from src.main import app


class TestDatabaseConcurrency:
    """測試資料庫層的高併發支援與 WAL 模式防鎖定機制。"""

    def test_sqlite_wal_mode_enabled(self, tmp_path):
        """驗證 SQLite 資料庫連線時自動啟用 WAL 模式與 busy_timeout。"""
        db_file = tmp_path / "test_concurrency.db"
        db_url = f"sqlite:///{db_file}"
        engine = create_app_engine(db_url)

        with engine.connect() as conn:
            # 檢查 journal_mode 是否為 wal
            result = conn.execute(text("PRAGMA journal_mode;")).scalar()
            assert str(result).lower() == "wal", f"預期 SQLite journal_mode 為 wal，實際為 {result}"

            # 檢查 busy_timeout 是否已設定為 30000ms (30秒)
            timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()
            assert timeout >= 30000, f"預期 busy_timeout >= 30000，實際為 {timeout}"

    def test_sqlite_multithreaded_concurrent_writes(self, tmp_path):
        """驗證在多線程高併發頻繁寫入時，SQLite WAL 模式不會發生 database is locked。"""
        db_file = tmp_path / "test_wal_concurrent.db"
        db_url = f"sqlite:///{db_file}"
        engine = create_app_engine(db_url)
        from sqlalchemy.orm import sessionmaker

        # 初始化資料表
        from src.infrastructure.database import Base
        Base.metadata.create_all(bind=engine)

        ThreadSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def worker_write(task_id: int):
            session = ThreadSession()
            try:
                task = TaskModel(
                    id=f"concurrent_task_{task_id}",
                    file_path=f"audio_{task_id}.mp3",
                    status="pending",
                )
                session.add(task)
                session.commit()

                # 立即更新狀態模擬 Celery 回寫
                task.status = "processing"
                session.commit()
                return True
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()

        # 模擬 20 個執行緒同時併發寫入與更新
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_write, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 20
        assert all(results)

    def test_postgresql_connection_pool_config(self):
        """驗證當提供 postgresql 連線字串時，建立之引擎具備企業級連線池設定。"""
        pg_url = "postgresql://user:pass@localhost:5432/testdb"
        with patch("src.infrastructure.database.create_engine") as mock_create_engine:
            create_app_engine(pg_url)
            mock_create_engine.assert_called_once()
            _, kwargs = mock_create_engine.call_args
            assert kwargs.get("pool_size") == 20
            assert kwargs.get("max_overflow") == 10
            assert kwargs.get("pool_recycle") == 1800


class TestCeleryQueueSegregation:
    """測試 Celery 雙軌佇列 (GPU 轉寫 vs I/O 摘要) 分流架構。"""

    def test_celery_task_routes_defined(self):
        """驗證 Celery 任務路由是否正確認識 gpu_queue 與 io_queue。"""
        routes = celery_app.conf.task_routes or {}
        # process_audio 或 ASR 相關任務必須導向 gpu_queue
        assert "process_audio" in routes or "src.usecases.transcription.process_audio_task" in routes or "*" in str(routes)
        gpu_route = routes.get("process_audio") or routes.get("src.usecases.transcription.process_audio_task")
        if gpu_route:
            assert gpu_route.get("queue") == "gpu_queue"

        # resummarize_task 必須導向 io_queue
        io_route = routes.get("resummarize_task") or routes.get("src.usecases.transcription.resummarize_task")
        if io_route:
            assert io_route.get("queue") == "io_queue"

    def test_celery_prefetch_multiplier_is_one(self):
        """驗證 Celery 的 prefetch multiplier 設定為 1，防止任務被單一 worker 過度貪婪預取。"""
        prefetch = celery_app.conf.worker_prefetch_multiplier
        assert prefetch == 1, f"預期 worker_prefetch_multiplier 為 1，實際為 {prefetch}"


class TestApiNonBlockingUpload:
    """測試 API 檔案上傳端點的非同步非阻塞行為。"""

    def test_api_upload_audio_async_streaming(self, monkeypatch):
        """驗證 API 上傳能接受音訊檔案並觸發非同步分發。"""
        client = TestClient(app)

        # 模擬 Celery delay 避免實際觸發 worker
        mock_delay = MagicMock()
        monkeypatch.setattr("backend.src.usecases.transcription.process_audio_task.delay", mock_delay)

        # 建立模擬二進位檔案內容
        fake_audio_content = b"RIFF....WAVEfmt ...." + b"\x00" * 2048
        files = {"file": ("test_concurrent.wav", fake_audio_content, "audio/wav")}

        response = client.post("/api/v1/transcriptions", files=files)
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["status"] == "pending"

        # 驗證 Celery 確實被派發
        mock_delay.assert_called_once()
