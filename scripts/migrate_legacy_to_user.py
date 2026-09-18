#!/usr/bin/env python3
"""Move flat pre-SSO data into users/{PORTAL_LEGACY_OWNER_USER_ID}/."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.user_store import (  # noqa: E402
    legacy_owner_user_id,
    migrate_legacy_data_if_needed,
    upsert_profile,
)


def main() -> int:
    uid = legacy_owner_user_id() or (os.environ.get("PORTAL_LEGACY_OWNER_USER_ID") or "").strip()
    if not uid:
        print("Set PORTAL_LEGACY_OWNER_USER_ID to the portal user_id that should own legacy data.", file=sys.stderr)
        return 1
    os.environ["PORTAL_LEGACY_OWNER_USER_ID"] = uid
    upsert_profile(uid, os.environ.get("PORTAL_LEGACY_OWNER_USERNAME") or "legacy")
    # Force re-run: remove marker if present and MIGRATE_FORCE=1
    from app.services.user_store import user_dir
    marker = user_dir(uid) / ".legacy_migrated"
    if os.environ.get("MIGRATE_FORCE") == "1" and marker.exists():
        marker.unlink()
    result = migrate_legacy_data_if_needed(uid)
    print(result)
    return 0 if result.get("migrated") or result.get("reason") == "already_done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
