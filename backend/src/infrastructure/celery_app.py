"""Celery 非同步任務排程與雙軌佇列設定模組。

落實高併發雙軌佇列分流 (Queue Segregation) 架構：
1. gpu_queue: 專門承載語音 ASR 模型推論運算，受限並發 (Concurrency 1-2)，預取 1，防範 CUDA OOM 顯存崩潰。
2. io_queue: 專門承載外部 LLM 錯別字校正、video-to-notes 會議紀錄生成與重新摘要，支援多執行緒高併發呼叫。
"""

import os
from celery import Celery
from dotenv import load_dotenv

# 修正 .env 的相對路徑
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))
load_dotenv(env_path)

# 預設連線至本機的 Redis (優先讀取 REDIS_URL)
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "transcription_worker",
    broker=redis_url,
    backend=redis_url,
    include=["src.usecases.transcription"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    # 關鍵防護：限制 worker 每次只預取 1 個任務，防止單一 worker 貪婪囤積任務造成資源飢餓
    worker_prefetch_multiplier=1,
    # 雙軌佇列分流路由設定 (GPU 轉寫 vs I/O 摘要)
    task_routes={
        "process_audio": {"queue": "gpu_queue"},
        "src.usecases.transcription.process_audio_task": {"queue": "gpu_queue"},
        "resummarize_task": {"queue": "io_queue"},
        "src.usecases.transcription.resummarize_task": {"queue": "io_queue"},
        "process_llm_correction": {"queue": "io_queue"},
    },
    task_default_queue="gpu_queue",
)
