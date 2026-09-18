# tests/test_user_storage.py
# Purpose: Contract for per-user localStorage keys (mirrors frontend/js/user_storage.js).

from __future__ import annotations

import json

import pytest

from app.services.conversation_store import sanitize_conv_id


def storage_key(user_id: str, name: str) -> str:
    uid = (user_id or "").strip()
    suffix = (name or "").strip()
    if not uid:
        raise ValueError("user_id required for storage key")
    if not suffix or ":" in suffix:
        raise ValueError("invalid storage suffix")
    return f"ai-hub:{uid}:{suffix}"


def parse_live_chat(raw, user_id: str, *, allow_bare_array: bool = False):
    uid = (user_id or "").strip()
    if not uid or not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return parsed if allow_bare_array else []
    if (
        isinstance(parsed, dict)
        and parsed.get("user_id") == uid
        and isinstance(parsed.get("messages"), list)
    ):
        return parsed["messages"]
    return []


def serialize_live_chat(user_id: str, messages):
    return json.dumps({"user_id": user_id, "messages": list(messages)})


LEGACY_UNSCOPED = [
    "ai-conversation-hub-current-chat",
    "ai-conversation-hub-selected-ai",
    "ai-conversation-hub-selected-model",
    "ai-conversation-hub-theme",
    "ai-conversation-hub-selected-context",
]


def test_storage_key_namespaces_by_user():
    ka = storage_key("user-a", "chat")
    kb = storage_key("user-b", "chat")
    assert ka != kb
    assert ka.startswith("ai-hub:user-a:")
    assert kb.startswith("ai-hub:user-b:")
    assert storage_key("user-a", "chat") != storage_key("user-a", "ai")


def test_storage_key_rejects_empty_uid():
    with pytest.raises(ValueError):
        storage_key("", "chat")


def test_parse_live_chat_refuses_other_user_envelope():
    raw = serialize_live_chat("admin", [{"role": "user", "content": "admin secret"}])
    assert parse_live_chat(raw, "family-kid") == []
    assert parse_live_chat(raw, "admin")[0]["content"] == "admin secret"


def test_parse_live_chat_refuses_unscoped_array_by_default():
    raw = json.dumps([{"role": "user", "content": "admin leftover"}])
    assert parse_live_chat(raw, "family-kid") == []
    assert parse_live_chat(raw, "family-kid", allow_bare_array=True)[0]["content"] == "admin leftover"


def test_legacy_unscoped_keys_are_not_namespaced():
    namespaced = storage_key("abc", "chat")
    for key in LEGACY_UNSCOPED:
        assert key != namespaced
        assert not key.startswith("ai-hub:")


LEGACY_CHAT = "ai-conversation-hub-current-chat"
SHOWN_UID_KEY = "ai-hub:shown-uid"


def wipe_foreign_live_chats(store: dict, keep_user_id: str | None) -> dict:
    keep = (keep_user_id or "").strip()
    remove = list(LEGACY_UNSCOPED)
    for key in list(store):
        if key.startswith("ai-hub:") and key.endswith(":chat"):
            uid = key[len("ai-hub:") : -len(":chat")]
            if not keep or uid != keep:
                remove.append(key)
    for key in remove:
        store.pop(key, None)
    if not keep:
        store.pop(SHOWN_UID_KEY, None)
    return store


def should_restore_live_chat(uid: str, *, shown: str | None, login: str | None) -> bool:
    u = (uid or "").strip()
    if not u:
        return False
    if not shown or shown != u:
        return False
    if login and login != u:
        return False
    return True


def test_wipe_foreign_live_chats_keeps_only_current_user():
    store = {
        LEGACY_CHAT: json.dumps([{"role": "user", "content": "admin leftover"}]),
        storage_key("admin", "chat"): serialize_live_chat("admin", [{"role": "user", "content": "admin"}]),
        storage_key("bill", "chat"): serialize_live_chat("bill", [{"role": "user", "content": "bill"}]),
        storage_key("admin", "theme"): "dark",
        storage_key("bill", "ai"): "grok",
    }
    wipe_foreign_live_chats(store, "bill")
    assert LEGACY_CHAT not in store
    assert storage_key("admin", "chat") not in store
    assert storage_key("bill", "chat") in store
    assert store[storage_key("admin", "theme")] == "dark"
    assert store[storage_key("bill", "ai")] == "grok"


def test_wipe_all_live_chats_on_logout():
    store = {
        LEGACY_CHAT: "[]",
        storage_key("admin", "chat"): "{}",
        storage_key("bill", "chat"): "{}",
        SHOWN_UID_KEY: "admin",
    }
    wipe_foreign_live_chats(store, None)
    assert LEGACY_CHAT not in store
    assert storage_key("admin", "chat") not in store
    assert storage_key("bill", "chat") not in store
    assert SHOWN_UID_KEY not in store


def test_live_chat_is_not_auto_restored_after_login():
    """Page load must not paint another user's cached transcript."""
    assert should_restore_live_chat("bill", shown="admin", login="bill") is False
    assert should_restore_live_chat("bill", shown=None, login="bill") is False


def test_should_restore_live_chat_only_same_shown_user():
    assert should_restore_live_chat("bill", shown="bill", login="bill") is True
    assert should_restore_live_chat("bill", shown="admin", login="bill") is False
    assert should_restore_live_chat("bill", shown=None, login="bill") is False
    assert should_restore_live_chat("bill", shown="bill", login="admin") is False
    assert should_restore_live_chat("", shown="bill", login="bill") is False


def test_sanitize_conv_id_rejects_traversal():
    assert sanitize_conv_id("aabbccddeeff00112233445566778899")
    assert sanitize_conv_id("../other/conversations/aabb") is None
    assert sanitize_conv_id("..%2Fsecret") is None
    assert sanitize_conv_id("not hex") is None
    assert sanitize_conv_id("") is None
    assert sanitize_conv_id("aabb/cc") is None
