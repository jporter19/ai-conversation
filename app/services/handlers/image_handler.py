# Image generation capability handler.

from __future__ import annotations

from typing import AsyncIterator

from app.services.handlers.types import RequestContext
from app.services.image_gen import ImageGenError, generate_image_url, image_markdown


class ImageHandler:
    name = "image"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        prompt = ctx.last_user_text()
        model = ctx.model
        try:
            url = await generate_image_url(ctx.provider, model, prompt)
            yield image_markdown(url, prompt, model)
        except ImageGenError as e:
            yield f"[Error: {e}]"
        except Exception as e:
            yield f"[Error: image generation failed: {e}]"
