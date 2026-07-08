from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

# 讀取上一層根目錄的 .env
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from src.interfaces.api import router as api_router
from src.infrastructure.database import init_db
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Breeze ASR Transcription API", version="1.0.0")

# Mount uploads directory for audio playback
# (Trigger hot-reload for Pyannote patch)
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev only, configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()
    # TODO: Preload Pyannote and Breeze ASR models here

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def root():
    return {"message": "Welcome to Breeze ASR Transcription API"}
