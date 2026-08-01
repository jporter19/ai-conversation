# Shared RequestContext construction + provider validation for HTTP routes.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.services.capability import resolve_capability
from app.services.handlers.types import RequestContext
from app.services.settings_store import get_provider


def require_provider(ai: Optional[str]) -> Dict[str, Any]:
    if not ai:
        raise HTTPException(status_code=400, detail="AI provider is required")
    provider = get_provider(ai)
    if not provider or not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"Unknown or disabled AI: {ai}")
    return provider


def require_model(model: Optional[str]) -> str:
    if not model:
        raise HTTPException(status_code=400, detail="Model is required")
    return model


def build_context(
    *,
    ai: str,
    model: str,
    messages: List[Dict[str, Any]],
    require_capability: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    audio_filename: Optional[str] = None,
    audio_content_type: Optional[str] = None,
    audio_language: Optional[str] = None,
) -> RequestContext:
    provider = require_provider(ai)
    model = require_model(model)
    if require_capability:
        cap = resolve_capability(provider, model)
        if cap != require_capability:
            # legacy image flag still honored only for image
            if not (
                require_capability == "image"
                and provider.get("supports_image_gen")
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Model `{model}` is not a {require_capability} model "
                        f"(capability={cap})."
                    ),
                )
    return RequestContext(
        ai=ai,
        model=model,
        messages=messages,
        provider=provider,
        audio_bytes=audio_bytes,
        audio_filename=audio_filename,
        audio_content_type=audio_content_type,
        audio_language=audio_language,
    )
