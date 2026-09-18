# App-specific portal env helpers. Canonical crypto: portal_sdk.session.

from __future__ import annotations

import os
from typing import Dict, List, Optional
from urllib.parse import quote

from portal_sdk.session import (
    SessionUser,
    issue_session_token,
    session_secret_from_env,
    verify_session_token as _sdk_verify,
)

PortalUser = SessionUser


def auth_disabled() -> bool:
    return (os.environ.get("AUTH_DISABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def portal_session_secret() -> str:
    secret = session_secret_from_env()
    if secret:
        return secret
    if auth_disabled():
        return "dev-only-insecure-portal-session-secret"
    raise RuntimeError(
        "PORTAL_SESSION_SECRET is required when portal SSO is enabled. "
        "Share the same secret as portal-admin, or set AUTH_DISABLED=1 for local dev."
    )


def cookie_name() -> str:
    return (os.environ.get("PORTAL_SESSION_COOKIE") or "portal_session").strip() or "portal_session"


def app_id() -> str:
    return (os.environ.get("APP_ID") or "ai-conversation").strip() or "ai-conversation"


def portal_login_url() -> str:
    return (os.environ.get("PORTAL_LOGIN_URL") or "/admin/login").strip() or "/admin/login"


def app_home_path() -> str:
    """
    Public URL path for this app shell on the family domain.
    Must NOT be '/' — nginx serves the portal at apex '/'.
    """
    path = (os.environ.get("APP_HOME_PATH") or "/chat/").strip() or "/chat/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    return path


def login_redirect_url(return_path: str) -> str:
    base = portal_login_url()
    nxt = return_path or app_home_path()
    if nxt in ("/", ""):
        nxt = app_home_path()
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}next={quote(nxt, safe='')}"


def cookie_domain() -> Optional[str]:
    return (os.environ.get("PORTAL_COOKIE_DOMAIN") or "").strip() or None


def effective_app_role(user: Optional[PortalUser], target_app_id: Optional[str] = None) -> Optional[str]:
    if user is None:
        return None
    aid = (target_app_id or app_id()).strip()
    role = user.grant_for(aid)
    if user.is_portal_admin:
        return "admin"
    return role


def can_use_app(user: Optional[PortalUser], target_app_id: Optional[str] = None) -> bool:
    return effective_app_role(user, target_app_id) is not None


def can_admin_app(user: Optional[PortalUser], target_app_id: Optional[str] = None) -> bool:
    return effective_app_role(user, target_app_id) == "admin"


def verify_session_token(token: str, secret: Optional[str] = None) -> Optional[PortalUser]:
    try:
        sec = secret if secret is not None else portal_session_secret()
    except RuntimeError:
        return None
    if not token or not sec:
        return None
    return _sdk_verify(token, secret=sec)


def issue_dev_token(
    *,
    user_id: str = "dev",
    username: str = "dev",
    role: str = "admin",
    is_portal_admin: bool = True,
    grants: Optional[List[Dict[str, str]]] = None,
    max_age_sec: int = 86400 * 14,
) -> str:
    """Mint a portal_session token (tests / AUTH_DISABLED helpers)."""
    sec = portal_session_secret()
    if grants is None:
        grants_in: List[Dict[str, str]] = [{"app_id": app_id(), "role": role}]
    else:
        grants_in = []
        for g in grants:
            gid = str(g.get("id") or g.get("app_id") or "").strip()
            if not gid:
                continue
            r = str(g.get("role") or "user").strip().lower()
            if r not in ("user", "admin"):
                r = "user"
            grants_in.append({"app_id": gid, "role": r})
    return issue_session_token(
        secret=sec,
        user_id=user_id,
        username=username,
        is_portal_admin=is_portal_admin,
        grants=grants_in,
        max_age_sec=max_age_sec,
    )
