# app/core/user_context.py
# Purpose: Request-scoped portal user via contextvars for stores/handlers.

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.portal_session import PortalUser

_current_user: ContextVar[Optional["PortalUser"]] = ContextVar("portal_user", default=None)


def set_current_user(user: Optional["PortalUser"]) -> None:
    _current_user.set(user)


def get_current_user() -> Optional["PortalUser"]:
    return _current_user.get()


def get_current_user_id() -> Optional[str]:
    user = _current_user.get()
    return user.user_id if user else None


def require_user_id() -> str:
    uid = get_current_user_id()
    if not uid:
        raise RuntimeError("No authenticated user in context")
    return uid
