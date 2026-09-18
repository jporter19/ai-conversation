# app/core/auth.py
# Purpose: Portal SSO middleware — portal_sdk verify, hub admin, lazy local profile.

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request as FastAPIRequest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.core.portal_session import (
    PortalUser,
    app_id,
    auth_disabled,
    can_admin_app,
    can_use_app,
    cookie_domain,
    cookie_name,
    effective_app_role,
)
from app.core.user_context import set_current_user
from portal_sdk.fastapi_auth import PortalAuth

os.environ.setdefault("APP_ID", "ai-conversation")
os.environ.setdefault("APP_HOME_PATH", "/chat/")

auth = PortalAuth.from_env(
    app_id="ai-conversation",
    public_paths=("/health", "/login"),
    public_prefixes=(
        "/api/v1/auth/",
        "/css/",
        "/js/",
        "/assets/",
        "/portal-assets/",
    ),
    html_redirect=True,
)

logger = logging.getLogger(__name__)

# Granted users (not only app admins) may call these (hub + legacy admin alias).
_ADMIN_OPEN_EXACT = {
    "/api/v1/hub/catalog",
    "/api/v1/hub/preferences",
    "/api/v1/admin/catalog",
    "/api/v1/admin/preferences",
}
_ADMIN_OPEN_PREFIXES = (
    "/api/v1/hub/tts/",
    "/api/v1/admin/tts/",
)

_HUB_API_PREFIXES = (
    "/api/v1/hub/",
    "/api/v1/admin/",  # legacy alias; Brave may block this path
)


def _admin_open_path(path: str) -> bool:
    """Personal catalog / prefs / TTS preview — any granted user, not app-admin-only."""
    if path in _ADMIN_OPEN_EXACT:
        return True
    for prefix in _ADMIN_OPEN_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def resolve_portal_user(request: Request) -> Optional[PortalUser]:
    return auth.resolve_user(request)


def current_portal_user(request: Request) -> Optional[PortalUser]:
    user = getattr(request.state, "portal_user", None)
    if user is not None:
        return user
    return resolve_portal_user(request)


def current_username(request: Request) -> Optional[str]:
    user = current_portal_user(request)
    return user.username if user else None


def current_user_id(request: Request) -> Optional[str]:
    user = current_portal_user(request)
    return user.user_id if user else None


def _forbidden(request: Request, detail: str, *, api: bool) -> Response:
    if api:
        return JSONResponse({"detail": detail}, status_code=403)
    return RedirectResponse(url=auth.login_url, status_code=302)


def _ensure_local_account(user: PortalUser) -> None:
    """Upsert profile + optional one-shot legacy migrate (owner only)."""
    try:
        from app.services.user_store import (
            migrate_legacy_data_if_needed,
            upsert_profile,
        )

        upsert_profile(user.user_id, user.username)
        migrate_legacy_data_if_needed(user.user_id)
    except Exception:
        logger.exception("user profile upsert failed for %s", user.user_id)


class AuthGateMiddleware(BaseHTTPMiddleware):
    """
    Verify portal_session; require grant for APP_ID (ai-conversation).
    Sets request.state.portal_user and contextvar for stores.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        set_current_user(None)
        path = request.url.path or "/"

        if auth.is_public(path):
            return await call_next(request)

        user = resolve_portal_user(request)
        is_api = path.startswith("/api/")

        if not user:
            return auth.unauthenticated_response(request)

        if not auth_disabled() and not can_use_app(user):
            return _forbidden(
                request,
                f"No access grant for application `{app_id()}`.",
                api=is_api,
            )

        request.state.portal_user = user
        request.state.username = user.username
        request.state.user_id = user.user_id
        request.state.app_role = effective_app_role(user)
        set_current_user(user)

        # Hub settings API: mutate shared catalog only with app admin role
        if path.startswith(_HUB_API_PREFIXES) and not _admin_open_path(path):
            if not auth_disabled() and not can_admin_app(user):
                return _forbidden(
                    request,
                    "Admin role required for this application.",
                    api=True,
                )

        # Local profile + dirs on first granted visit (lazy account)
        _ensure_local_account(user)

        try:
            return await call_next(request)
        finally:
            set_current_user(None)


def require_user(request: FastAPIRequest) -> PortalUser:
    user = current_portal_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not auth_disabled() and not can_use_app(user):
        raise HTTPException(403, f"No access grant for application `{app_id()}`.")
    return user


def request_user_id(request: FastAPIRequest) -> str:
    """Portal uid for this request. Prefer middleware request.state over ContextVar."""
    uid = getattr(request.state, "user_id", None)
    if uid:
        return str(uid)
    uid = current_user_id(request)
    if not uid:
        raise HTTPException(401, "Not authenticated")
    return str(uid)


def require_app_admin(user: PortalUser = Depends(require_user)) -> PortalUser:
    if auth_disabled():
        return user
    if can_admin_app(user):
        return user
    raise HTTPException(403, "Admin role required for this application.")


def clear_portal_cookie(response: Response) -> None:
    """
    Clear portal_session on logout.
    Match Path / SameSite / Secure used when portal-admin set the cookie,
    or browsers keep the old cookie and SSO looks "broken".
    """
    import os

    secure_flag = (os.environ.get("PORTAL_SESSION_HTTPS_ONLY") or os.environ.get("SESSION_HTTPS_ONLY") or "").strip().lower()
    secure = secure_flag in {"1", "true", "yes", "on"}
    # Production family domain is HTTPS; default Secure when not explicitly off
    if secure_flag in {"0", "false", "no", "off"}:
        secure = False
    elif not secure_flag:
        secure = True

    kwargs = {
        "key": cookie_name(),
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
    }
    domain = cookie_domain()
    if domain:
        kwargs["domain"] = domain
    response.delete_cookie(**kwargs)
