import uuid
import asyncio
import os
import urllib.request
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.domain.entities import TaskResponse
from src.infrastructure.database import TaskModel, SessionLocal
import configparser
from src.infrastructure.celery_app import celery_app

def get_summary_prompt() -> str:
    default_prompt = "請根據以下會議逐字稿，使用繁體中文整理出詳細的會議重點、決議事項與後續行動項目(Action Items)："
    try:
        config = configparser.ConfigParser()
        # config.ini 位於專案根目錄，相對於目前檔案的位置為 ../../../config.ini
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.ini"))
        if os.path.exists(config_path):
            config.read(config_path, encoding='utf-8')
            if "LLM" in config and "summary_prompt" in config["LLM"]:
                return config["LLM"]["summary_prompt"]
    except Exception as e:
        print(f"Failed to read config.ini for prompt: {e}")
    return default_prompt

def create_task(db: Session, filename: str) -> TaskResponse:
    task_id = str(uuid.uuid4())
    db_task = TaskModel(
        id=task_id,
        file_path=filename,
        status="pending",
        created_at=datetime.now(timezone.utc)
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return TaskResponse(id=task_id, status="pending", message="Audio uploaded successfully, processing started.")

@celery_app.task(name="process_audio")
def process_audio_task(task_id: str, file_path: str):
    db = SessionLocal()
    try:
        # 1. Update status to processing
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task:
            return
            
        db_task.status = "processing"
        db.commit()
        
        # Ensure audio is web-playable by converting to mp3
        import subprocess
        mp3_file_path = os.path.splitext(file_path)[0] + ".mp3"
        if not os.path.exists(mp3_file_path) and file_path != mp3_file_path:
            print(f"[{task_id}] Converting audio to MP3 for web playback...")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", file_path, "-vn", "-c:a", "libmp3lame", "-b:a", "128k", mp3_file_path],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                # Update db_task to point to the mp3 file for frontend playback
                db_task.file_path = os.path.basename(mp3_file_path)
                db.commit()
                file_path = mp3_file_path
            except Exception as e:
                print(f"[{task_id}] Audio conversion failed, continuing with original file: {e}")

        # Integrate Pyannote and Faster-Whisper (Breeze ASR 26)
        from src.infrastructure.ml_models import MeetingTranscriber
        transcriber = MeetingTranscriber.get_instance()
        
        print(f"[{task_id}] Start processing {file_path}...")
        
        # Get real output from ML models
        real_result = transcriber.process_audio(file_path)
        
        db_task.transcript = real_result
        db.commit()

        # 2. Call LLM API (vLLM / Ollama) to generate summary
        # 支援讀取新的 LLM_URL 或舊的 OLLAMA_URL
        llm_url = os.environ.get("LLM_URL", os.environ.get("OLLAMA_URL", "http://192.168.1.100:11434/v1"))
        llm_model = os.environ.get("LLM_MODEL", os.environ.get("OLLAMA_MODEL", "qwen2.5"))
        
        print(f"[{task_id}] Generating summary using LLM ({llm_model}) at {llm_url}...")
        base_prompt = get_summary_prompt()
        prompt = f"{base_prompt}\n\n{real_result}"
        
        # 使用相容於 vLLM 與 OpenAI 的標準格式
        data = {
            "model": llm_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 65536,
            "temperature": 0.3
        }
        
        # 確保 URL 結尾有接上正確的 endpoint
        api_endpoint = f"{llm_url.rstrip('/')}/chat/completions"
        if "v1" not in llm_url and "api/generate" not in llm_url:
             # 如果還是舊的 Ollama URL (例如 http://...:11434)，自動補上 /v1
             api_endpoint = f"{llm_url.rstrip('/')}/v1/chat/completions"
             
        req = urllib.request.Request(
            api_endpoint,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        try:
            # 由於 max_tokens 開到 65536，大型模型思考時間較長，將 timeout 設定為 1800 秒 (30分鐘)
            with urllib.request.urlopen(req, timeout=1800) as response:
                result = json.loads(response.read().decode('utf-8'))
                # 解析 OpenAI/vLLM 標準格式的回傳值
                message = result.get('choices', [{}])[0].get('message', {})
                
                # 針對思考型模型 (Reasoning models)，vLLM 會把思考過程放在 reasoning 欄位
                # 且如果中途達到 max_tokens，content 可能會是 None
                content = message.get('content') or ""
                reasoning = message.get('reasoning') or ""
                
                # 但是 Ollama 跑思考型模型時，可能會把思考過程直接放在 content 裡面，用 <think> 包起來
                # 我們把這兩種格式統一起來，確保 content 只包含最終結果
                if not reasoning and "<think>" in content:
                    parts = content.split("</think>")
                    if len(parts) == 2:
                        reasoning = parts[0].replace("<think>", "").strip()
                        content = parts[1].strip()
                
                final_summary = content
                
                if not final_summary.strip():
                    final_summary = "摘要生成失敗：模型回傳了空白結果（可能超出了 max_tokens 限制）。"
                    
                db_task.summary = final_summary
        except Exception as e:
            print(f"[{task_id}] LLM summarization failed: {e}")
            db_task.summary = f"摘要生成失敗: {e}"
        
        # 3. Update status to completed
        db_task.status = "completed"
        db.commit()
        print(f"[{task_id}] Processing completed.")
        
    except Exception as e:
        db.rollback()
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if db_task:
            db_task.status = "failed"
            db_task.error_message = str(e)
            db.commit()
        print(f"[{task_id}] Processing failed: {str(e)}")
    finally:
        db.close()
