"""Record-only candidate re-crawl (ADR-0013 Amendment 24 item 4(b)): mock transport, no network."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from apps.discovery.resolve_urls import _USER_AGENT
from apps.discovery.web_client import SiteFetcher
from apps.menu_pipeline.record_candidates import RecordingVerifier, page_id, record_venue

if TYPE_CHECKING:
    from pathlib import Path

_HOME = (
    "<html><title>Kitchen</title><body><h1>Kitchen</h1>"
    '<a href="/our-food">Our food</a>'
    '<a href="https://www.toasttab.com/kitchen-123">Order online</a></body></html>'
)
_MENU = "<html><title>Menu</title><body><h1>Menu</h1><p>Taco $3.50</p></body></html>"


def _fetcher(cache_dir: Path, calls: list[str], recorder: RecordingVerifier) -> SiteFetcher:
    routes = {
        "https://kitchen.example/": (200, _HOME),
        "https://kitchen.example/menu": (200, _MENU),
        "https://kitchen.example/our-food": (200, _MENU.replace("Menu", "Food")),
        "https://www.toasttab.com/kitchen-123": (200, _MENU.replace("Menu", "Order")),
    }

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        status, body = routes.get(str(request.url), (404, "nope"))
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})

    return SiteFetcher(
        cache_dir=cache_dir,
        user_agent=_USER_AGENT,
        min_interval_s=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        resolve=lambda _host: ["93.184.216.34"],
        page_check=recorder,
    )


def test_every_candidate_is_recorded_and_none_accepted(tmp_path: Path) -> None:
    calls: list[str] = []
    recorder = RecordingVerifier()
    with _fetcher(tmp_path, calls, recorder) as fetcher:
        reason, seen, homepage = record_venue(fetcher, recorder, "https://kitchen.example/", None)
    urls = [page.url for page in seen]
    # Every candidate discovery fetched and checked: a verified /menu doesn't stop it.
    assert urls == [
        "https://kitchen.example/menu",
        "https://kitchen.example/our-food",
        "https://kitchen.example/",  # nothing verified: the homepage itself (ADR-0026)
        "https://www.toasttab.com/kitchen-123",
    ]
    assert reason == "no_menu_found"
    assert homepage == _HOME
    assert calls.count("https://kitchen.example/") == 1, "the homepage is read from the cache"
    assert any(url.endswith("/robots.txt") for url in calls)
    assert page_id("g1", seen[0]) != page_id("g2", seen[0])
