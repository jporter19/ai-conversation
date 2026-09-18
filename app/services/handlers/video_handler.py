# Video generation is catalogued but not wired to a vendor video API yet.

from __future__ import annotations

from typing import AsyncIterator

from app.services.handlers.types import RequestContext


class VideoHandler:
    name = "video"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        model = ctx.model or "this video model"
        yield (
            f"Video generation is not enabled in this hub yet (`{model}`). "
            "Pick a chat model for conversation, or an image model to make a still picture."
        )
