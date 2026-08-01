# app/services/tts.py
# Purpose: Text-to-speech via xAI POST /v1/tts (raw audio) or OpenAI
#          POST /v1/audio/speech.

from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import resolve_api_key

# xAI built-in voice ids (case-insensitive). Default is eve.
XAI_VOICES = frozenset({
    "ara", "eve", "leo", "rex", "sal",
    "carina", "zagan", "helix", "orion", "luna", "iris", "altair",
    "zenith", "perseus", "helios", "lux", "kepler", "rigel", "cosmo",
    "lumen", "castor", "naksh", "atlas",
})

# Human-readable descriptions for Admin UI (fallback if API omits them)
XAI_VOICE_META: Dict[str, Dict[str, str]] = {
    "eve": {"name": "Eve", "tone": "Energetic and upbeat", "gender": "female"},
    "ara": {"name": "Ara", "tone": "Warm and friendly", "gender": "female"},
    "leo": {"name": "Leo", "tone": "Authoritative and strong", "gender": "male"},
    "rex": {"name": "Rex", "tone": "Confident and clear", "gender": "male"},
    "sal": {"name": "Sal", "tone": "Smooth and balanced", "gender": "male"},
    "carina": {"name": "Carina", "tone": "Soft, empathetic, soothing", "gender": "female"},
    "luna": {"name": "Luna", "tone": "Gentle, patient, nurturing", "gender": "female"},
    "iris": {"name": "Iris", "tone": "Friendly, upbeat, charming", "gender": "female"},
    "altair": {"name": "Altair", "tone": "Elegant, refined, premium", "gender": "male"},
    "orion": {"name": "Orion", "tone": "Rich, cinematic, resonant", "gender": "male"},
    "atlas": {"name": "Atlas", "tone": "Confident, commanding", "gender": "male"},
    "helios": {"name": "Helios", "tone": "Upbeat, energetic, versatile", "gender": "male"},
    "lux": {"name": "Lux", "tone": "Grounded, calm, wise", "gender": "neutral"},
    "kepler": {"name": "Kepler", "tone": "Inventive, charismatic", "gender": "male"},
    "rigel": {"name": "Rigel", "tone": "Precise, professional", "gender": "male"},
    "cosmo": {"name": "Cosmo", "tone": "Bright, curious", "gender": "neutral"},
    "lumen": {"name": "Lumen", "tone": "Warm, articulate", "gender": "neutral"},
    "castor": {"name": "Castor", "tone": "Charismatic, easygoing", "gender": "male"},
    "naksh": {"name": "Naksh", "tone": "Warm, thoughtful, wise", "gender": "male"},
    "zagan": {"name": "Zagan", "tone": "Powerful, dramatic", "gender": "male"},
    "helix": {"name": "Helix", "tone": "Bold, dynamic", "gender": "neutral"},
    "zenith": {"name": "Zenith", "tone": "Sharp, focused", "gender": "neutral"},
    "perseus": {"name": "Perseus", "tone": "Strong, trustworthy", "gender": "male"},
}

OPENAI_VOICES = frozenset({
    "alloy", "ash", "ballad", "coral", "echo", "fable", "onyx",
    "nova", "sage", "shimmer", "verse",
})

OPENAI_VOICE_META: Dict[str, Dict[str, str]] = {
    vid: {"name": vid.title(), "tone": "OpenAI TTS voice", "gender": "neutral"}
    for vid in sorted(OPENAI_VOICES)
}


class TtsError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def tts_api_style(provider: Optional[Dict[str, Any]]) -> str:
    """
    How to call TTS for this provider.
      - xai: POST {base}/tts  JSON {text, voice_id, language} → raw audio
      - openai: POST {base}/audio/speech  JSON {model, input, voice} → raw audio
    """
    provider = provider or {}
    explicit = (provider.get("tts_api") or "").lower().strip()
    if explicit in ("xai", "openai"):
        return explicit
    base = (provider.get("base_url") or "").lower()
    if "x.ai" in base:
        return "xai"
    return "openai"


async def list_voices(provider: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    List voices for Admin UI. Prefers live xAI GET /v1/tts/voices when keyed.
    """
    style = tts_api_style(provider) if provider else "xai"
    if style == "xai" and provider:
        live = await _fetch_xai_voices(provider)
        if live is not None:
            return live
        return {
            "ok": True,
            "source": "fallback",
            "style": "xai",
            "voices": _static_voice_list("xai"),
            "message": "Using built-in voice list (could not reach xAI /v1/tts/voices).",
        }
    if style == "openai":
        return {
            "ok": True,
            "source": "static",
            "style": "openai",
            "voices": _static_voice_list("openai"),
            "message": "OpenAI voice ids (static list).",
        }
    return {
        "ok": True,
        "source": "fallback",
        "style": "xai",
        "voices": _static_voice_list("xai"),
        "message": "No TTS provider configured — showing Grok voice list.",
    }


def _static_voice_list(style: str) -> List[Dict[str, Any]]:
    if style == "openai":
        meta = OPENAI_VOICE_META
        ids = sorted(OPENAI_VOICES)
    else:
        meta = XAI_VOICE_META
        ids = sorted(XAI_VOICES)
    out = []
    for vid in ids:
        m = meta.get(vid) or {}
        out.append({
            "voice_id": vid,
            "name": m.get("name") or vid.title(),
            "language": "multilingual" if style == "xai" else "en",
            "gender": m.get("gender") or "neutral",
            "tone": m.get("tone") or "",
        })
    return out


async def _fetch_xai_voices(provider: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    base = (provider.get("base_url") or "").rstrip("/")
    if not base:
        return None
    key_name = provider.get("api_key_name") or "XAI_API_KEY"
    api_key = resolve_api_key(key_name)
    if not api_key:
        return None
    url = f"{base}/tts/voices"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code != 200:
            return None
        data = r.json()
        raw = data.get("voices") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return None
        voices = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            vid = (item.get("voice_id") or item.get("id") or "").strip()
            if not vid:
                continue
            meta = XAI_VOICE_META.get(vid.lower()) or {}
            voices.append({
                "voice_id": vid,
                "name": item.get("name") or meta.get("name") or vid.title(),
                "language": item.get("language") or "multilingual",
                "gender": item.get("gender") or meta.get("gender") or "neutral",
                "tone": meta.get("tone") or item.get("description") or "",
            })
        voices.sort(key=lambda v: (v.get("name") or v["voice_id"]).lower())
        return {
            "ok": True,
            "source": "xai",
            "style": "xai",
            "voices": voices,
            "message": f"Loaded {len(voices)} voices from xAI.",
        }
    except Exception:
        return None


def parse_tts_directives(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Optional leading directives (case-insensitive), one per line:
      voice: ara
      language: en
      speed: 1.1
    Remaining lines are the spoken text.
    """
    raw = (text or "").strip()
    if not raw:
        return "", {}

    lines = raw.splitlines()
    opts: Dict[str, str] = {}
    i = 0
    key_re = re.compile(
        r"^(voice|voice_id|language|lang|speed|codec)\s*[:=]\s*(.+)$",
        re.I,
    )
    while i < len(lines):
        m = key_re.match(lines[i].strip())
        if not m:
            break
        key = m.group(1).lower()
        val = m.group(2).strip().strip("\"'")
        if key in ("voice", "voice_id"):
            opts["voice_id"] = val
        elif key in ("language", "lang"):
            opts["language"] = val
        elif key == "speed":
            opts["speed"] = val
        elif key == "codec":
            opts["codec"] = val
        i += 1

    spoken = "\n".join(lines[i:]).strip()
    return spoken, opts


async def synthesize_speech(
    provider: Dict[str, Any],
    model: str,
    text: str,
    *,
    voice_id: Optional[str] = None,
    language: Optional[str] = None,
    speed: Optional[float] = None,
) -> Tuple[bytes, str, Dict[str, Any]]:
    """
    Synthesize speech. Returns (audio_bytes, content_type, meta).
    """
    spoken = (text or "").strip()
    if not spoken:
        raise TtsError("No text to speak", 400)
    if len(spoken) > 15000:
        raise TtsError(
            f"Text is too long ({len(spoken)} chars). Max is 15,000 for REST TTS.",
            400,
        )

    base = (provider.get("base_url") or "").rstrip("/")
    if not base:
        raise TtsError("Provider has no base_url", 400)

    key_name = provider.get("api_key_name") or ""
    api_key = resolve_api_key(key_name) if key_name else None
    if not api_key:
        raise TtsError(
            f"API key not configured for {key_name or provider.get('id')}. "
            "Add it under Admin → API Keys.",
            401,
        )

    style = tts_api_style(provider)
    if style == "xai":
        return await _xai_tts(
            base, api_key, spoken,
            voice_id=voice_id or "eve",
            language=language or "en",
            speed=speed,
        )
    return await _openai_tts(
        base, api_key, model or "tts-1", spoken,
        voice=voice_id or "alloy",
        speed=speed,
    )


async def _xai_tts(
    base: str,
    api_key: str,
    text: str,
    *,
    voice_id: str,
    language: str,
    speed: Optional[float],
) -> Tuple[bytes, str, Dict[str, Any]]:
    """
    xAI REST TTS:
      POST https://api.x.ai/v1/tts
      JSON: text (required), voice_id, language (required), output_format?, speed?
      Response: raw audio bytes (default audio/mpeg), NOT a URL.
    Docs: https://docs.x.ai/developers/model-capabilities/audio/text-to-speech
    """
    url = f"{base}/tts"
    payload: Dict[str, Any] = {
        "text": text,
        "voice_id": (voice_id or "eve").strip() or "eve",
        "language": (language or "en").strip() or "en",
        "output_format": {
            "codec": "mp3",
            "sample_rate": 24000,
            "bit_rate": 128000,
        },
    }
    if speed is not None:
        # API range 0.7–1.5
        payload["speed"] = max(0.7, min(1.5, float(speed)))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg, application/json, */*",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        raise TtsError(f"xAI TTS timed out: {e}", 504) from e
    except Exception as e:
        raise TtsError(f"xAI TTS connection error: {e}", 502) from e

    return _parse_audio_response(r, label="xAI TTS", default_ct="audio/mpeg")


async def _openai_tts(
    base: str,
    api_key: str,
    model: str,
    text: str,
    *,
    voice: str,
    speed: Optional[float],
) -> Tuple[bytes, str, Dict[str, Any]]:
    """OpenAI-compatible POST /audio/speech → raw audio bytes."""
    url = f"{base}/audio/speech"
    payload: Dict[str, Any] = {
        "model": model or "tts-1",
        "input": text,
        "voice": (voice or "alloy").strip() or "alloy",
        "response_format": "mp3",
    }
    if speed is not None:
        payload["speed"] = max(0.25, min(4.0, float(speed)))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg, application/json, */*",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        raise TtsError(f"TTS timed out: {e}", 504) from e
    except Exception as e:
        raise TtsError(f"TTS connection error: {e}", 502) from e

    return _parse_audio_response(r, label="Audio speech", default_ct="audio/mpeg")


def _parse_audio_response(
    r: httpx.Response,
    label: str,
    default_ct: str,
) -> Tuple[bytes, str, Dict[str, Any]]:
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    body = r.content or b""

    if r.status_code != 200:
        detail = ""
        try:
            detail = (r.text or "")[:400]
        except Exception:
            detail = body[:200].decode("utf-8", errors="replace")
        hint = {
            400: "Bad request — check text / voice_id / language",
            401: "Unauthorized — API key invalid",
            403: "Forbidden — key lacks TTS permission",
            404: "TTS endpoint not found — base URL may be wrong",
            422: "Invalid request body (xAI needs text + language; not model/input)",
            429: "Rate limited",
        }.get(r.status_code, "Request failed")
        raise TtsError(
            f"{label}: {hint} (HTTP {r.status_code}). {detail}",
            r.status_code if r.status_code < 500 else 502,
        )

    meta: Dict[str, Any] = {"http_content_type": ct, "bytes": len(body)}

    # JSON envelope (with_timestamps=true, or some gateways)
    if "json" in ct or (body[:1] == b"{" and b"audio" in body[:200]):
        try:
            data = r.json()
        except Exception as e:
            raise TtsError(f"{label}: expected JSON audio envelope but parse failed: {e}", 502)
        if not isinstance(data, dict):
            raise TtsError(f"{label}: unexpected JSON response", 502)
        b64 = data.get("audio") or data.get("data")
        if not b64 or not isinstance(b64, str):
            raise TtsError(f"{label}: JSON response missing base64 'audio' field", 502)
        try:
            audio = base64.b64decode(b64)
        except Exception as e:
            raise TtsError(f"{label}: invalid base64 audio: {e}", 502)
        out_ct = (
            data.get("content_type")
            or data.get("mime_type")
            or default_ct
        )
        meta["duration"] = data.get("duration")
        meta["json_envelope"] = True
        if not audio:
            raise TtsError(f"{label}: empty audio payload", 502)
        return audio, str(out_ct), meta

    # Raw audio bytes (xAI default — audio/mpeg)
    if not body:
        raise TtsError(f"{label}: empty audio body", 502)

    if not ct or ct in ("application/octet-stream", "binary/octet-stream"):
        # Sniff MPEG frame sync
        if body[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xe3") or body[:3] == b"ID3":
            ct = "audio/mpeg"
        elif body[:4] == b"RIFF":
            ct = "audio/wav"
        elif body[:4] == b"OggS":
            ct = "audio/ogg"
        else:
            ct = default_ct

    if ct.startswith("text/") or ct == "application/json":
        raise TtsError(
            f"{label}: unexpected content-type {ct}: {body[:200]!r}",
            502,
        )

    return body, ct, meta


def audio_to_data_url(audio: bytes, content_type: str) -> str:
    """Embed audio for the chat markdown media player (no separate host URL)."""
    mime = (content_type or "audio/mpeg").split(";")[0].strip() or "audio/mpeg"
    b64 = base64.b64encode(audio).decode("ascii")
    return f"data:{mime};base64,{b64}"
