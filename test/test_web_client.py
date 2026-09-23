"""Unit tests for SiteFetcher + menu-URL discovery (mock transport, no network).

Routes are keyed by full URL or by path; a 3xx route's body is its Location.
DNS is faked (every host resolves to a public address unless a test says
otherwise) and the clocks are fakes, so throttling and cache expiry are exact.
"""

from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING

import httpx
import pytest

import apps.discovery.web_client as web_client_module
from apps.discovery.web_client import (
    CACHE_TTL_S,
    MAX_BODY_BYTES,
    SiteFetcher,
    is_public_address,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

_HTML = "text/html"
_TEXT = "text/plain"
_PUBLIC_IP = "93.184.216.34"

Route = tuple[int, str, str]


class FakeClock:
    """Wall clock, monotonic clock and sleep that only move when told to."""

    def __init__(self) -> None:
        self.wall = 1_800_000_000.0
        self.mono = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.mono += seconds


def _public(_host: str) -> Iterable[str]:
    return [_PUBLIC_IP]


def _fetcher(
    cache_dir: Path,
    routes: dict[str, Route],
    *,
    calls: list[str] | None = None,
    clock: FakeClock | None = None,
    min_interval_s: float = 0.0,
    resolve: Callable[[str], Iterable[str]] = _public,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> SiteFetcher:
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if handler is not None:
            return handler(request)
        status, body, ctype = routes.get(
            str(request.url), routes.get(request.url.path or "/", (404, "nope", _HTML))
        )
        if 300 <= status < 400:  # noqa: PLR2004
            return httpx.Response(status, headers={"location": body})
        return httpx.Response(status, text=body, headers={"content-type": ctype})

    clock = clock or FakeClock()
    return SiteFetcher(
        cache_dir=cache_dir,
        user_agent="helios-test/1.0",
        min_interval_s=min_interval_s,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        resolve=resolve,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


# -- cache ---------------------------------------------------------------------


def test_fetch_caches_on_disk(tmp_path: Path) -> None:
    calls: list[str] = []
    with _fetcher(tmp_path, {"/": (200, "<html>hi</html>", _HTML)}, calls=calls) as fetcher:
        first = fetcher.fetch("https://k.com/")
        second = fetcher.fetch("https://k.com/")
    assert first is not None and first.status == 200
    assert second == first
    assert calls == ["https://k.com/robots.txt", "https://k.com/"], "second fetch is cached"


def test_network_error_is_cached_as_negative(tmp_path: Path) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ConnectError("boom")

    with _fetcher(tmp_path, {}, calls=calls, handler=handle) as fetcher:
        assert fetcher.fetch("https://dead.com/") is None
        assert fetcher.fetch("https://dead.com/") is None
    assert calls.count("https://dead.com/") == 1, "a cached failure must not re-request"


def test_cached_entries_expire_after_ttl(tmp_path: Path) -> None:
    calls: list[str] = []
    clock = FakeClock()
    routes = {"/": (200, "<html>hi</html>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls, clock=clock) as fetcher:
        fetcher.fetch("https://k.com/")
    clock.wall += CACHE_TTL_S - 1
    with _fetcher(tmp_path, routes, calls=calls, clock=clock) as fetcher:
        fetcher.fetch("https://k.com/")
    assert len(calls) == 2, "within the TTL robots.txt and the page come from the cache"
    clock.wall += 2
    with _fetcher(tmp_path, routes, calls=calls, clock=clock) as fetcher:
        fetcher.fetch("https://k.com/")
    assert calls[2:] == ["https://k.com/robots.txt", "https://k.com/"]


def test_corrupt_or_legacy_cache_entry_is_refetched(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"/": (200, "<html>hi</html>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        fetcher.fetch("https://k.com/")
    entries = sorted(tmp_path.glob("*.json"))
    assert len(entries) == 2
    assert not list(tmp_path.glob("*.tmp")), "atomic writes leave no temp files"
    for entry in entries:
        assert "fetched_at" in json.loads(entry.read_text(encoding="utf-8"))
    entries[0].write_text('{"result": {"url": "https://k', encoding="utf-8")  # torn write
    entries[1].write_text('{"result": null}', encoding="utf-8")  # pre-S2 entry, no fetched_at
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        result = fetcher.fetch("https://k.com/")
    assert result is not None and result.status == 200
    assert len(calls) == 4, "both unreadable entries are re-fetched"


def test_body_over_size_cap_is_a_failure(tmp_path: Path) -> None:
    big = "x" * (MAX_BODY_BYTES + 1)
    routes = {"/big": (200, big, _HTML), "/ok": (200, "x" * MAX_BODY_BYTES, _HTML)}
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.fetch("https://k.com/big") is None
        ok = fetcher.fetch("https://k.com/ok")
    assert ok is not None and len(ok.text) == MAX_BODY_BYTES


def test_declared_content_length_over_cap_is_not_read(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, headers={"content-length": str(MAX_BODY_BYTES + 1)}, content=b"small"
        )

    with _fetcher(tmp_path, {}, handler=handle) as fetcher:
        assert fetcher.fetch("https://k.com/") is None


# -- robots.txt ----------------------------------------------------------------


def test_robots_disallow_is_honoured(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {
        "/robots.txt": (200, "User-agent: *\nDisallow: /menu", _TEXT),
        "/menu": (200, "<html>menu</html>", _HTML),
    }
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.allowed("https://k.com/about") is True
        assert fetcher.allowed("https://k.com/menu") is False
        # A robots-disallowed menu must not be discovered even though it 200s.
        assert fetcher.discover_menu_url("https://k.com/") is None
    assert "https://k.com/menu" not in calls


@pytest.mark.parametrize(
    ("robots", "path", "expected"),
    [
        # R05: longest match wins, not first match.
        ("User-agent: *\nAllow: /\nDisallow: /menu", "/menu", False),
        ("User-agent: *\nDisallow: /\nAllow: /menu", "/menu", True),
        # Allow wins an equal-length tie.
        ("User-agent: *\nDisallow: /menu\nAllow: /menu", "/menu", True),
        # R05: * and $ wildcards.
        ("User-agent: *\nDisallow: /*menu", "/our-menu", False),
        ("User-agent: *\nDisallow: /*.pdf$", "/menu.pdf", False),
        ("User-agent: *\nDisallow: /*.pdf$", "/menu.pdf?v=2", True),
        # Query strings are part of the matched path.
        ("User-agent: *\nDisallow: /*?order=", "/menu?order=1", False),
        # Our own group beats the * group; other bots' groups don't apply to us.
        ("User-agent: *\nDisallow:\n\nUser-agent: helios-test\nDisallow: /", "/", False),
        ("User-agent: GPTBot\nDisallow: /", "/menu", True),
    ],
)
def test_robots_rules_follow_rfc_9309(
    tmp_path: Path, robots: str, path: str, expected: bool
) -> None:
    with _fetcher(tmp_path, {"/robots.txt": (200, robots, _TEXT)}) as fetcher:
        assert fetcher.allowed(f"https://k.com{path}") is expected


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_robots_4xx_allows_all(tmp_path: Path, status: int) -> None:
    routes = {"/robots.txt": (status, "", _TEXT), "/menu": (200, "<html>m</html>", _HTML)}
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.allowed("https://k.com/menu") is True


@pytest.mark.parametrize("status", [500, 503])
def test_robots_5xx_skips_the_site(tmp_path: Path, status: int) -> None:
    calls: list[str] = []
    routes = {"/robots.txt": (status, "", _TEXT), "/menu": (200, "<html>m</html>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None
    assert calls == ["https://k.com/robots.txt"], "nothing but robots.txt is requested"


def test_unreachable_robots_skips_the_site(tmp_path: Path) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with _fetcher(tmp_path, {}, calls=calls, handler=handle) as fetcher:
        assert fetcher.fetch("https://k.com/") is None
        assert fetcher.fetch("https://k.com/menu") is None
    assert calls == ["https://k.com/robots.txt"]


def test_robots_redirect_off_site_skips_the_site(tmp_path: Path) -> None:
    routes = {"https://k.com/robots.txt": (301, "https://cdn.example.net/robots.txt", _TEXT)}
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.allowed("https://k.com/menu") is False


def test_crawl_delay_slows_the_host(tmp_path: Path) -> None:
    clock = FakeClock()
    routes = {"/robots.txt": (200, "User-agent: *\nCrawl-delay: 5", _TEXT)}
    with _fetcher(tmp_path, routes, clock=clock, min_interval_s=1.0) as fetcher:
        fetcher.fetch("https://k.com/a")
    assert clock.sleeps == [5.0]


def test_excessive_crawl_delay_skips_the_site(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"/robots.txt": (200, "User-agent: *\nCrawl-delay: 3600", _TEXT)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.fetch("https://k.com/menu") is None
    assert calls == ["https://k.com/robots.txt"]


# -- rate limit ----------------------------------------------------------------


def test_requests_to_one_host_are_spaced(tmp_path: Path) -> None:
    clock = FakeClock()
    with _fetcher(tmp_path, {}, clock=clock, min_interval_s=1.0) as fetcher:
        fetcher.fetch("https://k.com/a")  # robots.txt, then /a after 1 s
        clock.mono += 0.25
        fetcher.fetch("https://k.com/b")  # 0.25 s since /a
        fetcher.fetch("https://other.com/")  # a different host is not delayed by k.com
    assert clock.sleeps == [1.0, 0.75, 1.0]


# -- redirects -----------------------------------------------------------------


def test_same_site_redirects_are_followed(tmp_path: Path) -> None:
    routes = {
        "http://k.com/menu": (301, "https://www.k.com/menu", _HTML),
        "https://www.k.com/menu": (302, "/menu/", _HTML),
        "https://www.k.com/menu/": (200, "<html>menu</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        result = fetcher.fetch("http://k.com/menu")
    assert result is not None
    assert result.status == 200
    assert result.url == "https://www.k.com/menu/"


def test_each_hop_is_throttled(tmp_path: Path) -> None:
    clock = FakeClock()
    routes = {
        "https://k.com/menu": (301, "/menu/", _HTML),
        "https://k.com/menu/": (200, "<html>menu</html>", _HTML),
    }
    with _fetcher(tmp_path, routes, clock=clock, min_interval_s=1.0) as fetcher:
        fetcher.fetch("https://k.com/menu")
    assert clock.sleeps == [1.0, 1.0], "robots.txt → /menu → /menu/ each wait a second"


@pytest.mark.parametrize(
    "location",
    [
        "https://ordering.example.net/k",  # another site
        "http://192.168.1.10/admin",  # the Pi's LAN
        "http://127.0.0.1:8000/",  # loopback
        "http://[::ffff:10.0.0.1]/",  # IPv4-mapped private
        "ftp://k.com/menu.pdf",  # not http(s)
        "http://[::1",  # malformed Location
    ],
)
def test_redirects_off_policy_are_refused(tmp_path: Path, location: str) -> None:
    calls: list[str] = []
    routes = {"https://k.com/menu": (302, location, _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.fetch("https://k.com/menu") is None
    assert calls == ["https://k.com/robots.txt", "https://k.com/menu"], "target never requested"


def test_malformed_website_is_a_failure_not_a_crash(tmp_path: Path) -> None:
    with _fetcher(tmp_path, {}) as fetcher:
        assert fetcher.fetch("http://[k.com/") is None


def test_host_resolving_to_a_private_address_is_refused(tmp_path: Path) -> None:
    calls: list[str] = []

    def resolve(host: str) -> Iterable[str]:
        return ["10.0.0.5"] if host == "intranet.k.com" else [_PUBLIC_IP]

    with _fetcher(tmp_path, {}, calls=calls, resolve=resolve) as fetcher:
        assert fetcher.fetch("https://intranet.k.com/") is None
        assert fetcher.discover_menu_url("https://intranet.k.com/") is None
    assert calls == []


def test_redirect_hop_disallowed_by_robots_is_not_requested(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {
        "https://k.com/robots.txt": (200, "User-agent: *\nDisallow: /private", _TEXT),
        "https://k.com/menu": (302, "/private/menu", _HTML),
    }
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.fetch("https://k.com/menu") is None
    assert "https://k.com/private/menu" not in calls


def test_redirect_chain_is_capped(tmp_path: Path) -> None:
    routes = {f"https://k.com/{i}": (302, f"/{i + 1}", _HTML) for i in range(10)}
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.fetch("https://k.com/0") is None


@pytest.mark.parametrize(
    ("address", "public"),
    [
        (_PUBLIC_IP, True),
        ("2606:4700::1111", True),
        ("192.168.1.219", False),
        ("10.1.2.3", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("224.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_is_public_address(address: str, public: bool) -> None:
    assert is_public_address(address) is public


# -- discovery -----------------------------------------------------------------


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


def test_discover_resolves_links_against_the_post_redirect_homepage(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {
        "http://k.com/": (301, "https://www.k.com/en/", _HTML),
        "https://www.k.com/en/": (200, '<a href="dinner-menu">Dinner menu</a>', _HTML),
        "https://www.k.com/en/dinner-menu": (200, "<title>Dinner Menu</title>", _HTML),
    }
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        found = fetcher.discover_menu_url("http://k.com/")
    assert found is not None
    assert found.menu_url == "https://www.k.com/en/dinner-menu"
    assert "http://k.com/menu" not in calls, "well-known paths use the final homepage URL"


def test_discover_returns_none_when_no_candidate_resolves(tmp_path: Path) -> None:
    with _fetcher(tmp_path, {"/": (200, "<html>no menu here</html>", _HTML)}) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None


# --- Review remediation S4 (R08, R33, R34, R75, R76) ----------------------------


def test_candidate_redirecting_back_to_homepage_is_rejected(tmp_path: Path) -> None:
    routes = {
        "/": (200, "<html>home</html>", _HTML),
        "/menu": (301, "/", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None


def test_candidate_with_body_identical_to_homepage_is_rejected(tmp_path: Path) -> None:
    # A soft-404/SPA fallback answering every path with the homepage's own
    # markup (a distinct URL, not a redirect) must not be accepted either.
    routes = {
        "/": (200, "<html>Welcome home</html>", _HTML),
        "/menu": (200, "<html>Welcome home</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None


def test_catch_all_site_rejects_a_well_known_path_with_no_real_title(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, text="<html>nothing to see here</html>", headers={"content-type": _HTML}
        )

    with _fetcher(tmp_path, {}, handler=handle) as fetcher:
        # /menu 200s (like every other path on this catch-all host) but its
        # own content never says "menu" anywhere but the URL, which a
        # catch-all site must not be trusted for (R08).
        assert fetcher.discover_menu_url("https://k.com/") is None


def test_catch_all_site_still_accepts_a_well_known_path_with_a_real_title(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/menu":
            return httpx.Response(
                200, text="<title>Our Menu</title>", headers={"content-type": _HTML}
            )
        return httpx.Response(
            200, text="<html>generic catch-all page</html>", headers={"content-type": _HTML}
        )

    with _fetcher(tmp_path, {}, handler=handle) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert (found.menu_url, found.signal) == ("https://k.com/menu", "well_known")


# -- platform sites (D3.5) ------------------------------------------------------


def test_platform_website_is_verified_directly_with_no_root_probe(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"/venue-1": (200, "<html>order here</html>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        found = fetcher.discover_menu_url("https://order.toasttab.com/venue-1")
    assert found is not None
    assert (found.menu_url, found.signal) == ("https://order.toasttab.com/venue-1", "platform")
    assert "https://order.toasttab.com/menu" not in calls, "R33: no root-path probe on a platform"


def test_platform_root_website_is_not_a_menu(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"/": (200, "<html>facebook</html>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.discover_menu_url("https://www.facebook.com/") is None
    assert calls == [], "a platform's root belongs to the platform (R33)"


def test_own_site_never_falls_back_to_a_social_link(tmp_path: Path) -> None:
    routes = {
        "/": (200, '<a href="https://www.facebook.com/kerbey">Facebook</a>', _HTML),
        "https://www.facebook.com/kerbey": (200, "<html>fb</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None


def test_catch_all_probe_only_runs_when_a_well_known_path_answers(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"/": (200, "<html>no menu here</html>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        assert fetcher.discover_menu_url("https://k.com/") is None
    assert not [c for c in calls if "helios-probe-" in c], "no 200 well-known path, no probe"


def test_platform_website_that_fails_to_fetch_yields_no_menu(tmp_path: Path) -> None:
    with _fetcher(tmp_path, {}) as fetcher:  # /venue-1 falls through to the 404 default
        assert fetcher.discover_menu_url("https://order.toasttab.com/venue-1") is None


def test_own_site_falls_back_to_a_homepage_platform_link(tmp_path: Path) -> None:
    routes = {
        "/": (200, '<a href="https://order.toasttab.com/venue-1">Order Online</a>', _HTML),
        "https://order.toasttab.com/venue-1": (200, "<html>order</html>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert (found.menu_url, found.signal) == ("https://order.toasttab.com/venue-1", "platform")


def test_own_site_menu_wins_over_a_platform_fallback_link(tmp_path: Path) -> None:
    routes = {
        "/": (
            200,
            '<a href="/menu">Our Menu</a>'
            '<a href="https://order.toasttab.com/venue-1">Order Online</a>',
            _HTML,
        ),
        "/menu": (200, "<title>Our Menu</title>", _HTML),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert (found.menu_url, found.signal) == ("https://k.com/menu", "well_known")


# -- sitemaps (R75) --------------------------------------------------------------


def test_sitemap_url_comes_from_robots_sitemap_directive(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {
        "/": (200, "<html>home</html>", _HTML),
        "/robots.txt": (200, "User-agent: *\nSitemap: https://k.com/custom-sitemap.xml", _TEXT),
        "/custom-sitemap.xml": (
            200,
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://k.com/dinner-menu</loc></url></urlset>",
            "application/xml",
        ),
        "/dinner-menu": (200, "<title>Dinner Menu</title>", _HTML),
    }
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert found.menu_url == "https://k.com/dinner-menu"
    assert "https://k.com/custom-sitemap.xml" in calls
    assert "https://k.com/sitemap.xml" not in calls


def test_sitemap_index_children_are_expanded_for_menu_matches(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {
        "/": (200, "<html>home</html>", _HTML),
        "/sitemap.xml": (
            200,
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://k.com/sitemap-pages.xml</loc></sitemap>"
            "</sitemapindex>",
            "application/xml",
        ),
        "/sitemap-pages.xml": (
            200,
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://k.com/lunch-menu</loc></url></urlset>",
            "application/xml",
        ),
        "/lunch-menu": (200, "<title>Lunch Menu</title>", _HTML),
    }
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        found = fetcher.discover_menu_url("https://k.com/")
    assert found is not None
    assert found.menu_url == "https://k.com/lunch-menu"
    assert "https://k.com/sitemap-pages.xml" in calls, "index children must be fetched"
    assert "https://k.com/sitemap-pages.xml" not in [c for c in calls if c == found.menu_url], (
        "an index child is a sitemap document, never a page candidate itself"
    )


def test_fetch_decompresses_gzip_urls(tmp_path: Path) -> None:
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://k.com/menu</loc></url></urlset>"
    )
    compressed = gzip.compress(xml.encode("utf-8"))

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=compressed, headers={"content-type": "application/gzip"})

    with _fetcher(tmp_path, {}, handler=handle) as fetcher:
        result = fetcher.fetch("https://k.com/sitemap.xml.gz")
    assert result is not None
    assert result.text == xml


def test_gz_url_already_decoded_by_content_encoding_passes_through(tmp_path: Path) -> None:
    # A CDN serving sitemap.xml.gz with Content-Encoding: gzip: httpx decodes
    # it, so the body is plain XML and must not be gunzipped a second time.
    xml = "<urlset><url><loc>https://k.com/menu</loc></url></urlset>"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=gzip.compress(xml.encode("utf-8")),
            headers={"content-type": "application/xml", "content-encoding": "gzip"},
        )

    with _fetcher(tmp_path, {}, handler=handle) as fetcher:
        result = fetcher.fetch("https://k.com/sitemap.xml.gz")
    assert result is not None
    assert result.text == xml


def test_gzip_bomb_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A tiny compressed payload that decompresses far past the cap must be
    # refused rather than decompressed in full (R75).
    monkeypatch.setattr(web_client_module, "MAX_BODY_BYTES", 100)
    compressed = gzip.compress(b"x" * 10_000)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=compressed, headers={"content-type": "application/gzip"})

    with _fetcher(tmp_path, {}, handler=handle) as fetcher:
        assert fetcher.fetch("https://k.com/big.xml.gz") is None
