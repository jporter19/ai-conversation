# app/api/v1/auth.py
# Purpose: Expose the *portal* session to the AI shell. No local password login.
#
# Identity is always the portal_session cookie issued by portal-admin.
# This app never issues its own login credentials.

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.auth import clear_portal_cookie, current_portal_user
from app.core.portal_session import (
    app_home_path,
    app_id,
    auth_disabled,
    effective_app_role,
    login_redirect_url,
    portal_login_url,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login_removed():
    """AI Conversation does not accept logins — sign in at the family portal."""
    return JSONResponse(
        {
            "detail": (
                "This app has no login form. Sign in at the Porter Family Portal; "
                "AI Conversation uses that session automatically."
            ),
            "login_url": portal_login_url(),
            "portal_home": "/",
        },
        status_code=410,
    )


@router.post("/logout")
async def logout(request: Request):
    """
    Best-effort clear of portal_session (mirrors portal-admin logout flags).
    Prefer POST /api/portal/auth/logout from the browser when available.
    """
    response = JSONResponse({
        "ok": True,
        "redirect_url": "/",
        "login_url": login_redirect_url(app_home_path()),
        "detail": "Portal session cleared. Sign in again at the family portal if needed.",
    })
    clear_portal_cookie(response)
    return response


@router.get("/me")
async def me(request: Request):
    """
    Return the portal identity for the current browser cookie.
    No AI-specific credentials — only portal_session verification.
    """
    if auth_disabled():
        user = current_portal_user(request)
        return {
            "authenticated": True,
            "auth_disabled": True,
            "auth_mode": "portal-sso",
            "username": user.username if user else "dev",
            "user_id": user.user_id if user else "dev",
            "is_portal_admin": True,
            "app_id": app_id(),
            "role": "admin",
            "is_app_admin": True,
            "grants": user.grants if user else [{"id": app_id(), "role": "admin"}],
        }

    user = current_portal_user(request)
    if not user:
        return {
            "authenticated": False,
            "auth_mode": "portal-sso",
            "username": None,
            "user_id": None,
            "login_url": login_redirect_url(app_home_path()),
            "portal_home": "/",
            "detail": "No portal session. Sign in at the family portal.",
        }

    role = effective_app_role(user)
    return {
        "authenticated": True,
        "auth_disabled": False,
        "auth_mode": "portal-sso",
        "username": user.username,
        "user_id": user.user_id,
        "is_portal_admin": user.is_portal_admin,
        "app_id": app_id(),
        "role": role,
        "is_app_admin": role == "admin",
        "grants": user.grants,
        "must_reset_password": user.must_reset_password,
        "exp": user.exp,
    }


@router.get("/login-url")
async def get_login_url(request: Request):
    """Where to send the browser when there is no portal session."""
    return {
        "login_url": login_redirect_url(app_home_path()),
        "portal_home": "/",
        "detail": "AI Conversation has no login page; use the family portal.",
    }
