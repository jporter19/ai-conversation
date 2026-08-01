# app/services/stt.py
# Purpose: Speech-to-text via xAI /v1/stt or OpenAI-compatible /audio/transcriptions.

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import httpx

from app.config import resolve_api_key


class SttError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def stt_api_style(provider: Dict[str, Any]) -> str:
    """
    How to call STT for this provider.
      - xai: POST {base}/stt (multipart)
      - openai: POST {base}/audio/transcriptions
    """
    explicit = (provider.get("stt_api") or "").lower().strip()
    if explicit in ("xai", "openai"):
        return explicit
    base = (provider.get("base_url") or "").lower()
    if "x.ai" in base:
        return "xai"
    return "openai"


async def transcribe_audio(
    provider: Dict[str, Any],
    model: str,
    audio_bytes: bytes,
    filename: str = "audio.wav",
    content_type: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Transcribe audio bytes. Returns (transcript_text, raw_meta).
    """
    if not audio_bytes:
        raise SttError("No audio data provided", 400)

    base = (provider.get("base_url") or "").rstrip("/")
    if not base:
        raise SttError("Provider has no base_url", 400)

    key_name = provider.get("api_key_name") or ""
    api_key = resolve_api_key(key_name) if key_name else None
    if not api_key:
        raise SttError(
            f"API key not configured for {key_name or provider.get('id')}. "
            "Add it under Admin → API Keys.",
            401,
        )

    style = stt_api_style(provider)
    ctype = content_type or _guess_content_type(filename)
    safe_name = filename or "audio.wav"

    if style == "xai":
        return await _transcribe_xai(
            base, api_key, model, audio_bytes, safe_name, ctype, language
        )
    return await _transcribe_openai(
        base, api_key, model, audio_bytes, safe_name, ctype, language
    )


async def _transcribe_xai(
    base: str,
    api_key: str,
    model: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    language: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    url = f"{base}/stt"
    headers = {"Authorization": f"Bearer {api_key}"}
    data: Dict[str, str] = {
        "model": model or "grok-stt",
        "format": "json",
    }
    if language:
        data["language"] = language

    files = {"file": (filename, audio_bytes, content_type)}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(url, headers=headers, data=data, files=files)
    except httpx.TimeoutException as e:
        raise SttError(f"xAI STT timed out: {e}", 504) from e
    except Exception as e:
        raise SttError(f"xAI STT connection error: {e}", 502) from e

    return _parse_transcript_response(r, label="xAI STT")


async def _transcribe_openai(
    base: str,
    api_key: str,
    model: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    language: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    # OpenAI / Groq / compatible
    url = f"{base}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    data: Dict[str, str] = {
        "model": model or "whisper-1",
        "response_format": "json",
    }
    if language:
        data["language"] = language

    files = {"file": (filename, audio_bytes, content_type)}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(url, headers=headers, data=data, files=files)
    except httpx.TimeoutException as e:
        raise SttError(f"STT timed out: {e}", 504) from e
    except Exception as e:
        raise SttError(f"STT connection error: {e}", 502) from e

    return _parse_transcript_response(r, label="Audio transcriptions")


def _parse_transcript_response(
    r: httpx.Response,
    label: str,
) -> Tuple[str, Dict[str, Any]]:
    body_preview = (r.text or "")[:400]
    if r.status_code != 200:
        hint = {
            400: "Bad request — check model id / audio format",
            401: "Unauthorized — API key invalid",
            403: "Forbidden — key lacks permission for STT",
            404: "STT endpoint not found — base URL may be wrong",
            413: "Audio file too large",
            429: "Rate limited",
        }.get(r.status_code, "Request failed")
        raise SttError(
            f"{label}: {hint} (HTTP {r.status_code}). {body_preview}",
            r.status_code if r.status_code < 500 else 502,
        )

    meta: Dict[str, Any] = {}
    try:
        data = r.json()
        if isinstance(data, dict):
            meta = data
            text = (
                data.get("text")
                or data.get("transcript")
                or data.get("transcription")
                or ""
            )
            if not text and isinstance(data.get("segments"), list):
                text = " ".join(
                    (s.get("text") or "").strip()
                    for s in data["segments"]
                    if isinstance(s, dict)
                ).strip()
        else:
            text = str(data)
    except Exception:
        # Some APIs return plain text
        text = (r.text or "").strip()

    text = (text or "").strip()
    # Empty text is a valid result (silence / pure tone / no speech detected)
    if not text:
        text = ""
        meta = {**meta, "empty": True}
    return text, meta


def _guess_content_type(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".mp3"):
        return "audio/mpeg"
    if name.endswith(".wav"):
        return "audio/wav"
    if name.endswith(".m4a"):
        return "audio/mp4"
    if name.endswith(".ogg") or name.endswith(".oga"):
        return "audio/ogg"
    if name.endswith(".webm"):
        return "audio/webm"
    if name.endswith(".flac"):
        return "audio/flac"
    if name.endswith(".mp4"):
        return "video/mp4"
    if name.endswith(".mpeg") or name.endswith(".mpga"):
        return "audio/mpeg"
    return "application/octet-stream"
