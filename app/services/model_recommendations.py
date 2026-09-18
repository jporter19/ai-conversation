# app/services/model_recommendations.py
# Purpose: Tag models and recommend keep vs remove using AI (+ heuristic fallback).

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ALLOWED_TAGS = frozenset({
    "flagship",
    "fast",
    "cheap",
    "deepthink",
    "coding",
    "images",
    "stt",
    "tts",
    "transcript",
    "specialized",
    "multimodal",
    "legacy",
    "experimental",
    "balanced",
    "long-context",
})

RECOMMENDATIONS = frozenset({"keep", "remove", "review"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _version_key(model_id: str) -> Tuple[int, ...]:
    nums = re.findall(r"(\d+)", (model_id or "").lower())
    return tuple(int(n) for n in nums[:6]) if nums else (0,)


def _heuristic_tags(model: Dict[str, Any]) -> List[str]:
    mid = str(model.get("value") or "").lower()
    label = str(model.get("label") or "").lower()
    cap = str(model.get("capability") or "chat").lower()
    text = f"{mid} {label}"
    tags: List[str] = []

    if cap == "image":
        tags.extend(["images", "specialized"])
    elif cap == "stt":
        tags.extend(["stt", "specialized"])
    elif cap == "tts":
        tags.extend(["tts", "specialized"])
    elif cap == "transcript":
        tags.extend(["transcript", "specialized"])
    else:
        if any(t in text for t in ("mini", "nano", "instant", "turbo", "flash", "lite", "small")):
            tags.append("fast")
            tags.append("cheap")
        if any(t in text for t in ("reason", "think", "o1", "o3", "o4", "r1")):
            tags.append("deepthink")
        if any(t in text for t in ("code", "codex", "build", "composer")):
            tags.append("coding")
        if any(t in text for t in ("vision", "omni", "multimodal")):
            tags.append("multimodal")
        if any(t in text for t in ("1m", "128k", "long", "context")):
            tags.append("long-context")
        if any(t in text for t in ("preview", "beta", "experimental", "early")):
            tags.append("experimental")
        if any(t in text for t in ("legacy", "instruct", "davinci", "3.5", "gpt-3")):
            tags.append("legacy")
        if any(t in text for t in ("image", "dall-e", "imagine", "flux", "gpt-image")):
            tags.append("images")
        if not tags:
            tags.append("balanced")

    # de-dupe preserve order
    seen = set()
    out = []
    for t in tags:
        if t in ALLOWED_TAGS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _heuristic_recommend(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Offline policy:
      - Always keep specialized (stt/tts/image/transcript) and manual specialty
      - Keep newest flagship chat model
      - Keep exactly one cheap/fast chat model (best mini/turbo)
      - Mark older superseded chat variants as remove
    """
    by_id = {m.get("value"): dict(m) for m in models if m.get("value")}
    for m in by_id.values():
        m["tags"] = _heuristic_tags(m)
        m["recommendation"] = "keep"
        m["recommendation_reason"] = "Default keep"
        m["recommendation_source"] = "heuristic"
        m["recommendation_updated_at"] = _now_iso()

    chat = [
        m for m in by_id.values()
        if (m.get("capability") or "chat") == "chat"
        and "images" not in (m.get("tags") or [])
    ]
    specialized = [
        m for m in by_id.values()
        if (m.get("capability") or "chat") in ("stt", "tts", "image", "transcript")
        or "specialized" in (m.get("tags") or [])
    ]

    for m in specialized:
        m["recommendation"] = "keep"
        m["recommendation_reason"] = "Keep specialized capability model"
        if "specialized" not in m["tags"]:
            m["tags"].append("specialized")

    if chat:
        # Flagship = highest version among non-mini models
        non_mini = [
            m for m in chat
            if not any(t in str(m.get("value") or "").lower() for t in ("mini", "nano", "lite", "small"))
        ] or chat
        flagship = max(non_mini, key=lambda m: (_version_key(str(m.get("value") or "")), len(str(m.get("value") or ""))))
        flagship["tags"] = [t for t in flagship.get("tags") or [] if t != "balanced"]
        if "flagship" not in flagship["tags"]:
            flagship["tags"].insert(0, "flagship")
        flagship["recommendation"] = "keep"
        flagship["recommendation_reason"] = "Current flagship / most capable general model"

        # One cheap effective model
        cheap_pool = [
            m for m in chat
            if m.get("value") != flagship.get("value")
            and (
                "cheap" in (m.get("tags") or [])
                or "fast" in (m.get("tags") or [])
                or any(t in str(m.get("value") or "").lower() for t in ("mini", "nano", "turbo", "instant", "flash", "lite"))
            )
        ]
        if not cheap_pool:
            # second-best by reverse version among remaining
            rest = [m for m in chat if m.get("value") != flagship.get("value")]
            if rest:
                cheap_pool = [min(rest, key=lambda m: _version_key(str(m.get("value") or "")))]
        if cheap_pool:
            # Prefer higher version among cheap options
            cheap = max(cheap_pool, key=lambda m: _version_key(str(m.get("value") or "")))
            if "cheap" not in cheap["tags"]:
                cheap["tags"].append("cheap")
            if "fast" not in cheap["tags"]:
                cheap["tags"].append("fast")
            cheap["recommendation"] = "keep"
            cheap["recommendation_reason"] = "Keep one highly effective, low-cost model"
            cheap_id = cheap.get("value")
        else:
            cheap_id = None

        flagship_id = flagship.get("value")
        # Family prefix for supersession (e.g. gpt-4o*, grok-4*, o1*)
        def family(mid: str) -> str:
            mid = (mid or "").lower()
            mid = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", mid)
            mid = re.sub(r"-\d{4}$", "", mid)
            # grok-4.5 / grok-4.3 → grok-4 ; gpt-4o-mini → gpt-4o
            m = re.match(r"^((?:gpt|grok|o\d|claude|gemini|llama)[a-z]*-?\d+)", mid)
            if m:
                base = m.group(1).rstrip("-")
                # collapse grok-4.x to grok-4
                base = re.sub(r"^((?:grok|gpt)-\d+)\.\d+.*$", r"\1", mid)
                if re.match(r"^(?:grok|gpt)-\d+", base):
                    return re.match(r"^((?:grok|gpt)-\d+)", base).group(1)
                return base
            parts = mid.split("-")
            if len(parts) >= 2:
                return "-".join(parts[:2])
            return mid

        families: Dict[str, List[Dict[str, Any]]] = {}
        for m in chat:
            families.setdefault(family(str(m.get("value") or "")), []).append(m)

        keep_ids = {flagship_id, cheap_id}
        for m in specialized:
            keep_ids.add(m.get("value"))

        for fam, group in families.items():
            # Sort newest first
            group_sorted = sorted(
                group,
                key=lambda m: _version_key(str(m.get("value") or "")),
                reverse=True,
            )
            newest = group_sorted[0]
            for m in group_sorted[1:]:
                mid = m.get("value")
                if mid in keep_ids:
                    continue
                # Keep deepthink variants if distinct
                if "deepthink" in (m.get("tags") or []) and mid != newest.get("value"):
                    m["recommendation"] = "keep"
                    m["recommendation_reason"] = "Keep specialized reasoning (deepthink) variant"
                    keep_ids.add(mid)
                    continue
                if "coding" in (m.get("tags") or []) and "coding" not in (newest.get("tags") or []):
                    m["recommendation"] = "keep"
                    m["recommendation_reason"] = "Keep specialized coding variant"
                    keep_ids.add(mid)
                    continue
                if "legacy" in (m.get("tags") or []) or _version_key(str(mid)) < _version_key(str(newest.get("value") or "")):
                    m["recommendation"] = "remove"
                    m["recommendation_reason"] = (
                        f"Superseded by more current model `{newest.get('value')}` in the same family"
                    )
                    if "legacy" not in m["tags"]:
                        m["tags"].append("legacy")
                else:
                    m["recommendation"] = "review"
                    m["recommendation_reason"] = "Similar to other models — review if still needed"

        # Ensure flagship/cheap not marked remove
        for mid in (flagship_id, cheap_id):
            if mid and mid in by_id:
                by_id[mid]["recommendation"] = "keep"

    # Preserve order of input, return list
    out = []
    for m in models:
        vid = m.get("value")
        out.append(by_id.get(vid) or m)
    return out


def _parse_llm_json(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


async def _llm_recommend(
    provider_label: str,
    models: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    """Ask Grok/OpenAI to tag + recommend. Returns list of {value, tags, recommendation, reason}."""
    from openai import AsyncOpenAI

    from app.config import resolve_api_key

    clients = []
    xai = resolve_api_key("XAI_API_KEY")
    oai = resolve_api_key("OPENAI_API_KEY")
    cheap_id = None
    try:
        from app.services.settings_store import get_provider
        from app.services.model_roster import SLOT_CHEAP_CHAT

        grok = get_provider("grok") or {}
        for m in grok.get("models") or []:
            if m.get("roster_slot") == SLOT_CHEAP_CHAT and m.get("value"):
                cheap_id = str(m["value"])
                break
            if "cheap" in (m.get("tags") or []) and (m.get("capability") or "chat") == "chat":
                cheap_id = str(m.get("value") or "") or cheap_id
    except Exception:
        cheap_id = None
    if xai:
        clients.append((
            cheap_id or "grok-4.1-fast-non-reasoning",
            AsyncOpenAI(api_key=xai, base_url="https://api.x.ai/v1"),
        ))
    if oai:
        clients.append(("gpt-4o-mini", AsyncOpenAI(api_key=oai, base_url="https://api.openai.com/v1")))
    if not clients:
        return None

    # Cap payload size for the LLM
    payload = []
    for m in models[:80]:
        payload.append({
            "value": m.get("value"),
            "label": m.get("label") or m.get("value"),
            "capability": m.get("capability") or "chat",
            "description": (m.get("description") or m.get("tooltip") or "")[:220],
            "manual": bool(m.get("manual")),
        })

    system = (
        "You curate an AI model picker for a small family chat hub.\n"
        "Return ONLY JSON (no markdown) as an array of objects:\n"
        '[{"value":"model-id","tags":["flagship"],"recommendation":"keep|remove|review",'
        '"reason":"short why"}]\n\n'
        "Allowed tags (use only these): "
        + ", ".join(sorted(ALLOWED_TAGS))
        + "\n\n"
        "Policy (strict):\n"
        "1. KEEP all highly specialized models: stt, tts, images/image-gen, transcript, "
        "and clearly specialized coding or deepthink variants that are not pure duplicates.\n"
        "2. KEEP exactly ONE current flagship chat model (tag: flagship) — the best general model.\n"
        "3. KEEP exactly ONE highly effective cheap/fast chat model (tags: cheap and/or fast) "
        "for everyday use.\n"
        "4. RECOMMEND remove for older/superseded chat models when a better current alternative exists "
        "in the same family (tag those legacy). Prefer fewer chat options.\n"
        "5. Use deepthink for reasoning-heavy models; images for image generation; coding for code-focused.\n"
        "6. Every input model value must appear exactly once in the output.\n"
        "7. recommendation must be keep, remove, or review.\n"
        f"Provider: {provider_label}\n"
    )

    model_id, client = clients[0]
    try:
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
        text = (resp.choices[0].message.content or "").strip()
        data = _parse_llm_json(text)
        if isinstance(data, dict) and "models" in data:
            data = data["models"]
        if not isinstance(data, list):
            return None
        return data
    except Exception:
        return None


def _apply_llm_rows(
    models: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_val = {str(r.get("value") or ""): r for r in rows if r.get("value")}
    out = []
    for m in models:
        nm = dict(m)
        row = by_val.get(str(m.get("value") or ""))
        if row:
            tags = []
            for t in row.get("tags") or []:
                t = str(t).lower().strip()
                if t in ALLOWED_TAGS and t not in tags:
                    tags.append(t)
            if not tags:
                tags = _heuristic_tags(m)
            rec = str(row.get("recommendation") or "review").lower()
            if rec not in RECOMMENDATIONS:
                rec = "review"
            nm["tags"] = tags
            nm["recommendation"] = rec
            nm["recommendation_reason"] = str(row.get("reason") or row.get("recommendation_reason") or "")[:240]
            nm["recommendation_source"] = "ai"
            nm["recommendation_updated_at"] = _now_iso()
        else:
            # Missing from LLM — heuristic for this one
            nm["tags"] = _heuristic_tags(m)
            nm["recommendation"] = "review"
            nm["recommendation_reason"] = "AI omitted this model — please review"
            nm["recommendation_source"] = "ai+heuristic"
            nm["recommendation_updated_at"] = _now_iso()
        out.append(nm)

    # Enforce policy: at least one flagship keep and one cheap keep among chat
    chat_keeps = [
        m for m in out
        if (m.get("capability") or "chat") == "chat" and m.get("recommendation") == "keep"
    ]
    if not any("flagship" in (m.get("tags") or []) for m in chat_keeps):
        candidates = [m for m in out if (m.get("capability") or "chat") == "chat"]
        if candidates:
            best = max(candidates, key=lambda m: _version_key(str(m.get("value") or "")))
            best["recommendation"] = "keep"
            if "flagship" not in best["tags"]:
                best["tags"] = ["flagship"] + [t for t in best.get("tags") or [] if t != "flagship"]
            best["recommendation_reason"] = best.get("recommendation_reason") or "Selected as flagship"

    if not any("cheap" in (m.get("tags") or []) and m.get("recommendation") == "keep" for m in out):
        cheap_cands = [
            m for m in out
            if (m.get("capability") or "chat") == "chat"
            and m.get("value")
            and any(t in str(m.get("value") or "").lower() for t in ("mini", "nano", "turbo", "flash", "instant", "lite"))
        ]
        if cheap_cands:
            c = max(cheap_cands, key=lambda m: _version_key(str(m.get("value") or "")))
            c["recommendation"] = "keep"
            tags = list(c.get("tags") or [])
            if "cheap" not in tags:
                tags.append("cheap")
            if "fast" not in tags:
                tags.append("fast")
            c["tags"] = tags
            c["recommendation_reason"] = c.get("recommendation_reason") or "Keep one effective cheap model"

    # Specialized always keep
    for m in out:
        cap = (m.get("capability") or "chat").lower()
        if cap in ("stt", "tts", "image", "transcript") or "specialized" in (m.get("tags") or []):
            m["recommendation"] = "keep"
            if "specialized" not in (m.get("tags") or []) and cap != "chat":
                m["tags"] = list(m.get("tags") or []) + ["specialized"]
            if not m.get("recommendation_reason"):
                m["recommendation_reason"] = "Keep specialized model"

    return out


def sort_models_for_display(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep/recommended first, remove last; flagship before others."""
    order_rec = {"keep": 0, "review": 1, "remove": 2}

    def key(m: Dict[str, Any]):
        rec = order_rec.get(str(m.get("recommendation") or "review"), 1)
        tags = m.get("tags") or []
        flag = 0 if "flagship" in tags else 1
        cheap = 0 if "cheap" in tags else 1
        spec = 0 if "specialized" in tags else 1
        return (rec, flag, spec, cheap, str(m.get("label") or m.get("value") or "").lower())

    return sorted(models, key=key)


async def recommend_models(
    models: List[Dict[str, Any]],
    *,
    provider_label: str = "",
    use_ai: bool = True,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Tag + recommend keep/remove for a provider's model list.
    Prefer AI; fall back to heuristics.
    """
    if not models:
        return models, "no models"

    if use_ai:
        rows = await _llm_recommend(provider_label, models)
        if rows:
            out = _apply_llm_rows(models, rows)
            from app.services.model_roster import preserve_roster_rows
            out = preserve_roster_rows(out)
            out = sort_models_for_display(out)
            n_remove = sum(1 for m in out if m.get("recommendation") == "remove")
            n_keep = sum(1 for m in out if m.get("recommendation") == "keep")
            return out, f"AI recommendations: keep {n_keep}, remove {n_remove}, of {len(out)}"

    out = _heuristic_recommend(models)
    from app.services.model_roster import preserve_roster_rows
    out = preserve_roster_rows(out)
    out = sort_models_for_display(out)
    n_remove = sum(1 for m in out if m.get("recommendation") == "remove")
    n_keep = sum(1 for m in out if m.get("recommendation") == "keep")
    return out, f"Heuristic recommendations: keep {n_keep}, remove {n_remove}, of {len(out)}"


async def recommend_provider_models(
    provider_id: str,
    *,
    use_ai: bool = True,
) -> Tuple[Dict[str, Any], str]:
    from app.services.settings_store import get_provider, set_provider_models

    provider = get_provider(provider_id)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_id}")
    models = list(provider.get("models") or [])
    if not models:
        return provider, f"{provider_id}: no models"

    updated, msg = await recommend_models(
        models,
        provider_label=str(provider.get("label") or provider_id),
        use_ai=use_ai,
    )
    provider = set_provider_models(provider_id, updated)
    return provider, f"{provider_id}: {msg}"


async def recommend_all_providers(*, use_ai: bool = True) -> List[Dict[str, Any]]:
    from app.services.settings_store import get_providers, provider_has_active_key

    results = []
    for p in get_providers():
        pid = p.get("id")
        if not pid:
            continue
        if p.get("enabled") is False:
            continue
        if not provider_has_active_key(p) and p.get("type") != "tool":
            # still allow tools
            if not p.get("api_key_optional"):
                continue
        try:
            _prov, msg = await recommend_provider_models(pid, use_ai=use_ai)
            results.append({"provider_id": pid, "ok": True, "message": msg})
        except Exception as e:
            results.append({"provider_id": pid, "ok": False, "message": str(e)})
    return results
