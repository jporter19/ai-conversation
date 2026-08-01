# app/services/capability.py
# Purpose: Single source of truth for model capability (chat | image | transcript).
#          Catalog fields win; name heuristics are temporary migration fallbacks only.

from __future__ import annotations

from typing import Any, Dict, Optional


CAPABILITIES = frozenset({"chat", "image", "transcript", "stt", "tts"})


def get_model_entry(provider: Dict[str, Any], model_id: str) -> Optional[Dict[str, Any]]:
    for m in provider.get("models") or []:
        if m.get("value") == model_id:
            return m
    return None


def resolve_capability(provider: Dict[str, Any], model_id: str) -> str:
    """
    Resolve how a request should be handled.

    Priority:
      1. model.capability from provider catalog
      2. provider.type == "tool" → transcript (tool providers)
      3. Temporary name heuristics (remove when all models declare capability)
    """
    entry = get_model_entry(provider, model_id or "")
    if entry:
        cap = (entry.get("capability") or "chat").lower().strip()
        if cap in CAPABILITIES:
            return cap

    if (provider.get("type") or "").lower() == "tool":
        return "transcript"

    # Migration fallbacks — catalog should own these long-term
    mid = (model_id or "").lower()
    if mid and "vision" not in mid:
        if any(tok in mid for tok in ("imagine-image", "dall-e", "gpt-image", "-image")):
            return "image"
        if "image" in mid and "vision" not in mid:
            return "image"
    if any(tok in mid for tok in ("whisper", "-stt", "transcribe", "speech-to-text")):
        return "stt"
    if any(tok in mid for tok in ("-tts", "text-to-speech", "tts-1")):
        return "tts"
    if "transcript" in mid:
        return "transcript"
    return "chat"


def image_api_style(provider: Dict[str, Any]) -> str:
    """
    How to call the provider's image API.
      - openai: OpenAI Images API (response_format=url)
      - xai: xAI-style body (image_format=url)
    Prefer explicit provider.image_api; else infer from base_url.
    """
    explicit = (provider.get("image_api") or "").lower().strip()
    if explicit in ("openai", "xai"):
        return explicit
    base = (provider.get("base_url") or "").lower()
    if "x.ai" in base:
        return "xai"
    return "openai"


def supports_image_generation(provider: Dict[str, Any], model_id: str) -> bool:
    if resolve_capability(provider, model_id) == "image":
        return True
    return bool(provider.get("supports_image_gen")) and resolve_capability(provider, model_id) == "image"
