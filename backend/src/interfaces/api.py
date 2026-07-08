from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from src.infrastructure.database import get_db, TaskModel
from src.usecases import transcription
from src.domain.entities import TaskResponse, TaskStatusResponse
import shutil
import os
import time
from fastapi.responses import FileResponse

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def cleanup_old_files(directory: str, days: int = 30):
    now = time.time()
    cutoff = now - (days * 86400)
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                if os.path.getmtime(file_path) < cutoff:
                    try:
                        os.remove(file_path)
                        print(f"Cleaned up old file: {file_path}")
                    except Exception as e:
                        print(f"Error deleting {file_path}: {e}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

@router.post("/transcriptions", response_model=TaskResponse, status_code=201)
def upload_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Create task
    task_res = transcription.create_task(db, file.filename)
    
    # 清理大於 1 個月未變動的音檔 (背景執行)
    background_tasks.add_task(cleanup_old_files, UPLOAD_DIR, 30)
    
    # Save file locally using task_id to prevent collision
    file_extension = os.path.splitext(file.filename)[1]
    safe_filename = f"{task_res.id}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Update task with new safe_filename
    db_task = db.query(TaskModel).filter(TaskModel.id == task_res.id).first()
    db_task.file_path = safe_filename
    db.commit()
    
    # Schedule background processing via Celery
    transcription.process_audio_task.delay(task_res.id, file_path)
    
    return task_res

@router.get("/transcriptions/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    return TaskStatusResponse(
        id=db_task.id,
        status=db_task.status,
        transcript=db_task.transcript,
        summary=db_task.summary,
        error_message=db_task.error_message,
        created_at=db_task.created_at
    )

@router.get("/transcriptions/{task_id}/audio")
def get_task_audio(task_id: str, db: Session = Depends(get_db)):
    db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    file_path = os.path.join(UPLOAD_DIR, db_task.file_path)
    
    # 如果原始檔是 m4a 等不易在網頁端直接播放的格式，且我們有轉檔出 mp3，則優先提供 mp3
    mp3_file_path = os.path.splitext(file_path)[0] + ".mp3"
    if os.path.exists(mp3_file_path):
        file_path = mp3_file_path
        
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    filename = f"audio_{task_id}{os.path.splitext(file_path)[1]}"
    return FileResponse(file_path, filename=filename)

@router.get("/transcriptions")
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(TaskModel).order_by(TaskModel.created_at.desc()).all()
    return {"items": tasks, "total": len(tasks)}

@router.delete("/transcriptions/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db)):
    db_task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    db.delete(db_task)
    db.commit()
    return None
