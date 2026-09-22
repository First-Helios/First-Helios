"""Unit tests for SiteFetcher + menu-URL discovery (mock transport, no network)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from apps.discovery.web_client import SiteFetcher

if TYPE_CHECKING:
    from pathlib import Path

_HTML = "text/html"
_TEXT = "text/plain"

Route = tuple[int, str, str]


def _fetcher(
    cache_dir: Path,
    routes: dict[str, Route],
    *,
    calls: list[str] | None = None,
) -> SiteFetcher:
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path or "/"
        status, body, ctype = routes.get(path, (404, "nope", _HTML))
        return httpx.Response(status, text=body, headers={"content-type": ctype})

    return SiteFetcher(
        cache_dir=cache_dir,
        user_agent="helios-test/1.0",
        min_interval_s=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )


def test_fetch_caches_on_disk(tmp_path: Path) -> None:
    calls: list[str] = []
    with _fetcher(tmp_path, {"/": (200, "<html>hi</html>", _HTML)}, calls=calls) as fetcher:
        first = fetcher.fetch("https://k.com/")
        second = fetcher.fetch("https://k.com/")
    assert first is not None and first.status == 200
    assert second == first
    assert calls == ["https://k.com/"], "second fetch must be served from cache"


def test_network_error_is_cached_as_negative(tmp_path: Path) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        raise httpx.ConnectError("boom")

    with SiteFetcher(
        cache_dir=tmp_path,
        user_agent="helios-test/1.0",
        min_interval_s=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as fetcher:
        assert fetcher.fetch("https://dead.com/") is None
        assert fetcher.fetch("https://dead.com/") is None
    assert calls == ["https://dead.com/"], "a cached failure must not re-request"


def test_robots_disallow_is_honoured(tmp_path: Path) -> None:
    routes = {
        "/robots.txt": (200, "User-agent: *\nDisallow: /menu", _TEXT),
        "/menu": (200, "<html>menu</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.allowed("https://k.com/about") is True
        assert fetcher.allowed("https://k.com/menu") is False
        # A robots-disallowed menu must not be discovered even though it 200s.
        assert fetcher.discover_menu_url("https://k.com/") is None


def test_missing_robots_allows_all(tmp_path: Path) -> None:
    with _fetcher(tmp_path, {"/menu": (200, "<html>m</html>", _HTML)}) as fetcher:
        assert fetcher.allowed("https://k.com/menu") is True


def test_discover_finds_well_known_menu_path(tmp_path: Path) -> None:
    routes = {
        "/": (200, "<html>home</html>", _HTML),
        "/menu": (200, "<html>the menu</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert found.menu_url == "https://k.com/menu"
    assert found.signal == "well_known"


def test_discover_falls_back_to_homepage_anchor(tmp_path: Path) -> None:
    routes = {
        "/": (200, '<a href="/specials-menu">Our Menu</a>', _HTML),
        "/specials-menu": (200, "<html>menu</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert found.menu_url == "https://k.com/specials-menu"
    assert found.signal == "crawled"


def test_discover_returns_none_when_no_candidate_resolves(tmp_path: Path) -> None:
    with _fetcher(tmp_path, {"/": (200, "<html>no menu here</html>", _HTML)}) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None
