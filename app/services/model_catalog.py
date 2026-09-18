# app/services/model_catalog.py
# Purpose: Auto-update model lists from OpenAI / xAI APIs (and heuristics).

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.services.settings_store import get_provider, get_secret, set_provider_models

# Noise / non-picker models. Keep whisper, tts, sora — those are roster slots.
OPENAI_SKIP_PREFIXES = (
    "text-embedding",
    "davinci",
    "babbage",
    "omni-moderation",
    "text-moderation",
    "gpt-realtime",
    "gpt-audio",
    "gpt-live",
    "computer-use",
)

OPENAI_KEEP_PREFIXES = (
    "gpt-",
    "o1",
    "o3",
    "o4",
    "chatgpt",
    "dall-e",
    "whisper",
    "tts-",
    "sora",
)

XAI_IMAGE_MARKERS = ("imagine-image", "image", "flux")
OPENAI_IMAGE_MARKERS = ("dall-e", "gpt-image", "image")


def _capability_for(model_id: str, source: str) -> str:
    mid = (model_id or "").lower()
    if "sora" in mid or "imagine-video" in mid or ("video" in mid and "imagine" in mid):
        return "video"
    if any(tok in mid for tok in ("whisper", "-stt", "transcribe", "speech-to-text")):
        return "stt"
    if mid.startswith("tts-") or mid.endswith("-tts") or "text-to-speech" in mid:
        return "tts"
    if source == "openai":
        if "vision" not in mid and any(m in mid for m in OPENAI_IMAGE_MARKERS):
            return "image"
    if source == "xai":
        if "imagine-image" in mid or (mid.endswith("-image") and "vision" not in mid):
            return "image"
        if "image" in mid and "vision" not in mid and "imagine" in mid:
            return "image"
    return "chat"


def _label_from_id(model_id: str) -> str:
    return model_id.replace("-", " ").replace(".", " ").title()


def _filter_openai_models(ids: List[str]) -> List[str]:
    out = []
    for mid in ids:
        if any(mid.startswith(p) for p in OPENAI_SKIP_PREFIXES):
            continue
        if mid.startswith(OPENAI_KEEP_PREFIXES) or "gpt-image" in mid:
            out.append(mid)
    return sorted(set(out))


def _filter_xai_models(ids: List[str]) -> List[str]:
    out = []
    for mid in ids:
        if mid.startswith("grok") or "imagine" in mid:
            out.append(mid)
    return sorted(set(out))


async def fetch_openai_models(api_key: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        r.raise_for_status()
        data = r.json()
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    ids = _filter_openai_models(ids)
    models = []
    for mid in ids:
        cap = _capability_for(mid, "openai")
        models.append({
            "value": mid,
            "label": _label_from_id(mid),
            "tooltip": f"OpenAI model `{mid}` (auto-updated)",
            "capability": cap,
        })
    return models


async def fetch_xai_models(api_key: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        r.raise_for_status()
        data = r.json()
    # xAI may return {data: [...]} or {models: [...]}
    raw = data.get("data") or data.get("models") or []
    ids = []
    for m in raw:
        if isinstance(m, str):
            ids.append(m)
        elif isinstance(m, dict):
            mid = m.get("id") or m.get("name")
            if mid:
                ids.append(mid)
    ids = _filter_xai_models(ids)
    models = []
    for mid in ids:
        cap = _capability_for(mid, "xai")
        models.append({
            "value": mid,
            "label": _label_from_id(mid),
            "tooltip": f"xAI model `{mid}` (auto-updated)",
            "capability": cap,
        })
    return models


def _version_tuple(model_id: str) -> Tuple[int, ...]:
    """Extract numeric version chunks from a model id (e.g. grok-4.5 → (4, 5))."""
    mid = (model_id or "").lower()
    nums = re.findall(r"(\d+)", mid)
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def score_chat_model(model_id: str) -> Tuple[int, ...]:
    """
    Higher score = better default flagship candidate.
    Prefers higher version numbers; demotes specialty variants.
    """
    mid = (model_id or "").lower()
    score = 100
    # Specialty / non-default demotions
    for token, pen in (
        ("reasoning", -20),
        ("non-reasoning", -5),
        ("multi-agent", -15),
        ("build", -10),
        ("mini", -25),
        ("nano", -30),
        ("preview", -8),
        ("legacy", -40),
        ("instruct", -5),
    ):
        if token in mid:
            score += pen
    # Prefer clear flagship families
    if mid.startswith("grok-"):
        score += 50
    if mid.startswith("gpt-"):
        score += 40
    if "flagship" in mid:
        score += 10
    ver = _version_tuple(mid)
    # Pad version for comparison
    ver_pad = ver + (0,) * (4 - len(ver))
    return (score, *ver_pad)


def pick_best_chat_model(models: List[Dict[str, Any]]) -> Optional[str]:
    from app.services.model_roster import pick_flagship_chat_id

    flagged = pick_flagship_chat_id(models)
    if flagged:
        return flagged
    chat = [
        m for m in (models or [])
        if (m.get("capability") or "chat") == "chat" and m.get("value")
    ]
    if not chat:
        return None
    best = max(chat, key=lambda m: score_chat_model(str(m.get("value") or "")))
    return best.get("value")


def maybe_bump_default_model(provider_id: str, models: List[Dict[str, Any]]) -> Optional[str]:
    """
    When auto-updating the default AI's catalog, move *this user's* default_model
    to the newest flagship (e.g. grok-4.5 → grok-4.6). Also fixes a missing default.
    """
    from app.core.user_context import get_current_user_id
    from app.services.user_store import get_user_preferences, save_user_preferences

    uid = get_current_user_id()
    if not uid:
        return None

    prefs = get_user_preferences(uid)
    default_ai = prefs.get("default_ai") or ""
    current = prefs.get("default_model") or ""
    best = pick_best_chat_model(models)
    if not best:
        return None

    model_ids = {m.get("value") for m in (models or []) if m.get("value")}

    should_update = False
    if default_ai == provider_id:
        if current not in model_ids:
            should_update = True
        elif score_chat_model(best) > score_chat_model(current):
            should_update = True

    if should_update and best != current:
        save_user_preferences(uid, {"default_model": best})
        return best
    return None


async def update_provider_models(provider_id: str) -> Tuple[Dict[str, Any], str]:
    """
    Refresh the live model list and fill the family roster.
    Does not web-search descriptions or call an LLM.
    """
    from app.services.provider_sync import sync_provider

    out = await sync_provider(
        provider_id,
        fetch_remote=True,
        describe=False,
        recommend=False,
    )
    return out["provider"], out["message"]


async def update_all_auto_providers() -> List[Dict[str, Any]]:
    from app.services.provider_sync import sync_all_auto_providers

    results = await sync_all_auto_providers(
        describe=False,
        recommend=False,
        use_ai_recommend=False,
    )
    # Preserve previous shape (optional model_count)
    for r in results:
        if r.get("ok"):
            p = get_provider(r["provider_id"])
            r["model_count"] = len((p or {}).get("models") or [])
        else:
            r["model_count"] = 0
    return results
