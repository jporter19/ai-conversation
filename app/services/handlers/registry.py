# Capability → handler registry. chat.py stays thin HTTP plumbing.

from __future__ import annotations

from typing import Any, AsyncIterator, Dict

from fastapi.responses import StreamingResponse

from app.services.capability import resolve_capability
from app.services.handlers.chat_handler import ChatHandler
from app.services.handlers.image_handler import ImageHandler
from app.services.handlers.stt_handler import SttHandler
from app.services.handlers.tts_handler import TtsHandler
from app.services.handlers.tools import get_tool_handler
from app.services.handlers.types import CapabilityHandler, RequestContext

_CHAT = ChatHandler()
_IMAGE = ImageHandler()
_STT = SttHandler()
_TTS = TtsHandler()


class HandlerResolutionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_handler(provider: Dict[str, Any], model: str) -> CapabilityHandler:
    """
    Pick the handler for this provider + model.

    - image capability → ImageHandler
    - stt → SttHandler (needs audio on context; else prompts to attach)
    - tts → TtsHandler (speaks last user text; embeds audio for player)
    - transcript capability OR provider.type == tool → tool registry
    - else → ChatHandler
    """
    capability = resolve_capability(provider, model)
    ptype = (provider.get("type") or "").lower()

    if capability == "image":
        return _IMAGE

    if capability == "stt":
        return _STT  # type: ignore[return-value]

    if capability == "tts":
        return _TTS  # type: ignore[return-value]

    if capability == "transcript" or ptype == "tool":
        tool = get_tool_handler(provider)
        if tool is None:
            pid = provider.get("id") or "?"
            raise HandlerResolutionError(
                f"No tool handler registered for provider `{pid}`. "
                f"Set provider.tool_handler to a known tool id, or implement one under "
                f"app/services/handlers/tools/."
            )
        return tool  # type: ignore[return-value]

    return _CHAT


async def stream_response(ctx: RequestContext) -> StreamingResponse:
    """Run the resolved handler and wrap as plain-text StreamingResponse."""
    try:
        handler = get_handler(ctx.provider, ctx.model)
    except HandlerResolutionError as e:
        async def err_gen():
            yield f"[Error: {e}]"

        return StreamingResponse(err_gen(), media_type="text/plain; charset=utf-8")

    async def gen() -> AsyncIterator[str]:
        try:
            async for chunk in handler.stream(ctx):
                yield chunk
        except Exception as e:
            yield f"\n\n[Error: {e}]"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
