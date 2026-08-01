# Text-to-speech capability handler.
# xAI returns raw MP3 bytes from POST /v1/tts. We store them and return a short
# /api/v1/media/{id}.mp3 URL so markdown + the chat player work (huge data: URLs
# dump base64 into the bubble and break markdown link parsing).

from __future__ import annotations

from typing import AsyncIterator, Optional

from app.services.handlers.types import RequestContext
from app.services.media_store import store_media
from app.services.tts import (
    TtsError,
    parse_tts_directives,
    synthesize_speech,
    tts_api_style,
)


class TtsHandler:
    name = "tts"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        raw = (ctx.last_user_text() or "").strip()
        if not raw:
            yield (
                "**No text to speak.**\n\n"
                "Type something and Send while a text-to-speech model is selected.\n\n"
                "Optional directives on their own lines at the top:\n"
                "```\n"
                "voice: ara\n"
                "language: en\n"
                "speed: 1.0\n"
                "Hello, this is what will be spoken.\n"
                "```\n"
            )
            return

        spoken, opts = parse_tts_directives(raw)
        if not spoken:
            # Whole message was directives only — or treat full raw as speech
            spoken = raw if not opts else ""
        if not spoken:
            yield "**No spoken text after directives.** Add the text you want spoken below `voice:` / `language:` lines."
            return

        # Preferred voice/language from Admin → Voice (overridable per message)
        try:
            from app.services import settings_store
            prefs = settings_store.get_preferences() or {}
        except Exception:
            prefs = {}
        voice = opts.get("voice_id") or prefs.get("tts_voice") or "eve"
        language = opts.get("language") or prefs.get("tts_language") or "en"
        speed: Optional[float] = None
        if opts.get("speed"):
            try:
                speed = float(opts["speed"])
            except ValueError:
                speed = None

        label = (ctx.provider or {}).get("label") or ctx.ai
        style = tts_api_style(ctx.provider or {})
        model = ctx.model or "grok-tts"

        yield (
            f"Generating speech with **{label}** "
            f"(voice `{voice}`, language `{language}`)…\n\n"
        )

        try:
            audio, content_type, meta = await synthesize_speech(
                ctx.provider,
                model,
                spoken,
                voice_id=voice,
                language=language,
                speed=speed,
            )
        except TtsError as e:
            yield f"**Speech generation failed:** {e}"
            return
        except Exception as e:
            yield f"**Speech generation error:** {e}"
            return

        try:
            _id, public_url = store_media(audio, content_type)
        except Exception as e:
            yield f"**Could not store audio for playback:** {e}"
            return

        # Short relative URL — frontend media player detects .mp3 / /media/
        # Keep link text plain (no emoji) so markdown + player attach reliably.
        yield "### Speech\n\n"
        yield f"[Play speech]({public_url})\n\n"

        # Quote a short preview of what was spoken (not the whole essay)
        preview = spoken if len(spoken) <= 280 else spoken[:277] + "…"
        preview_safe = preview.replace("```", "'''")
        yield f"> {preview_safe.replace(chr(10), ' ')}\n\n"

        extras = [
            f"voice: `{voice}`",
            f"language: `{language}`",
            f"{meta.get('bytes', len(audio)):,} bytes",
            f"`{content_type}`",
        ]
        if meta.get("duration") is not None:
            extras.append(f"duration: `{meta['duration']}`s")
        if speed is not None:
            extras.append(f"speed: `{speed}`")
        endpoint = "/v1/tts" if style == "xai" else "/v1/audio/speech"
        extras.append(f"via `{endpoint}`")
        yield f"_{' · '.join(extras)}_\n"
