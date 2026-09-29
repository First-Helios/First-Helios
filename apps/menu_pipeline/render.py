"""Headed Chromium rendering for pages that need JavaScript (ADR-0013 §4, Amendments 1–2).

Discovery's :class:`~apps.discovery.web_client.SiteFetcher` hands a page here
when the static fetch can't verify it (a platform page answering ``403`` or
failing the page check; an own-site page that looks JavaScript-only). One
Chromium, one page at a time, **headed** under a virtual display (Xvfb): Toast
refuses headless Chromium but loads for a headed one (S6d render probe).

Etiquette, as for the static fetcher, plus the owner's S6f decisions:

- **User-Agent:** the browser's own, with the Helios token appended. No stealth
  plugins, no spoofing, no challenge or CAPTCHA solving: a page that still
  answers ``403``/``429`` or a bot challenge is a skipped Capture
  (``bot_challenge``).
- **robots.txt is read through the browser** (S6f decision 2), because a
  static fetch can get a challenge page where a browser gets the real file.
  Redirects are followed (RFC 9309 §2.3.1.2 allows five, across hosts). 2xx →
  its rules; 4xx → allow all; 429, 5xx, unreachable, more than five redirects
  or still challenged → the host is unavailable.
- **Every request is checked** (S6f decision 1, ADR-0013 open question 3): the
  navigation, each redirect hop and every sub-request the page's own scripts
  make are checked against their own host's robots.txt for the Helios token,
  and must go to a public address. Disallowed or unavailable → aborted and
  counted. Images, fonts and media are never fetched. A sub-request to a host
  whose robots.txt isn't known yet is aborted too; once the page settles those
  hosts' robots.txt are read and, if any aborted request turns out allowed, the
  page is rendered again (at most :data:`MAX_RENDER_PASSES` times). Reading them
  inside the interception handler instead would start one read per parallel
  request (a page firing dozens of requests at one CDN stalled the browser).
  The robots.txt cache lasts the run, so later pages need one pass.
- **Redirects** of the page itself stay on the site, or on the same ordering
  platform (``toasttab.com`` ↔ ``toast.app``, ``clover.com`` ↔
  ``cloveronline.com``; S6f decisions).
- **Rate limit:** each navigation hop and robots.txt read waits on the
  fetcher's per-host pacing, with any Crawl-delay the browser-read robots.txt
  sets. Sub-requests are the page's own and are not paced.

Playwright is the ``menu`` extra (worker image). The browser session is
injectable, so tests drive the renderer with fakes and CI starts no browser.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, NamedTuple
from urllib.parse import urlsplit

from protego import Protego

from apps.discovery.menu_url import ordering_platform_host, same_site
from apps.discovery.web_client import (
    MAX_BODY_BYTES,
    MAX_CRAWL_DELAY_S,
    CaptureFailure,
    FetchResult,
    is_public_address,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

RENDER_NAME = "headed-chromium"
NAVIGATION_TIMEOUT_MS = 30_000
# After DOMContentLoaded, wait this long at most for the network to go idle
# (long-polling pages never do).
SETTLE_TIMEOUT_MS = 15_000
MAX_ROBOTS_REDIRECTS = 5
MAX_RENDER_PASSES = 3
BLOCKED_RESOURCE_TYPES = frozenset({"image", "font", "media"})
_CHALLENGE_STATUSES = frozenset({403, 429})
# Generic interstitial markers (not per-platform parsing): a challenge page,
# whatever the vendor, names its challenge or CAPTCHA.
_CHALLENGE_MARKERS = ("challenge-platform", "cf-chl", "captcha", "just a moment")


class BrowserSession(NamedTuple):
    """A launched browser plus the library's exception types and its shutdown."""

    browser: Any  # playwright.sync_api.Browser (the `menu` extra; Any keeps CI import-free)
    timeout_error: type[Exception]
    error: type[Exception]
    close: Callable[[], None]


@dataclass(frozen=True, slots=True)
class RobotsAnswer:
    """What the browser got for ``/robots.txt``: final status (None if unreachable)."""

    status: int | None
    text: str = ""
    redirects: int = 0
    challenged: bool = False


@dataclass(slots=True)
class RenderStats:
    """Counters for the run report and the ADR-0013 §4 measurement."""

    renders: int = 0
    rendered: int = 0
    passes: int = 0
    failures: Counter[str] = field(default_factory=Counter)
    seconds: list[float] = field(default_factory=list)
    subrequests: int = 0  # the final pass's, per render
    subrequests_blocked: int = 0
    subrequests_unchecked: int = 0  # robots.txt still unknown after the last pass
    blocked_hosts: Counter[str] = field(default_factory=Counter)

    def summary(self) -> dict[str, object]:
        ordered = sorted(self.seconds)
        return {
            "renders": self.renders,
            "rendered": self.rendered,
            "passes": self.passes,
            "failures": dict(self.failures),
            "median_s": round(ordered[len(ordered) // 2], 1) if ordered else None,
            "max_s": round(ordered[-1], 1) if ordered else None,
            "subrequests": self.subrequests,
            "subrequests_blocked": self.subrequests_blocked,
            "subrequests_unchecked": self.subrequests_unchecked,
        }


def is_challenge(status: int, headers: Mapping[str, str], text: str) -> bool:
    """A bot challenge: Cloudflare's ``cf-mitigated`` header, or a refusal naming one."""
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    head = text[:20_000].lower()
    return status in _CHALLENGE_STATUSES | {503} and any(m in head for m in _CHALLENGE_MARKERS)


def robots_rules(answer: RobotsAnswer) -> tuple[Protego | None, str]:
    """RFC 9309 over a browser read: the rules, or ``None`` and why the host is skipped."""
    status = answer.status
    if status is None or answer.challenged or answer.redirects > MAX_ROBOTS_REDIRECTS:
        return None, "robots_unavailable"
    if 200 <= status < 300:  # noqa: PLR2004 - HTTP status classes
        return Protego.parse(answer.text), "robots_disallowed"
    if 400 <= status < 500 and status != 429:  # noqa: PLR2004
        return Protego.parse(""), "robots_disallowed"
    return None, "robots_unavailable"


def stays_on(start: str, url: str) -> bool:
    """A page's own navigation may go to its site or to the same ordering platform."""
    platform = ordering_platform_host(start)
    return same_site(start, url) or (
        platform is not None and ordering_platform_host(url) == platform
    )


def _origin(url: str) -> str:
    split = urlsplit(url)
    return f"{split.scheme}://{split.netloc}"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class RobotsCache:
    """Per-origin robots.txt decisions for the run, read through ``load``."""

    def __init__(self, load: Callable[[str], RobotsAnswer], user_agent: str) -> None:
        self._load = load
        self._user_agent = user_agent
        self._rules: dict[str, tuple[Protego | None, str]] = {}

    def known(self, url: str) -> bool:
        return _origin(url) in self._rules

    def load(self, origin: str) -> None:
        if origin not in self._rules:
            self._rules[origin] = robots_rules(self._load(origin))

    def check(self, url: str) -> tuple[str | None, float]:
        """``(None, crawl delay)`` when allowed, else ``(reason, 0)``; reads if unknown."""
        origin = _origin(url)
        self.load(origin)
        rules, reason = self._rules[origin]
        if rules is None:
            return reason, 0.0
        delay = float(rules.crawl_delay(self._user_agent) or 0.0)
        if delay > MAX_CRAWL_DELAY_S:
            return "crawl_delay_too_long", 0.0
        if not rules.can_fetch(url, self._user_agent):
            return reason, 0.0
        return None, delay


class RequestPolicy:
    """Allow or abort each request of one render pass (the interception handler's decisions).

    The main navigation and its redirect hops come one at a time, so their
    robots.txt is read on demand. A sub-request to an origin whose robots.txt
    isn't known is aborted and listed in :attr:`pending` for the next pass.
    """

    def __init__(
        self,
        start_url: str,
        *,
        robots: RobotsCache,
        public_host: Callable[[str], bool],
        pace: Callable[[str, float], None],
    ) -> None:
        self._start = start_url
        self._robots = robots
        self._public_host = public_host
        self._pace = pace
        self.navigation_refused: str | None = None
        self.pending: dict[str, list[str]] = {}  # origin -> aborted sub-request URLs
        self.subrequests = 0
        self.blocked_hosts: Counter[str] = Counter()

    def decide(self, url: str, resource_type: str, *, main_navigation: bool) -> str | None:
        """``None`` to let the request through, else the reason it is aborted."""
        reason = self._reason(url, resource_type, main_navigation=main_navigation)
        if main_navigation:
            if reason is not None:
                self.navigation_refused = reason
        elif resource_type not in BLOCKED_RESOURCE_TYPES:
            self.subrequests += 1
            if reason == "robots_pending":
                self.pending.setdefault(_origin(url), []).append(url)
            elif reason is not None:
                self.blocked_hosts[_host(url)] += 1
        return reason

    def commit(self, stats: RenderStats) -> None:
        """Add this pass's sub-request counts to the run's."""
        stats.subrequests += self.subrequests
        stats.subrequests_blocked += sum(self.blocked_hosts.values())
        stats.subrequests_unchecked += sum(len(urls) for urls in self.pending.values())
        stats.blocked_hosts.update(self.blocked_hosts)

    def _reason(self, url: str, resource_type: str, *, main_navigation: bool) -> str | None:
        split = urlsplit(url)
        if split.scheme not in {"http", "https"}:
            return "scheme"
        if not main_navigation and resource_type in BLOCKED_RESOURCE_TYPES:
            return "resource_type"
        if not self._public_host(_host(url)):
            return "non_public_host"
        if main_navigation and not stays_on(self._start, url):
            return "redirect_refused"
        if split.path == "/robots.txt":
            return None  # robots.txt itself is never subject to robots.txt
        if not main_navigation and not self._robots.known(url):
            return "robots_pending"
        reason, delay = self._robots.check(url)
        if reason is not None:
            return reason
        if main_navigation:
            self._pace(_host(url), delay)
        return None


def _resolve_host(host: str) -> list[str]:
    import socket  # noqa: PLC0415 - only the default resolver needs it

    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


def launch_headed_chromium() -> BrowserSession:
    """Start Playwright's Chromium with a window; needs a display (``xvfb-run -a``)."""
    if not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "headed Chromium needs a display: run the command under `xvfb-run -a` "
            "(the worker image installs Xvfb; ADR-0013 Amendment 1)"
        )
    from playwright.sync_api import Error, TimeoutError, sync_playwright  # noqa: PLC0415, A004

    manager = sync_playwright().start()
    browser = manager.chromium.launch(headless=False)

    def close() -> None:
        browser.close()
        manager.stop()

    return BrowserSession(browser, TimeoutError, Error, close)


class BrowserRenderer:
    """A :class:`~apps.discovery.web_client.PageRenderer` over one headed Chromium."""

    def __init__(
        self,
        *,
        user_agent: str,
        launch: Callable[[], BrowserSession] = launch_headed_chromium,
        resolve: Callable[[str], Iterable[str]] = _resolve_host,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("BrowserRenderer requires a non-empty User-Agent token")
        self._token = user_agent
        self._launch = launch
        self._resolve = resolve
        self._clock = clock
        self._monotonic = monotonic
        self._session: BrowserSession | None = None
        self._browser_ua = ""
        self._robots_context: Any = None
        self._public: dict[str, bool] = {}
        self._pace: Callable[[str, float], None] = lambda _host, _delay: None
        self._robots = RobotsCache(self._read_robots, user_agent)
        self.stats = RenderStats()

    @property
    def name(self) -> str:
        return RENDER_NAME

    @property
    def user_agent(self) -> str:
        """The browser's own User-Agent with the Helios token appended."""
        return f"{self._browser_ua} {self._token}".strip()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
            self._robots_context = None

    def __enter__(self) -> BrowserRenderer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- session --------------------------------------------------------------

    def _started(self) -> BrowserSession:
        if self._session is None:
            session = self._launch()
            probe = session.browser.new_page()
            try:
                self._browser_ua = str(probe.evaluate("navigator.userAgent"))
            finally:
                probe.close()
            self._session = session
        return self._session

    def _new_context(self) -> Any:  # noqa: ANN401 - playwright BrowserContext
        # Service workers are blocked so every request passes the interception handler.
        return self._started().browser.new_context(
            user_agent=self.user_agent, service_workers="block", accept_downloads=False
        )

    def _is_public(self, host: str) -> bool:
        if host not in self._public:
            try:
                addresses = [host] if _is_ip(host) else list(self._resolve(host))
            except OSError:
                addresses = []
            self._public[host] = bool(addresses) and all(is_public_address(a) for a in addresses)
        return self._public[host]

    # -- robots.txt through the browser ----------------------------------------

    def _read_robots(self, origin: str) -> RobotsAnswer:
        session = self._started()
        if self._robots_context is None:
            self._robots_context = self._new_context()
        page = self._robots_context.new_page()
        documents: list[Any] = []
        page.on("response", _main_documents(page, documents))
        _intercept(
            self._robots_context,
            page,
            lambda url, kind, _main: (
                None
                if kind not in BLOCKED_RESOURCE_TYPES and self._is_public(_host(url))
                else "blocked"
            ),
            session.error,
        )
        self._pace(_host(origin), 0.0)
        try:
            try:
                page.goto(f"{origin}/robots.txt", wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                _settle(page, session)
            except session.error:
                # Chromium fails the navigation on an empty 4xx/5xx body
                # (ERR_HTTP_RESPONSE_CODE_FAILURE), but the response still came.
                pass
            final = _final_document(documents)
            if final is None:
                return RobotsAnswer(None)  # timeout or network error: unreachable
            status = int(final.status)
            text = _body(final, session)
            return RobotsAnswer(
                status,
                text,
                redirects=_redirects(final),
                challenged=is_challenge(status, dict(final.headers), text),
            )
        finally:
            page.close()

    # -- rendering --------------------------------------------------------------

    def render(
        self, url: str, *, pace: Callable[[str, float], None]
    ) -> FetchResult | CaptureFailure:
        """Render ``url`` once and return its DOM, or why it was refused or failed."""
        self._pace = pace
        self.stats.renders += 1
        started = self._monotonic()
        try:
            outcome = self._render(url)
        finally:
            self._pace = lambda _host, _delay: None
        self.stats.seconds.append(self._monotonic() - started)
        if isinstance(outcome, CaptureFailure):
            self.stats.failures[outcome.reason_code] += 1
        else:
            self.stats.rendered += 1
        return outcome

    def _failure(self, outcome: Literal["failed", "skipped"], reason: str) -> CaptureFailure:
        return CaptureFailure(outcome, reason, datetime.fromtimestamp(self._clock(), UTC))

    def _render(self, url: str) -> FetchResult | CaptureFailure:
        """Render passes until no aborted sub-request turns out to be allowed."""
        for done in range(1, MAX_RENDER_PASSES + 1):
            policy = RequestPolicy(
                url, robots=self._robots, public_host=self._is_public, pace=self._pace
            )
            outcome = self._render_pass(url, policy)
            again = False
            if done < MAX_RENDER_PASSES and not isinstance(outcome, CaptureFailure):
                for origin in policy.pending:
                    self._robots.load(origin)
                again = any(
                    self._robots.check(pending)[0] is None
                    for urls in policy.pending.values()
                    for pending in urls
                )
            if not again:
                policy.commit(self.stats)
                self.stats.passes += done
                return outcome
        raise AssertionError("unreachable: the last pass always returns")  # pragma: no cover

    def _render_pass(self, url: str, policy: RequestPolicy) -> FetchResult | CaptureFailure:
        # The first navigation is decided before a context exists, so a refused
        # page never opens one.
        refused = policy.decide(url, "document", main_navigation=True)
        if refused is not None:
            return self._failure("skipped", refused)
        session = self._started()
        context = self._new_context()
        try:
            page = context.new_page()
            documents: list[Any] = []
            page.on("response", _main_documents(page, documents))
            first = [True]

            def decide(request_url: str, kind: str, main: bool) -> str | None:  # noqa: FBT001
                if main and first[0]:
                    first[0] = False  # our own navigation: decided (and paced) above
                    return None
                return policy.decide(request_url, kind, main_navigation=main)

            _intercept(context, page, decide, session.error)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            except session.timeout_error:
                return self._failure("failed", "render_timeout")
            except session.error:
                refusal = policy.navigation_refused
                if refusal is not None:
                    return self._failure("skipped", refusal)
                final = _final_document(documents)
                if final is None:
                    return self._failure("failed", "network_error")
                # An empty 4xx/5xx body fails the navigation, yet it answered.
                status = int(final.status)
                if status in _CHALLENGE_STATUSES:
                    return self._failure("skipped", "bot_challenge")
                return self._failure("failed", f"http_{status}")
            _settle(page, session)
            return self._result(page, documents, url)
        finally:
            context.close()

    def _result(
        self,
        page: Any,  # noqa: ANN401 - playwright Page
        documents: list[Any],
        url: str,
    ) -> FetchResult | CaptureFailure:
        """The settled page: a challenge or error status fails. A later navigation
        the policy refused leaves the loaded page as it stands."""
        final = _final_document(documents)
        status = int(final.status) if final is not None else 0
        html = str(page.content())
        headers = dict(final.headers) if final is not None else {}
        if is_challenge(status, headers, html) or status in _CHALLENGE_STATUSES:
            return self._failure("skipped", "bot_challenge")
        if status != 200:  # noqa: PLR2004
            return self._failure("failed", f"http_{status}" if status else "network_error")
        final_url = str(page.url)
        if not stays_on(url, final_url):
            return self._failure("skipped", "redirect_refused")
        body = html.encode("utf-8", errors="ignore")
        if len(body) > MAX_BODY_BYTES:
            return self._failure("failed", "too_large")
        return FetchResult(
            url=final_url,
            status=200,
            text=html,
            content_type="text/html",
            fetched_at=self._clock(),
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
            render=self.name,
        )


def _intercept(
    context: Any,  # noqa: ANN401 - playwright BrowserContext
    page: Any,  # noqa: ANN401 - playwright Page
    decide: Callable[[str, str, bool], str | None],
    error: type[Exception],
) -> None:
    """Pause every request of ``page`` (redirect hops included) for ``decide``.

    Chrome DevTools Protocol ``Fetch`` interception, not ``page.route``:
    Playwright's routes are not called for redirect hops, so a redirect could
    otherwise leave the site or reach a robots-disallowed URL unchecked.
    ``decide(url, resource type, main-frame document?)`` returns ``None`` to
    continue or a reason to fail the request.
    """
    cdp = context.new_cdp_session(page)
    main_frame = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]

    def paused(event: dict[str, Any]) -> None:
        kind = str(event.get("resourceType", "")).lower()
        url = str(event["request"]["url"])
        if urlsplit(url).path == "/favicon.ico":
            kind = "image"  # the browser's own favicon fetch: never needed
        main = kind == "document" and event.get("frameId") == main_frame
        request_id = event["requestId"]
        try:
            verdict = decide(url, kind, main)
        except error:  # e.g. the browser failed mid robots.txt read: never leave it paused
            verdict = "robots_unavailable"
        # A request the page already cancelled (or a closed page) can't be answered.
        with contextlib.suppress(error):
            if verdict is None:
                cdp.send("Fetch.continueRequest", {"requestId": request_id})
            else:
                cdp.send(
                    "Fetch.failRequest",
                    {"requestId": request_id, "errorReason": "BlockedByClient"},
                )

    cdp.on("Fetch.requestPaused", paused)
    cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})


def _is_ip(host: str) -> bool:
    import ipaddress  # noqa: PLC0415

    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _main_documents(page: Any, documents: list[Any]) -> Callable[[Any], None]:  # noqa: ANN401
    """A response listener collecting the page's main-frame document responses."""

    def on_response(response: Any) -> None:  # noqa: ANN401 - playwright Response
        request = response.request
        if request.is_navigation_request() and request.frame == page.main_frame:
            documents.append(response)

    return on_response


def _final_document(documents: list[Any]) -> Any:  # noqa: ANN401
    """The last main-frame document that is not a redirect (a challenge may reload)."""
    finals = [doc for doc in documents if not 300 <= int(doc.status) < 400]  # noqa: PLR2004
    return finals[-1] if finals else None


def _body(response: Any, session: BrowserSession) -> str:  # noqa: ANN401
    """A response's text, or ``""`` when the browser kept no body for it."""
    try:
        return str(response.text())
    except session.error:
        return ""


def _redirects(response: Any) -> int:  # noqa: ANN401 - playwright Response
    hops, request = 0, response.request.redirected_from
    while request is not None:
        hops += 1
        request = request.redirected_from
    return hops


def _settle(page: Any, session: BrowserSession) -> None:  # noqa: ANN401
    # A page that never goes idle is read as it stands.
    with contextlib.suppress(session.error):
        page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
