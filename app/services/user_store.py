# app/services/user_store.py
# Purpose: Local profile + per-user data directories keyed by portal user_id.

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.paths import get_data_dir

_lock = threading.RLock()
_SAFE_UID = re.compile(r"^[a-zA-Z0-9_.:@-]{1,128}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").strip()
    if not uid or not _SAFE_UID.match(uid):
        raise ValueError(f"Invalid user_id for data path: {user_id!r}")
    if ".." in uid or "/" in uid or "\\" in uid:
        raise ValueError(f"Invalid user_id for data path: {user_id!r}")
    return uid


def users_root() -> Path:
    return get_data_dir() / "users"


def user_dir(user_id: str) -> Path:
    return users_root() / sanitize_user_id(user_id)


def user_conversations_dir(user_id: str) -> Path:
    return user_dir(user_id) / "conversations"


def user_media_dir(user_id: str) -> Path:
    return user_dir(user_id) / "media"


def user_contexts_path(user_id: str) -> Path:
    return user_dir(user_id) / "contexts.json"


def user_preferences_path(user_id: str) -> Path:
    return user_dir(user_id) / "preferences.json"


def user_profile_path(user_id: str) -> Path:
    return user_dir(user_id) / "profile.json"


def ensure_user_dirs(user_id: str) -> Path:
    root = user_dir(user_id)
    with _lock:
        root.mkdir(parents=True, exist_ok=True)
        (root / "conversations").mkdir(exist_ok=True)
        (root / "media").mkdir(exist_ok=True)
    return root


def upsert_profile(user_id: str, username: str, *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create local profile on first authenticated request; update username if renamed
    in portal. Avoid rewriting profile.json on every request.
    """
    ensure_user_dirs(user_id)
    path = user_profile_path(user_id)
    uname = (username or "").strip() or user_id
    with _lock:
        profile: Dict[str, Any] = {}
        if path.exists():
            try:
                profile = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(profile, dict):
                    profile = {}
            except Exception:
                profile = {}

        need_write = not path.exists() or not profile
        if extra:
            need_write = True
        if profile.get("username") != uname:
            need_write = True
        if profile.get("user_id") != sanitize_user_id(user_id):
            need_write = True

        if not need_write:
            return profile

        now = _now()
        profile["user_id"] = sanitize_user_id(user_id)
        profile["username"] = uname
        profile["updated_at"] = now
        if not profile.get("created_at"):
            profile["created_at"] = now
        if extra:
            profile.update(extra)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return profile


def _default_preferences() -> Dict[str, Any]:
    return {
        "theme": "light",
        "default_ai": "grok",
        "default_model": "grok-4.6",
        "tts_voice": "eve",
        "tts_language": "en",
    }


def current_user_preferences() -> Dict[str, Any]:
    """Preferences for the request-scoped portal user (defaults if no user)."""
    from app.core.user_context import get_current_user_id

    uid = get_current_user_id()
    if not uid:
        return _default_preferences()
    return get_user_preferences(uid)


def get_user_preferences(user_id: str) -> Dict[str, Any]:
    path = user_preferences_path(user_id)
    defaults = _default_preferences()
    if not path.exists():
        return dict(defaults)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(defaults)
        return {**defaults, **data}
    except Exception:
        return dict(defaults)


def save_user_preferences(user_id: str, prefs: Dict[str, Any]) -> Dict[str, Any]:
    ensure_user_dirs(user_id)
    path = user_preferences_path(user_id)
    with _lock:
        current = get_user_preferences(user_id)
        merged = {**current, **{k: v for k, v in prefs.items() if v is not None}}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return merged


def legacy_owner_user_id() -> Optional[str]:
    """
    Portal user_id that should inherit flat (pre-SSO) data.
    Env: PORTAL_LEGACY_OWNER_USER_ID
    """
    return (os.environ.get("PORTAL_LEGACY_OWNER_USER_ID") or "").strip() or None


def migrate_legacy_data_if_needed(user_id: str) -> Dict[str, Any]:
    """
    One-time move of flat conversations/media/contexts into users/{user_id}/
    when this user is the designated legacy owner.
    """
    owner = legacy_owner_user_id()
    if not owner or owner != user_id:
        return {"migrated": False, "reason": "not_legacy_owner"}

    data = get_data_dir()
    marker = user_dir(user_id) / ".legacy_migrated"
    if marker.exists():
        return {"migrated": False, "reason": "already_done"}

    ensure_user_dirs(user_id)
    result = {
        "migrated": True,
        "conversations": 0,
        "media": 0,
        "contexts": False,
        "preferences": False,
    }

    with _lock:
        # Conversations: data/conversations/*.json → users/{uid}/conversations/
        legacy_conv = data / "conversations"
        dest_conv = user_conversations_dir(user_id)
        if legacy_conv.is_dir():
            for path in legacy_conv.glob("*.json"):
                target = dest_conv / path.name
                if not target.exists():
                    shutil.move(str(path), str(target))
                    result["conversations"] += 1

        # Media: data/media/* → users/{uid}/media/
        legacy_media = data / "media"
        dest_media = user_media_dir(user_id)
        if legacy_media.is_dir():
            for path in legacy_media.iterdir():
                if path.is_file():
                    target = dest_media / path.name
                    if not target.exists():
                        shutil.move(str(path), str(target))
                        result["media"] += 1

        # Contexts: prefer user file; move global if user has none
        legacy_ctx = data / "contexts.json"
        dest_ctx = user_contexts_path(user_id)
        if legacy_ctx.is_file() and not dest_ctx.exists():
            shutil.move(str(legacy_ctx), str(dest_ctx))
            result["contexts"] = True

        # Preferences: copy global prefs into user prefs once
        legacy_prefs = data / "preferences.json"
        dest_prefs = user_preferences_path(user_id)
        if legacy_prefs.is_file() and not dest_prefs.exists():
            try:
                data_prefs = json.loads(legacy_prefs.read_text(encoding="utf-8"))
                if isinstance(data_prefs, dict):
                    save_user_preferences(user_id, data_prefs)
                    result["preferences"] = True
            except Exception:
                pass

        marker.write_text(
            json.dumps({"at": _now(), "result": result}, indent=2) + "\n",
            encoding="utf-8",
        )

    return result
