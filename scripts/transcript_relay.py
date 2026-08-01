#!/usr/bin/env python3
"""
Home-PC YouTube transcript relay for ai-conversation on AWS.

YouTube blocks AWS IPs. Run this on your home machine (non-cloud IP), then open
an SSH reverse tunnel so the EC2 app can call it on localhost.

  # Terminal 1 — home PC (repo venv)
  .venv/bin/python scripts/transcript_relay.py --token 'YOUR_SHARED_SECRET'

  # Terminal 2 — home PC
  YOUTUBE_TRANSCRIPT_RELAY_TOKEN='YOUR_SHARED_SECRET' ./scripts/transcript_relay_tunnel.sh

On EC2 /etc/ai-conversation/env:
  YOUTUBE_TRANSCRIPT_RELAY_URL=http://127.0.0.1:8791
  YOUTUBE_TRANSCRIPT_RELAY_TOKEN=YOUR_SHARED_SECRET
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Relay must never call itself
os.environ.pop("YOUTUBE_TRANSCRIPT_RELAY_URL", None)

from app.services.youtube_transcript import (  # noqa: E402
    extract_video_id,
    fetch_transcript_local,
)


def _authorized(handler: BaseHTTPRequestHandler, expected: Optional[str]) -> bool:
    if not expected:
        return True
    auth = handler.headers.get("Authorization") or ""
    if auth == f"Bearer {expected}":
        return True
    if handler.headers.get("X-Relay-Token") == expected:
        return True
    return False


def make_handler(token: Optional[str]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/health"):
                self._json(200, {"ok": True, "service": "youtube-transcript-relay"})
                return
            self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/v1/transcript":
                self._json(404, {"ok": False, "error": "not found"})
                return
            if not _authorized(self, token):
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                n = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                n = 0
            raw = self.rfile.read(n) if n > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return

            url_or_id = (data.get("url_or_id") or data.get("video_id") or "").strip()
            languages = data.get("languages") or ["en", "en-US", "en-GB"]
            if not url_or_id:
                self._json(400, {"ok": False, "error": "url_or_id required"})
                return
            if not extract_video_id(url_or_id):
                self._json(400, {"ok": False, "error": "could not parse YouTube id"})
                return

            try:
                video_id, text = fetch_transcript_local(url_or_id, languages=languages)
            except Exception as e:
                self._json(502, {"ok": False, "error": str(e), "detail": str(e)})
                return

            self._json(
                200,
                {
                    "ok": True,
                    "video_id": video_id,
                    "text": text,
                    "chars": len(text),
                },
            )

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Home-PC YouTube transcript relay")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8791, help="Port (default 8791)")
    parser.add_argument(
        "--token",
        default=os.environ.get("YOUTUBE_TRANSCRIPT_RELAY_TOKEN", ""),
        help="Shared bearer token (or env YOUTUBE_TRANSCRIPT_RELAY_TOKEN)",
    )
    args = parser.parse_args()
    token = (args.token or "").strip() or None
    if not token:
        print(
            "WARNING: no --token / YOUTUBE_TRANSCRIPT_RELAY_TOKEN — relay is open to anyone who can reach it.",
            file=sys.stderr,
        )

    server = ThreadingHTTPServer((args.host, args.port), make_handler(token))
    print(
        f"Transcript relay listening on http://{args.host}:{args.port} "
        f"(token={'set' if token else 'none'})",
        flush=True,
    )
    print("Health: GET /health   Transcript: POST /v1/transcript", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
