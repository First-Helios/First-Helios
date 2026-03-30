"""
scrapers/cache.py — Shared JSON response cache for all scraper adapters.

Prevents redundant API calls during development, testing, and within normal
rate-gate windows. Every adapter calls read_cache() before any HTTP request;
on a fresh fetch it calls write_cache() immediately after parsing.

Cache files live in data/<source_key>_cache.json with the format:
    {
        "fetched_at": "2026-03-29T12:00:00+00:00",  # ISO 8601 UTC
        "data": <any JSON-serialisable value>         # list, dict, etc.
    }

Usage:
    from collectors.cache import read_cache, write_cache

    jobs = read_cache("jobicy", ttl_minutes=60)
    if jobs is None:
        resp = tracked_get(...)
        jobs = resp.json().get("jobs", [])
        write_cache("jobicy", jobs)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"


def _cache_path(source_key: str) -> Path:
    return _DATA_DIR / f"{source_key}_cache.json"


def read_cache(source_key: str, ttl_minutes: float) -> Any | None:
    """Return cached data if the cache file exists and is younger than ttl_minutes.

    Returns None when:
      - the cache file does not exist
      - the cache is older than ttl_minutes
      - the file is unreadable or malformed

    Args:
        source_key:   Matches the API_SOURCE_REGISTRY key, e.g. "jobicy".
        ttl_minutes:  How long the cached response is considered fresh.

    Returns:
        The cached "data" value (list, dict, etc.), or None on miss.
    """
    path = _cache_path(source_key)
    try:
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        age_minutes = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60
        if age_minutes >= ttl_minutes:
            logger.debug(
                "[Cache] %s stale (%.1f min old, ttl=%.0f min) — will fetch fresh",
                source_key, age_minutes, ttl_minutes,
            )
            return None

        data = payload["data"]
        count = len(data) if isinstance(data, (list, dict)) else "n/a"
        logger.info(
            "[Cache] %s hit (%s items, age %.1f min)",
            source_key, count, age_minutes,
        )
        return data

    except Exception as exc:
        logger.warning("[Cache] %s read failed — will fetch fresh: %s", source_key, exc)
        return None


def write_cache(source_key: str, data: Any) -> None:
    """Write data to the local cache file for source_key.

    Silently no-ops on write failure so a cache error never crashes the scraper.

    Args:
        source_key: Matches the API_SOURCE_REGISTRY key, e.g. "jobicy".
        data:       Any JSON-serialisable value (list, dict, etc.).
    """
    path = _cache_path(source_key)
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        path.write_text(json.dumps(payload, default=str), encoding="utf-8")
        count = len(data) if isinstance(data, (list, dict)) else "n/a"
        logger.debug("[Cache] %s written (%s items → %s)", source_key, count, path)
    except Exception as exc:
        logger.warning("[Cache] %s write failed (non-fatal): %s", source_key, exc)


def invalidate_cache(source_key: str) -> bool:
    """Delete the cache file for source_key.  Returns True if a file was removed."""
    path = _cache_path(source_key)
    if path.exists():
        path.unlink()
        logger.info("[Cache] %s invalidated", source_key)
        return True
    return False


def cache_age_minutes(source_key: str) -> float | None:
    """Return how many minutes old the cache is, or None if no cache exists."""
    path = _cache_path(source_key)
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60
    except Exception:
        return None
