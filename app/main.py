# app/main.py
# Purpose: Entry point for our FastAPI application.
#          Serves static files and will handle API routes later.

import os  # ← Add this import

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Get the absolute path to the project root (one level up from app/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Now build the absolute path to the frontend folder
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

app = FastAPI(
    title="AI Conversation Hub",
    description="Personal tool to chat with Grok or ChatGPT models",
    version="0.1.0"
)

# Mount the frontend folder using the calculated absolute path
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serves a simple welcome page when visiting http://127.0.0.1:8000"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Conversation Hub</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f0f4f8; }
            h1 { color: #2c3e50; }
        </style>
    </head>
    <body>
        <h1>AI Conversation Hub – Ready to build!</h1>
        <p>Backend is running. Next: frontend + AI integration.</p>
    </body>
    </html>
    """

# Optional: Basic health check endpoint
@app.get("/health")
async def health():
    return {"status": "healthy"}