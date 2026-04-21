#!/usr/bin/env python3
"""
scripts/issue_spiritpool_dev_key.py — Enroll a new Spirit Pool dev device.

Usage:
    python scripts/issue_spiritpool_dev_key.py --note "Fortune laptop Firefox"
    python scripts/issue_spiritpool_dev_key.py --list
    python scripts/issue_spiritpool_dev_key.py --revoke <device_token>

Writes a shared secret into data/cache/spiritpool_dev/keys.json (chmod 0600,
gitignored). Prints the device_token + secret_hex that the operator pastes
into the Spirit Pool extension's Dev Mode settings.

The server must also have SPIRITPOOL_DEV_SIGNING_KEY set in its environment
(value doesn't need to match anything — the env var is just the kill switch
for the dev-capture blueprint). If that env var is unset, /api/spiritpool/dev
returns 404 regardless of enrolled keys.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import datetime, timezone

# Add project root to sys.path so we can import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from postings.spiritpool_dev_capture import _load_keys, save_keys  # noqa: E402


def issue(note: str) -> None:
    keys = _load_keys()
    device_token = f"spdev_{secrets.token_urlsafe(12)}"
    secret_hex = secrets.token_hex(32)  # 256-bit HMAC secret
    keys[device_token] = {
        "secret_hex": secret_hex,
        "enabled": True,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    save_keys(keys)

    print()
    print("NEW DEV DEVICE ENROLLED")
    print("=" * 60)
    print(f"note         : {note}")
    print(f"device_token : {device_token}")
    print(f"secret_hex   : {secret_hex}")
    print("=" * 60)
    print()
    print("Paste BOTH fields into the Spirit Pool extension:")
    print("  Options → Developer → Dev Capture → Paste device token / secret")
    print()
    print("Reminder: set SPIRITPOOL_DEV_SIGNING_KEY=1 in the server env to")
    print("activate the /api/spiritpool/dev blueprint. In production environments")
    print("that env var should remain UNSET so dev-mode returns 404.")


def list_keys() -> None:
    keys = _load_keys()
    if not keys:
        print("(no enrolled devices)")
        return
    print(f"{'device_token':30s} {'enabled':8s} {'issued_at':26s} note")
    print("-" * 90)
    for tok, entry in keys.items():
        print(
            f"{tok:30s} {str(entry.get('enabled')):8s} "
            f"{str(entry.get('issued_at', ''))[:26]:26s} "
            f"{entry.get('note', '')}"
        )


def revoke(device_token: str) -> int:
    keys = _load_keys()
    entry = keys.get(device_token)
    if not entry:
        print(f"No device with token {device_token!r}", file=sys.stderr)
        return 1
    entry["enabled"] = False
    entry["revoked_at"] = datetime.now(timezone.utc).isoformat()
    keys[device_token] = entry
    save_keys(keys)
    print(f"Revoked {device_token}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--note", help="Free-form note for the new device")
    g.add_argument("--list", action="store_true", help="List enrolled devices")
    g.add_argument("--revoke", metavar="DEVICE_TOKEN", help="Disable a device")
    args = p.parse_args()

    if args.list:
        list_keys()
        return 0
    if args.revoke:
        return revoke(args.revoke)
    issue(args.note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
