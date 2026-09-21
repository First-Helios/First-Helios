"""Nominatim geocoding client used only to fill coordinate gaps in discovery.

Overture POIs already carry lat/lon; this client is a fallback for the few that
do not (ADR-0009 §1). It honours Nominatim's usage policy: a real User-Agent and
at most one request per second, with every answer (including "no match") cached
on disk so a re-run never re-queries. The HTTP client is injectable so tests
replay from a mock transport and CI makes no live network calls.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from packages.helios_core.identity.normalize import normalize_address

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org"


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A resolved WGS84 coordinate."""

    latitude: float
    longitude: float


class NominatimClient:
    """Disk-cached, rate-limited free-form geocoder."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        user_agent: str,
        base_url: str = _DEFAULT_BASE_URL,
        min_interval_s: float = 1.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("Nominatim requires a non-empty User-Agent")
        self._cache_dir = cache_dir
        self._base_url = base_url.rstrip("/")
        self._min_interval_s = min_interval_s
        self._owns_client = client is None
        self._client = client or httpx.Client(headers={"User-Agent": user_agent}, timeout=30.0)
        self._last_request_at: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> NominatimClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _read_cache(self, key: str) -> GeoPoint | None | _Miss:
        path = self._cache_path(key)
        if not path.exists():
            return _MISS
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("result") is None:
            return None
        result: Mapping[str, object] = payload["result"]
        return GeoPoint(latitude=float(result["latitude"]), longitude=float(result["longitude"]))  # type: ignore[arg-type]

    def _write_cache(self, key: str, point: GeoPoint | None) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        result = (
            None if point is None else {"latitude": point.latitude, "longitude": point.longitude}
        )
        self._cache_path(key).write_text(json.dumps({"result": result}), encoding="utf-8")

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)

    def geocode(self, query: str) -> GeoPoint | None:
        """Return coordinates for a free-form address, or ``None`` if unresolved."""
        key = normalize_address(query)
        if not key:
            return None
        cached = self._read_cache(key)
        if not isinstance(cached, _Miss):
            return cached

        self._throttle()
        response = self._client.get(
            f"{self._base_url}/search",
            params={"q": query, "format": "jsonv2", "limit": 1},
        )
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        point = _parse_first_match(response.json())
        self._write_cache(key, point)
        return point


class _Miss:
    """Sentinel distinguishing a cache miss from a cached negative result."""


_MISS = _Miss()


def _parse_first_match(payload: object) -> GeoPoint | None:
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict) or "lat" not in first or "lon" not in first:
        return None
    return GeoPoint(latitude=float(first["lat"]), longitude=float(first["lon"]))
