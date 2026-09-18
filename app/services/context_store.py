# app/services/context_store.py
# Purpose: Persist reusable conversation contexts (personas, guidelines, params).

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.user_context import get_current_user_id, require_user_id
from app.services.user_store import user_contexts_path

_lock = threading.RLock()

_DEFAULT_CONTEXTS: List[Dict[str, Any]] = [
    {
        "id": "ctx-professional",
        "name": "Professional assistant",
        "description": "Clear, formal, business-ready answers",
        "content": (
            "You are a professional assistant.\n"
            "Guidelines:\n"
            "- Be clear, concise, and well-structured.\n"
            "- Prefer actionable recommendations.\n"
            "- Avoid slang; use a polite, confident tone.\n"
            "Parameters:\n"
            "- If unsure, say so and list what you need."
        ),
    },
    {
        "id": "ctx-concise",
        "name": "Concise answers",
        "description": "Short replies; bullets over essays",
        "content": (
            "Answer as briefly as possible while remaining correct.\n"
            "Guidelines:\n"
            "- Prefer bullet points and short paragraphs.\n"
            "- Skip filler and long preambles.\n"
            "- Lead with the direct answer, then optional detail."
        ),
    },
    {
        "id": "ctx-coding",
        "name": "Coding expert",
        "description": "Software engineering focus",
        "content": (
            "You are an expert software engineer.\n"
            "Guidelines:\n"
            "- Prefer correct, modern, maintainable code.\n"
            "- Explain trade-offs briefly when relevant.\n"
            "- Call out security and edge cases.\n"
            "- Use fenced code blocks with language tags.\n"
            "Parameters:\n"
            "- Ask for language/runtime only if missing and necessary."
        ),
    },
    {
        "id": "ctx-tutor",
        "name": "Patient tutor",
        "description": "Step-by-step teaching style",
        "content": (
            "You are a patient tutor.\n"
            "Guidelines:\n"
            "- Explain concepts step by step.\n"
            "- Check understanding with a short question when helpful.\n"
            "- Use simple language and examples.\n"
            "- Encourage the learner; avoid shaming mistakes."
        ),
    },
]


def contexts_path(user_id: Optional[str] = None) -> Path:
    uid = user_id or get_current_user_id()
    if not uid:
        raise RuntimeError("user_id required for contexts")
    return user_contexts_path(uid)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (s[:40] or "context")


def _read(user_id: Optional[str] = None) -> Dict[str, Any]:
    path = contexts_path(user_id)
    if not path.exists():
        return {"version": 1, "contexts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "contexts": []}
        if not isinstance(data.get("contexts"), list):
            data["contexts"] = []
        return data
    except Exception:
        return {"version": 1, "contexts": []}


def _write(data: Dict[str, Any], user_id: Optional[str] = None) -> None:
    path = contexts_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_defaults(user_id: Optional[str] = None) -> None:
    """Seed built-in contexts once if the user file is empty/missing."""
    uid = user_id or require_user_id()
    with _lock:
        data = _read(uid)
        if data.get("contexts"):
            return
        now = _now()
        seeded = []
        for c in _DEFAULT_CONTEXTS:
            seeded.append({
                **c,
                "created_at": now,
                "updated_at": now,
                "builtin": True,
            })
        data = {"version": 1, "contexts": seeded}
        _write(data, uid)


def list_contexts(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    uid = user_id or require_user_id()
    ensure_defaults(uid)
    with _lock:
        data = _read(uid)
        items = list(data.get("contexts") or [])
    items.sort(key=lambda c: (str(c.get("name") or "").lower(), str(c.get("id") or "")))
    return items


def get_context(context_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not context_id:
        return None
    uid = user_id or require_user_id()
    ensure_defaults(uid)
    with _lock:
        for c in _read(uid).get("contexts") or []:
            if c.get("id") == context_id:
                return dict(c)
    return None


def create_context(
    *,
    name: str,
    content: str,
    description: str = "",
    context_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    name = (name or "").strip()
    content = (content or "").strip()
    description = (description or "").strip()
    if not name:
        raise ValueError("Name is required")
    if not content:
        raise ValueError("Context content is required")

    uid = user_id or require_user_id()
    ensure_defaults(uid)
    with _lock:
        data = _read(uid)
        contexts = list(data.get("contexts") or [])
        cid = (context_id or "").strip() or f"ctx-{_slug(name)}-{uuid.uuid4().hex[:8]}"
        if any(c.get("id") == cid for c in contexts):
            raise ValueError(f"Context id already exists: {cid}")
        now = _now()
        item = {
            "id": cid,
            "name": name,
            "description": description,
            "content": content,
            "created_at": now,
            "updated_at": now,
            "builtin": False,
        }
        contexts.append(item)
        data["contexts"] = contexts
        _write(data, uid)
        return item


def update_context(
    context_id: str,
    *,
    name: Optional[str] = None,
    content: Optional[str] = None,
    description: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    uid = user_id or require_user_id()
    ensure_defaults(uid)
    with _lock:
        data = _read(uid)
        contexts = list(data.get("contexts") or [])
        idx = next((i for i, c in enumerate(contexts) if c.get("id") == context_id), None)
        if idx is None:
            raise ValueError("Context not found")
        item = dict(contexts[idx])
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Name cannot be empty")
            item["name"] = name
        if content is not None:
            content = content.strip()
            if not content:
                raise ValueError("Content cannot be empty")
            item["content"] = content
        if description is not None:
            item["description"] = description.strip()
        item["updated_at"] = _now()
        contexts[idx] = item
        data["contexts"] = contexts
        _write(data, uid)
        return item


def delete_context(context_id: str, user_id: Optional[str] = None) -> bool:
    uid = user_id or require_user_id()
    ensure_defaults(uid)
    with _lock:
        data = _read(uid)
        contexts = list(data.get("contexts") or [])
        new_list = [c for c in contexts if c.get("id") != context_id]
        if len(new_list) == len(contexts):
            return False
        data["contexts"] = new_list
        _write(data, uid)
        return True
