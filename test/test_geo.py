"""Unit tests for the Nominatim gap-fill client (mock transport, no network)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from packages.helios_core.geo import GeoPoint, NominatimClient

if TYPE_CHECKING:
    from pathlib import Path


def _client(
    cache_dir: Path,
    handler: httpx.MockTransport,
) -> NominatimClient:
    return NominatimClient(
        cache_dir=cache_dir,
        user_agent="helios-test/1.0",
        min_interval_s=0.0,
        client=httpx.Client(transport=handler),
    )


def test_geocode_returns_point_and_caches_it(tmp_path: Path) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[{"lat": "30.2701", "lon": "-97.7313"}])

    with _client(tmp_path, httpx.MockTransport(handle)) as client:
        first = client.geocode("900 E 11th St, Austin, TX")
        second = client.geocode("900 E 11th St, Austin, TX")

    assert first == GeoPoint(latitude=30.2701, longitude=-97.7313)
    assert second == first
    assert calls == 1, "second lookup must be served from the disk cache"


def test_geocode_caches_a_negative_result(tmp_path: Path) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    with _client(tmp_path, httpx.MockTransport(handle)) as client:
        first = client.geocode("nowhere at all")
        second = client.geocode("nowhere at all")

    assert first is None
    assert second is None
    assert calls == 1, "a cached miss must not re-query"


def test_blank_query_never_calls_the_network(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("blank query must not hit the network")

    with _client(tmp_path, httpx.MockTransport(handle)) as client:
        assert client.geocode("   ") is None


def test_requests_are_spaced_by_min_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [100.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr("packages.helios_core.geo.time.monotonic", lambda: now[0])
    monkeypatch.setattr("packages.helios_core.geo.time.sleep", fake_sleep)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with NominatimClient(
        cache_dir=tmp_path,
        user_agent="helios-test/1.0",
        min_interval_s=1.0,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        client.geocode("1 First St, Austin, TX")
        now[0] += 0.4
        client.geocode("2 Second St, Austin, TX")
    assert sleeps == [pytest.approx(0.6)]
