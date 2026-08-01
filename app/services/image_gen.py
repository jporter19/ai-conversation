# app/services/image_gen.py
# Purpose: Provider-config-driven image generation (no hardcoded chatgpt/grok ids).

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from openai import AsyncOpenAI

from app.config import resolve_api_key
from app.services.capability import image_api_style


class ImageGenError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


async def generate_image_url(
    provider: Dict[str, Any],
    model: str,
    prompt: str,
    *,
    size: str = "1024x1024",
    n: int = 1,
) -> str:
    """
    Generate one image URL using the provider's base_url + API key + image_api style.
    """
    if not prompt or not str(prompt).strip():
        raise ImageGenError("Missing prompt", 400)
    if not model:
        raise ImageGenError("Model is required", 400)

    key_name = provider.get("api_key_name")
    api_key = resolve_api_key(key_name) if key_name else None
    if not api_key:
        raise ImageGenError(
            f"API key {key_name or '(missing)'} not configured. Open Admin Tools to paste it.",
            500,
        )

    base_url = (provider.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    style = image_api_style(provider)

    if style == "xai":
        return await _generate_xai_style(base_url, api_key, model, prompt, n=n)

    return await _generate_openai_style(base_url, api_key, model, prompt, size=size, n=n)


async def _generate_openai_style(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    size: str,
    n: int,
) -> str:
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    # Some newer image models reject response_format; try with it, then without.
    try:
        resp = await client.images.generate(
            model=model,
            prompt=prompt,
            n=n,
            size=size,
            response_format="url",
        )
    except Exception:
        resp = await client.images.generate(
            model=model,
            prompt=prompt,
            n=n,
            size=size,
        )
    if not resp.data:
        raise ImageGenError("Image API returned no data", 502)
    url = getattr(resp.data[0], "url", None)
    if not url:
        # b64 responses are not handled yet
        raise ImageGenError("Image API returned no URL (b64 not supported here)", 502)
    return url


async def _generate_xai_style(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    n: int,
) -> str:
    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(
            f"{base_url}/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "prompt": prompt,
                "n": n,
                "image_format": "url",
            },
        )
        if r.status_code >= 400:
            raise ImageGenError(
                f"Image API error HTTP {r.status_code}: {(r.text or '')[:300]}",
                502,
            )
        data = r.json()
        try:
            return data["data"][0]["url"]
        except (KeyError, IndexError, TypeError) as e:
            raise ImageGenError(f"Unexpected image API payload: {e}", 502) from e


def image_markdown(url: str, prompt: str, model: str) -> str:
    short = (prompt or "").strip()
    if len(short) > 120:
        short = short[:120] + "..."
    # Escape minimal markdown breakage in alt text
    alt = short.replace("]", "").replace("\n", " ")
    return f'![{alt}]({url})\n\n*Generated with {model} from prompt: "{short}"*'
