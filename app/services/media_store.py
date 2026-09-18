# app/services/media_store.py
# Purpose: Persist generated media (TTS audio, etc.) per portal user.

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path
from typing import Optional, Tuple

from app.core.user_context import get_current_user_id, require_user_id
from app.services.user_store import user_media_dir

_lock = threading.RLock()

_SAFE_ID = re.compile(r"^[a-f0-9]{8,64}$", re.I)

_EXT_FOR_CT = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/flac": ".flac",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _media_dir(user_id: Optional[str] = None) -> Path:
    uid = user_id or get_current_user_id()
    if not uid:
        raise RuntimeError("user_id required for media")
    return user_media_dir(uid)


def _ensure_dir(user_id: Optional[str] = None) -> Path:
    d = _media_dir(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_media(
    data: bytes,
    content_type: str = "audio/mpeg",
    user_id: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Write bytes to disk. Returns (media_id, public_path) where public_path is
    like /api/v1/media/{id}.mp3 for the chat player.
    """
    if not data:
        raise ValueError("Empty media payload")
    uid = user_id or require_user_id()
    ct = (content_type or "audio/mpeg").split(";")[0].strip().lower() or "audio/mpeg"
    ext = _EXT_FOR_CT.get(ct, ".bin")
    media_id = uuid.uuid4().hex
    root = _ensure_dir(uid)
    path = root / f"{media_id}{ext}"
    with _lock:
        path.write_bytes(data)
        (root / f"{media_id}.ctype").write_text(ct, encoding="utf-8")
    public = f"/api/v1/media/{media_id}{ext}"
    return media_id, public


def resolve_media_file(
    token: str,
    user_id: Optional[str] = None,
) -> Optional[Tuple[Path, str]]:
    """
    Resolve a media token or filename to (path, content_type) for this user.
    """
    name = (token or "").strip().lstrip("/")
    if not name or ".." in name or "/" in name or "\\" in name:
        return None

    uid = user_id or get_current_user_id()
    if not uid:
        return None

    root = _ensure_dir(uid)

    stem = name
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        if not _SAFE_ID.match(stem):
            return None
        candidate = root / f"{stem}.{ext}"
        if candidate.is_file():
            ct = _read_ctype(root, stem) or _ct_from_ext(ext)
            return candidate, ct
        return None

    if not _SAFE_ID.match(stem):
        return None

    for ext in (".mp3", ".wav", ".ogg", ".webm", ".m4a", ".flac", ".mp4", ".bin"):
        candidate = root / f"{stem}{ext}"
        if candidate.is_file():
            ct = _read_ctype(root, stem) or _ct_from_ext(ext.lstrip("."))
            return candidate, ct
    return None


def _read_ctype(root: Path, stem: str) -> Optional[str]:
    p = root / f"{stem}.ctype"
    if p.is_file():
        try:
            return p.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


def _ct_from_ext(ext: str) -> str:
    e = (ext or "").lower().lstrip(".")
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "webm": "audio/webm",
        "m4a": "audio/mp4",
        "flac": "audio/flac",
        "mp4": "video/mp4",
    }.get(e, "application/octet-stream")
