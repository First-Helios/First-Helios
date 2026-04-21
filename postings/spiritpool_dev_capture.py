"""
postings/spiritpool_dev_capture.py — Secure whole-page capture for Spirit Pool dev mode.

Purpose
-------
Spirit Pool can (in developer mode only) send the *entire rendered HTML* of
a page the contributor is looking at, so First-Helios can replay extraction
against real browser-rendered content. This is the bridge that lets SP
cover the aggregator pages our server-side scraper can't reach (JS-rendered,
UA-blocked, etc.).

Security posture
----------------
This route handles unsanitized, user-controlled HTML that is ~megabytes in
size. Three layers gate it:

  1. **Kill switch.** If the env var `SPIRITPOOL_DEV_SIGNING_KEY` is not set
     (the default on any production deploy that hasn't explicitly opted in),
     the route returns 404 and refuses to process the body at all. Dev mode
     is impossible without a key.

  2. **Per-device enrollment.** A dev device enrolls once via
     `scripts/issue_spiritpool_dev_key.py`, which derives a 32-byte HMAC
     secret and writes it to `data/cache/spiritpool_dev/keys.json` (git-
     ignored). The extension stores the device token + secret in
     `browser.storage.local`. The server validates (a) the token exists
     and is enabled, and (b) the HMAC signature was computed with that
     token's secret.

  3. **Replay window + size cap.** Signed timestamps must be within ±300s
     of server time. HTML bodies larger than 8 MB are rejected.

If any check fails, the request is rejected and nothing is persisted.

Storage policy
--------------
One JSON bundle per canonical URL, overwrite on each new capture — mirrors
`collectors/meal_deals/website_scraper._write_site_debug_bundle`. Files
live under `data/cache/spiritpool_dev/page_captures/`.

No data from this module ever reaches `meal_deals`, `job_postings`, or any
customer-facing table. Captures are raw replay material for operators only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

_DEV_DIR = Path(__file__).parent.parent / "data" / "cache" / "spiritpool_dev"
_PAGE_CAPTURE_DIR = _DEV_DIR / "page_captures"
_KEYS_FILE = _DEV_DIR / "keys.json"

# ── Limits / policy ──────────────────────────────────────────────────────────

MAX_BODY_BYTES = 8 * 1024 * 1024           # 8 MB post-body cap
MAX_HTML_BYTES = 7 * 1024 * 1024           # leave ~1 MB for envelope
REPLAY_WINDOW_SECONDS = 300                # ±5 minutes

# Domains the dev capture route will accept. Broader than the ingest
# allowlist because the whole point of dev mode is to cover sites we
# can't yet scrape server-side. Still restricted to http(s) URLs and
# rejects localhost, file://, raw-IP, internal ranges.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Env var name — if unset, the route returns 404.
_ENV_DEV_ENABLED_FLAG = "SPIRITPOOL_DEV_SIGNING_KEY"

# ── Blueprint ────────────────────────────────────────────────────────────────

spiritpool_dev_bp = Blueprint(
    "spiritpool_dev", __name__, url_prefix="/api/spiritpool/dev"
)


# ── Key store ────────────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    """Dev mode is opt-in via env var. Never default-enabled in production."""
    return bool(os.environ.get(_ENV_DEV_ENABLED_FLAG))


def _load_keys() -> dict[str, dict[str, Any]]:
    """Return { device_token: {secret_hex, enabled, issued_at, note} }."""
    if not _KEYS_FILE.exists():
        return {}
    try:
        data = json.loads(_KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("[SPDevCapture] keys.json unreadable; treating as empty")
        return {}
    if not isinstance(data, dict):
        return {}
    keys = data.get("keys")
    return keys if isinstance(keys, dict) else {}


def save_keys(keys: dict[str, dict[str, Any]]) -> None:
    """Overwrite the keys file. Used only by the issuance CLI."""
    _DEV_DIR.mkdir(parents=True, exist_ok=True)
    _KEYS_FILE.write_text(
        json.dumps({"version": 1, "keys": keys}, indent=2), encoding="utf-8"
    )
    try:
        os.chmod(_KEYS_FILE, 0o600)
    except OSError:
        pass


# ── Signature verification ───────────────────────────────────────────────────

def _canonical_sign_string(
    *, url: str, html_sha256: str, nonce: str, ts: int
) -> bytes:
    """Bytes that client and server both HMAC. Newline-separated, no ambiguity."""
    return f"v1\n{url}\n{html_sha256}\n{nonce}\n{ts}".encode("utf-8")


def verify_signature(
    *,
    device_token: str,
    url: str,
    html: str,
    nonce: str,
    ts: int,
    signature_hex: str,
    now_ts: int | None = None,
) -> tuple[bool, str | None]:
    """Return (ok, reason_if_failed)."""
    if not isinstance(device_token, str) or not device_token:
        return False, "missing_device_token"
    if not isinstance(signature_hex, str) or not signature_hex:
        return False, "missing_signature"
    if not isinstance(nonce, str) or not (8 <= len(nonce) <= 128):
        return False, "bad_nonce"
    if not isinstance(ts, int):
        return False, "bad_timestamp"

    now = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts) > REPLAY_WINDOW_SECONDS:
        return False, "replay_window"

    keys = _load_keys()
    entry = keys.get(device_token)
    if not entry or not entry.get("enabled", False):
        return False, "unknown_or_disabled_device"

    secret_hex = entry.get("secret_hex")
    if not isinstance(secret_hex, str):
        return False, "corrupt_key_entry"
    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError:
        return False, "corrupt_key_entry"

    html_sha = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()
    expected = hmac.new(
        secret,
        _canonical_sign_string(url=url, html_sha256=html_sha, nonce=nonce, ts=ts),
        hashlib.sha256,
    ).hexdigest()

    try:
        provided = signature_hex.lower()
    except AttributeError:
        return False, "bad_signature_encoding"

    if not hmac.compare_digest(expected, provided):
        return False, "bad_signature"

    return True, None


# ── Storage ──────────────────────────────────────────────────────────────────

def _canonicalize_url_for_storage(raw: str) -> str | None:
    """Return a stable key form of the URL. Drop fragment; keep query."""
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    if not parsed.netloc:
        return None
    netloc = parsed.netloc.lower()
    # Block localhost / private nets (SSRF-adjacent capture abuse).
    if netloc in {"localhost", "127.0.0.1", "0.0.0.0"} or netloc.startswith(
        ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
         "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
         "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")
    ):
        return None
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{netloc}{path}{query}"


def _capture_path(canonical_url: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", canonical_url.lower()).strip("_")[:80] or "page"
    digest = hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()[:12]
    return _PAGE_CAPTURE_DIR / f"{slug}__{digest}.json"


def write_page_capture(
    *,
    canonical_url: str,
    html: str,
    device_token: str,
    captured_at_iso: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Overwrite-on-hit: one JSON bundle per canonical URL.

    Mirrors `collectors/meal_deals/website_scraper._write_site_debug_bundle`.
    """
    _PAGE_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = _capture_path(canonical_url)
    bundle = {
        "schema_version": 1,
        "canonical_url": canonical_url,
        "captured_at": captured_at_iso,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "device_token": device_token,
        "html_sha256": hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest(),
        "html_bytes": len(html),
        "html": html,
        "extra": extra or {},
    }
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return path


# ── Route: POST /api/spiritpool/dev/page-capture ─────────────────────────────

@spiritpool_dev_bp.route("/page-capture", methods=["POST"])
def page_capture():
    if not _is_enabled():
        # Fall closed. In production this route simply doesn't exist.
        return jsonify({"error": "not_found"}), 404

    # Reject oversized bodies before parsing JSON
    cl = request.content_length
    if cl is not None and cl > MAX_BODY_BYTES:
        return jsonify({"error": "payload_too_large"}), 413

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "json_body_required"}), 400

    url = body.get("url")
    html = body.get("html")
    nonce = body.get("nonce")
    ts = body.get("ts")
    device_token = body.get("device_token")
    signature = body.get("signature")
    captured_at_iso = body.get("captured_at") or datetime.now(timezone.utc).isoformat()
    extra = body.get("extra") if isinstance(body.get("extra"), dict) else None

    if not isinstance(url, str) or not isinstance(html, str):
        return jsonify({"error": "bad_fields"}), 400
    if len(html.encode("utf-8", errors="replace")) > MAX_HTML_BYTES:
        return jsonify({"error": "html_too_large"}), 413

    ok, reason = verify_signature(
        device_token=device_token,
        url=url,
        html=html,
        nonce=nonce,
        ts=ts if isinstance(ts, int) else -1,
        signature_hex=signature,
    )
    if not ok:
        logger.warning("[SPDevCapture] signature rejected: %s (url=%s)", reason, url[:120])
        return jsonify({"error": "unauthorized", "reason": reason}), 401

    canonical = _canonicalize_url_for_storage(url)
    if canonical is None:
        return jsonify({"error": "url_rejected"}), 400

    path = write_page_capture(
        canonical_url=canonical,
        html=html,
        device_token=device_token,
        captured_at_iso=captured_at_iso,
        extra=extra,
    )

    logger.info(
        "[SPDevCapture] stored capture device=%s url=%s bytes=%d path=%s",
        device_token[:8], canonical, len(html), path.name,
    )
    return jsonify({
        "ok": True,
        "path": str(path.relative_to(_DEV_DIR.parent.parent)),
        "bytes": len(html),
    })
