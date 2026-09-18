# tests/test_portal_sso.py
# Purpose: Portal SSO auth gate + per-user conversation isolation.

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate data before app import
_TEST_DATA = ROOT / "tests" / "_sso_data"
os.environ["AI_HUB_DATA_DIR"] = str(_TEST_DATA)
os.environ["AUTH_DISABLED"] = "0"
os.environ["PORTAL_SESSION_SECRET"] = "test-portal-secret-for-sso-unit-tests"
os.environ["PORTAL_LOGIN_URL"] = "/admin/login"
os.environ["APP_ID"] = "ai-conversation"
os.environ["APP_HOME_PATH"] = "/chat/"
os.environ.pop("PORTAL_LEGACY_OWNER_USER_ID", None)


def _token(
    user_id: str,
    username: str,
    role: str = "user",
    *,
    grants=None,
    is_portal_admin: bool = False,
) -> str:
    from app.core.portal_session import issue_dev_token

    return issue_dev_token(
        user_id=user_id,
        username=username,
        role=role,
        is_portal_admin=is_portal_admin,
        grants=grants,
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AI_HUB_DATA_DIR", str(data))
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("PORTAL_SESSION_SECRET", "test-portal-secret-for-sso-unit-tests")
    monkeypatch.setenv("APP_ID", "ai-conversation")
    monkeypatch.setenv("APP_HOME_PATH", "/chat/")
    monkeypatch.delenv("PORTAL_LEGACY_OWNER_USER_ID", raising=False)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    from app.main import app

    return TestClient(app, raise_server_exceptions=True), data


def test_health_public(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_login_helper_redirects_to_portal(client):
    c, _ = client
    r = c.get("/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers.get("location") or ""
    assert "/admin/login" in loc
    assert "chat" in loc or "%2Fchat" in loc


def test_no_cookie_redirects_html(client):
    c, _ = client
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers.get("location") or ""
    assert "login" in loc
    assert "next=" in loc
    # Prefer chat home, never leave next as bare portal apex when path is /
    assert "chat" in loc or "%2Fchat" in loc or "/chat" in loc


def test_no_cookie_api_401(client):
    c, _ = client
    r = c.get("/api/v1/conversations")
    assert r.status_code == 401
    body = r.json()
    assert "login_url" in body or body.get("detail")


def test_no_grant_403(client):
    c, _ = client
    tok = _token(
        "u-nogrant",
        "nogrant",
        grants=[{"id": "other-app", "role": "user"}],
    )
    r = c.get("/api/v1/conversations", cookies={"portal_session": tok})
    assert r.status_code == 403


def test_conversations_isolated(client):
    c, data = client
    t_a = _token("user-a", "alice", role="user")
    t_b = _token("user-b", "bob", role="user")

    r = c.post(
        "/api/v1/conversations",
        cookies={"portal_session": t_a},
        json={
            "name": "Alice chat",
            "kind": "whole",
            "messages": [{"role": "user", "content": "hello from alice"}],
        },
    )
    assert r.status_code == 200, r.text
    alice_id = r.json()["conversation"]["id"]

    r = c.post(
        "/api/v1/conversations",
        cookies={"portal_session": t_b},
        json={
            "name": "Bob chat",
            "kind": "whole",
            "messages": [{"role": "user", "content": "hello from bob"}],
        },
    )
    assert r.status_code == 200
    bob_id = r.json()["conversation"]["id"]

    la = c.get("/api/v1/conversations", cookies={"portal_session": t_a}).json()["conversations"]
    lb = c.get("/api/v1/conversations", cookies={"portal_session": t_b}).json()["conversations"]
    ids_a = {x["id"] for x in la}
    ids_b = {x["id"] for x in lb}
    assert alice_id in ids_a and bob_id not in ids_a
    assert bob_id in ids_b and alice_id not in ids_b

    r = c.get(f"/api/v1/conversations/{alice_id}", cookies={"portal_session": t_b})
    assert r.status_code == 404

    assert (data / "users" / "user-a" / "conversations" / f"{alice_id}.json").is_file()
    assert (data / "users" / "user-b" / "conversations" / f"{bob_id}.json").is_file()
    assert (data / "users" / "user-a" / "profile.json").is_file()


def test_me_reflects_portal_identity(client):
    c, _ = client
    tok = _token("uid-9", "carol", role="admin")
    r = c.get("/api/v1/auth/me", cookies={"portal_session": tok})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["user_id"] == "uid-9"
    assert body["username"] == "carol"
    assert body["role"] == "admin"
    assert body["is_app_admin"] is True


def test_admin_requires_admin_role(client):
    c, _ = client
    tok = _token("user-c", "carol", role="user")
    r = c.get("/api/v1/hub/providers", cookies={"portal_session": tok})
    assert r.status_code == 403

    r = c.get("/api/v1/hub/catalog", cookies={"portal_session": tok})
    assert r.status_code == 200
    assert "providers" in r.json()
    assert "preferences" in r.json()


def test_preferences_are_per_user(client):
    c, data = client
    t_a = _token("pref-a", "alice", role="user")
    t_b = _token("pref-b", "bob", role="user")

    r = c.put(
        "/api/v1/hub/preferences",
        cookies={"portal_session": t_a},
        json={"theme": "dark", "tts_voice": "ara"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["theme"] == "dark"

    ra = c.get("/api/v1/hub/preferences", cookies={"portal_session": t_a}).json()
    rb = c.get("/api/v1/hub/preferences", cookies={"portal_session": t_b}).json()
    assert ra["theme"] == "dark"
    assert ra["tts_voice"] == "ara"
    assert rb.get("theme") != "dark" or rb.get("tts_voice") != "ara"
    # Bob never saved dark/ara — defaults
    assert rb["theme"] == "light"
    assert (data / "users" / "pref-a" / "preferences.json").is_file()
    assert not (data / "users" / "pref-b" / "preferences.json").is_file()


def test_local_login_gone(client):
    c, _ = client
    r = c.post("/api/v1/auth/login", json={"username": "hub", "password": "x"})
    assert r.status_code == 410


def test_portal_admin_without_grant_can_enter(client):
    c, _ = client
    tok = _token(
        "portal-admin-1",
        "owner",
        grants=[],
        is_portal_admin=True,
    )
    r = c.get("/api/v1/conversations", cookies={"portal_session": tok})
    assert r.status_code == 200
    me = c.get("/api/v1/auth/me", cookies={"portal_session": tok}).json()
    assert me["is_app_admin"] is True


def test_no_profile_without_grant(client):
    c, data = client
    tok = _token(
        "no-access",
        "locked",
        grants=[{"id": "other", "role": "user"}],
    )
    r = c.get("/", cookies={"portal_session": tok}, follow_redirects=False)
    assert r.status_code in (302, 403)
    assert not (data / "users" / "no-access").exists()


def test_cannot_delete_other_users_conversation(client):
    c, _ = client
    t_a = _token("del-a", "alice", role="user")
    t_b = _token("del-b", "bob", role="user")
    r = c.post(
        "/api/v1/conversations",
        cookies={"portal_session": t_a},
        json={
            "name": "Alice private",
            "kind": "whole",
            "messages": [{"role": "user", "content": "secret from alice"}],
        },
    )
    assert r.status_code == 200
    alice_id = r.json()["conversation"]["id"]

    r = c.delete(f"/api/v1/conversations/{alice_id}", cookies={"portal_session": t_b})
    assert r.status_code == 404
    r = c.get(f"/api/v1/conversations/{alice_id}", cookies={"portal_session": t_a})
    assert r.status_code == 200
    assert "secret from alice" in r.json()["messages"][0]["content"]


def test_conversation_path_traversal_rejected(client):
    c, _ = client
    t_a = _token("trav-a", "alice", role="user")
    t_b = _token("trav-b", "bob", role="user")
    r = c.post(
        "/api/v1/conversations",
        cookies={"portal_session": t_a},
        json={
            "name": "Alice hidden",
            "kind": "whole",
            "messages": [{"role": "user", "content": "do not leak"}],
        },
    )
    assert r.status_code == 200
    alice_id = r.json()["conversation"]["id"]

    probes = [
        f"../trav-a/conversations/{alice_id}",
        f"..%2Ftrav-a%2Fconversations%2F{alice_id}",
        f"..%2F..%2Fconversations%2F{alice_id}",
        alice_id + "/../" + alice_id,
        "not-a-hex-id",
        "../../etc/passwd",
    ]
    for probe in probes:
        r = c.get(f"/api/v1/conversations/{probe}", cookies={"portal_session": t_b})
        assert r.status_code in (404, 422), probe
        if r.status_code == 200:
            assert "do not leak" not in r.text


def test_mismatched_payload_user_id_is_hidden(client):
    c, data = client
    t_a = _token("own-a", "alice", role="user")
    c.get("/api/v1/conversations", cookies={"portal_session": t_a})
    conv_id = "aabbccddeeff00112233445566778899"
    path = data / "users" / "own-a" / "conversations" / f"{conv_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"id":"%s","user_id":"someone-else","name":"leaked","messages":'
        '[{"role":"user","content":"should not list"}]}' % conv_id,
        encoding="utf-8",
    )
    listed = c.get("/api/v1/conversations", cookies={"portal_session": t_a}).json()["conversations"]
    assert conv_id not in {x["id"] for x in listed}
    r = c.get(f"/api/v1/conversations/{conv_id}", cookies={"portal_session": t_a})
    assert r.status_code == 404
    r = c.delete(f"/api/v1/conversations/{conv_id}", cookies={"portal_session": t_a})
    assert r.status_code == 404
    assert path.is_file()


def test_contexts_isolated(client):
    c, _ = client
    t_a = _token("ctx-a", "alice", role="user")
    t_b = _token("ctx-b", "bob", role="user")
    r = c.post(
        "/api/v1/contexts",
        cookies={"portal_session": t_a},
        json={"name": "Alice persona", "content": "You know Alice secrets."},
    )
    assert r.status_code == 200, r.text
    cid = r.json()["context"]["id"]

    la = c.get("/api/v1/contexts", cookies={"portal_session": t_a}).json()["contexts"]
    lb = c.get("/api/v1/contexts", cookies={"portal_session": t_b}).json()["contexts"]
    assert any(x["id"] == cid for x in la)
    assert all(x["id"] != cid for x in lb)
    r = c.get(f"/api/v1/contexts/{cid}", cookies={"portal_session": t_b})
    assert r.status_code == 404


def test_media_isolated(client):
    c, data = client
    t_a = _token("media-a", "alice", role="user")
    t_b = _token("media-b", "bob", role="user")
    c.get("/api/v1/conversations", cookies={"portal_session": t_a})
    c.get("/api/v1/conversations", cookies={"portal_session": t_b})
    mid = "aabbccddeeff00112233445566778899"
    media_dir = data / "users" / "media-a" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / f"{mid}.mp3").write_bytes(b"ID3fake")
    (media_dir / f"{mid}.ctype").write_text("audio/mpeg", encoding="utf-8")

    r = c.get(f"/api/v1/media/{mid}.mp3", cookies={"portal_session": t_a})
    assert r.status_code == 200
    r = c.get(f"/api/v1/media/{mid}.mp3", cookies={"portal_session": t_b})
    assert r.status_code == 404


def test_index_html_is_not_cached(client):
    c, _ = client
    tok = _token("cache-a", "alice", role="user")
    r = c.get("/", cookies={"portal_session": tok})
    assert r.status_code == 200
    cc = (r.headers.get("cache-control") or "").lower()
    assert "no-store" in cc or "no-cache" in cc
    html = r.text
    assert 'id="portal-chrome"' in html
    assert "portal-app.css" in html
