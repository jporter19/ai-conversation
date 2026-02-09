# app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

from app.api.v1 import chat

app = FastAPI(
    title="AI Conversation Hub",
    description="Personal tool to chat with Grok or ChatGPT models",
    version="0.1.0"
)

# CORS first
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# IMPORTANT: Include API routers BEFORE static mount
app.include_router(chat.router, prefix="/api/v1")

# Frontend directory
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Mount static assets under /assets, /css, /js — but NOT the whole root
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
app.mount("/css",    StaticFiles(directory=FRONTEND_DIR / "css"),    name="css")
app.mount("/js",     StaticFiles(directory=FRONTEND_DIR / "js"),     name="js")

# Explicitly serve index.html at root (prevents static catch-all for /api/v1)
@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")