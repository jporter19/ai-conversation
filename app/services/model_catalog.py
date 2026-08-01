# app/services/model_catalog.py
# Purpose: Auto-update model lists from OpenAI / xAI APIs (and heuristics).

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.services.settings_store import get_provider, get_secret, set_provider_models

# Prefer chat/image models; skip embeddings, whisper, etc.
OPENAI_SKIP_PREFIXES = (
    "text-embedding",
    "tts-",
    "whisper",
    "davinci",
    "babbage",
    "omni-moderation",
    "gpt-realtime",
    "gpt-audio",
    "gpt-transcribe",
    "gpt-live",
    "chatgpt-image",
    "sora-",
    "computer-use",
    "o1-",
    "o3-",
    "o4-",
    "gpt-4o",  # legacy; keep list modern-focused if desired — actually keep gpt-4o for usability
)

# Actually allow gpt-4o etc. - refine skip list
OPENAI_SKIP_PREFIXES = (
    "text-embedding",
    "tts-",
    "whisper",
    "davinci",
    "babbage",
    "omni-moderation",
    "text-moderation",
    "chatgpt-4o-latest",
)

XAI_IMAGE_MARKERS = ("imagine-image", "image", "flux")
OPENAI_IMAGE_MARKERS = ("dall-e", "gpt-image", "image")


def _capability_for(model_id: str, source: str) -> str:
    mid = model_id.lower()
    if source == "openai":
        if any(m in mid for m in OPENAI_IMAGE_MARKERS):
            return "image"
    if source == "xai":
        if "imagine-image" in mid or mid.endswith("-image") or "image" in mid and "vision" not in mid:
            if "vision" not in mid:
                return "image"
    return "chat"


def _label_from_id(model_id: str) -> str:
    return model_id.replace("-", " ").replace(".", " ").title()


def _filter_openai_models(ids: List[str]) -> List[str]:
    out = []
    for mid in ids:
        if any(mid.startswith(p) for p in OPENAI_SKIP_PREFIXES):
            continue
        # Prefer modern GPT / image models
        if mid.startswith(("gpt-", "o1", "o3", "o4", "chatgpt", "dall-e", "gpt-image")):
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
    When auto-updating the default AI's catalog, move default_model to the newest
    flagship (e.g. grok-4.5 → grok-4.6). Also fixes a missing default.
    """
    from app.services.settings_store import get_preferences, save_preferences

    prefs = get_preferences()
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
    elif current and current not in model_ids and default_ai == provider_id:
        should_update = True

    if should_update and best != current:
        save_preferences({"default_model": best})
        return best
    return None


async def update_provider_models(provider_id: str) -> Tuple[Dict[str, Any], str]:
    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")
    if not provider.get("auto_update"):
        raise ValueError(f"Provider {provider_id} does not support auto-update")

    source = provider.get("auto_update_source")
    key_name = provider.get("api_key_name")
    api_key = get_secret(key_name) if key_name else None
    if not api_key:
        raise ValueError(f"API key {key_name} is not configured")

    if source == "openai":
        models = await fetch_openai_models(api_key)
    elif source == "xai":
        models = await fetch_xai_models(api_key)
    else:
        raise ValueError(f"Unknown auto_update_source: {source}")

    if not models:
        raise ValueError("Provider returned no usable models")

    # Preserve manually added models (STT/TTS etc.) that weren't in the remote list
    # and keep researched descriptions when the same model id returns from the API.
    remote_ids = {m["value"] for m in models}
    old_by_id = {
        m.get("value"): m
        for m in (provider.get("models") or [])
        if m.get("value")
    }
    for m in models:
        old = old_by_id.get(m["value"])
        if not old:
            continue
        # Keep prior researched blurb until re-enriched
        if old.get("description_source") == "web_search" and old.get("tooltip"):
            m["tooltip"] = old.get("tooltip")
            m["description"] = old.get("description") or old.get("tooltip")
            m["description_source"] = old.get("description_source")
            if old.get("description_updated_at"):
                m["description_updated_at"] = old["description_updated_at"]
        if old.get("manual"):
            m["manual"] = True

    for old in provider.get("models") or []:
        if old.get("value") and old["value"] not in remote_ids and old.get("manual"):
            models.append(old)

    # Research short "what it's good for" blurbs for new/placeholder models
    try:
        from app.services.model_descriptions import enrich_models

        models, n_desc = await enrich_models(
            models,
            provider_label=str(provider.get("label") or provider_id),
            force=False,
        )
    except Exception:
        n_desc = 0

    # AI/heuristic tags + keep/remove recommendations
    try:
        from app.services.model_recommendations import recommend_models

        models, rec_msg = await recommend_models(
            models,
            provider_label=str(provider.get("label") or provider_id),
            use_ai=True,
        )
    except Exception as e:
        rec_msg = f"recommendations skipped: {e}"

    updated = set_provider_models(provider_id, models)
    default_msg = ""
    bumped = maybe_bump_default_model(provider_id, models)
    if bumped:
        default_msg = f"; default model → {bumped}"
    desc_msg = f"; {n_desc} description(s)" if n_desc else ""
    rec_part = f"; {rec_msg}" if rec_msg else ""

    return updated, f"Updated {provider_id}: {len(models)} models{default_msg}{desc_msg}{rec_part}"


async def update_all_auto_providers() -> List[Dict[str, Any]]:
    from app.services.settings_store import get_providers

    results = []
    for p in get_providers():
        if not p.get("auto_update"):
            continue
        pid = p.get("id")
        try:
            updated, msg = await update_provider_models(pid)
            results.append({
                "provider_id": pid,
                "ok": True,
                "message": msg,
                "model_count": len(updated.get("models") or []),
            })
        except Exception as e:
            results.append({
                "provider_id": pid,
                "ok": False,
                "message": str(e),
                "model_count": 0,
            })
    return results
