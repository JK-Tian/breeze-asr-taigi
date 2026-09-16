"""後端轉錄與會議紀錄 Use Case 模組。

採用 Clean Architecture 分層設計，整合 Breeze ASR 轉錄、LLM 語意錯別字校正與四區塊會議紀錄整理。
"""

from __future__ import annotations

import configparser
from datetime import datetime, timezone
import json
import logging
import os
import re
import subprocess
import sys
from typing import Optional
import urllib.request
import uuid

from sqlalchemy.orm import Session
from src.domain.entities import TaskResponse
from src.infrastructure.celery_app import celery_app
from src.infrastructure.database import SessionLocal, TaskModel

# 確保可引用 taigi_asr 共用服務層
parent_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))
if parent_src not in sys.path:
    sys.path.insert(0, parent_src)

from taigi_asr.llm import LLMClient
from taigi_asr.minutes import (
    extract_meeting_title,
    sanitize_filename,
    save_meeting_outputs,
)

logger = logging.getLogger("transcription_usecase")


def get_llm_client() -> LLMClient:
    """從設定檔與環境變數取得 LLMClient 實例。"""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
    llm_url = "http://192.168.1.100:8002/v1"
    llm_model = "auto"

    if os.path.exists(config_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding="utf-8")
            if "Correction" in parser and "correction_url" in parser["Correction"]:
                llm_url = parser["Correction"]["correction_url"]
            elif "LLM" in parser and "llm_url" in parser["LLM"]:
                llm_url = parser["LLM"]["llm_url"]

            if "Correction" in parser and "correction_model" in parser["Correction"]:
                llm_model = parser["Correction"]["correction_model"]
            elif "LLM" in parser and "llm_model" in parser["LLM"]:
                llm_model = parser["LLM"]["llm_model"]
        except Exception as e:
            logger.warning(f"讀取 config.ini 失敗: {e}")

    # 環境變數優先
    llm_url = os.environ.get("LLM_CORRECTION_URL", os.environ.get("LLM_URL", os.environ.get("OLLAMA_URL", llm_url)))
    llm_model = os.environ.get("LLM_CORRECTION_MODEL", os.environ.get("LLM_MODEL", os.environ.get("OLLAMA_MODEL", llm_model)))

    return LLMClient(base_url=llm_url, model=llm_model, timeout=1800)


def create_task(db: Session, filename: str) -> TaskResponse:
    """建立新上傳音訊的轉錄任務記錄。"""
    task_id = str(uuid.uuid4())
    db_task = TaskModel(
        id=task_id,
        file_path=filename,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return TaskResponse(id=task_id, status="pending", message="Audio uploaded successfully, processing started.")


@celery_app.task(name="process_audio")
def process_audio_task(task_id: str, file_path: str):
    """Celery 背景任務：音訊轉換、ASR 轉寫、LLM 錯別字校正、四區塊會議紀錄整理與檔案歸檔。"""
    db = SessionLocal()
    try:
        # 1. 更新狀態為 processing
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task:
            return

        db_task.status = "processing"
        db.commit()

        # 確保音訊可於網頁播放 (轉換為 mp3)
        mp3_file_path = os.path.splitext(file_path)[0] + ".mp3"
        if not os.path.exists(mp3_file_path) and file_path != mp3_file_path:
            logger.info(f"[{task_id}] 正在將音訊轉換為 MP3 供前端播放...")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", file_path, "-vn", "-c:a", "libmp3lame", "-b:a", "128k", mp3_file_path],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                db_task.file_path = os.path.basename(mp3_file_path)
                db.commit()
                file_path = mp3_file_path
            except Exception as e:
                logger.warning(f"[{task_id}] 音訊轉換失敗，繼續使用原始檔案: {e}")

        # 調用 ASR 模型進行轉寫與講者辨識
        from src.infrastructure.ml_models import MeetingTranscriber
        transcriber = MeetingTranscriber.get_instance()
        logger.info(f"[{task_id}] 開始進行語音轉錄 ({file_path})...")
        real_result = transcriber.process_audio(file_path)

        # 2. 階段一：語意錯別字校正
        client = get_llm_client()
        logger.info(f"[{task_id}] 執行語意錯別字校正 (LLM: {client.base_url})...")
        corrected_transcript = client.correct_transcript(real_result)
        db_task.transcript = corrected_transcript
        db.commit()

        # 3. 階段二：四區塊結構化會議記錄生成
        logger.info(f"[{task_id}] 生成四區塊會議紀錄摘要...")
        minutes_summary = client.generate_meeting_minutes(corrected_transcript)
        db_task.summary = minutes_summary

        # 4. 更新任務為 completed
        db_task.status = "completed"
        db.commit()

        # 5. 自動歸檔 Markdown 檔案至 output/YYYY-MM-DD/
        save_output_md_files(
            task_id=task_id,
            original_filename=db_task.file_path,
            transcript=db_task.transcript,
            summary=db_task.summary,
        )

        logger.info(f"[{task_id}] 任務全流程處理完成。")

    except Exception as e:
        db.rollback()
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if db_task:
            db_task.status = "failed"
            db_task.error_message = str(e)
            db.commit()
        logger.error(f"[{task_id}] 任務處理失敗: {e}")
    finally:
        db.close()


@celery_app.task(name="resummarize_task")
def resummarize_task(task_id: str):
    """Celery 背景任務：重新進行會議記錄摘要生成。"""
    db = SessionLocal()
    try:
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task or not db_task.transcript:
            return

        db_task.status = "processing"
        db_task.error_message = None
        db.commit()

        client = get_llm_client()
        logger.info(f"[{task_id}] 重新生成會議記錄摘要...")
        minutes_summary = client.generate_meeting_minutes(db_task.transcript)
        db_task.summary = minutes_summary
        db_task.status = "completed"
        db.commit()

        save_output_md_files(
            task_id=task_id,
            original_filename=db_task.file_path,
            transcript=db_task.transcript,
            summary=db_task.summary,
        )
        logger.info(f"[{task_id}] 重新生成會議紀錄完成。")
    except Exception as e:
        db.rollback()
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if db_task:
            db_task.status = "completed"
            db_task.summary = f"摘要生成失敗: {e}"
            db.commit()
        logger.error(f"[{task_id}] 重新摘要錯誤: {e}")
    finally:
        db.close()


def save_output_md_files(task_id: str, original_filename: str, transcript: str, summary: str):
    """將逐字稿與會議紀錄摘要自動儲存至 output/YYYY-MM-DD/ 目錄下的 .md 檔案。"""
    try:
        base_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../output"))
        today_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = os.path.join(base_output_dir, today_str)

        raw_name = os.path.splitext(os.path.basename(original_filename))[0] if original_filename else f"Task_{task_id[:8]}"
        t_file, s_file = save_meeting_outputs(
            transcript=transcript or "",
            summary=summary or "",
            output_dir=date_dir,
            fallback_name=raw_name,
            task_id=task_id,
        )
        logger.info(f"[{task_id}] 成功儲存輸出 MD 檔案: {t_file.name}, {s_file.name}")
    except Exception as e:
        logger.error(f"[{task_id}] 儲存輸出 MD 檔案失敗: {e}")
