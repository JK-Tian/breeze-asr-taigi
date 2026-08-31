import uuid
import asyncio
import os
import re
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

        # 4. Save output MD files to output/YYYY-MM-DD/
        save_output_md_files(
            task_id=task_id,
            original_filename=db_task.file_path,
            transcript=db_task.transcript,
            summary=db_task.summary
        )

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

@celery_app.task(name="resummarize_task")
def resummarize_task(task_id: str):
    db = SessionLocal()
    try:
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task or not db_task.transcript:
            return
            
        db_task.status = "processing"
        db_task.error_message = None
        db.commit()
        
        llm_url = os.environ.get("LLM_URL", os.environ.get("OLLAMA_URL", "http://192.168.1.100:11434/v1"))
        llm_model = os.environ.get("LLM_MODEL", os.environ.get("OLLAMA_MODEL", "qwen2.5"))
        
        print(f"[{task_id}] Resummarizing using LLM ({llm_model}) at {llm_url}...")
        base_prompt = get_summary_prompt()
        prompt = f"{base_prompt}\n\n{db_task.transcript}"
        
        data = {
            "model": llm_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 65536,
            "temperature": 0.3
        }
        
        api_endpoint = f"{llm_url.rstrip('/')}/chat/completions"
        if "v1" not in llm_url and "api/generate" not in llm_url:
             api_endpoint = f"{llm_url.rstrip('/')}/v1/chat/completions"
             
        req = urllib.request.Request(
            api_endpoint,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=1800) as response:
                result = json.loads(response.read().decode('utf-8'))
                message = result.get('choices', [{}])[0].get('message', {})
                content = message.get('content') or ""
                reasoning = message.get('reasoning') or ""
                
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
            print(f"[{task_id}] LLM resummarization failed: {e}")
            db_task.summary = f"摘要生成失敗: {e}"
            
        db_task.status = "completed"
        db.commit()

        save_output_md_files(
            task_id=task_id,
            original_filename=db_task.file_path,
            transcript=db_task.transcript,
            summary=db_task.summary
        )
        print(f"[{task_id}] Resummarization completed.")
    except Exception as e:
        db.rollback()
        db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if db_task:
            db_task.status = "completed"
            db_task.summary = f"摘要生成失敗: {e}"
            db.commit()
        print(f"[{task_id}] Resummarization error: {e}")
    finally:
        db.close()

def sanitize_filename(name: str) -> str:
    """過濾非法檔名字元並清理前後空白"""
    if not name:
        return ""
    sanitized = re.sub(r'[\\/*?:"<>|\r\n\t]', '', name).strip()
    sanitized = re.sub(r'^[#*\s]+', '', sanitized).strip()
    return sanitized[:60]

def extract_meeting_title(summary: str, fallback: str) -> str:
    """從 LLM 生成的會議摘要中提取會議名稱/主題"""
    if summary:
        lines = summary.splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            clean_line = line_str.replace('*', '').strip()

            match = re.search(r'(?:會議名稱|會議主題|主題|標題)[：:]\s*(.+)', clean_line)
            if match:
                extracted = match.group(1).strip()
                clean_name = sanitize_filename(extracted)
                if clean_name:
                    return clean_name

            if clean_line.startswith('#'):
                extracted = clean_line.lstrip('#').strip()
                clean_name = sanitize_filename(extracted)
                if clean_name and clean_name not in ["會議紀錄", "會議摘要", "會議重點", "摘要"]:
                    return clean_name

    clean_fallback = sanitize_filename(fallback)
    return clean_fallback if clean_fallback else "未命名會議"

def save_output_md_files(task_id: str, original_filename: str, transcript: str, summary: str):
    """將逐字稿與會議紀錄摘要自動儲存至 output/YYYY-MM-DD/ 目錄下的 .md 檔案"""
    try:
        base_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../output"))
        today_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = os.path.join(base_output_dir, today_str)
        os.makedirs(date_dir, exist_ok=True)

        raw_name = os.path.splitext(os.path.basename(original_filename))[0] if original_filename else f"Task_{task_id[:8]}"
        meeting_title = extract_meeting_title(summary, raw_name)

        base_filename = meeting_title
        transcript_file = os.path.join(date_dir, f"{base_filename}_逐字稿.md")
        summary_file = os.path.join(date_dir, f"{base_filename}_會議紀錄與摘要.md")

        counter = 1
        while os.path.exists(transcript_file) or os.path.exists(summary_file):
            base_filename = f"{meeting_title}_{counter}"
            transcript_file = os.path.join(date_dir, f"{base_filename}_逐字稿.md")
            summary_file = os.path.join(date_dir, f"{base_filename}_會議紀錄與摘要.md")
            counter += 1

        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(f"# {meeting_title} - 會議逐字稿\n\n")
            f.write(f"- **日期**: {today_str}\n")
            f.write(f"- **任務 ID**: {task_id}\n\n")
            f.write("---\n\n")
            f.write(transcript or "")

        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(f"# {meeting_title} - 會議紀錄與摘要\n\n")
            f.write(f"- **日期**: {today_str}\n")
            f.write(f"- **任務 ID**: {task_id}\n\n")
            f.write("---\n\n")
            f.write(summary or "")

        print(f"[{task_id}] Successfully saved output MD files to {date_dir}: {base_filename}")
    except Exception as e:
        print(f"[{task_id}] Failed to save output MD files: {e}")

