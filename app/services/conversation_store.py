# app/services/conversation_store.py
# Purpose: Persist named conversations to disk for later restore.

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.paths import get_data_dir

_lock = threading.RLock()


def _conversations_dir() -> Path:
    return get_data_dir() / "conversations"


def _ensure_dir() -> None:
    _conversations_dir().mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "").strip())[:40].strip("-")
    return slug or "conversation"


def _path_for(conv_id: str) -> Path:
    return _conversations_dir() / f"{conv_id}.json"


def list_conversations() -> List[Dict[str, Any]]:
    """Return summary rows newest-first (no full message bodies)."""
    _ensure_dir()
    rows: List[Dict[str, Any]] = []
    with _lock:
        for path in _conversations_dir().glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
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


def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    path = _path_for(conv_id)
    if not path.exists():
        return None
    with _lock:
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None


def save_conversation(
    name: str,
    messages: List[Dict[str, Any]],
    kind: str = "whole",
    conv_id: Optional[str] = None,
) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("A conversation name is required")
    if not messages:
        raise ValueError("Cannot store an empty conversation")
    if kind not in ("whole", "summary"):
        kind = "whole"

    _ensure_dir()
    conv_id = conv_id or uuid.uuid4().hex
    stored_at = _now_iso()

    payload = {
        "id": conv_id,
        "name": name,
        "stored_at": stored_at,
        "kind": kind,
        "message_count": len(messages),
        "messages": messages,
        "slug": _safe_slug(name),
    }

    path = _path_for(conv_id)
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


def delete_conversation(conv_id: str) -> bool:
    path = _path_for(conv_id)
    with _lock:
        if not path.exists():
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
