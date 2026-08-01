# app/services/setup/rules.py — rule-based discovery helpers.
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from app.services import settings_store
from app.services.setup.presets import PRESETS, _CAP_HINTS

def _detect_capability(text: str) -> Optional[str]:
    lower = (text or "").lower()
    best_cap = None
    best_len = 0
    for cap, phrases in _CAP_HINTS:
        for p in phrases:
            if p in lower and len(p) > best_len:
                best_cap = cap
                best_len = len(p)
    return best_cap


def _match_preset(text: str) -> Optional[Dict[str, Any]]:
    lower = (text or "").lower()
    # Prefer longer/more specific keyword hits
    best = None
    best_score = 0
    for preset in PRESETS:
        for kw in preset.get("keywords") or []:
            if kw in lower:
                score = len(kw)
                if score > best_score:
                    best = preset
                    best_score = score
    return best


def _pick_model(
    preset: Dict[str, Any],
    text: str,
    capability: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    t = (text or "").lower()
    models = preset.get("models") or []
    candidates = models
    if capability:
        cap_models = [m for m in models if (m.get("capability") or "chat") == capability]
        if cap_models:
            candidates = cap_models

    best = None
    best_score = -1
    for m in candidates:
        score = 0
        val = (m.get("value") or "").lower()
        label = (m.get("label") or "").lower()
        if val and val in t:
            score += 12
        if label and label in t:
            score += 6
        for a in m.get("aliases") or []:
            if a and a.lower() in t:
                score += 5 + min(len(a), 20) // 4
        if "8b" in t and "8b" in val:
            score += 3
        if "70b" in t and "70b" in val:
            score += 3
        if capability and (m.get("capability") or "chat") == capability:
            score += 2
        if score > best_score:
            best_score = score
            best = m

    # Capability-only request: take the first matching capability model
    if best is None and capability and candidates:
        best = candidates[0]
        best_score = 1

    # Generic request with no model hint: first chat model
    if best is None and models and best_score < 0:
        chat_models = [m for m in models if (m.get("capability") or "chat") == "chat"]
        best = (chat_models or models)[0]
        best_score = 0

    if not best:
        return None

    # Require some signal when capability was not constrained and score is zero
    # (caller decides whether that is enough)
    return {
        "value": best["value"],
        "label": best.get("label") or best["value"],
        "tooltip": best.get("endpoint_hint")
        or f"Suggested from: {preset.get('label')}",
        "capability": best.get("capability") or "chat",
        "manual": True,
        "_score": best_score,
        "endpoint_hint": best.get("endpoint_hint"),
    }


def _proposal_from_preset(
    preset: Dict[str, Any],
    model: Dict[str, Any],
    *,
    confidence: str = "high",
) -> Dict[str, Any]:
    existing_id = preset.get("maps_to_existing") or preset["id"]
    existing = settings_store.get_provider(existing_id)
    cap = model.get("capability") or "chat"
    proposal = {
        "id": existing_id if existing else preset["id"],
        "label": (existing or {}).get("label") or preset["label"],
        "base_url": (existing or {}).get("base_url") or preset["base_url"],
        "api_key_name": (existing or {}).get("api_key_name") or preset["api_key_name"],
        "key_test": "models" if cap in ("stt", "tts") else (preset.get("key_test") or "auto"),
        "supports_tools": preset.get("supports_tools", False),
        "supports_image_gen": bool(
            preset.get("supports_image_gen")
            or (existing or {}).get("supports_image_gen")
            or cap == "image"
        ),
        "badge_color": preset.get("badge_color") or "#555555",
        "needs_api_key": True,
        "api_key_optional": False,
        "type": "openai_compatible",
        "models": [{
            "value": model["value"],
            "label": model.get("label") or model["value"],
            "tooltip": model.get("tooltip") or "",
            "capability": cap,
            "manual": True,
        }],
        "notes": preset.get("notes") or "",
        "confidence": confidence,
        "already_exists": bool(existing),
        "suggested_models": [
            {
                "value": m["value"],
                "label": m.get("label") or m["value"],
                "capability": m.get("capability") or "chat",
            }
            for m in (preset.get("models") or [])
        ],
        "capability": cap,
    }
    if model.get("endpoint_hint"):
        proposal["notes"] = (
            (proposal["notes"] + " " if proposal["notes"] else "")
            + f"Endpoint: {model['endpoint_hint']}."
        ).strip()
    return proposal


def _key_info(api_key_name: str) -> Dict[str, Any]:
    configured = bool(settings_store.get_secret(api_key_name))
    hint = ""
    if configured:
        val = settings_store.get_secret(api_key_name) or ""
        hint = (val[:4] + "…" + val[-4:]) if len(val) >= 12 else "••••"
    return {
        "name": api_key_name,
        "configured": configured,
        "hint": hint,
    }


def _stt_provider_options() -> List[Dict[str, str]]:
    opts = []
    for pid, label, model in (
        ("xai", "Grok (xAI) — grok-stt", "grok-stt"),
        ("openai", "OpenAI — whisper-1", "whisper-1"),
        ("groq", "Groq — whisper-large-v3", "whisper-large-v3"),
    ):
        preset = next((p for p in PRESETS if p["id"] == pid), None)
        if not preset:
            continue
        existing_id = preset.get("maps_to_existing") or preset["id"]
        key_name = preset["api_key_name"]
        has_key = bool(settings_store.get_secret(key_name))
        has_provider = bool(settings_store.get_provider(existing_id))
        suffix = []
        if has_provider:
            suffix.append("already configured")
        if has_key:
            suffix.append("key on file")
        label_full = label
        if suffix:
            label_full += f" ({', '.join(suffix)})"
        opts.append({"value": pid, "label": label_full})
    return opts


def _clarify(
    message: str,
    questions: List[Dict[str, Any]],
    *,
    proposal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "needs_clarification",
        "message": message,
        "questions": questions,
        "proposal": proposal,
        "key": None,
        "test": None,
        "applied": False,
    }


def _ambiguous_or_insufficient(description: str) -> Optional[Dict[str, Any]]:
    """Return a clarification response when the request is too vague."""
    text = (description or "").strip()
    if not text:
        return _clarify(
            "Describe what you want to add — for example “Grok speech to text”, "
            "“OpenAI whisper”, or “Groq Llama 8B”.",
            [{
                "id": "example",
                "prompt": "Try one of these starting points",
                "options": [
                    {"value": "Grok speech to text", "label": "Grok speech to text"},
                    {"value": "OpenAI whisper", "label": "OpenAI Whisper (STT)"},
                    {"value": "Grok image generation", "label": "Grok image generation"},
                    {"value": "Groq Llama 8B", "label": "Groq Llama 8B chat"},
                ],
            }],
        )

    lower = text.lower()
    # Too short / vague without provider or model
    preset = _match_preset(lower)
    cap = _detect_capability(lower)

    # STT/TTS without a provider → ask which vendor
    if cap in ("stt", "tts") and not preset:
        kind = "speech-to-text" if cap == "stt" else "text-to-speech"
        return _clarify(
            f"You asked for {kind}, but not which provider. "
            "Which API should I set up?",
            [{
                "id": "provider",
                "prompt": f"Choose a {kind} provider",
                "options": _stt_provider_options() if cap == "stt" else [
                    {"value": "xai", "label": "Grok (xAI) TTS"},
                    {"value": "openai", "label": "OpenAI TTS"},
                ],
            }],
        )

    # Capability only with multiple models, provider known but model unclear
    if preset and cap:
        return None  # resolvable

    if not preset and not cap and len(text.split()) < 3:
        return _clarify(
            "I need a bit more detail. Which provider and what kind of model "
            "(chat, image, speech-to-text, …)?",
            [{
                "id": "provider",
                "prompt": "Which provider?",
                "options": [
                    {"value": p["id"], "label": p["label"]}
                    for p in PRESETS[:6]
                ],
            }, {
                "id": "capability",
                "prompt": "What kind of model?",
                "options": [
                    {"value": "chat", "label": "Chat / LLM"},
                    {"value": "image", "label": "Image generation"},
                    {"value": "stt", "label": "Speech to text"},
                    {"value": "tts", "label": "Text to speech"},
                ],
            }],
        )

    return None


def suggest_from_description(description: str) -> Dict[str, Any]:
    """Rule-based suggestion from free text (no LLM required). Legacy shape."""
    result = discover_rules_only(description)
    if result.get("status") == "needs_clarification":
        return {
            "ok": True,
            "message": result.get("message") or "Need more information",
            "proposal": result.get("proposal"),
            "status": "needs_clarification",
            "questions": result.get("questions") or [],
        }
    if result.get("proposal"):
        p = result["proposal"]
        model = (p.get("models") or [{}])[0]
        msg = result.get("message") or (
            f"Matched **{p.get('label')}**. Suggested model: `{model.get('value')}`."
        )
        return {
            "ok": True,
            "message": msg,
            "proposal": p,
            "status": "ready",
            "questions": [],
        }
    return {
        "ok": False,
        "message": result.get("message") or "Could not suggest a setup",
        "proposal": None,
        "status": "error",
        "questions": [],
    }


def discover_rules_only(
    description: str,
    answers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Deterministic discovery from text + optional answers to prior questions.
    Does not test keys or apply.
    """
    answers = answers or {}
    text = (description or "").strip()

    # Fold answers into synthetic description for matching
    parts = [text]
    if answers.get("provider"):
        parts.append(str(answers["provider"]))
    if answers.get("capability"):
        parts.append(str(answers["capability"]))
    if answers.get("example"):
        parts.append(str(answers["example"]))
        text = answers["example"]  # example chip replaces vague input
        parts = [text]
    if answers.get("model"):
        parts.append(str(answers["model"]))
    combined = " ".join(p for p in parts if p).strip()

    # Map answer provider ids to keywords
    provider_ans = (answers.get("provider") or "").lower().strip()
    if provider_ans:
        preset_by_id = next((p for p in PRESETS if p["id"] == provider_ans), None)
        if preset_by_id and preset_by_id["id"] not in combined.lower():
            combined = f"{preset_by_id['label']} {combined}"

    cap_ans = (answers.get("capability") or "").lower().strip()
    cap = cap_ans if cap_ans in ("chat", "image", "stt", "tts", "transcript") else _detect_capability(combined)

    vague = _ambiguous_or_insufficient(combined if not answers else "")
    if vague and not answers:
        # Only short-circuit when no answers yet
        if not _match_preset(combined) or (
            _detect_capability(combined) in ("stt", "tts") and not _match_preset(combined)
        ):
            return vague
        # if empty description
        if not (description or "").strip() and not answers:
            return vague

    if not combined:
        return _ambiguous_or_insufficient("") or {
            "ok": False,
            "status": "error",
            "message": "Empty request",
            "proposal": None,
            "questions": [],
            "applied": False,
        }

    # Re-check STT without provider after answers still missing
    preset = _match_preset(combined)
    if not preset and provider_ans:
        preset = next((p for p in PRESETS if p["id"] == provider_ans), None)

    if cap in ("stt", "tts") and not preset:
        return _clarify(
            f"Which provider should I use for {'speech-to-text' if cap == 'stt' else 'text-to-speech'}?",
            [{
                "id": "provider",
                "prompt": "Choose a provider",
                "options": _stt_provider_options() if cap == "stt" else [
                    {"value": "xai", "label": "Grok (xAI)"},
                    {"value": "openai", "label": "OpenAI"},
                ],
            }],
        )

    if not preset:
        model_guess = None
        m = re.search(r"\b([a-z0-9][a-z0-9._/-]{2,80})\b", combined.lower())
        if m and any(c in m.group(1) for c in "-_/."):
            model_guess = m.group(1)
        return {
            "ok": True,
            "status": "needs_clarification",
            "message": (
                "I couldn’t match a known provider. "
                "Pick one below, or fill base URL / model manually in Advanced details."
            ),
            "questions": [{
                "id": "provider",
                "prompt": "Known providers",
                "options": [
                    {"value": p["id"], "label": p["label"]}
                    for p in PRESETS
                ],
            }],
            "proposal": {
                "id": "custom",
                "label": "Custom API",
                "base_url": "",
                "api_key_name": "CUSTOM_API_KEY",
                "key_test": "auto",
                "supports_tools": False,
                "badge_color": "#555555",
                "needs_api_key": True,
                "api_key_optional": False,
                "models": [{
                    "value": model_guess or "",
                    "label": model_guess or "Model",
                    "tooltip": "Paste the exact model id from the provider",
                    "capability": cap or "chat",
                    "manual": True,
                }],
                "notes": "OpenAI-compatible providers need a base URL ending in /v1 (or /api/v1).",
                "confidence": "low",
                "capability": cap or "chat",
            },
            "key": None,
            "test": None,
            "applied": False,
        }

    model = _pick_model(preset, combined, capability=cap)
    if not model:
        return _clarify(
            f"I matched **{preset['label']}**, but I’m not sure which model. Pick one:",
            [{
                "id": "model",
                "prompt": "Model",
                "options": [
                    {
                        "value": m["value"],
                        "label": f"{m.get('label') or m['value']} ({m.get('capability') or 'chat'})",
                    }
                    for m in (preset.get("models") or [])
                ],
            }],
        )

    # If user picked a specific model via answers
    if answers.get("model"):
        mid = answers["model"]
        found = next(
            (m for m in (preset.get("models") or []) if m.get("value") == mid),
            None,
        )
        if found:
            model = {
                "value": found["value"],
                "label": found.get("label") or found["value"],
                "tooltip": found.get("endpoint_hint") or f"Suggested from: {preset.get('label')}",
                "capability": found.get("capability") or "chat",
                "manual": True,
                "endpoint_hint": found.get("endpoint_hint"),
            }

    # Capability intent with low model score and many options → clarify
    score = model.get("_score", 0)
    if cap is None and score < 3 and len(preset.get("models") or []) > 3:
        # Provider clear, model/capability not
        return _clarify(
            f"I matched **{preset['label']}**. What kind of model do you want?",
            [{
                "id": "capability",
                "prompt": "Capability",
                "options": [
                    {"value": "chat", "label": "Chat / LLM"},
                    {"value": "image", "label": "Image generation"},
                    {"value": "stt", "label": "Speech to text"},
                    {"value": "tts", "label": "Text to speech"},
                ],
            }],
        )

    proposal = _proposal_from_preset(preset, model, confidence="high" if score >= 2 or cap else "medium")
    model_val = model["value"]
    msg = f"Matched **{proposal['label']}**"
    if proposal.get("already_exists"):
        msg += " (provider already configured — will add/update this model)"
    msg += f". Model: `{model_val}` ({model.get('capability') or 'chat'})."

    return {
        "ok": True,
        "status": "ready",
        "message": msg,
        "proposal": proposal,
        "questions": [],
        "key": None,
        "test": None,
        "applied": False,
    }


