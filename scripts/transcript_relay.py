#!/usr/bin/env python3
"""
Home-PC YouTube transcript relay for ai-conversation on AWS (Lightsail or EC2).

YouTube blocks cloud IPs. Run this on your home machine (non-cloud IP), then open
an SSH reverse tunnel so the hub can call it on localhost.

  # Terminal 1 — home PC (repo venv)
  .venv/bin/python scripts/transcript_relay.py --token 'YOUR_SHARED_SECRET'

  # Terminal 2 — home PC (Lightsail default; or DEPLOY_TARGET=ec2)
  ./scripts/transcript_relay_tunnel.sh

On the hub (/etc/ai-conversation/env):
  YOUTUBE_TRANSCRIPT_RELAY_URL=http://127.0.0.1:8791
  YOUTUBE_TRANSCRIPT_RELAY_TOKEN=YOUR_SHARED_SECRET

Or use the tray UI: scripts/transcript_relay_app.py (Lightsail | EC2 tabs).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Relay must never call itself
os.environ.pop("YOUTUBE_TRANSCRIPT_RELAY_URL", None)

from app.services.youtube_transcript import (  # noqa: E402
    extract_video_id,
    fetch_transcript_local,
)

# Bound request size / concurrency so a stuck or abusive client cannot grow forever.
MAX_BODY_BYTES = 64 * 1024
MAX_IN_FLIGHT = 4
REQUEST_SOCKET_TIMEOUT_SEC = 120.0

_sem = threading.BoundedSemaphore(MAX_IN_FLIGHT)


def _authorized(handler: BaseHTTPRequestHandler, expected: Optional[str]) -> bool:
    if not expected:
        return True
    auth = handler.headers.get("Authorization") or ""
    if auth == f"Bearer {expected}":
        return True
    if handler.headers.get("X-Relay-Token") == expected:
        return True
    return False


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server with request socket timeout and daemon worker threads."""

    daemon_threads = True  # do not block process exit on hung workers
    allow_reuse_address = True
    request_queue_size = 8

    def get_request(self):  # noqa: D401
        sock, addr = super().get_request()
        try:
            sock.settimeout(REQUEST_SOCKET_TIMEOUT_SEC)
        except OSError:
            pass
        return sock, addr


def make_handler(token: Optional[str]):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            # Keep logs short; avoid huge dumps if a client floods
            try:
                msg = fmt % args
            except Exception:
                msg = fmt
            if len(msg) > 300:
                msg = msg[:300] + "…"
            sys.stderr.write("%s - %s\n" % (self.address_string(), msg))

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            # Cap response size reporting only; transcript text can be large but finite
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/health"):
                self._json(
                    200,
                    {
                        "ok": True,
                        "service": "youtube-transcript-relay",
                        "in_flight_limit": MAX_IN_FLIGHT,
                    },
                )
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
            if n < 0:
                n = 0
            if n > MAX_BODY_BYTES:
                self._json(
                    413,
                    {
                        "ok": False,
                        "error": f"request body too large (max {MAX_BODY_BYTES} bytes)",
                    },
                )
                return

            raw = self.rfile.read(n) if n > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return

            url_or_id = (data.get("url_or_id") or data.get("video_id") or "").strip()
            languages = data.get("languages") or ["en", "en-US", "en-GB"]
            if not isinstance(languages, list):
                languages = ["en"]
            # Cap language list noise
            languages = [str(x)[:16] for x in languages[:8]]

            if not url_or_id:
                self._json(400, {"ok": False, "error": "url_or_id required"})
                return
            if not extract_video_id(url_or_id):
                self._json(400, {"ok": False, "error": "could not parse YouTube id"})
                return

            # Bound concurrent YouTube fetches (threads pile up when API hangs)
            acquired = _sem.acquire(timeout=5.0)
            if not acquired:
                self._json(
                    503,
                    {
                        "ok": False,
                        "error": "relay busy — too many concurrent transcript fetches",
                    },
                )
                return
            try:
                video_id, text = fetch_transcript_local(url_or_id, languages=languages)
            except Exception as e:
                self._json(502, {"ok": False, "error": str(e), "detail": str(e)})
                return
            finally:
                _sem.release()

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

    server = BoundedThreadingHTTPServer((args.host, args.port), make_handler(token))
    # Also set timeout on listening socket accept path
    try:
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        pass

    print(
        f"Transcript relay listening on http://{args.host}:{args.port} "
        f"(token={'set' if token else 'none'}; max_in_flight={MAX_IN_FLIGHT})",
        flush=True,
    )
    print("Health: GET /health   Transcript: POST /v1/transcript", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        try:
            server.server_close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
