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
from typing import Any, Dict, Optional
import urllib.request
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.domain.entities import TaskResponse
from src.infrastructure.celery_app import celery_app
from src.infrastructure.database import SessionLocal, TaskModel

# 確保可引用 taigi_asr 共用服務層
parent_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))
if parent_src not in sys.path:
    sys.path.insert(0, parent_src)

from taigi_asr.km_wiki import KMWikiService
from taigi_asr.llm import LLMClient
from taigi_asr.minutes import (
    extract_meeting_title,
    format_obsidian_meeting_notes,
    sanitize_filename,
    save_meeting_outputs,
)
from taigi_asr.vision import KeyframeExtractor, VLMClient

logger = logging.getLogger("transcription_usecase")


def get_correction_llm_client() -> LLMClient:
    """取得專責語意錯別字校正的 LLMClient (預設 8001)。"""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
    correction_url = "http://192.168.1.100:8001/v1"
    correction_model = "auto"

    if os.path.exists(config_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding="utf-8")
            if "Correction" in parser:
                correction_url = parser["Correction"].get("correction_url", correction_url)
                correction_model = parser["Correction"].get("correction_model", correction_model)
        except Exception as e:
            logger.warning(f"讀取 config.ini [Correction] 失敗: {e}")

    # 環境變數優先：LLM_CORRECTION_URL > LLM_URL > config.ini
    correction_url = os.environ.get("LLM_CORRECTION_URL", os.environ.get("LLM_URL", correction_url))
    correction_model = os.environ.get("LLM_CORRECTION_MODEL", os.environ.get("LLM_MODEL", correction_model))

    return LLMClient(base_url=correction_url, model=correction_model, timeout=1800)


def get_minutes_llm_client() -> LLMClient:
    """取得專責結構化會議記錄提煉的 LLMClient (預設 8002)。"""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
    minutes_url = "http://192.168.1.100:8002/v1"
    minutes_model = "auto"

    if os.path.exists(config_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding="utf-8")
            if "LLM" in parser:
                minutes_url = parser["LLM"].get("llm_url", minutes_url)
                minutes_model = parser["LLM"].get("llm_model", minutes_model)
            elif "MeetingMinutes" in parser:
                minutes_url = parser["MeetingMinutes"].get("minutes_url", minutes_url)
                minutes_model = parser["MeetingMinutes"].get("minutes_model", minutes_model)
        except Exception as e:
            logger.warning(f"讀取 config.ini [LLM] 失敗: {e}")

    # 環境變數優先：LLM_MINUTES_URL > LLM_URL > config.ini (絕不讀取 LLM_CORRECTION_URL，徹底杜絕遮蔽)
    minutes_url = os.environ.get("LLM_MINUTES_URL", os.environ.get("LLM_URL", minutes_url))
    minutes_model = os.environ.get("LLM_MINUTES_MODEL", os.environ.get("LLM_MODEL", minutes_model))

    return LLMClient(base_url=minutes_url, model=minutes_model, timeout=1800)


def get_llm_client() -> LLMClient:
    """向下相容別名，取得會議記錄 Client。"""
    return get_minutes_llm_client()


def get_vlm_client() -> VLMClient:
    """從設定檔與環境變數取得 VLMClient 實例。"""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
    vlm_url = "http://192.168.1.100:8000/v1"
    vlm_model = "Qwen/Qwen3.8-27B-FP8"
    vlm_timeout = 60

    if os.path.exists(config_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding="utf-8")
            if "Vision" in parser:
                vision_cfg = parser["Vision"]
                vlm_url = vision_cfg.get("vlm_url", vlm_url)
                vlm_model = vision_cfg.get("vlm_model", vlm_model)
                vlm_timeout = int(vision_cfg.get("vlm_timeout", vlm_timeout))
        except Exception as e:
            logger.warning(f"讀取 config.ini [Vision] 失敗: {e}")

    # 環境變數優先
    vlm_url = os.environ.get("VLM_URL", vlm_url)
    vlm_model = os.environ.get("VLM_MODEL", vlm_model)
    vlm_timeout = int(os.environ.get("VLM_TIMEOUT", vlm_timeout))

    return VLMClient(base_url=vlm_url, model=vlm_model, timeout=vlm_timeout)


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
    """Celery 背景任務：多模態視覺分析、音訊轉換、ASR 轉寫、LLM 錯別字校正、雙模態會議記錄整理與檔案歸檔。"""
    db = SessionLocal()
    try:
        # 1. 更新狀態為 processing
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task:
            return

        db_task.status = "processing"
        db.commit()

        # 檢查原始檔案是否為影片，並進行多模態關鍵畫面擷取與 VLM 分析
        visual_context: Optional[str] = None
        raw_media_path = file_path
        extractor = KeyframeExtractor()

        if extractor.is_video_file(raw_media_path):
            logger.info(f"[{task_id}] 偵測到影片檔案，啟動多模態關鍵幀擷取與 VLM 視覺分析...")
            keyframes = []
            try:
                keyframes = extractor.extract_keyframes(raw_media_path)
                if keyframes:
                    logger.info(f"[{task_id}] 擷取到 {len(keyframes)} 張關鍵幀，交由視覺模型分析...")
                    vlm_client = get_vlm_client()
                    visual_context = vlm_client.analyze_keyframes(keyframes)
            except Exception as vlm_exc:
                logger.warning(f"[{task_id}] 多模態視覺分析異常 ({vlm_exc})，平滑降級為純音訊摘要流程。")
                visual_context = None
            finally:
                # 零截圖純淨排版與看完即忘原則：推論完成或異常時立即抹除暫存畫面
                if keyframes:
                    extractor.cleanup_keyframes(keyframes)

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

        # 2. 階段一：語意錯別字校正 (專屬 8001 / Correction 端點)
        correction_client = get_correction_llm_client()
        logger.info(f"[{task_id}] 執行語意錯別字校正 (Correction LLM: {correction_client.base_url})...")
        corrected_transcript = correction_client.correct_transcript(real_result)
        db_task.transcript = corrected_transcript
        db.commit()

        # 3. 階段二：音視雙模態結構化會議記錄生成 (專屬 8002 / Minutes 端點，遵循 video-to-notes 規範)
        minutes_client = get_minutes_llm_client()
        logger.info(f"[{task_id}] 生成結構化會議紀錄摘要 (Minutes LLM: {minutes_client.base_url}, 結合視覺時間軸: {visual_context is not None})...")
        raw_minutes_summary = minutes_client.generate_meeting_minutes(
            corrected_transcript, visual_context=visual_context
        )
        # 包裝為 Obsidian PKM YAML Frontmatter 格式與文末參考資料
        media_name = os.path.basename(raw_media_path) if raw_media_path else (os.path.basename(db_task.file_path) if db_task.file_path else f"Task_{task_id[:8]}")
        obsidian_summary = format_obsidian_meeting_notes(
            summary=raw_minutes_summary,
            media_filename=media_name,
        )
        db_task.summary = obsidian_summary

        # 4. 更新任務為 completed
        db_task.status = "completed"
        db.commit()

        # 5. 自動歸檔 Markdown 檔案至 output/YYYY-MM-DD/ 並同步至 KM Wiki
        is_synced = save_output_md_files(
            task_id=task_id,
            original_filename=db_task.file_path,
            transcript=db_task.transcript,
            summary=db_task.summary,
        )
        db_task.km_wiki_synced = bool(is_synced)
        db.commit()
        logger.info(f"[{task_id}] 任務全流程處理完成 (KM Wiki 同步: {is_synced})。")

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
    """Celery 背景任務：重新進行會議記錄摘要生成 (使用專屬 Minutes LLM 端點)。"""
    db = SessionLocal()
    try:
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task or not db_task.transcript:
            return

        db_task.status = "processing"
        db_task.error_message = None
        db.commit()

        minutes_client = get_minutes_llm_client()
        logger.info(f"[{task_id}] 重新生成會議記錄摘要 (Minutes LLM: {minutes_client.base_url})...")
        raw_minutes_summary = minutes_client.generate_meeting_minutes(db_task.transcript)
        media_name = os.path.basename(db_task.file_path) if db_task.file_path else f"Task_{task_id[:8]}"
        obsidian_summary = format_obsidian_meeting_notes(
            summary=raw_minutes_summary,
            media_filename=media_name,
        )
        db_task.summary = obsidian_summary
        db_task.status = "completed"
        db.commit()

        is_synced = save_output_md_files(
            task_id=task_id,
            original_filename=db_task.file_path,
            transcript=db_task.transcript,
            summary=db_task.summary,
        )
        db_task.km_wiki_synced = bool(is_synced)
        db.commit()
        logger.info(f"[{task_id}] 重新生成會議紀錄完成 (KM Wiki 同步: {is_synced})。")
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


def get_km_wiki_service() -> KMWikiService:
    """取得 KM Wiki 同步服務實例。"""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
    enabled = True
    raw_dir = "D:/km_wiki/Minutes/raw"
    date_subfolder = True

    if os.path.exists(config_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding="utf-8")
            if "KMWiki" in parser:
                km_cfg = parser["KMWiki"]
                enabled = km_cfg.getboolean("enabled", fallback=enabled)
                raw_dir = km_cfg.get("raw_dir", fallback=raw_dir)
                date_subfolder = km_cfg.getboolean("date_subfolder", fallback=date_subfolder)
        except Exception as e:
            logger.warning(f"讀取 config.ini [KMWiki] 失敗: {e}")

    # 環境變數優先
    if "KM_WIKI_ENABLED" in os.environ:
        enabled = os.environ["KM_WIKI_ENABLED"].lower() in ("true", "1", "yes")
    if "KM_WIKI_RAW_DIR" in os.environ:
        raw_dir = os.environ["KM_WIKI_RAW_DIR"]
    if "KM_WIKI_DATE_SUBFOLDER" in os.environ:
        date_subfolder = os.environ["KM_WIKI_DATE_SUBFOLDER"].lower() in ("true", "1", "yes")

    return KMWikiService(enabled=enabled, raw_dir=raw_dir, date_subfolder=date_subfolder)


def save_output_md_files(task_id: str, original_filename: str, transcript: str, summary: str) -> bool:
    """將逐字稿與會議紀錄摘要自動儲存至 output/YYYY-MM-DD/ 目錄，並同步至 KM Wiki Minutes 知識庫 raw 檔區。

    Returns:
        bool: 是否成功同步至 KM Wiki (未啟用或失敗時回傳 False)。
    """
    km_synced = False
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
            media_filename=original_filename,
        )
        logger.info(f"[{task_id}] 成功儲存本地輸出 MD 檔案: {t_file.name}, {s_file.name}")

        # 同步至 KM Wiki Minutes 知識庫 raw 檔區
        km_service = get_km_wiki_service()
        sync_result = km_service.sync_files(transcript_path=t_file, summary_path=s_file)
        km_synced = sync_result.get("synced", False)
        if km_synced:
            logger.info(f"[{task_id}] 成功同步至 KM Wiki: {sync_result.get('synced_files')}")
    except Exception as e:
        logger.error(f"[{task_id}] 儲存輸出 MD 檔案或同步 KM Wiki 失敗: {e}")

    return km_synced


def sync_task_km_wiki(db: Session, task_id: str) -> Dict[str, Any]:
    """手動或外部重新觸發特定任務同步至 KM Wiki Minutes raw 檔區。

    Args:
        db: 資料庫 Session
        task_id: 任務 ID

    Returns:
        同步狀態字典
    """
    db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not db_task.transcript and not db_task.summary:
        raise HTTPException(status_code=400, detail="任務尚未具備逐字稿或會議紀錄，無法同步至 KM Wiki")

    km_synced = save_output_md_files(
        task_id=task_id,
        original_filename=db_task.file_path,
        transcript=db_task.transcript or "",
        summary=db_task.summary or "",
    )

    db_task.km_wiki_synced = km_synced
    db.commit()

    km_service = get_km_wiki_service()
    return {
        "task_id": task_id,
        "km_wiki_synced": km_synced,
        "raw_dir": km_service.raw_dir,
        "message": "成功同步至 KM Wiki Minutes 知識庫 raw 檔區" if km_synced else "KM Wiki 同步失敗或未啟用 (請檢查目錄權限或設定)",
    }
