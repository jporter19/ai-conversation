# app/services/youtube_transcript.py
# Purpose: Fetch YouTube transcripts via pluggable sources (local IP or home relay).

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, List, Optional, Protocol, Tuple
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{6,20}$")

_DEFAULT_LANGS = ["en", "en-US", "en-GB"]

_CLOUD_BLOCK_HINT = (
    "YouTube is blocking this server’s IP (common on AWS).\n\n"
    "**Recommended:** home-PC relay — see scripts/transcript_relay_app.py\n"
    "  YOUTUBE_TRANSCRIPT_RELAY_URL=http://127.0.0.1:8791\n"
    "  YOUTUBE_TRANSCRIPT_RELAY_TOKEN=...\n\n"
    "**Alternative:** residential proxy WEBSHARE_PROXY_USERNAME / PASSWORD"
)


def extract_video_id(text: str) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    if VIDEO_ID_RE.match(text):
        return text
    try:
        parsed = urlparse(text)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if "youtu.be" in host:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid if VIDEO_ID_RE.match(vid) else None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            vid = qs["v"][0]
            return vid if VIDEO_ID_RE.match(vid) else None
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
            vid = parts[1]
            return vid if VIDEO_ID_RE.match(vid) else None
    return None


def _require_video_id(video_url_or_id: str) -> str:
    vid = extract_video_id(video_url_or_id)
    if not vid:
        raise ValueError(
            "Could not parse a YouTube video id from the input. Paste a full URL or video id."
        )
    return vid


def _proxy_config() -> Any:
    ws_user = (os.environ.get("WEBSHARE_PROXY_USERNAME") or "").strip()
    ws_pass = (os.environ.get("WEBSHARE_PROXY_PASSWORD") or "").strip()
    if ws_user and ws_pass:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        return WebshareProxyConfig(proxy_username=ws_user, proxy_password=ws_pass)

    proxy_url = (os.environ.get("YOUTUBE_PROXY_URL") or "").strip()
    http_proxy = (
        os.environ.get("YOUTUBE_HTTP_PROXY") or os.environ.get("HTTP_PROXY") or ""
    ).strip()
    https_proxy = (
        os.environ.get("YOUTUBE_HTTPS_PROXY") or os.environ.get("HTTPS_PROXY") or ""
    ).strip()
    if proxy_url:
        http_proxy = http_proxy or proxy_url
        https_proxy = https_proxy or proxy_url
    if http_proxy or https_proxy:
        from youtube_transcript_api.proxies import GenericProxyConfig

        return GenericProxyConfig(http_url=http_proxy or None, https_url=https_proxy or None)
    return None


def _snippets_to_text(fetched) -> str:
    lines = []
    for item in fetched:
        if hasattr(item, "text"):
            lines.append(item.text)
        elif isinstance(item, dict) and "text" in item:
            lines.append(item["text"])
        else:
            lines.append(str(item))
    return "\n".join(lines).strip()


def _is_ip_block_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in {"RequestBlocked", "IpBlocked", "YouTubeRequestFailed"}:
        return True
    return any(
        s in msg
        for s in (
            "blocking requests from your ip",
            "cloud provider",
            "requestblocked",
            "ipblocked",
            "too many requests",
        )
    )


class TranscriptSource(Protocol):
    def fetch(self, video_id: str, languages: List[str]) -> str: ...


class LocalYoutubeSource:
    """Fetch via youtube-transcript-api on this host (optional residential proxy)."""

    def fetch(self, video_id: str, languages: List[str]) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as e:
            raise RuntimeError(
                "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"
            ) from e

        proxy = _proxy_config()
        api = YouTubeTranscriptApi(proxy_config=proxy)
        try:
            return _snippets_to_text(api.fetch(video_id, languages=languages))
        except Exception as e:
            try:
                return _snippets_to_text(api.fetch(video_id))
            except Exception as inner:
                if _is_ip_block_error(inner) or _is_ip_block_error(e):
                    extra = f"\n\n{_CLOUD_BLOCK_HINT}" if proxy is None else (
                        "\n\nProxy still blocked — use Webshare Residential rotating proxies."
                    )
                    raise RuntimeError(
                        f"Failed to fetch transcript for {video_id}: YouTube blocked the request.{extra}"
                    ) from inner
                raise RuntimeError(f"Failed to fetch transcript for {video_id}: {inner}") from e


class RelayHttpSource:
    """Call a home-PC (or other) relay over HTTP."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def fetch(self, video_id: str, languages: List[str]) -> str:
        url = f"{self.base_url}/v1/transcript"
        body = json.dumps(
            {"url_or_id": video_id, "video_id": video_id, "languages": languages}
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ai-conversation-hub/transcript-client",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
            try:
                err = json.loads(detail)
                detail = err.get("detail") or err.get("error") or detail
            except Exception:
                pass
            raise RuntimeError(f"Transcript relay HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                "Transcript relay unreachable. Start the home relay tray app "
                f"(or scripts/transcript_relay.py + tunnel). Looking for {self.base_url} — {e}"
            ) from e

        data = json.loads(raw)
        if not data.get("ok", True) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        text = (data.get("text") or "").strip()
        if not text:
            raise RuntimeError(f"Transcript relay returned empty text for {video_id}")
        return text


def get_transcript_source() -> TranscriptSource:
    base = (os.environ.get("YOUTUBE_TRANSCRIPT_RELAY_URL") or "").strip()
    if base:
        token = (os.environ.get("YOUTUBE_TRANSCRIPT_RELAY_TOKEN") or "").strip()
        timeout = float(os.environ.get("YOUTUBE_TRANSCRIPT_RELAY_TIMEOUT", "90"))
        return RelayHttpSource(base, token=token, timeout=timeout)
    return LocalYoutubeSource()


def fetch_transcript_local(
    video_url_or_id: str,
    languages: Optional[list] = None,
) -> Tuple[str, str]:
    """Always use local YouTube API (home relay worker). Never calls relay URL."""
    video_id = _require_video_id(video_url_or_id)
    langs = list(languages or _DEFAULT_LANGS)
    text = LocalYoutubeSource().fetch(video_id, langs)
    if not text:
        raise RuntimeError(f"No transcript text returned for video {video_id}")
    return video_id, text


def fetch_transcript(
    video_url_or_id: str,
    languages: Optional[list] = None,
) -> Tuple[str, str]:
    """Fetch via env-selected source (relay on AWS, local elsewhere)."""
    video_id = _require_video_id(video_url_or_id)
    langs = list(languages or _DEFAULT_LANGS)
    text = get_transcript_source().fetch(video_id, langs)
    if not text:
        raise RuntimeError(f"No transcript text returned for video {video_id}")
    return video_id, text
