# Tool providers (non-LLM capabilities): registry by provider id / tool_handler key.

from __future__ import annotations

from typing import Dict

from app.services.handlers.tools.youtube import YoutubeTranscriptHandler

# Map provider.tool_handler or provider.id → handler instance
TOOL_REGISTRY: Dict[str, object] = {
    "youtube": YoutubeTranscriptHandler(),
}


def get_tool_handler(provider: dict):
    """
    Resolve a tool handler for a catalog provider.
    Prefer explicit provider['tool_handler'], else provider['id'].
    """
    key = (provider.get("tool_handler") or provider.get("id") or "").strip().lower()
    return TOOL_REGISTRY.get(key)


def list_tool_ids():
    return sorted(TOOL_REGISTRY.keys())
