# app/paths.py
# Purpose: Resolve durable data directory (local dev vs EC2 volume).

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent / "data"


def get_data_dir() -> Path:
    """
    Directory for conversations, media, secrets, preferences, providers, users.

    Override with AI_HUB_DATA_DIR (e.g. /var/lib/ai-conversation/data on EC2)
    so code deploys never wipe runtime data.
    """
    override = (os.environ.get("AI_HUB_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT
