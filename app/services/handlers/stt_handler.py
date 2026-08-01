# Speech-to-text capability handler.

from __future__ import annotations

from typing import AsyncIterator

from app.services.handlers.types import RequestContext
from app.services.stt import SttError, stt_api_style, transcribe_audio


class SttHandler:
    name = "stt"

    async def stream(self, ctx: RequestContext) -> AsyncIterator[str]:
        if not ctx.audio_bytes:
            yield (
                "**No audio attached.**\n\n"
                "Select a speech-to-text model, attach an audio file (or record), "
                "then click Send."
            )
            return

        filename = ctx.audio_filename or "audio.wav"
        model = ctx.model or "grok-stt"
        label = (ctx.provider or {}).get("label") or ctx.ai
        style = stt_api_style(ctx.provider or {})

        notes = (ctx.last_user_text() or "").strip()
        # Strip our synthetic "[Audio: …]" prefix if present in notes
        if notes.lower().startswith("[audio:"):
            # Keep any notes after the first line
            parts = notes.split("\n", 1)
            notes = parts[1].strip() if len(parts) > 1 else ""

        yield f"Transcribing `{filename}` with **{label}** (`{model}`)…\n\n"

        try:
            text, meta = await transcribe_audio(
                ctx.provider,
                model,
                ctx.audio_bytes,
                filename=filename,
                content_type=ctx.audio_content_type,
                language=ctx.audio_language,
            )
        except SttError as e:
            yield f"**Transcription failed:** {e}"
            return
        except Exception as e:
            yield f"**Transcription error:** {e}"
            return

        if text:
            yield f"### Transcript\n\n{text}\n"
        else:
            yield (
                "### Transcript\n\n"
                "_No speech detected in this audio_ "
                "(silence, pure tone, or unsupported content).\n"
            )

        if notes:
            yield f"\n---\n\n*Notes from you:* {notes}\n"

        # Optional light metadata
        extras = []
        if isinstance(meta, dict):
            if meta.get("language"):
                extras.append(f"language: `{meta['language']}`")
            if meta.get("duration") is not None:
                extras.append(f"duration: `{meta['duration']}`s")
        if extras:
            yield f"\n_{' · '.join(extras)}_\n"

        endpoint = "/v1/stt" if style == "xai" else "/v1/audio/transcriptions"
        yield f"\n<!-- stt via {endpoint} -->\n"
