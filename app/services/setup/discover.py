# app/services/setup/discover.py — AI-assisted and multi-turn discovery.
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from app.services import settings_store
from app.services.key_test import test_api_key
from app.services.setup.presets import PRESETS
from app.services.setup.rules import (
    _ambiguous_or_insufficient,
    _clarify,
    _detect_capability,
    _key_info,
    _match_preset,
    _pick_model,
    _proposal_from_preset,
    _stt_provider_options,
    discover_rules_only,
    suggest_from_description,
)

async def suggest_with_ai(description: str) -> Dict[str, Any]:
    """Legacy entry: prefer rules; refine with LLM when confidence is low."""
    base = suggest_from_description(description)
    if base.get("status") == "needs_clarification":
        return base
    if base.get("proposal") and base["proposal"].get("confidence") == "high":
        return base
    refined = await _llm_suggest(description)
    if refined:
        return refined
    return base


async def discover_setup(
    message: str,
    *,
    history: Optional[List[Dict[str, str]]] = None,
    answers: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
    auto_apply: bool = True,
    use_ai: bool = True,
) -> Dict[str, Any]:
    """
    Full discover → clarify | test → optionally apply pipeline.

    Returns status:
      - needs_clarification
      - ready          (proposal filled; may need key)
      - applied        (saved + key ok)
      - error
    """
    history = history or []
    answers = dict(answers or {})

    # Merge free-text follow-ups from history answers already structured
    description = (message or "").strip()
    # Append short history for context in AI path
    if history:
        hist_bits = []
        for turn in history[-6:]:
            role = turn.get("role") or "user"
            content = (turn.get("content") or "").strip()
            if content:
                hist_bits.append(f"{role}: {content}")
        if hist_bits and description:
            # keep primary message as latest
            pass

    # Rule pass
    result = discover_rules_only(description, answers=answers)

    # If still unclear and AI allowed, try LLM
    if (
        use_ai
        and result.get("status") == "needs_clarification"
        and result.get("proposal", {}).get("confidence") == "low"
    ) or (
        use_ai
        and result.get("status") == "ready"
        and (result.get("proposal") or {}).get("confidence") in ("low", "medium")
        and not answers
    ):
        refined = await _llm_suggest(description, answers=answers, history=history)
        if refined and refined.get("status") == "needs_clarification":
            result = refined
        elif refined and refined.get("proposal"):
            result = refined

    if result.get("status") == "needs_clarification":
        return result

    proposal = result.get("proposal")
    if not proposal:
        return {
            "ok": False,
            "status": "error",
            "message": result.get("message") or "Could not build a setup proposal",
            "proposal": None,
            "questions": [],
            "key": None,
            "test": None,
            "applied": False,
        }

    # Key reuse
    key_name = proposal.get("api_key_name") or ""
    key_meta = _key_info(key_name) if key_name else None
    pasted = (api_key or "").strip() or None
    has_key = bool(pasted) or bool(key_meta and key_meta.get("configured"))

    result["key"] = key_meta
    result["status"] = "ready"

    # Enrich message about key
    msgs = [result.get("message") or ""]
    if key_meta and key_meta.get("configured") and not pasted:
        msgs.append(f"Reusing stored key `{key_name}` ({key_meta.get('hint')}).")
    elif pasted:
        msgs.append(f"Using the key you pasted for `{key_name}`.")
    elif key_name:
        msgs.append(
            f"No key on file for `{key_name}`. Paste a key below, then run Find & add again "
            "(or Save after filling Advanced details)."
        )

    # Auto-test when we have a key and base_url
    test_result = None
    if has_key and proposal.get("base_url"):
        model_val = (proposal.get("models") or [{}])[0].get("value") or "default"
        cap = (proposal.get("models") or [{}])[0].get("capability") or "chat"
        # For STT/TTS avoid chat probe with non-chat model id
        preferred = proposal.get("key_test") or ("models" if cap in ("stt", "tts") else "auto")
        # Prefer a chat model for chat probe if capability is non-chat
        probe_model = model_val
        if cap in ("stt", "tts", "image"):
            existing = settings_store.get_provider(proposal.get("id") or "")
            if existing:
                for m in existing.get("models") or []:
                    if (m.get("capability") or "chat") == "chat" and m.get("value"):
                        probe_model = m["value"]
                        preferred = "auto"
                        break
            if preferred == "models":
                probe_model = model_val  # models list doesn't need a chat model

        try:
            test_result = await test_api_key(
                key_name,
                pasted,
                base_url=proposal.get("base_url"),
                model=probe_model,
                label=proposal.get("label"),
                key_test=preferred,
            )
        except Exception as e:
            test_result = {
                "ok": False,
                "key_name": key_name,
                "message": f"Key test error: {e}",
            }
        result["test"] = test_result
        if test_result.get("ok"):
            msgs.append(f"Key test OK — {test_result.get('message')}")
        else:
            msgs.append(f"Key test failed — {test_result.get('message')}")
            result["message"] = " ".join(m for m in msgs if m)
            result["status"] = "ready"
            return result

    # Auto-apply when key works (or key optional) and auto_apply
    can_apply = auto_apply and proposal.get("base_url") and proposal.get("id")
    if can_apply and has_key and (test_result is None or test_result.get("ok")):
        try:
            applied = await apply_setup(
                proposal,
                api_key=pasted,
                run_test=False,  # already tested
            )
            result["applied"] = True
            result["status"] = "applied"
            result["provider"] = applied.get("provider")
            result["catalog"] = applied.get("catalog")
            result["key_saved"] = applied.get("key_saved")
            model_val = (proposal.get("models") or [{}])[0].get("value")
            msgs.append(
                f"Saved and enabled. Model `{model_val}` is now available under "
                f"**{proposal.get('label')}**."
            )
            if (proposal.get("models") or [{}])[0].get("capability") in ("stt", "tts"):
                msgs.append(
                    "Note: speech models are in the catalog; the chat panel does not "
                    "yet upload audio — they are ready for future audio tools / API use."
                )
        except Exception as e:
            result["applied"] = False
            result["status"] = "ready"
            msgs.append(f"Could not save yet: {e}")
    elif can_apply and not has_key:
        result["status"] = "ready"
        # leave unapplied

    # Join sentences cleanly
    cleaned = []
    for m in msgs:
        m = (m or "").strip()
        if not m:
            continue
        if cleaned and not cleaned[-1].endswith((".", "!", "?", "…")):
            cleaned[-1] = cleaned[-1] + "."
        cleaned.append(m)
    result["message"] = " ".join(cleaned)
    result["proposal"] = proposal
    result["ok"] = True
    return result


async def _llm_suggest(
    description: str,
    *,
    answers: Optional[Dict[str, str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    from openai import AsyncOpenAI
    from app.config import resolve_api_key

    clients = []
    xai = resolve_api_key("XAI_API_KEY")
    oai = resolve_api_key("OPENAI_API_KEY")
    if xai:
        clients.append(("grok-4.5", AsyncOpenAI(api_key=xai, base_url="https://api.x.ai/v1")))
    if oai:
        clients.append(("gpt-4o-mini", AsyncOpenAI(api_key=oai, base_url="https://api.openai.com/v1")))
    if not clients:
        return None

    existing = []
    for p in settings_store.get_providers():
        existing.append({
            "id": p.get("id"),
            "label": p.get("label"),
            "base_url": p.get("base_url"),
            "api_key_name": p.get("api_key_name"),
            "has_key": bool(settings_store.get_secret(p.get("api_key_name") or "")),
            "models": [
                {"value": m.get("value"), "capability": m.get("capability") or "chat"}
                for m in (p.get("models") or [])[:12]
            ],
        })

    system = (
        "You help configure AI APIs for a multi-provider chat app. "
        "Reply with ONLY JSON (no markdown).\n"
        "Schema:\n"
        "{\n"
        '  "status": "ready" | "needs_clarification",\n'
        '  "message": "short human message",\n'
        '  "questions": [{"id":"slug","prompt":"...","options":[{"value":"...","label":"..."}]}],\n'
        '  "id":"provider-slug","label":"Name","base_url":"https://.../v1",\n'
        '  "api_key_name":"FOO_API_KEY","model_value":"exact-id","model_label":"Human",\n'
        '  "capability":"chat|image|stt|tts|transcript","key_test":"auto|chat|models",\n'
        '  "notes":"short","confidence":"high|medium|low",\n'
        '  "maps_to_existing":"optional existing provider id"\n'
        "}\n"
        "Rules:\n"
        "- If the user request is ambiguous (missing provider or capability), set status=needs_clarification "
        "and fill questions (2–4 options each). Leave model fields empty.\n"
        "- If clear, status=ready with full fields.\n"
        "- Prefer mapping onto existing providers when the vendor matches.\n"
        "- Known facts:\n"
        "  * Grok/xAI: base https://api.x.ai/v1, XAI_API_KEY, chat grok-4.5, image grok-imagine-image, "
        "STT model grok-stt (POST /v1/stt), TTS via /v1/tts.\n"
        "  * OpenAI: https://api.openai.com/v1, OPENAI_API_KEY, whisper-1 for STT, gpt-4o chat, gpt-image-1 image.\n"
        "  * Groq: https://api.groq.com/openai/v1, GROQ_API_KEY, whisper-large-v3 STT, llama-3.1-8b-instant chat.\n"
        "  * Magisterium: https://www.magisterium.com/api/v1, key_test chat, magisterium-1.\n"
        "- For STT/TTS set key_test=models (chat probe will fail on those model ids).\n"
        f"Existing providers: {json.dumps(existing)}\n"
        f"User answers so far: {json.dumps(answers or {})}\n"
    )

    user_content = description
    if history:
        user_content = "Conversation so far:\n" + "\n".join(
            f"{t.get('role','user')}: {t.get('content','')}" for t in history[-8:]
        ) + f"\n\nLatest request: {description}"

    model_id, client = clients[0]
    try:
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            max_tokens=600,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)

        status = data.get("status") or "ready"
        if status == "needs_clarification":
            return {
                "ok": True,
                "status": "needs_clarification",
                "message": data.get("message") or "I need a bit more information.",
                "questions": data.get("questions") or [],
                "proposal": None,
                "key": None,
                "test": None,
                "applied": False,
                "source": "ai",
            }

        pid_raw = data.get("maps_to_existing") or data.get("id") or "custom"
        pid = re.sub(r"[^a-z0-9_-]+", "-", str(pid_raw).lower()).strip("-") or "custom"
        existing = settings_store.get_provider(pid)
        # Also try common maps
        if not existing and data.get("id"):
            for preset in PRESETS:
                if preset["id"] == data.get("id") and preset.get("maps_to_existing"):
                    alt = settings_store.get_provider(preset["maps_to_existing"])
                    if alt:
                        existing = alt
                        pid = preset["maps_to_existing"]
                        break

        model_value = data.get("model_value") or "default"
        cap = (data.get("capability") or "chat").lower()
        if cap not in ("chat", "image", "stt", "tts", "transcript"):
            cap = "chat"
        proposal = {
            "id": pid,
            "label": data.get("label") or (existing or {}).get("label") or pid,
            "base_url": (
                (data.get("base_url") or "").rstrip("/")
                or (existing or {}).get("base_url")
                or ""
            ),
            "api_key_name": data.get("api_key_name")
            or (existing or {}).get("api_key_name")
            or f"{pid.upper()}_API_KEY",
            "key_test": data.get("key_test") or ("models" if cap in ("stt", "tts") else "auto"),
            "supports_tools": bool((existing or {}).get("supports_tools")),
            "supports_image_gen": bool(
                (existing or {}).get("supports_image_gen") or cap == "image"
            ),
            "badge_color": (existing or {}).get("badge_color") or "#555555",
            "needs_api_key": True,
            "api_key_optional": False,
            "type": "openai_compatible",
            "models": [{
                "value": model_value,
                "label": data.get("model_label") or model_value,
                "tooltip": data.get("notes") or "AI-suggested model",
                "capability": cap,
                "manual": True,
            }],
            "notes": data.get("notes") or "Suggested by AI — verify base URL and model id.",
            "confidence": data.get("confidence") or "medium",
            "already_exists": bool(existing),
            "capability": cap,
        }
        return {
            "ok": True,
            "status": "ready",
            "message": data.get("message")
            or f"AI suggested {proposal['label']} with model `{model_value}` ({cap}).",
            "proposal": proposal,
            "questions": [],
            "key": None,
            "test": None,
            "applied": False,
            "source": "ai",
        }
    except Exception:
        return None


