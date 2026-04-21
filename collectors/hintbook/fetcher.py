"""
Polite HTTP fetcher for hintbook adapters.

- Per-URL disk cache under data/cache/hintbook/fetch/
- Conservative default TTL (24h) — aggregator sites change slowly.
- Rate limit: minimum 1s between requests to the same host.
- Identifies itself clearly in User-Agent.
- Treats 403/503/429 as soft failures — the adapter records the URL as
  a failed fetch in the harvest report rather than raising.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache" / "hintbook" / "fetch"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "FirstHeliosHintbook/1.0 (+competitive intelligence crawler; "
    "contact=ops@first-helios.local; respect-robots=true)"
)

_DEFAULT_TIMEOUT = 20
_MIN_HOST_INTERVAL_S = 1.0
_last_host_hit: dict[str, float] = {}


def _cache_key(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]
    host = urlparse(url).netloc.replace(":", "_")
    return _CACHE_DIR / host / f"{digest}.json"


def _read_cache(url: str, ttl_hours: float) -> str | None:
    path = _cache_key(url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        age_h = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_h > ttl_hours:
            return None
        return payload.get("html")
    except Exception as exc:  # pragma: no cover
        logger.debug("[Hintbook.fetch] cache read failed for %s: %s", url, exc)
        return None


def _write_cache(url: str, html: str, status_code: int) -> None:
    path = _cache_key(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status_code": status_code,
        "html": html,
    }
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        logger.debug("[Hintbook.fetch] cache write failed for %s: %s", url, exc)


def _rate_limit(url: str) -> None:
    host = urlparse(url).netloc
    now = time.monotonic()
    last = _last_host_hit.get(host, 0.0)
    delta = now - last
    if delta < _MIN_HOST_INTERVAL_S:
        time.sleep(_MIN_HOST_INTERVAL_S - delta)
    _last_host_hit[host] = time.monotonic()


def fetch(
    url: str,
    *,
    ttl_hours: float = 24.0,
    timeout: int = _DEFAULT_TIMEOUT,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str | None, int | None, str | None]:
    """Fetch a URL with caching. Returns (html, status_code, error)."""
    cached = _read_cache(url, ttl_hours=ttl_hours)
    if cached is not None:
        return cached, 200, None

    _rate_limit(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json;q=0.8,*/*;q=0.1"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra_headers:
        headers.update(extra_headers)

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return None, None, f"request_exception:{type(exc).__name__}:{exc}"

    status = resp.status_code
    if status == 200 and resp.text:
        _write_cache(url, resp.text, status)
        return resp.text, status, None
    return None, status, f"http_{status}"
