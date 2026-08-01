# app/services/key_test.py
# Purpose: Probe API keys against their provider endpoints without saving.
#          Many OpenAI-compatible APIs omit GET /models (e.g. Magisterium) —
#          we fall back to a minimal chat/completions request.

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.services.settings_store import get_providers, get_secret


def _providers_for_key(key_name: str) -> List[Dict[str, Any]]:
    return [p for p in get_providers() if p.get("api_key_name") == key_name]


def _chat_model_for_provider(provider: Dict[str, Any]) -> str:
    for m in provider.get("models") or []:
        if (m.get("capability") or "chat") == "chat" and m.get("value"):
            return m["value"]
    models = provider.get("models") or []
    if models and models[0].get("value"):
        return models[0]["value"]
    return "default"


async def test_api_key(
    key_name: str,
    api_key: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    label: Optional[str] = None,
    key_test: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Test a key. Never writes disk / config.

    - api_key: if non-empty, test this value; else use saved/env secret.
    - base_url / model / label / key_test: optional ephemeral overrides so the
      Add API wizard can probe a key *before* the provider is saved.
    """
    key_name = (key_name or "").strip()
    if not key_name:
        return {"ok": False, "key_name": key_name, "message": "Key name is required"}

    value = (api_key or "").strip() or (get_secret(key_name) or "")
    if not value:
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{key_name} is not set. Paste a key and try again (or Save first).",
        }

    # Ephemeral path: wizard provides base_url without saving provider first
    ephemeral_base = (base_url or "").strip().rstrip("/")
    ephemeral_base = ephemeral_base.replace("/chat/completions", "") if ephemeral_base else ""
    if ephemeral_base.endswith("/"):
        ephemeral_base = ephemeral_base.rstrip("/")

    if ephemeral_base:
        return await _test_openai_compatible(
            key_name,
            value,
            ephemeral_base,
            (label or key_name).strip() or key_name,
            model=(model or "default").strip() or "default",
            preferred=(key_test or "auto").lower(),
        )

    providers = _providers_for_key(key_name)

    if key_name == "YOUTUBE_API_KEY" or any(p.get("id") == "youtube" for p in providers):
        return await _test_youtube_key(key_name, value)

    compatible = [
        p for p in providers
        if p.get("type") in (None, "openai_compatible") and p.get("base_url")
    ]
    if not compatible:
        if key_name == "OPENAI_API_KEY":
            return await _test_openai_compatible(
                key_name, value, "https://api.openai.com/v1", "OpenAI", model="gpt-4o-mini"
            )
        if key_name == "XAI_API_KEY":
            return await _test_openai_compatible(
                key_name, value, "https://api.x.ai/v1", "xAI", model="grok-4.5"
            )
        return {
            "ok": False,
            "key_name": key_name,
            "message": (
                f"No test endpoint known for {key_name}. "
                "Provide a base URL (wizard) or save a provider first."
            ),
        }

    p = compatible[0]
    preferred = (key_test or p.get("key_test") or "auto").lower()
    chat_model = (model or "").strip() or _chat_model_for_provider(p)
    return await _test_openai_compatible(
        key_name,
        value,
        p.get("base_url"),
        (label or p.get("label") or p.get("id") or key_name),
        model=chat_model,
        preferred=preferred,
    )


async def _test_openai_compatible(
    key_name: str,
    api_key: str,
    base_url: str,
    label: str,
    model: str = "default",
    preferred: str = "auto",
) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 1) Prefer GET /models when requested or auto
    if preferred in ("auto", "models"):
        models_result = await _probe_models(base, headers, label, key_name)
        if models_result["ok"]:
            return models_result
        # 404/405 → many providers only expose chat; fall through unless forced models
        if preferred == "models":
            return models_result
        status = models_result.get("status_code")
        if status not in (404, 405, 501):
            # Auth failures etc. are definitive
            if status in (401, 403):
                return models_result
            # Still try chat for other odd statuses
        # else fall through to chat

    # 2) Minimal chat/completions (works for Magisterium, many gateways)
    return await _probe_chat(base, headers, label, key_name, model)


async def _probe_models(
    base: str,
    headers: Dict[str, str],
    label: str,
    key_name: str,
) -> Dict[str, Any]:
    url = f"{base}/models"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            count = None
            if isinstance(data, dict):
                items = data.get("data") or data.get("models") or []
                if isinstance(items, list):
                    count = len(items)
            msg = f"{label}: key works (GET /models)"
            if count is not None:
                msg += f" — {count} models listed"
            return {
                "ok": True,
                "key_name": key_name,
                "message": msg,
                "status_code": r.status_code,
                "method": "models",
            }

        body = (r.text or "")[:240]
        hint = {
            401: "Unauthorized — key invalid or revoked",
            403: "Forbidden — key lacks permission",
            404: "No /models endpoint (will try chat)",
            405: "GET /models not allowed (will try chat)",
            429: "Rate limited — key may still be valid",
        }.get(r.status_code, "Request failed")
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{label}: {hint} (HTTP {r.status_code})",
            "status_code": r.status_code,
            "detail": body,
            "method": "models",
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{label}: timed out contacting {url}",
            "method": "models",
        }
    except Exception as e:
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{label}: connection error — {e}",
            "method": "models",
        }


async def _probe_chat(
    base: str,
    headers: Dict[str, str],
    label: str,
    key_name: str,
    model: str,
) -> Dict[str, Any]:
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(url, headers=headers, json=payload)

        if r.status_code == 200:
            return {
                "ok": True,
                "key_name": key_name,
                "message": f"{label}: key works (chat/completions with model `{model}`)",
                "status_code": 200,
                "method": "chat",
            }

        body = (r.text or "")[:300]
        # Common failure modes
        if r.status_code in (401, 403):
            hint = "Unauthorized — key invalid, expired, or wrong"
        elif r.status_code == 404:
            hint = "Chat endpoint not found — base URL is wrong"
        elif r.status_code == 400:
            # Often wrong model id but key is valid
            lower = body.lower()
            if "model" in lower:
                return {
                    "ok": True,
                    "key_name": key_name,
                    "message": (
                        f"{label}: key is accepted, but model `{model}` may be wrong "
                        f"(HTTP 400). Update the model id under Admin → Models."
                    ),
                    "status_code": 400,
                    "detail": body,
                    "method": "chat",
                    "warning": True,
                }
            hint = "Bad request — check model id / payload"
        elif r.status_code == 429:
            return {
                "ok": True,
                "key_name": key_name,
                "message": f"{label}: rate limited (HTTP 429) — key is likely valid",
                "status_code": 429,
                "method": "chat",
                "warning": True,
            }
        else:
            hint = "Request failed"

        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{label}: {hint} (HTTP {r.status_code})",
            "status_code": r.status_code,
            "detail": body,
            "method": "chat",
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{label}: timed out on chat/completions (server may be slow)",
            "method": "chat",
        }
    except Exception as e:
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"{label}: connection error — {e}",
            "method": "chat",
        }


async def _test_youtube_key(key_name: str, api_key: str) -> Dict[str, Any]:
    """YouTube Data API key check (transcripts often work without a key)."""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "id",
        "id": "dQw4w9WgXcQ",
        "key": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params=params)
        if r.status_code == 200:
            return {
                "ok": True,
                "key_name": key_name,
                "message": "YouTube Data API: key works (note: public captions often work without a key)",
                "status_code": 200,
            }
        body = (r.text or "")[:240]
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"YouTube Data API: failed (HTTP {r.status_code})",
            "status_code": r.status_code,
            "detail": body,
        }
    except Exception as e:
        return {
            "ok": False,
            "key_name": key_name,
            "message": f"YouTube: connection error — {e}",
        }
