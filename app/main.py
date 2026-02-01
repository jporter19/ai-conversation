# app/main.py
# Purpose: Thin FastAPI entry point
#          - Creates the app
#          - Adds middleware (CORS)
#          - Serves frontend static files
#          - Includes API routers

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

# Import the chat router
from app.api.v1 import chat

app = FastAPI(
    title="AI Conversation Hub",
    description="Personal tool to chat with Grok or ChatGPT models",
    version="0.1.0"
)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Serve index.html at root
@app.get("/", include_in_schema=False)
async def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return {"error": "index.html not found"}
    return FileResponse(index_path)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(chat.router, prefix="/api")