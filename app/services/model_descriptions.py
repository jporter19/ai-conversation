# app/services/model_descriptions.py
# Purpose: Research short "what it's good for" blurbs via web search and store on models.

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.tools.web_search import execute_web_search

# Generic / placeholder tooltips we replace when enriching
_PLACEHOLDER_RE = re.compile(
    r"(auto-updated)|"
    r"^openai model\b|"
    r"^xai model\b|"
    r"^suggested from\b|"
    r"^from\s+\w|"
    r"^no description|"
    r"^paste the exact model|"
    r"endpoint:\s*https?://",
    re.I,
)

_MAX_DESC_LEN = 280
_SEARCH_CONCURRENCY = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def needs_description(model: Dict[str, Any], *, force: bool = False) -> bool:
    if force:
        return True
    if (model.get("description_source") or "") == "web_search":
        tip = (model.get("description") or model.get("tooltip") or "").strip()
        if len(tip) >= 40:
            return False
    tip = (model.get("description") or model.get("tooltip") or "").strip()
    if not tip or len(tip) < 40:
        return True
    if _PLACEHOLDER_RE.search(tip):
        return True
    return False


def _capability_fallback(model_id: str, capability: str, provider_label: str) -> str:
    cap = (capability or "chat").lower()
    mid = model_id or "this model"
    prov = provider_label or "the provider"
    if cap == "stt":
        return (
            f"{mid} is a speech-to-text model from {prov}. "
            "Good for transcribing recordings, dictation, and turning audio into text."
        )
    if cap == "tts":
        return (
            f"{mid} is a text-to-speech model from {prov}. "
            "Good for reading messages aloud and generating natural spoken audio."
        )
    if cap == "image":
        return (
            f"{mid} is an image-generation model from {prov}. "
            "Good for creating pictures from text prompts and visual concepts."
        )
    if cap == "transcript":
        return (
            f"{mid} fetches video transcripts. "
            "Good for turning YouTube (and similar) videos into readable text."
        )
    return (
        f"{mid} is a chat/LLM model from {prov}. "
        "Good for conversation, writing, coding help, and general reasoning."
    )


def _clean_snippet(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    t = re.sub(r"\[\d+\]", "", t)
    return t.strip(" -•|")


def _synthesize_from_search(
    model_id: str,
    label: str,
    provider_label: str,
    capability: str,
    search_blob: str,
) -> str:
    """Turn raw search lines into a short 1–2 sentence blurb."""
    if not search_blob or search_blob.startswith("Search error") or "No search results" in search_blob:
        return _capability_fallback(model_id, capability, provider_label)

    lines = []
    for line in search_blob.splitlines():
        line = line.strip().lstrip("- ").strip()
        if not line:
            continue
        # "- Title: body (url)"
        m = re.match(r"^(.*?):\s*(.*?)\s*\((https?://[^)]+)\)\s*$", line)
        if m:
            title, body, _url = m.group(1), m.group(2), m.group(3)
            lines.append(_clean_snippet(f"{title}. {body}"))
        else:
            lines.append(_clean_snippet(line))

    # Prefer snippets that mention the model or useful capability words
    mid_l = (model_id or "").lower()
    label_l = (label or "").lower()
    scored: List[Tuple[int, str]] = []
    for s in lines:
        sl = s.lower()
        score = 0
        if mid_l and mid_l in sl:
            score += 5
        if label_l and label_l in sl and len(label_l) > 3:
            score += 3
        for kw in ("good for", "best for", "designed for", "capable", "excels", "ideal", "use case", "chat", "coding", "reasoning", "multimodal", "speech", "image"):
            if kw in sl:
                score += 1
        # Penalize pure nav/marketing junk
        if any(x in sl for x in ("cookie", "sign up", "log in", "pricing page", "subscribe")):
            score -= 3
        if len(s) > 40:
            scored.append((score, s))

    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    if not scored:
        return _capability_fallback(model_id, capability, provider_label)

    # Build description: leading identity + best snippet condensed
    best = scored[0][1]
    # Truncate to sentence-ish chunk
    if len(best) > _MAX_DESC_LEN:
        cut = best[: _MAX_DESC_LEN - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        best = cut + "…"

    name = label or model_id
    # Avoid "Name. Name is..."
    if best.lower().startswith(name.lower()):
        desc = best
    else:
        desc = f"{name}: {best}"
    if len(desc) > _MAX_DESC_LEN:
        desc = desc[: _MAX_DESC_LEN - 1].rsplit(" ", 1)[0] + "…"
    return desc


def research_model_description_sync(
    model_id: str,
    *,
    label: str = "",
    provider_label: str = "",
    capability: str = "chat",
) -> str:
    """Blocking web search + synthesis for one model."""
    cap = capability or "chat"
    name = label or model_id
    prov = provider_label or ""
    queries = [
        f"{prov} {model_id} AI model capabilities what is it good for".strip(),
        f"{model_id} LLM overview strengths".strip(),
    ]
    if cap in ("stt", "tts", "image"):
        queries.insert(0, f"{prov} {model_id} {cap} model description".strip())

    blob = ""
    for q in queries[:2]:
        blob = execute_web_search(q)
        if blob and not blob.startswith("Search error") and "No search results" not in blob:
            break

    return _synthesize_from_search(model_id, name, prov, cap, blob)


async def research_model_description(
    model_id: str,
    *,
    label: str = "",
    provider_label: str = "",
    capability: str = "chat",
) -> str:
    return await asyncio.to_thread(
        research_model_description_sync,
        model_id,
        label=label,
        provider_label=provider_label,
        capability=capability,
    )


async def enrich_models(
    models: List[Dict[str, Any]],
    *,
    provider_label: str = "",
    force: bool = False,
    max_models: int = 40,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Fill description/tooltip on models via web search.
    Returns (updated_models, count_updated).
    """
    if not models:
        return models, 0

    sem = asyncio.Semaphore(_SEARCH_CONCURRENCY)
    updated = 0
    out = [dict(m) for m in models]

    async def one(idx: int) -> None:
        nonlocal updated
        m = out[idx]
        mid = (m.get("value") or "").strip()
        if not mid or not needs_description(m, force=force):
            return
        async with sem:
            try:
                desc = await research_model_description(
                    mid,
                    label=str(m.get("label") or mid),
                    provider_label=provider_label,
                    capability=str(m.get("capability") or "chat"),
                )
            except Exception:
                desc = _capability_fallback(
                    mid,
                    str(m.get("capability") or "chat"),
                    provider_label,
                )
        m["description"] = desc
        m["tooltip"] = desc
        m["description_source"] = "web_search"
        m["description_updated_at"] = _now_iso()
        out[idx] = m
        updated += 1

    # Prefer enriching models missing descriptions first, cap total work
    indices = [i for i, m in enumerate(out) if needs_description(m, force=force)]
    indices = indices[:max_models]
    if indices:
        await asyncio.gather(*(one(i) for i in indices))
    return out, updated


async def enrich_provider_models(
    provider_id: str,
    *,
    force: bool = False,
) -> Tuple[Dict[str, Any], str]:
    """Load provider, enrich models, persist."""
    from app.services.settings_store import get_provider, set_provider_models

    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")

    models = list(provider.get("models") or [])
    if not models:
        return provider, f"{provider_id}: no models to describe"

    enriched, n = await enrich_models(
        models,
        provider_label=str(provider.get("label") or provider_id),
        force=force,
    )
    if n:
        provider = set_provider_models(provider_id, enriched)
    return provider, f"{provider_id}: updated descriptions for {n} model(s)"


async def enrich_all_providers(*, force: bool = False) -> List[Dict[str, Any]]:
    from app.services.settings_store import get_providers

    results = []
    for p in get_providers():
        pid = p.get("id")
        if not pid:
            continue
        # Only enrich providers that are "in use" (keyed or optional)
        try:
            from app.services.settings_store import provider_has_active_key

            if not provider_has_active_key(p) and p.get("enabled", True) is False:
                continue
        except Exception:
            pass
        try:
            _prov, msg = await enrich_provider_models(pid, force=force)
            results.append({"provider_id": pid, "ok": True, "message": msg})
        except Exception as e:
            results.append({"provider_id": pid, "ok": False, "message": str(e)})
    return results
