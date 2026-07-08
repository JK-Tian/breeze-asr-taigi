import os
from celery import Celery
from dotenv import load_dotenv

# 修正 .env 的相對路徑
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))
load_dotenv(env_path)

# 預設連線至本機的 Redis
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "transcription_worker",
    broker=redis_url,
    backend=redis_url,
    include=["src.usecases.transcription"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    # 這是非常關鍵的設定：限制 worker 一次只能處理一個任務，避免 GPU/CPU 爆炸 (CUDA OOM)
    worker_concurrency=1,
)
