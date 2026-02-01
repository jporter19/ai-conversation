# app/main.py
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse   # ← add FileResponse here
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import httpx
import json
from typing import AsyncGenerator, List, Dict

# ... rest of your file ...

from app.api.v1 import chat  # import routers later
from app.config import settings

app = FastAPI(
    title="AI Conversation Hub API",
    description="Proxy + storage for Grok and ChatGPT",
    version="0.1.0"
)

# Mount frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")

# CORS (for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers later
app.include_router(chat.router, prefix=f"{settings.API_PREFIX}/v1/chat")