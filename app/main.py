# app/main.py
# Purpose: Entry point for our FastAPI application.
#          Serves static files and will handle API routes later.

import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Calculate absolute path to the project root (one level up from app/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Path to the frontend folder
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

app = FastAPI(
    title="AI Conversation Hub",
    description="Personal tool to chat with Grok or ChatGPT models",
    version="0.1.0"
)

# Mount the frontend folder so CSS, JS, images, etc. are accessible
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Serves the main frontend page (index.html) when visiting the root URL.
    """
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    
    # Optional: You could add error handling here later
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    return HTMLResponse(content=html_content)

# Optional: Keep the health check
@app.get("/health")
async def health():
    return {"status": "healthy"}