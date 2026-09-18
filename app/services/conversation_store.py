# app/services/conversation_store.py
# Purpose: Persist named conversations to disk for later restore (per portal user).

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.user_context import get_current_user_id, require_user_id
from app.services.user_store import user_conversations_dir

_lock = threading.RLock()
_SAFE_CONV_ID = re.compile(r"^[a-fA-F0-9]{8,64}$")


def sanitize_conv_id(conv_id: str) -> Optional[str]:
    cid = (conv_id or "").strip()
    if not cid or not _SAFE_CONV_ID.match(cid):
        return None
    if ".." in cid or "/" in cid or "\\" in cid:
        return None
    return cid


def _resolve_uid(user_id: Optional[str] = None) -> str:
    uid = (user_id or get_current_user_id() or "").strip()
    if not uid:
        raise RuntimeError("user_id required for conversations")
    return uid


def _conversations_dir(user_id: Optional[str] = None) -> Path:
    return user_conversations_dir(_resolve_uid(user_id))


def _ensure_dir(user_id: Optional[str] = None) -> Path:
    d = _conversations_dir(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "").strip())[:40].strip("-")
    return slug or "conversation"


def _path_for(conv_id: str, user_id: Optional[str] = None) -> Optional[Path]:
    cid = sanitize_conv_id(conv_id)
    if not cid:
        return None
    root = _conversations_dir(user_id).resolve()
    path = (root / f"{cid}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _owned_payload(data: Dict[str, Any], user_id: Optional[str] = None) -> bool:
    owner = data.get("user_id")
    if not owner:
        return True
    return str(owner) == _resolve_uid(user_id)


def list_conversations(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return summary rows newest-first (no full message bodies)."""
    _ensure_dir(user_id)
    rows: List[Dict[str, Any]] = []
    with _lock:
        for path in _conversations_dir(user_id).glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict) or not _owned_payload(data, user_id):
                    continue
                messages = data.get("messages") or []
                rows.append({
                    "id": data.get("id") or path.stem,
                    "name": data.get("name") or "Untitled",
                    "stored_at": data.get("stored_at") or "",
                    "kind": data.get("kind") or "whole",
                    "message_count": data.get("message_count")
                        if data.get("message_count") is not None
                        else len(messages),
                    "preview": _preview(messages),
                })
            except (OSError, json.JSONDecodeError):
                continue
    rows.sort(key=lambda r: r.get("stored_at") or "", reverse=True)
    return rows


def _preview(messages: List[Dict[str, Any]], max_len: int = 120) -> str:
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            text = str(m["content"]).replace("\n", " ").strip()
            if len(text) > max_len:
                return text[: max_len - 1] + "…"
            return text
    return ""


def get_conversation(conv_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = _path_for(conv_id, user_id)
    if not path or not path.exists():
        return None
    with _lock:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    if not isinstance(data, dict) or not _owned_payload(data, user_id):
        return None
    return data


def save_conversation(
    name: str,
    messages: List[Dict[str, Any]],
    kind: str = "whole",
    conv_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("A conversation name is required")
    if not messages:
        raise ValueError("Cannot store an empty conversation")
    if kind not in ("whole", "summary"):
        kind = "whole"

    uid = user_id or require_user_id()
    _ensure_dir(uid)
    if conv_id:
        cid = sanitize_conv_id(conv_id)
        if not cid:
            raise ValueError("Invalid conversation id")
        conv_id = cid
    else:
        conv_id = uuid.uuid4().hex
    stored_at = _now_iso()

    payload = {
        "id": conv_id,
        "user_id": uid,
        "name": name,
        "stored_at": stored_at,
        "kind": kind,
        "message_count": len(messages),
        "messages": messages,
        "slug": _safe_slug(name),
    }

    path = _path_for(conv_id, uid)
    if not path:
        raise ValueError("Invalid conversation id")
    with _lock:
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(path)

    return {
        "id": conv_id,
        "name": name,
        "stored_at": stored_at,
        "kind": kind,
        "message_count": len(messages),
        "preview": _preview(messages),
    }


def delete_conversation(conv_id: str, user_id: Optional[str] = None) -> bool:
    path = _path_for(conv_id, user_id)
    if not path:
        return False
    with _lock:
        if not path.exists():
            return False
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and not _owned_payload(data, user_id):
                return False
        except (OSError, json.JSONDecodeError):
            return False
        path.unlink()
        return True


def build_summary_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Lightweight local summary (no LLM): keep first user turn + short rollup.
    Stored as a short conversation that can still be restored and continued.
    """
    if not messages:
        return []

    first_user = next((m for m in messages if m.get("role") == "user"), None)
    last_assistant = next(
        (m for m in reversed(messages) if m.get("role") == "assistant"),
        None,
    )

    lines = [
        f"Summary of a conversation with {len(messages)} messages.",
    ]
    if first_user:
        content = str(first_user.get("content") or "")[:500]
        lines.append(f"Started with: {content}")
    if last_assistant:
        content = str(last_assistant.get("content") or "")[:500]
        ai = last_assistant.get("ai") or "assistant"
        lines.append(f"Last reply ({ai}): {content}")

    summary_text = "\n\n".join(lines)
    out: List[Dict[str, Any]] = []
    if first_user:
        out.append({"role": "user", "content": first_user.get("content") or ""})
    out.append({
        "role": "assistant",
        "content": summary_text,
        "ai": (last_assistant or {}).get("ai") or "system",
    })
    return out
