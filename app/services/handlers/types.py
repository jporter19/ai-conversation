# Shared request context for capability handlers.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol


@dataclass
class RequestContext:
    """Normalized request passed to all capability handlers."""

    ai: str
    model: str
    messages: List[Dict[str, str]]  # role + content only
    provider: Dict[str, Any]
    # Optional audio for speech-to-text
    audio_bytes: Optional[bytes] = None
    audio_filename: Optional[str] = None
    audio_content_type: Optional[str] = None
    audio_language: Optional[str] = None

    def last_user_text(self) -> str:
        for m in reversed(self.messages):
            if m.get("role") == "user" and m.get("content"):
                return m["content"]
        if self.messages:
            return self.messages[-1].get("content") or ""
        return ""


class CapabilityHandler(Protocol):
    """Stream text (markdown) chunks for the client."""

    name: str

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        ...
