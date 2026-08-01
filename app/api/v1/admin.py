# app/api/v1/admin.py
# Purpose: Administrative API — providers/models, secrets, preferences, auto-update

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import settings_store
from app.services.model_catalog import update_all_auto_providers, update_provider_models

router = APIRouter(prefix="/admin", tags=["admin"])


class ModelIn(BaseModel):
    value: str
    label: str
    tooltip: str = ""
    capability: str = "chat"
    manual: bool = True


class ProviderIn(BaseModel):
    id: str
    label: str
    enabled: bool = True
    type: str = "openai_compatible"
    base_url: Optional[str] = None
    api_key_name: Optional[str] = None
    supports_tools: bool = False
    supports_image_gen: bool = False
    auto_update: bool = False
    auto_update_source: Optional[str] = None
    key_test: str = "auto"  # auto | models | chat
    badge_color: str = "#555555"
    models: List[ModelIn] = Field(default_factory=list)


class SecretsIn(BaseModel):
    secrets: Dict[str, Optional[str]]


class TestKeyIn(BaseModel):
    """
    Dry-run key probe — never writes providers.json or secrets.json.
    api_key: if set, test this value; else use stored secret.
    base_url / model / label / key_test: optional ephemeral overrides for the
    Add API wizard (test before the provider is saved).
    """
    key_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    label: Optional[str] = None
    key_test: Optional[str] = None  # auto | models | chat


class PreferencesIn(BaseModel):
    theme: Optional[str] = None
    default_ai: Optional[str] = None
    default_model: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_language: Optional[str] = None


class SetupSuggestIn(BaseModel):
    description: str
    use_ai: bool = True


class SetupHistoryTurn(BaseModel):
    role: str = "user"
    content: str = ""


class SetupDiscoverIn(BaseModel):
    """
    Conversational Add API:
      - message: free text ("Grok speech to text")
      - answers: responses to prior clarifying questions {question_id: value}
      - history: optional prior turns for multi-step context
      - api_key: optional paste; otherwise reuses stored key for the matched provider
      - auto_apply: when True, save model if key test succeeds
    """
    message: str
    answers: Dict[str, str] = Field(default_factory=dict)
    history: List[SetupHistoryTurn] = Field(default_factory=list)
    api_key: Optional[str] = None
    auto_apply: bool = True
    use_ai: bool = True


class SetupModelIn(BaseModel):
    value: str
    label: str = ""
    tooltip: str = ""
    capability: str = "chat"
    manual: bool = True


class SetupApplyIn(BaseModel):
    """One-shot: create/update provider + models + optional API key + test."""
    id: str
    label: str
    base_url: Optional[str] = None
    api_key_name: str
    api_key: Optional[str] = None
    api_key_optional: bool = False
    key_test: str = "auto"
    type: str = "openai_compatible"
    supports_tools: bool = False
    supports_image_gen: bool = False
    badge_color: str = "#555555"
    models: List[SetupModelIn] = Field(default_factory=list)
    notes: str = ""
    run_test: bool = True


# ── Public catalog (used by chat UI) ───────────────────────────────────────────

@router.get("/catalog")
async def get_catalog():
    return settings_store.public_catalog()


# ── Providers ──────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers():
    return {"providers": settings_store.get_providers()}


@router.put("/providers/{provider_id}")
async def put_provider(provider_id: str, body: ProviderIn):
    if body.id != provider_id:
        raise HTTPException(400, "URL provider_id must match body.id")
    data = body.model_dump()
    data["models"] = [m.model_dump() for m in body.models]
    try:
        saved = settings_store.upsert_provider(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"provider": saved}


@router.delete("/providers/{provider_id}")
async def remove_provider(provider_id: str, hard: bool = False):
    """
    Remove an AI from the hub.
    - By default: soft-disable (enabled=false) so it leaves the main AI dropdown
      but can be re-enabled later. Built-ins always soft-disable.
    - hard=true: permanently delete from providers.json (not allowed for grok/chatgpt).
    """
    p = settings_store.get_provider(provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")

    if hard and provider_id not in ("grok", "chatgpt"):
        ok = settings_store.delete_provider(provider_id)
        if not ok:
            raise HTTPException(404, "Provider not found")
        return {
            "ok": True,
            "deleted": True,
            "disabled": False,
            "catalog": settings_store.public_catalog(),
        }

    # Soft-disable (default, and always for built-ins)
    p = {**p, "enabled": False}
    settings_store.upsert_provider(p)
    return {
        "ok": True,
        "deleted": False,
        "disabled": True,
        "catalog": settings_store.public_catalog(),
    }


@router.post("/providers/{provider_id}/enable")
async def enable_provider(provider_id: str):
    """Re-enable a previously disabled AI so it appears in the main dropdown again."""
    p = settings_store.get_provider(provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    p = {**p, "enabled": True}
    settings_store.upsert_provider(p)
    return {
        "ok": True,
        "enabled": True,
        "provider": settings_store.get_provider(provider_id),
        "catalog": settings_store.public_catalog(),
    }


@router.post("/providers/{provider_id}/models")
async def add_model(provider_id: str, body: ModelIn):
    try:
        model = body.model_dump()
        model["manual"] = True
        provider = settings_store.add_model(provider_id, model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"provider": provider}


@router.delete("/providers/{provider_id}/models/{model_value}")
async def delete_model(provider_id: str, model_value: str):
    try:
        provider = settings_store.remove_model(provider_id, model_value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"provider": provider}


# ── Secrets (API keys) ─────────────────────────────────────────────────────────

@router.get("/secrets")
async def get_secrets_status():
    return {"secrets": settings_store.secrets_status()}


@router.put("/secrets")
async def put_secrets(body: SecretsIn):
    settings_store.save_secrets(body.secrets, merge=True)
    return {"secrets": settings_store.secrets_status()}


@router.post("/secrets/test")
async def test_secret(body: TestKeyIn):
    """Dry-run: probe a key (saved or pasted). Does not persist anything."""
    from app.services.key_test import test_api_key

    result = await test_api_key(
        body.key_name,
        body.api_key,
        base_url=body.base_url,
        model=body.model,
        label=body.label,
        key_test=body.key_test,
    )
    # Always 200 so the UI can show ok/fail without treating auth probe as HTTP error
    return result


@router.post("/setup/test")
async def setup_test(body: TestKeyIn):
    """
    Same as /secrets/test — explicit setup alias for the wizard.
    Guaranteed side-effect free (no provider/key writes).
    """
    return await test_secret(body)


# ── Preferences ────────────────────────────────────────────────────────────────

@router.get("/preferences")
async def get_preferences():
    return settings_store.get_preferences()


@router.put("/preferences")
async def put_preferences(body: PreferencesIn):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return settings_store.save_preferences(updates)


# ── TTS voices ─────────────────────────────────────────────────────────────────

class TtsPreviewIn(BaseModel):
    """Short sample clip for Admin voice browsing."""
    voice_id: str = "eve"
    language: Optional[str] = None
    text: Optional[str] = None
    provider_id: str = "grok"


@router.get("/tts/voices")
async def list_tts_voices(provider_id: str = "grok"):
    """
    List available speech voices for a provider (xAI /v1/tts/voices when keyed).
    Falls back to a curated static list if the upstream call fails.
    """
    from app.services.tts import list_voices

    provider = settings_store.get_provider(provider_id)
    result = await list_voices(provider)
    prefs = settings_store.get_preferences()
    result["preferred_voice"] = prefs.get("tts_voice") or "eve"
    result["preferred_language"] = prefs.get("tts_language") or "en"
    result["provider_id"] = provider_id if provider else None
    return result


@router.post("/tts/preview")
async def tts_preview(body: TtsPreviewIn):
    """
    Generate a short spoken sample and return raw audio (audio/mpeg).
    Used by Admin → Voice to audition a voice with no on-screen player.
    """
    from fastapi.responses import Response

    from app.services.tts import TtsError, synthesize_speech

    provider = settings_store.get_provider(body.provider_id or "grok")
    if not provider or not provider.get("enabled", True):
        # Fall back to any xAI-style provider
        for p in settings_store.get_providers():
            if "x.ai" in (p.get("base_url") or "").lower() and p.get("enabled", True):
                provider = p
                break
    if not provider:
        raise HTTPException(400, "No TTS provider available. Configure Grok with an API key.")

    prefs = settings_store.get_preferences()
    language = (body.language or prefs.get("tts_language") or "en").strip() or "en"
    voice_id = (body.voice_id or "eve").strip() or "eve"
    sample = (body.text or "").strip()
    if not sample:
        sample = (
            f"Hi, I'm {voice_id.title()}. "
            "This is a short preview of how I sound when reading your messages."
        )
    # Keep previews cheap / fast
    if len(sample) > 280:
        sample = sample[:277] + "…"

    try:
        audio, content_type, _meta = await synthesize_speech(
            provider,
            "grok-tts",
            sample,
            voice_id=voice_id,
            language=language,
        )
    except TtsError as e:
        raise HTTPException(e.status_code if 400 <= e.status_code < 600 else 502, str(e))
    except Exception as e:
        raise HTTPException(502, f"Preview failed: {e}")

    return Response(
        content=audio,
        media_type=content_type or "audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="voice-preview.mp3"',
            "X-Voice-Id": voice_id,
        },
    )


# ── Auto-update models ─────────────────────────────────────────────────────────

@router.post("/models/auto-update")
async def auto_update_all():
    results = await update_all_auto_providers()
    return {
        "results": results,
        "catalog": settings_store.public_catalog(),
    }


@router.post("/models/auto-update/{provider_id}")
async def auto_update_one(provider_id: str):
    try:
        updated, msg = await update_provider_models(provider_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Upstream model list failed: {e}")
    return {
        "ok": True,
        "message": msg,
        "provider": updated,
        "catalog": settings_store.public_catalog(),
    }


# ── Guided / AI-assisted API setup ─────────────────────────────────────────────

@router.get("/setup/presets")
async def setup_presets():
    from app.services.setup import list_presets_public
    return {"presets": list_presets_public()}


@router.post("/setup/suggest")
async def setup_suggest(body: SetupSuggestIn):
    """Turn free text like 'Groq llama 8B' into a fillable provider proposal."""
    from app.services.setup import suggest_from_description, suggest_with_ai

    if body.use_ai:
        result = await suggest_with_ai(body.description)
    else:
        result = suggest_from_description(body.description)
    return result


@router.post("/setup/discover")
async def setup_discover(body: SetupDiscoverIn):
    """
    Conversational setup:
      describe → optional clarifying questions → reuse key → test → auto-apply.
    """
    from app.services.setup import discover_setup

    try:
        result = await discover_setup(
            body.message,
            history=[t.model_dump() for t in body.history],
            answers=body.answers or {},
            api_key=body.api_key,
            auto_apply=body.auto_apply,
            use_ai=body.use_ai,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    return result


@router.post("/setup/apply")
async def setup_apply(body: SetupApplyIn):
    """Save provider + model(s) + key, then optionally test the key."""
    from app.services.setup import apply_setup

    proposal = body.model_dump()
    proposal["models"] = [m.model_dump() for m in body.models]
    try:
        result = await apply_setup(
            proposal,
            api_key=body.api_key,
            run_test=body.run_test,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    return result
