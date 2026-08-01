# app/services/auth_store.py
# Purpose: Small allowlist of users with bcrypt password hashes (file or env).

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt

from app.paths import get_data_dir

_lock = threading.RLock()


def users_path() -> Path:
    return get_data_dir() / "users.json"


def _read_users_file() -> List[Dict[str, Any]]:
    path = users_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        users = data.get("users") or []
    elif isinstance(data, list):
        users = data
    else:
        users = []
    return [u for u in users if isinstance(u, dict) and u.get("username")]


def _users_from_env() -> List[Dict[str, Any]]:
    """
    AUTH_USERS JSON array:
      [{"username":"hub","password_hash":"$2b$..."}]
    """
    raw = (os.environ.get("AUTH_USERS") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [u for u in data if isinstance(u, dict) and u.get("username")]


def list_users() -> List[Dict[str, Any]]:
    """Return user records (includes password_hash). Env overrides file if set."""
    with _lock:
        env_users = _users_from_env()
        if env_users:
            return deepcopy(env_users)
        return deepcopy(_read_users_file())


def get_user(username: str) -> Optional[Dict[str, Any]]:
    uname = (username or "").strip().lower()
    if not uname:
        return None
    for u in list_users():
        if str(u.get("username", "")).strip().lower() == uname:
            return u
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def authenticate(username: str, password: str) -> Optional[str]:
    """
    Verify credentials. Returns canonical username on success, else None.
    """
    user = get_user(username)
    if not user:
        try:
            bcrypt.hashpw(b"invalid", bcrypt.gensalt(rounds=4))
        except Exception:
            pass
        return None
    ph = str(user.get("password_hash") or "")
    if not verify_password(password, ph):
        return None
    return str(user.get("username"))


def save_users(users: List[Dict[str, Any]]) -> None:
    """Write users.json (for scripts)."""
    path = users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"users": users}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(path)
