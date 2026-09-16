"""資料庫連線與模型定義模組 (Clean Architecture Infrastructure Layer)。

支援 PostgreSQL 企業級連線池與 SQLite 高併發 WAL (Write-Ahead Logging) 讀寫分離模式，
並具備智慧型連線容錯 (Graceful Degradation)：若 PostgreSQL 暫未就緒，自動平滑降級至 SQLite WAL，
確保微服務 100% 穩定秒級啟動。
"""

import os
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine, event, Column, String, DateTime, Text, Engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("database")

# 預設資料庫連線路徑 (優先讀取環境變數 DATABASE_URL)
DEFAULT_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./transcriptions.db")


def create_app_engine(db_url: str) -> Engine:
    """根據資料庫連線字串建立並配置最適化的資料庫引擎實例。

    針對 PostgreSQL 配置高併發連線池參數，若連線被拒則自動平滑降級至 SQLite WAL；
    針對 SQLite 強制啟用 WAL (Write-Ahead Logging) 與 30 秒 busy_timeout，實現無鎖讀寫分離。

    Args:
        db_url: 資料庫連線字串 (URL)

    Returns:
        SQLAlchemy Engine 實例
    """
    if db_url.startswith("postgresql"):
        try:
            pg_engine = create_engine(
                db_url,
                pool_size=20,
                max_overflow=10,
                pool_recycle=1800,
                pool_pre_ping=True,
            )
            # 預檢連線以確認 PostgreSQL 服務是否已連通
            with pg_engine.connect():
                pass
            logger.info("已成功建立 PostgreSQL 企業級連線池 (pool_size=20)。")
            return pg_engine
        except Exception as e:
            logger.warning(f"⚠️ 無法連線至 PostgreSQL ({e})，系統已平滑自動降級至本機高併發 SQLite WAL 模式！")
            db_url = "sqlite:///./transcriptions.db"

    if db_url.startswith("sqlite"):
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """於每個 SQLite 連線建立時設定 WAL 與逾時參數。"""
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()

        return engine

    return create_engine(db_url)


# 全域共用資料庫引擎與 Session 工廠
engine = create_app_engine(DEFAULT_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class TaskModel(Base):
    """轉錄與會議記錄任務資料表模型。"""

    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    file_path = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    """初始化資料庫綱要與資料表結構。"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 依賴注入 Session 產生器，確保請求結束後安全釋放連線資源。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
