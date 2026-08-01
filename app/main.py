# app/main.py
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1 import admin, auth, chat, conversations
from app.core.auth import AuthGateMiddleware, cookie_https_only, session_secret

app = FastAPI(
    title="AI Conversation Hub",
    description="Personal multi-API chat hub with admin tools for providers, keys, and preferences",
    version="0.4.0",
)

# Middleware order: last added runs first on request.
# Auth gate → session → CORS
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="ai_hub_session",
    same_site="lax",
    https_only=cookie_https_only(),
    max_age=60 * 60 * 24 * 14,  # 14 days
)
# Same-origin nginx deploy does not need open CORS. Keep permissive methods
# only for local file:// debugging if needed — credentials + "*" is invalid.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # same-origin only
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")


@app.get("/health")
async def health():
    return {"ok": True, "service": "ai-conversation"}


@app.get("/login", response_class=FileResponse)
async def serve_login():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")
