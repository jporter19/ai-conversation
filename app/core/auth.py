# app/core/auth.py
# Purpose: Session helpers, login rate limit, and request-auth middleware.

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

SESSION_COOKIE_USER = "username"

# Public routes: auth endpoints + health + login HTML.
# Static mounts (/css, /js, /assets) are public so login assets always load.
_PUBLIC_EXACT = {
    "/login",
    "/health",
}

_PUBLIC_PREFIXES = (
    "/api/v1/auth/",
    "/css/",
    "/js/",
    "/assets/",
)

_FAILS: Dict[str, Deque[float]] = defaultdict(deque)
_FAIL_WINDOW_SEC = 15 * 60
_FAIL_MAX = 5
_rate_lock = threading.Lock()

_resolved_secret: Optional[str] = None


def auth_disabled() -> bool:
    return (os.environ.get("AUTH_DISABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def session_secret() -> str:
    """
    Stable session signing key.
    Production (auth on) requires SESSION_SECRET — do not mint ephemeral secrets.
    """
    global _resolved_secret
    if _resolved_secret is not None:
        return _resolved_secret

    secret = (os.environ.get("SESSION_SECRET") or "").strip()
    if secret:
        _resolved_secret = secret
        return secret
    if auth_disabled():
        _resolved_secret = "dev-only-insecure-session-secret"
        return _resolved_secret
    raise RuntimeError(
        "SESSION_SECRET is required when auth is enabled. "
        "Set it in the environment (e.g. /etc/ai-conversation/env) or set AUTH_DISABLED=1 for local dev."
    )


def cookie_https_only() -> bool:
    flag = (os.environ.get("SESSION_HTTPS_ONLY") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return False


def current_username(request: Request) -> Optional[str]:
    if auth_disabled():
        return "dev"
    try:
        user = request.session.get(SESSION_COOKIE_USER)
    except AssertionError:
        return None
    if not user:
        return None
    return str(user)


def login_user(request: Request, username: str) -> None:
    request.session[SESSION_COOKIE_USER] = username


def logout_user(request: Request) -> None:
    request.session.clear()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def login_rate_limited(request: Request) -> bool:
    ip = _client_ip(request)
    now = time.time()
    with _rate_lock:
        q = _FAILS[ip]
        while q and now - q[0] > _FAIL_WINDOW_SEC:
            q.popleft()
        return len(q) >= _FAIL_MAX


def record_login_failure(request: Request) -> None:
    ip = _client_ip(request)
    now = time.time()
    with _rate_lock:
        q = _FAILS[ip]
        q.append(now)
        while q and now - q[0] > _FAIL_WINDOW_SEC:
            q.popleft()


def clear_login_failures(request: Request) -> None:
    ip = _client_ip(request)
    with _rate_lock:
        _FAILS.pop(ip, None)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    return False


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Require a session for the app shell and /api/* (except public auth routes)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if auth_disabled():
            return await call_next(request)

        path = request.url.path or "/"
        if _is_public(path):
            return await call_next(request)

        user = current_username(request)
        if user:
            request.state.username = user
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        return RedirectResponse(url="/login", status_code=302)
