# YouTube transcript tool provider.

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.services.handlers.types import RequestContext
from app.services.youtube_transcript import fetch_transcript


class YoutubeTranscriptHandler:
    """
    Non-LLM tool: last user message is a YouTube URL or video id.
    Streams markdown transcript text.
    """

    name = "youtube"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        user_text = ctx.last_user_text()
        try:
            video_id, text = await asyncio.to_thread(fetch_transcript, user_text)
            yield f"**YouTube transcript** (`{video_id}`)\n\n{text}"
        except Exception as e:
            yield f"[Error: {e}]"
