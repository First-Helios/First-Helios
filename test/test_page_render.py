"""Page rendering (ADR-0013 §4, Amendments 1–2; session S6f), without a browser.

Two layers: :class:`SiteFetcher`'s render triggers, driven by a scripted
:class:`PageRenderer`; and :class:`BrowserRenderer`'s etiquette, driven by a
fake Playwright session whose "sites" are dicts. CI starts no browser and makes
no network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import pytest

from apps.discovery.menu_url import (
    is_platform_venue_page,
    ordering_platform_host,
    platform_links_by_host,
)
from apps.discovery.url_pipeline import _with_render
from apps.discovery.web_client import (
    MAX_BODY_BYTES,
    MAX_RENDER_CANDIDATES,
    CaptureFailure,
    FetchResult,
    MenuUrlDiscovery,
    looks_js_only,
)
from apps.menu_pipeline.render import (
    RENDER_NAME,
    BrowserRenderer,
    BrowserSession,
    RobotsAnswer,
    _intercept,
    is_challenge,
    launch_headed_chromium,
    robots_rules,
    stays_on,
)
from test.test_web_client import _HTML, FakeClock, _fetcher

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_MENU = "<html><body><h1>MENU-OK</h1></body></html>"
_SHELL = '<html><body><div id="app"></div><script src="/app.js"></script></body></html>'
_NOW = datetime(2027, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _MarkerCheck:
    """A page verifier: a menu is a page containing ``MENU-OK``."""

    name: str = "marker-v1"

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        del url, trust_path
        return "MENU-OK" in html


@dataclass
class _ScriptedRenderer:
    """A PageRenderer answering from a dict; records calls and paces each host."""

    pages: dict[str, FetchResult | CaptureFailure]
    calls: list[str] = field(default_factory=list)
    name: str = "headed-test"

    def render(
        self, url: str, *, pace: Callable[[str, float], None]
    ) -> FetchResult | CaptureFailure:
        self.calls.append(url)
        pace(url.split("/")[2], 0.0)
        return self.pages.get(url, CaptureFailure("failed", "network_error", _NOW))


def _rendered(url: str, html: str = _MENU) -> FetchResult:
    return FetchResult(url, 200, html, "text/html", 1_800_000_000.0, "sha256:r", "headed-test")


# -- SiteFetcher: platform pages ------------------------------------------------


def test_platform_page_refused_statically_is_rendered(tmp_path: Path) -> None:
    url = "https://www.toasttab.com/local/order/lucky-robot"
    final = "https://toast.app/r/lucky-robot/order"
    renderer = _ScriptedRenderer({url: _rendered(final)})
    routes = {url: (403, "Just a moment...", _HTML)}
    with _fetcher(tmp_path, routes, page_check=_MarkerCheck(), renderer=renderer) as fetcher:
        found = fetcher.discover_menu_url(url)
    assert renderer.calls == [url]
    (menu,) = found
    assert isinstance(menu, MenuUrlDiscovery)
    assert (menu.menu_url, menu.signal, menu.render) == (final, "platform", "headed-test")


def test_platform_page_failing_the_check_statically_is_rendered(tmp_path: Path) -> None:
    url = "https://shop.square.site/order"
    renderer = _ScriptedRenderer({url: _rendered(url)})
    routes = {url: (200, _SHELL, _HTML)}
    with _fetcher(tmp_path, routes, page_check=_MarkerCheck(), renderer=renderer) as fetcher:
        (menu,) = fetcher.discover_menu_url(url)
    assert renderer.calls == [url]
    assert isinstance(menu, MenuUrlDiscovery) and menu.render == "headed-test"


def test_verified_static_platform_page_is_not_rendered(tmp_path: Path) -> None:
    url = "https://www.grubhub.com/restaurant/x-1"
    renderer = _ScriptedRenderer({})
    with _fetcher(
        tmp_path, {url: (200, _MENU, _HTML)}, page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        (menu,) = fetcher.discover_menu_url(url)
    assert isinstance(menu, MenuUrlDiscovery) and menu.render is None
    assert renderer.calls == []


def test_static_robots_refusal_is_never_rendered(tmp_path: Path) -> None:
    url = "https://www.toasttab.com/x/giftcards"
    renderer = _ScriptedRenderer({url: _rendered(url)})
    routes = {"/robots.txt": (200, "User-agent: *\nDisallow: /x/", "text/plain")}
    with _fetcher(tmp_path, routes, page_check=_MarkerCheck(), renderer=renderer) as fetcher:
        attempt = fetcher.discover_menu_attempt(url)
    assert renderer.calls == []
    assert isinstance(attempt, CaptureFailure) and attempt.reason_code == "robots_disallowed"


def test_other_static_errors_are_not_rendered(tmp_path: Path) -> None:
    url = "https://www.doordash.com/store/x-1/"
    renderer = _ScriptedRenderer({url: _rendered(url)})
    with _fetcher(
        tmp_path, {url: (500, "down", _HTML)}, page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        attempt = fetcher.discover_menu_attempt(url)
    assert renderer.calls == []
    assert isinstance(attempt, CaptureFailure) and attempt.reason_code == "http_500"


def test_a_render_challenge_is_the_platform_sites_skip_reason(tmp_path: Path) -> None:
    url = "https://www.doordash.com/store/x-1/"
    renderer = _ScriptedRenderer({url: CaptureFailure("skipped", "bot_challenge", _NOW)})
    with _fetcher(
        tmp_path, {url: (403, "no", _HTML)}, page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        attempt = fetcher.discover_menu_attempt(url)
    assert isinstance(attempt, CaptureFailure)
    assert (attempt.outcome, attempt.reason_code) == ("skipped", "bot_challenge")


def test_without_a_renderer_a_refused_platform_page_fails_as_before(tmp_path: Path) -> None:
    url = "https://www.doordash.com/store/x-1/"
    with _fetcher(tmp_path, {url: (403, "no", _HTML)}, page_check=_MarkerCheck()) as fetcher:
        attempt = fetcher.discover_menu_attempt(url)
    assert isinstance(attempt, CaptureFailure) and attempt.reason_code == "http_403"


def test_homepage_platform_link_is_rendered(tmp_path: Path) -> None:
    link = "https://order.toasttab.com/online/venue"
    homepage = f'<html><body><h1>Hi</h1><a href="{link}">Order online</a></body></html>'
    renderer = _ScriptedRenderer({link: _rendered(link)})
    routes = {
        "https://venue.com/": (200, homepage, _HTML),
        link: (403, "Just a moment...", _HTML),
    }
    with _fetcher(tmp_path, routes, page_check=_MarkerCheck(), renderer=renderer) as fetcher:
        found = fetcher.discover_menu_url("https://venue.com/")
    assert [(m.menu_url, m.render) for m in found if isinstance(m, MenuUrlDiscovery)] == [
        (link, "headed-test")
    ]


# -- SiteFetcher: own-site pages -------------------------------------------------


def _own_site(
    menu_body: str, extra: dict[str, tuple[int, str, str]] | None = None
) -> dict[str, tuple[int, str, str]]:
    homepage = '<html><body><h1>Home</h1><a href="/menu">Our menu</a></body></html>'
    return {"/": (200, homepage, _HTML), "/menu": (200, menu_body, _HTML), **(extra or {})}


def test_js_only_own_site_candidate_is_rendered(tmp_path: Path) -> None:
    renderer = _ScriptedRenderer({"https://site.com/menu": _rendered("https://site.com/menu")})
    with _fetcher(
        tmp_path, _own_site(_SHELL), page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        found = fetcher.discover_menu_url("https://site.com/")
    assert renderer.calls == ["https://site.com/menu"]
    (menu,) = found
    assert isinstance(menu, MenuUrlDiscovery)
    assert (menu.menu_url, menu.render) == ("https://site.com/menu", "headed-test")


def test_a_readable_non_menu_page_is_not_rendered(tmp_path: Path) -> None:
    text_page = (
        "<html><body><h1>About</h1><p>" + "We cook. " * 100 + "</p><script></script></body></html>"
    )
    renderer = _ScriptedRenderer({})
    with _fetcher(
        tmp_path, _own_site(text_page), page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        assert fetcher.discover_menu_url("https://site.com/") == ()
    assert renderer.calls == []


def test_a_static_own_site_menu_is_not_rendered(tmp_path: Path) -> None:
    renderer = _ScriptedRenderer({})
    with _fetcher(
        tmp_path, _own_site(_MENU), page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        (menu,) = fetcher.discover_menu_url("https://site.com/")
    assert isinstance(menu, MenuUrlDiscovery) and menu.render is None
    assert renderer.calls == []


def test_own_site_renders_are_capped_per_site(tmp_path: Path) -> None:
    links = "".join(f'<a href="/menu-{i}">Menu {i}</a>' for i in range(5))
    homepage = f"<html><body><h1>Home</h1>{links}</body></html>"
    routes = {"/": (200, homepage, _HTML), **{f"/menu-{i}": (200, _SHELL, _HTML) for i in range(5)}}
    renderer = _ScriptedRenderer({})
    with _fetcher(tmp_path, routes, page_check=_MarkerCheck(), renderer=renderer) as fetcher:
        assert fetcher.discover_menu_url("https://site.com/") == ()
    assert len(renderer.calls) == MAX_RENDER_CANDIDATES


def test_a_render_that_lands_on_the_homepage_is_not_a_menu(tmp_path: Path) -> None:
    renderer = _ScriptedRenderer({"https://site.com/menu": _rendered("https://site.com/")})
    with _fetcher(
        tmp_path, _own_site(_SHELL), page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        assert fetcher.discover_menu_url("https://site.com/") == ()


def test_looks_js_only() -> None:
    assert looks_js_only(_SHELL)
    assert not looks_js_only("<html><body><p>tiny</p></body></html>"), "no scripts"
    assert not looks_js_only("<html><body><p>" + "x" * 400 + "</p><script></script></body></html>")


# -- SiteFetcher: re-verification renders before it rejects ----------------------


def test_reverify_renders_a_refused_platform_page(tmp_path: Path) -> None:
    url = "https://order.toasttab.com/online/venue"
    renderer = _ScriptedRenderer({url: _rendered(url)})
    with _fetcher(
        tmp_path, {url: (403, "no", _HTML)}, page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        result = fetcher.verify_menu_attempt("https://venue.com/", url, not_before=_NOW)
    assert isinstance(result, MenuUrlDiscovery) and result.render == "headed-test"


def test_reverify_keeps_a_challenged_platform_page(tmp_path: Path) -> None:
    url = "https://order.toasttab.com/online/venue"
    renderer = _ScriptedRenderer({url: CaptureFailure("skipped", "bot_challenge", _NOW)})
    with _fetcher(
        tmp_path, {url: (403, "no", _HTML)}, page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        result = fetcher.verify_menu_attempt("https://venue.com/", url, not_before=_NOW)
    assert isinstance(result, CaptureFailure) and result.reason_code == "bot_challenge"


def test_reverify_rejects_on_the_rendered_verdict(tmp_path: Path) -> None:
    url = "https://order.toasttab.com/online/venue"
    renderer = _ScriptedRenderer({url: _rendered(url, "<html><body>Jobs</body></html>")})
    with _fetcher(
        tmp_path, {url: (403, "no", _HTML)}, page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        result = fetcher.verify_menu_attempt("https://venue.com/", url, not_before=_NOW)
    assert isinstance(result, CaptureFailure) and result.reason_code == "no_menu_found"


def test_reverify_renders_a_js_only_own_site_menu(tmp_path: Path) -> None:
    renderer = _ScriptedRenderer({"https://site.com/menu": _rendered("https://site.com/menu")})
    with _fetcher(
        tmp_path, _own_site(_SHELL), page_check=_MarkerCheck(), renderer=renderer
    ) as fetcher:
        result = fetcher.verify_menu_attempt(
            "https://site.com/", "https://site.com/menu", not_before=_NOW
        )
    assert isinstance(result, MenuUrlDiscovery) and result.render == "headed-test"


# -- pacing ------------------------------------------------------------------------


def test_render_waits_out_the_static_fetch_on_the_same_host(tmp_path: Path) -> None:
    url = "https://www.doordash.com/store/x-1/"
    clock = FakeClock()
    renderer = _ScriptedRenderer({url: _rendered(url)})
    with _fetcher(
        tmp_path,
        {url: (403, "no", _HTML)},
        clock=clock,
        min_interval_s=3.0,
        page_check=_MarkerCheck(),
        renderer=renderer,
    ) as fetcher:
        fetcher.discover_menu_url(url)
    assert clock.sleeps[-1] == pytest.approx(3.0), "the render waits the per-host interval"


def test_pace_applies_a_crawl_delay_from_the_renderer(tmp_path: Path) -> None:
    clock = FakeClock()
    with _fetcher(tmp_path, {}, clock=clock, min_interval_s=1.0) as fetcher:
        fetcher.pace("a.com", 10.0)
        fetcher.pace("a.com")
    assert clock.sleeps == [pytest.approx(10.0)]


# -- toast.app alias (S6f decision 3) --------------------------------------------------


def test_toast_app_is_a_toast_alias() -> None:
    assert ordering_platform_host("https://toast.app/r/lucky/order") == "toasttab.com"
    assert ordering_platform_host("https://order.toasttab.com/online/x") == "toasttab.com"
    assert is_platform_venue_page("https://toast.app/r/lucky/order", ordering_only=True)
    html = '<a href="https://toast.app/r/a/order">A</a><a href="https://www.toasttab.com/b">B</a>'
    assert list(platform_links_by_host(html, "https://v.com/")) == ["toasttab.com"]


# -- payload -------------------------------------------------------------------------


def test_payload_records_the_renderer_and_a_static_pass_drops_it() -> None:
    rendered = MenuUrlDiscovery("https://x.com/m", "platform", _NOW, "sha256:a", None, "headed")
    static = MenuUrlDiscovery("https://x.com/m", "platform", _NOW, "sha256:a")
    assert _with_render({"menu_url": "u"}, rendered) == {"menu_url": "u", "render": "headed"}
    assert _with_render({"menu_url": "u", "render": "headed"}, static) == {"menu_url": "u"}


# == BrowserRenderer against a fake Playwright ======================================


class _FakeError(Exception):
    pass


class _FakeTimeout(_FakeError):
    pass


@dataclass
class _Resp:
    """A page's answer: status, body, headers, a redirect target, sub-requests."""

    status: int = 200
    body: str = _MENU
    headers: dict[str, str] = field(default_factory=dict)
    location: str | None = None
    subrequests: tuple[tuple[str, str], ...] = ()  # (url, resource type)
    timeout: bool = False
    fails: bool = False  # Chromium: an empty 4xx/5xx body fails the navigation


class _Request:
    def __init__(
        self, url: str, resource_type: str, frame: object, nav: bool, prev: _Request | None
    ) -> None:
        self.url = url
        self.resource_type = resource_type
        self.frame = frame
        self._nav = nav
        self.redirected_from = prev

    def is_navigation_request(self) -> bool:
        return self._nav


class _Response:
    def __init__(self, request: _Request, answer: _Resp) -> None:
        self.request = request
        self.status = answer.status
        self.headers = answer.headers
        self._body = answer.body

    def text(self) -> str:
        return self._body


class _Cdp:
    """A DevTools session: pauses each request for the renderer's Fetch handler."""

    def __init__(self) -> None:
        self._handler: Callable[[dict[str, Any]], None] | None = None
        self.enabled = False
        self.verdicts: dict[str, str] = {}

    def on(self, event: str, handler: Callable[[dict[str, Any]], None]) -> None:
        assert event == "Fetch.requestPaused"
        self._handler = handler

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "main"}}}
        if method == "Fetch.enable":
            self.enabled = True
        elif method in {"Fetch.continueRequest", "Fetch.failRequest"}:
            assert params is not None
            self.verdicts[params["requestId"]] = method
        return {}

    def through(self, request_id: str, url: str, kind: str, frame: str) -> bool:
        if not self.enabled or self._handler is None:
            return True
        self._handler(
            {
                "requestId": request_id,
                "request": {"url": url},
                "resourceType": kind,
                "frameId": frame,
            }
        )
        return self.verdicts[request_id] == "Fetch.continueRequest"


class _Web:
    """The fake internet: URL → answer; records every request that got through."""

    def __init__(self, answers: dict[str, _Resp]) -> None:
        self.answers = answers
        self.fetched: list[str] = []
        self.aborted: list[str] = []
        self.contexts: list[dict[str, Any]] = []


class _Page:
    def __init__(self, web: _Web) -> None:
        self._web = web
        self.main_frame = object()
        self.url = "about:blank"
        self.cdp = _Cdp()
        self._listeners: list[Callable[[Any], None]] = []
        self._html = ""
        self._ids = 0

    def on(self, _event: str, listener: Callable[[Any], None]) -> None:
        self._listeners.append(listener)

    def _through(self, request: _Request) -> bool:
        self._ids += 1
        kind = request.resource_type.capitalize() if request.resource_type != "xhr" else "XHR"
        frame = "main" if request.frame is self.main_frame else "child"
        if self.cdp.through(f"r{self._ids}", request.url, kind, frame):
            self._web.fetched.append(request.url)
            return True
        self._web.aborted.append(request.url)
        return False

    def goto(self, url: str, **_kwargs: object) -> None:
        prev: _Request | None = None
        for _hop in range(10):
            request = _Request(url, "document", self.main_frame, True, prev)
            if not self._through(request):
                raise _FakeError(f"net::ERR_BLOCKED_BY_CLIENT at {url}")
            answer = self._web.answers.get(url, _Resp(404, "nope"))
            if answer.timeout:
                raise _FakeTimeout(url)
            response = _Response(request, answer)
            for listener in self._listeners:
                listener(response)
            if answer.fails:
                raise _FakeError(f"net::ERR_HTTP_RESPONSE_CODE_FAILURE at {url}")
            if answer.location is None:
                break
            prev, url = request, answer.location
        self.url, self._html = url, answer.body
        for sub_url, kind in answer.subrequests:
            self._through(_Request(sub_url, kind, self.main_frame, False, None))

    def wait_for_load_state(self, *_args: object, **_kwargs: object) -> None:
        return None

    def content(self) -> str:
        return self._html

    def evaluate(self, _script: str) -> str:
        return "Mozilla/5.0 Chrome/153"

    def close(self) -> None:
        return None


class _Context:
    def __init__(self, web: _Web) -> None:
        self._web = web

    def new_page(self) -> _Page:
        return _Page(self._web)

    def new_cdp_session(self, page: _Page) -> _Cdp:
        return page.cdp

    def close(self) -> None:
        return None


class _Browser:
    def __init__(self, web: _Web) -> None:
        self._web = web

    def new_page(self) -> _Page:
        return _Page(self._web)

    def new_context(self, **kwargs: Any) -> _Context:  # noqa: ANN401
        self._web.contexts.append(kwargs)
        return _Context(self._web)


_TOKEN = "helios-test/1.0"  # noqa: S105 - a User-Agent, not a secret


def _renderer(
    answers: dict[str, _Resp], *, private: frozenset[str] = frozenset()
) -> tuple[BrowserRenderer, _Web, list[tuple[str, float]]]:
    web = _Web(answers)
    session = BrowserSession(cast("Any", _Browser(web)), _FakeTimeout, _FakeError, lambda: None)
    paced: list[tuple[str, float]] = []
    renderer = BrowserRenderer(
        user_agent=_TOKEN,
        launch=lambda: session,
        resolve=lambda host: ["10.0.0.1"] if host in private else ["93.184.216.34"],
        clock=lambda: 1_800_000_000.0,
        monotonic=lambda: 5.0,
    )
    return renderer, web, paced


def _render(
    renderer: BrowserRenderer, paced: list[tuple[str, float]], url: str
) -> FetchResult | CaptureFailure:
    return renderer.render(url, pace=lambda host, delay: paced.append((host, delay)))


_ALLOW_ALL = _Resp(200, "User-agent: *\nDisallow:\n", {"content-type": "text/plain"})


def test_render_returns_the_dom_with_an_honest_user_agent() -> None:
    url = "https://order.toasttab.com/online/venue"
    renderer, web, paced = _renderer(
        {"https://order.toasttab.com/robots.txt": _ALLOW_ALL, url: _Resp(200, _MENU)}
    )
    result = _render(renderer, paced, url)
    assert isinstance(result, FetchResult)
    assert (result.url, result.text, result.render) == (url, _MENU, RENDER_NAME)
    assert result.content_hash.startswith("sha256:")
    assert renderer.user_agent == f"Mozilla/5.0 Chrome/153 {_TOKEN}"
    assert all(kw["user_agent"] == renderer.user_agent for kw in web.contexts)
    assert all(kw["service_workers"] == "block" for kw in web.contexts)
    assert ("order.toasttab.com", 0.0) in paced, "robots read and navigation are paced"
    assert renderer.stats.summary()["rendered"] == 1


def test_robots_is_read_through_the_browser_following_redirects() -> None:
    url = "https://order.toasttab.com/x/giftcards"
    rules = _Resp(200, "User-agent: *\nDisallow: /*/giftcards\n")
    renderer, web, paced = _renderer(
        {
            "https://order.toasttab.com/robots.txt": _Resp(
                301, location="https://www.toasttab.com/robots.txt"
            ),
            "https://www.toasttab.com/robots.txt": rules,
            url: _Resp(200, _MENU),
        }
    )
    result = _render(renderer, paced, url)
    assert isinstance(result, CaptureFailure)
    assert (result.outcome, result.reason_code) == ("skipped", "robots_disallowed")
    assert url not in web.fetched, "a disallowed page is never navigated"


def test_a_challenged_robots_txt_makes_the_host_unavailable() -> None:
    url = "https://p.example/menu"
    renderer, _web, paced = _renderer(
        {
            "https://p.example/robots.txt": _Resp(
                403, "<script src=/cdn-cgi/challenge-platform/x>"
            ),
            url: _Resp(200, _MENU),
        }
    )
    result = _render(renderer, paced, url)
    assert isinstance(result, CaptureFailure) and result.reason_code == "robots_unavailable"


def test_crawl_delay_from_browser_robots_paces_the_navigation() -> None:
    url = "https://p.example/menu"
    renderer, _web, paced = _renderer(
        {
            "https://p.example/robots.txt": _Resp(200, "User-agent: *\nCrawl-delay: 7\n"),
            url: _Resp(200, _MENU),
        }
    )
    assert isinstance(_render(renderer, paced, url), FetchResult)
    assert ("p.example", 7.0) in paced


def test_every_sub_request_is_checked_against_its_own_robots() -> None:
    url = "https://order.toasttab.com/online/venue"
    renderer, web, paced = _renderer(
        {
            "https://order.toasttab.com/robots.txt": _ALLOW_ALL,
            "https://api.example/robots.txt": _Resp(200, "User-agent: *\nDisallow: /private\n"),
            "https://cdn.example/robots.txt": _Resp(404, "nope"),
            url: _Resp(
                200,
                _MENU,
                subrequests=(
                    ("https://api.example/menu.json", "fetch"),
                    ("https://api.example/private/x", "xhr"),
                    ("https://cdn.example/app.js", "script"),
                    ("https://cdn.example/logo.png", "image"),
                    ("https://lan.example/x.js", "script"),
                    ("https://cdn.example/favicon.ico", "other"),
                ),
            ),
        },
        private=frozenset({"lan.example"}),
    )
    assert isinstance(_render(renderer, paced, url), FetchResult)
    assert "https://api.example/menu.json" in web.fetched
    assert "https://cdn.example/app.js" in web.fetched, "404 robots.txt allows all"
    assert {
        "https://api.example/private/x",
        "https://cdn.example/logo.png",
        "https://lan.example/x.js",
        "https://cdn.example/favicon.ico",
    } <= set(web.aborted)
    stats = renderer.stats
    assert (stats.subrequests, stats.subrequests_blocked) == (4, 2), "images are not counted"
    assert stats.blocked_hosts == {"api.example": 1, "lan.example": 1}
    assert ("api.example", 0.0) in paced, "a sub-request host's robots read is paced"
    assert stats.passes == 2, "unknown sub-request hosts: aborted, read, rendered again"
    assert web.fetched.count("https://api.example/robots.txt") == 1
    assert isinstance(_render(renderer, paced, url), FetchResult)
    assert stats.passes == 3, "the robots cache lasts the run: one more pass"


def test_redirect_off_the_site_is_refused_but_a_platform_alias_is_not() -> None:
    start = "https://www.toasttab.com/local/order/lucky"
    alias = "https://toast.app/r/lucky/order"
    renderer, _web, paced = _renderer(
        {
            "https://www.toasttab.com/robots.txt": _ALLOW_ALL,
            "https://toast.app/robots.txt": _ALLOW_ALL,
            start: _Resp(302, location=alias),
            alias: _Resp(200, _MENU),
        }
    )
    result = _render(renderer, paced, start)
    assert isinstance(result, FetchResult) and result.url == alias

    off = "https://venue.example/menu"
    renderer, _web, paced = _renderer(
        {
            "https://venue.example/robots.txt": _ALLOW_ALL,
            off: _Resp(302, location="https://elsewhere.example/menu"),
        }
    )
    result = _render(renderer, paced, off)
    assert isinstance(result, CaptureFailure)
    assert (result.outcome, result.reason_code) == ("skipped", "redirect_refused")


@pytest.mark.parametrize(
    ("answer", "outcome", "reason"),
    [
        (_Resp(403, "Access denied"), "skipped", "bot_challenge"),
        (_Resp(429, "slow down"), "skipped", "bot_challenge"),
        (_Resp(200, _MENU, {"cf-mitigated": "challenge"}), "skipped", "bot_challenge"),
        (_Resp(503, "<title>Just a moment...</title>"), "skipped", "bot_challenge"),
        (_Resp(404, "gone"), "failed", "http_404"),
        (_Resp(503, "maintenance"), "failed", "http_503"),
        (_Resp(200, "x" * (MAX_BODY_BYTES + 1)), "failed", "too_large"),
        (_Resp(timeout=True), "failed", "render_timeout"),
    ],
)
def test_render_failures(answer: _Resp, outcome: str, reason: str) -> None:
    url = "https://p.example/menu"
    renderer, _web, paced = _renderer({"https://p.example/robots.txt": _ALLOW_ALL, url: answer})
    result = _render(renderer, paced, url)
    assert isinstance(result, CaptureFailure)
    assert (result.outcome, result.reason_code) == (outcome, reason)
    assert renderer.stats.failures[reason] == 1


def test_a_non_public_page_is_refused_before_the_browser_starts() -> None:
    launched: list[bool] = []

    def launch() -> BrowserSession:
        launched.append(True)
        raise AssertionError("the browser must not start")

    renderer = BrowserRenderer(
        user_agent=_TOKEN, launch=launch, resolve=lambda _host: ["192.168.1.219"]
    )
    result = renderer.render("https://pi.local/menu", pace=lambda _h, _d: None)
    assert isinstance(result, CaptureFailure) and result.reason_code == "non_public_host"
    assert launched == []


def test_headed_chromium_needs_a_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="xvfb-run"):
        launch_headed_chromium()


def test_renderer_requires_a_token() -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        BrowserRenderer(user_agent=" ")


# -- pure rules ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "skipped"),
    [
        (RobotsAnswer(200, "User-agent: *\nDisallow: /a"), False),
        (RobotsAnswer(404), False),
        (RobotsAnswer(403), False),
        (RobotsAnswer(429), True),
        (RobotsAnswer(500), True),
        (RobotsAnswer(None), True),
        (RobotsAnswer(200, "", redirects=6), True),
        (RobotsAnswer(403, challenged=True), True),
    ],
)
def test_robots_rules(answer: RobotsAnswer, skipped: bool) -> None:
    rules, reason = robots_rules(answer)
    assert (rules is None) == skipped
    assert reason == ("robots_unavailable" if skipped else "robots_disallowed")


def test_is_challenge_is_generic() -> None:
    assert is_challenge(200, {"cf-mitigated": "challenge"}, "")
    assert is_challenge(403, {}, '<div class="g-recaptcha captcha">')
    assert not is_challenge(200, {}, "captcha in a menu description")
    assert not is_challenge(403, {}, "Forbidden")


def test_stays_on() -> None:
    assert stays_on("https://www.x.com/a", "https://x.com/b")
    assert stays_on("https://www.toasttab.com/a", "https://order.toasttab.com/b")
    assert stays_on("https://www.toasttab.com/a", "https://toast.app/r/b")
    assert not stays_on("https://x.com/a", "https://y.com/a")
    assert not stays_on("https://www.toasttab.com/a", "https://www.doordash.com/a")


def test_a_redirect_hop_is_checked_against_robots() -> None:
    """Regression (live check): Playwright routes skip redirect hops; CDP Fetch doesn't."""
    start, hop = "https://p.example/a", "https://p.example/private/b"
    renderer, web, paced = _renderer(
        {
            "https://p.example/robots.txt": _Resp(200, "User-agent: *\nDisallow: /private\n"),
            start: _Resp(302, location=hop),
            hop: _Resp(200, _MENU),
        }
    )
    result = _render(renderer, paced, start)
    assert isinstance(result, CaptureFailure)
    assert (result.outcome, result.reason_code) == ("skipped", "robots_disallowed")
    assert hop in web.aborted and hop not in web.fetched


def test_cloveronline_is_a_clover_alias() -> None:
    assert ordering_platform_host("https://yanagi-austin.cloveronline.com/") == "clover.com"
    assert stays_on(
        "https://www.clover.com/online-ordering/yanagi-austin",
        "https://yanagi-austin.cloveronline.com/",
    )


def test_a_failing_decision_fails_the_request_instead_of_leaving_it_paused() -> None:
    web = _Web({})
    page = _Page(web)

    def decide(_url: str, _kind: str, _main: bool) -> str | None:  # noqa: FBT001
        raise _FakeError("browser closed mid robots.txt read")

    _intercept(_Context(web), page, decide, _FakeError)
    assert not page.cdp.through("r1", "https://p.example/x.js", "Script", "main")
    assert page.cdp.verdicts == {"r1": "Fetch.failRequest"}


def test_a_page_whose_unknown_hosts_all_refuse_is_rendered_once() -> None:
    url = "https://p.example/menu"
    renderer, web, paced = _renderer(
        {
            "https://p.example/robots.txt": _ALLOW_ALL,
            "https://ads.example/robots.txt": _Resp(200, "User-agent: *\nDisallow: /\n"),
            url: _Resp(200, _MENU, subrequests=(("https://ads.example/t.js", "script"),)),
        }
    )
    assert isinstance(_render(renderer, paced, url), FetchResult)
    assert renderer.stats.passes == 1
    assert web.fetched.count(url) == 1
    assert renderer.stats.subrequests_unchecked == 1, "aborted before its robots.txt was read"


def test_an_empty_4xx_robots_txt_still_allows_all() -> None:
    """Regression (live measurement): Chromium fails the navigation on an empty 400/404
    body; the answer is still a 4xx (allow all), not an unreachable host."""
    url = "https://shop.square.site/"
    renderer, web, paced = _renderer(
        {
            "https://shop.square.site/robots.txt": _ALLOW_ALL,
            "https://cdn.example/robots.txt": _Resp(400, "", fails=True),
            url: _Resp(200, _MENU, subrequests=(("https://cdn.example/app.js", "script"),)),
        }
    )
    assert isinstance(_render(renderer, paced, url), FetchResult)
    assert "https://cdn.example/app.js" in web.fetched


def test_an_empty_error_page_is_its_status_not_a_network_error() -> None:
    url = "https://p.example/menu"
    renderer, _web, paced = _renderer(
        {"https://p.example/robots.txt": _ALLOW_ALL, url: _Resp(404, "", fails=True)}
    )
    result = _render(renderer, paced, url)
    assert isinstance(result, CaptureFailure) and result.reason_code == "http_404"
    renderer, _web, paced = _renderer(
        {"https://p.example/robots.txt": _ALLOW_ALL, url: _Resp(403, "", fails=True)}
    )
    result = _render(renderer, paced, url)
    assert isinstance(result, CaptureFailure) and result.reason_code == "bot_challenge"
