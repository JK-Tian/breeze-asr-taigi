from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

class TranscriptionTaskBase(BaseModel):
    filename: str

class TranscriptionTask(TranscriptionTaskBase):
    id: str
    status: str = "pending" # pending, processing, completed, failed
    result: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TaskResponse(BaseModel):
    id: str
    status: str
    message: str

class TaskStatusResponse(BaseModel):
    id: str
    status: str
    transcript: Optional[str] = None
    summary: Optional[str] = None
    error_message: Optional[str] = None
    km_wiki_synced: Optional[bool] = None
    created_at: datetime
