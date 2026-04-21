"""
tests/HeliosDeployment/test_spiritpool_dev_capture.py — Security tests for
the Spirit Pool whole-page dev-capture route.

These tests are security-critical: they prove the kill switch, HMAC signing,
replay-window, oversized-body, URL allowlist, and overwrite-storage policies
all work as designed. If any of these fail, the dev-capture route must be
considered broken and the SPIRITPOOL_DEV_SIGNING_KEY env var must NOT be
set in any production-like environment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

import pytest
from flask import Flask


# Force a clean module-scoped keyfile dir BEFORE importing the module.
# Each test that needs isolation will monkeypatch further.
@pytest.fixture(autouse=True)
def _isolate_dev_dir(tmp_path, monkeypatch):
    """Redirect the module's file-system paths into tmp_path for every test."""
    from postings import spiritpool_dev_capture as mod

    dev_dir = tmp_path / "spiritpool_dev"
    page_dir = dev_dir / "page_captures"
    keys_file = dev_dir / "keys.json"
    monkeypatch.setattr(mod, "_DEV_DIR", dev_dir)
    monkeypatch.setattr(mod, "_PAGE_CAPTURE_DIR", page_dir)
    monkeypatch.setattr(mod, "_KEYS_FILE", keys_file)
    yield


@pytest.fixture
def app_client(monkeypatch):
    """Flask test client with the dev-capture blueprint registered.

    Defaults to SPIRITPOOL_DEV_SIGNING_KEY=1 (enabled). Tests that need the
    disabled path will clear the env var themselves.
    """
    monkeypatch.setenv("SPIRITPOOL_DEV_SIGNING_KEY", "1")

    from postings.spiritpool_dev_capture import spiritpool_dev_bp

    app = Flask(__name__)
    app.register_blueprint(spiritpool_dev_bp)
    return app.test_client()


# ── helpers ──────────────────────────────────────────────────────────────────

def _enroll_device(note: str = "test") -> tuple[str, str]:
    """Create a valid device_token + secret_hex pair in the tmp keys file."""
    from postings.spiritpool_dev_capture import _load_keys, save_keys

    device_token = f"spdev_{secrets.token_urlsafe(8)}"
    secret_hex = secrets.token_hex(32)
    keys = _load_keys()
    keys[device_token] = {
        "secret_hex": secret_hex,
        "enabled": True,
        "issued_at": "2026-04-21T00:00:00+00:00",
        "note": note,
    }
    save_keys(keys)
    return device_token, secret_hex


def _sign(secret_hex: str, url: str, html: str, nonce: str, ts: int) -> str:
    secret = bytes.fromhex(secret_hex)
    html_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    msg = f"v1\n{url}\n{html_sha}\n{nonce}\n{ts}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def _build_payload(
    secret_hex: str,
    device_token: str,
    *,
    url: str = "https://www.retailmenot.com/view/applebees.com",
    html: str = "<html><body>hi</body></html>",
    ts_offset: int = 0,
    tamper_signature: bool = False,
) -> dict:
    ts = int(time.time()) + ts_offset
    nonce = secrets.token_hex(16)
    sig = _sign(secret_hex, url, html, nonce, ts)
    if tamper_signature:
        sig = "0" * len(sig)
    return {
        "url": url,
        "html": html,
        "nonce": nonce,
        "ts": ts,
        "device_token": device_token,
        "signature": sig,
        "captured_at": "2026-04-21T00:00:00+00:00",
    }


# ── Tests ────────────────────────────────────────────────────────────────────

def test_kill_switch_returns_404_when_env_unset(monkeypatch):
    """When SPIRITPOOL_DEV_SIGNING_KEY is unset, the route must 404 — no body parsing."""
    monkeypatch.delenv("SPIRITPOOL_DEV_SIGNING_KEY", raising=False)
    from postings.spiritpool_dev_capture import spiritpool_dev_bp

    app = Flask(__name__)
    app.register_blueprint(spiritpool_dev_bp)
    client = app.test_client()

    device_token, secret_hex = _enroll_device()
    payload = _build_payload(secret_hex, device_token)

    resp = client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "not_found"}


def test_valid_signature_stores_capture(app_client, tmp_path):
    from postings import spiritpool_dev_capture as mod

    device_token, secret_hex = _enroll_device()
    payload = _build_payload(secret_hex, device_token)

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["bytes"] == len(payload["html"])

    files = list(mod._PAGE_CAPTURE_DIR.glob("*.json"))
    assert len(files) == 1
    bundle = json.loads(files[0].read_text())
    assert bundle["schema_version"] == 1
    assert bundle["canonical_url"] == payload["url"]
    assert bundle["html"] == payload["html"]
    assert bundle["device_token"] == device_token
    assert bundle["html_sha256"] == hashlib.sha256(payload["html"].encode()).hexdigest()


def test_replay_window_rejected(app_client):
    device_token, secret_hex = _enroll_device()
    # 10 minutes in the past — outside the ±300s window.
    payload = _build_payload(secret_hex, device_token, ts_offset=-600)

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "replay_window"


def test_bad_signature_rejected(app_client):
    device_token, secret_hex = _enroll_device()
    payload = _build_payload(secret_hex, device_token, tamper_signature=True)

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "bad_signature"


def test_unknown_device_rejected(app_client):
    # Never enroll — unknown device token.
    payload = _build_payload(secret_hex="aa" * 32, device_token="spdev_bogus")

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "unknown_or_disabled_device"


def test_disabled_device_rejected(app_client):
    from postings.spiritpool_dev_capture import _load_keys, save_keys

    device_token, secret_hex = _enroll_device()
    keys = _load_keys()
    keys[device_token]["enabled"] = False
    save_keys(keys)

    payload = _build_payload(secret_hex, device_token)
    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "unknown_or_disabled_device"


def test_wrong_secret_for_valid_token_rejected(app_client):
    """If an attacker knows a real device_token but not the secret, sig must fail."""
    device_token, _real_secret = _enroll_device()
    wrong_secret = "bb" * 32
    payload = _build_payload(wrong_secret, device_token)

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "bad_signature"


@pytest.mark.parametrize("bad_url", [
    "http://localhost/x",
    "http://127.0.0.1/x",
    "http://10.0.0.5/x",
    "http://192.168.1.50/x",
    "http://172.20.0.3/x",
    "ftp://example.com/x",
    "file:///etc/passwd",
    "javascript:alert(1)",
])
def test_url_rejected_for_ssrf_and_bad_schemes(app_client, bad_url):
    device_token, secret_hex = _enroll_device()
    payload = _build_payload(secret_hex, device_token, url=bad_url)

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    # Some bad schemes fail at URL parse (400 url_rejected);
    # all must NOT return 200.
    assert resp.status_code in (400, 401), (bad_url, resp.get_json())


def test_oversized_html_rejected(app_client):
    device_token, secret_hex = _enroll_device()
    # 7 MB + 1 byte
    giant = "a" * (7 * 1024 * 1024 + 1)
    payload = _build_payload(secret_hex, device_token, html=giant)

    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "html_too_large"


def test_overwrite_on_hit(app_client):
    from postings import spiritpool_dev_capture as mod

    device_token, secret_hex = _enroll_device()
    url = "https://www.slickdeals.net/deals/food-drink/"

    p1 = _build_payload(secret_hex, device_token, url=url, html="<html>v1</html>")
    r1 = app_client.post("/api/spiritpool/dev/page-capture", json=p1)
    assert r1.status_code == 200

    p2 = _build_payload(secret_hex, device_token, url=url, html="<html>v2</html>")
    r2 = app_client.post("/api/spiritpool/dev/page-capture", json=p2)
    assert r2.status_code == 200

    files = list(mod._PAGE_CAPTURE_DIR.glob("*.json"))
    assert len(files) == 1, "overwrite-on-hit: same canonical URL must produce one file"
    bundle = json.loads(files[0].read_text())
    assert bundle["html"] == "<html>v2</html>"


def test_malformed_json_body_rejected(app_client):
    resp = app_client.post(
        "/api/spiritpool/dev/page-capture",
        data="not json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "json_body_required"


def test_missing_required_fields_rejected(app_client):
    resp = app_client.post(
        "/api/spiritpool/dev/page-capture",
        json={"url": "https://example.com"},  # html missing
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_fields"


def test_short_nonce_rejected(app_client):
    device_token, secret_hex = _enroll_device()
    payload = _build_payload(secret_hex, device_token)
    payload["nonce"] = "abc"  # < 8 chars
    # Re-sign isn't needed — verifier checks nonce length before HMAC.
    resp = app_client.post("/api/spiritpool/dev/page-capture", json=payload)
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "bad_nonce"
