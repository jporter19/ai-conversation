#!/usr/bin/env python3
"""Hash a password for users.json (shared hub account)."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

# Allow running from repo root without install
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.auth_store import hash_password, save_users, users_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create bcrypt hash for hub login")
    parser.add_argument("-u", "--username", default="hub", help="Username (default: hub)")
    parser.add_argument("-p", "--password", help="Password (prompt if omitted)")
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write users.json at {users_path()} (overwrites users list with this one user)",
    )
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("Empty password", file=sys.stderr)
        return 1

    ph = hash_password(password)
    user = {"username": args.username, "password_hash": ph}
    print(json.dumps(user, indent=2))
    if args.write:
        save_users([user])
        print(f"Wrote {users_path()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
