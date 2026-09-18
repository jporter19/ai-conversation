# app/main.py
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import admin, auth, chat, contexts, conversations
from app.core.auth import AuthGateMiddleware
from app.core.portal_session import app_home_path, login_redirect_url

app = FastAPI(
    title="AI Conversation Hub",
    description="Family multi-API chat hub (Porter Family Portal SSO)",
    version="0.5.0",
)

# Middleware order: last added runs first on the request.
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # same-origin only (portal cookie)
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
# Hub settings API (canonical). Also alias /admin for older cached clients.
app.include_router(admin.router, prefix="/api/v1/hub")
app.include_router(admin.router, prefix="/api/v1/admin")
app.include_router(contexts.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")


@app.middleware("http")
async def no_cache_static_assets(request, call_next):
    """Avoid stale ES modules (Brave/Firefox) after deploys — entry ?v= alone is not enough."""
    response = await call_next(request)
    path = request.url.path or ""
    if path.startswith("/js/") or path.startswith("/css/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path in ("/", "/index.html") or path.endswith("/index.html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health")
async def health():
    return {"ok": True, "service": "ai-conversation", "auth": "portal-sso"}


@app.get("/login")
async def serve_login():
    """No AI login page — send the browser to the family portal."""
    return RedirectResponse(url=login_redirect_url(app_home_path()), status_code=302)


@app.get("/", response_class=FileResponse)
async def serve_index():
    # Public shell at /chat/ (nginx). Identity is portal_session, not an app login.
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
        },
    )
