"""Polite, disk-cached site fetcher + menu-URL discovery orchestration.

Etiquette is a hard requirement (ADR-0010 §3, amended by review session S2):

- **robots.txt** is parsed with ``protego`` (RFC 9309: longest match wins,
  ``*``/``$`` wildcards, Allow wins ties) and checked before every request,
  including each redirect hop. robots.txt 2xx → its rules; 4xx → allow all;
  5xx, network error or a refused redirect → the whole site is skipped. A
  ``Crawl-delay`` is honoured; one above :data:`MAX_CRAWL_DELAY_S` skips the
  site rather than stall the run.
- **Redirects** are followed by hand, at most :data:`MAX_REDIRECTS` hops, only
  over http/https, only within the same site (host, ``www.`` ignored), and only
  to hosts that resolve to public addresses, so a site cannot point the
  fetcher at the Pi's LAN.
- **Rate limit:** one request per ``max(min_interval_s, Crawl-delay)`` per
  host, for every hop.
- **Size cap:** bodies are streamed and abandoned past :data:`MAX_BODY_BYTES`.
- **Cache:** every outcome (including failures) is written atomically to disk
  with its fetch time and reused for :data:`CACHE_TTL_S`, so a restarted run
  does not re-fetch and the next monthly run starts fresh.

The httpx client, DNS resolver and clocks are injectable, so tests replay from
a mock transport and CI makes no live network calls.

The pure candidate logic lives in :mod:`apps.discovery.menu_url`; this module
only fetches inputs, verifies which candidate actually resolves, and records
which signal produced it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx
from protego import Protego

from apps.discovery.menu_url import ordered_menu_candidates, path_candidates, same_site

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

MAX_REDIRECTS = 5
MAX_BODY_BYTES = 3 * 1024 * 1024  # owner decision D2.4
MAX_CRAWL_DELAY_S = 60.0
# Owner decision D2.5: robots.txt and failures expire after 7 days; good pages
# are kept for the run. A Pi run takes a day or two, so one TTL covers all three.
CACHE_TTL_S = 7 * 24 * 60 * 60

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One cached HTTP response reduced to what discovery needs."""

    url: str  # the final URL after any followed redirects
    status: int
    text: str
    content_type: str


@dataclass(frozen=True, slots=True)
class MenuUrlDiscovery:
    """A verified menu URL and the signal that produced it."""

    menu_url: str
    signal: str  # "well_known" (a known path) | "crawled" (sitemap or anchor)


def _is_html(result: FetchResult) -> bool:
    ctype = result.content_type.lower()
    return "html" in ctype or ctype == ""


def _resolve_host(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


def is_public_address(address: str) -> bool:
    """True for a globally routable unicast IP (not private/loopback/link-local/…)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class SiteFetcher:
    """Disk-cached, per-host rate-limited fetcher that honours robots.txt."""

    def __init__(  # noqa: PLR0913 - keyword-only injection points for tests
        self,
        *,
        cache_dir: Path,
        user_agent: str,
        min_interval_s: float = 1.0,
        timeout_s: float = 15.0,
        client: httpx.Client | None = None,
        resolve: Callable[[str], Iterable[str]] = _resolve_host,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SiteFetcher requires a non-empty User-Agent")
        self._cache_dir = cache_dir
        self._user_agent = user_agent
        self._min_interval_s = min_interval_s
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            follow_redirects=False,
        )
        self._resolve = resolve
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: dict[str, float] = {}
        self._crawl_delay: dict[str, float] = {}
        # origin -> rules; None means the site is skipped this run.
        self._robots: dict[str, Protego | None] = {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SiteFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- caching --------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> FetchResult | None | _Miss:
        """A fresh cached outcome, or a miss for absent, expired or corrupt entries."""
        path = self._cache_path(url)
        if not path.exists():
            return _MISS
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(payload["fetched_at"])
            if self._clock() - fetched_at > CACHE_TTL_S:
                return _MISS
            result = payload["result"]
            if result is None:
                return None
            return FetchResult(
                url=str(result["url"]),
                status=int(result["status"]),
                text=str(result["text"]),
                content_type=str(result["content_type"]),
            )
        except (ValueError, KeyError, TypeError):
            return _MISS

    def _write_cache(self, url: str, result: FetchResult | None) -> None:
        """Write via a temp file + ``Path.replace`` so a crash never leaves a torn entry."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        body = (
            None
            if result is None
            else {
                "url": result.url,
                "status": result.status,
                "text": result.text,
                "content_type": result.content_type,
            }
        )
        fd, tmp_name = tempfile.mkstemp(dir=self._cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"fetched_at": self._clock(), "result": body}, handle)
            Path(tmp_name).replace(self._cache_path(url))
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # -- fetching -------------------------------------------------------------

    def fetch(self, url: str) -> FetchResult | None:
        """GET a URL through the cache, honouring robots on every hop.

        ``None`` when robots disallows it, the site is skipped, a redirect
        leaves the site, or the request fails.
        """
        return self._get(url, obey_robots=True)

    def _get(self, url: str, *, obey_robots: bool) -> FetchResult | None:
        cached = self._read_cache(url)
        if not isinstance(cached, _Miss):
            return cached
        outcome = self._follow(url, obey_robots=obey_robots)
        if isinstance(outcome, _Blocked):
            return None  # robots decisions are cached via robots.txt itself
        self._write_cache(url, outcome)
        return outcome

    def _follow(self, url: str, *, obey_robots: bool) -> FetchResult | None | _Blocked:
        """Follow redirects by hand under the same-site, public-address policy."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                split = urlsplit(current)
            except ValueError:  # malformed URL or Location header
                return None
            if split.scheme not in {"http", "https"} or not same_site(current, url):
                return None
            if not self._is_public_host(split.hostname or ""):
                return None
            if obey_robots and not self.allowed(current):
                return _BLOCKED
            response = self._request(current)
            if not isinstance(response, _Redirect):
                return response
            try:
                current = urljoin(current, response.location)
            except ValueError:
                return None
        return None

    def _is_public_host(self, host: str) -> bool:
        if not host:
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return is_public_address(host)
        try:
            addresses = list(self._resolve(host))
        except OSError:
            return False
        return bool(addresses) and all(is_public_address(a) for a in addresses)

    def _throttle(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is None:
            return
        interval = max(self._min_interval_s, self._crawl_delay.get(host, 0.0))
        wait = interval - (self._monotonic() - last)
        if wait > 0:
            self._sleep(wait)

    def _request(self, url: str) -> FetchResult | _Redirect | None:
        """One throttled GET: a final response, a redirect to follow, or ``None``."""
        host = urlsplit(url).hostname or ""
        self._throttle(host)
        try:
            with self._client.stream("GET", url, follow_redirects=False) as response:
                location = response.headers.get("location")
                if response.status_code in _REDIRECT_STATUSES and location:
                    return _Redirect(location)
                body = _read_capped(response)
                if body is None:
                    return None
                return FetchResult(
                    url=url,
                    status=response.status_code,
                    text=_decode(body, response.encoding),
                    content_type=response.headers.get("content-type", ""),
                )
        except (httpx.HTTPError, httpx.InvalidURL):
            return None
        finally:
            self._last_request_at[host] = self._monotonic()

    # -- robots ---------------------------------------------------------------

    def allowed(self, url: str) -> bool:
        """Whether robots.txt permits our User-Agent to fetch ``url``."""
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin, split.hostname or "")
        rules = self._robots[origin]
        return rules is not None and rules.can_fetch(url, self._user_agent)

    def _load_robots(self, origin: str, host: str) -> Protego | None:
        """An origin's rules, or ``None`` to skip the site (owner decision D2.2).

        RFC 9309 §2.3.1: 4xx means "unavailable" (allow all); 5xx or an
        unreachable server means "assume complete disallow".
        """
        result = self._get(f"{origin}/robots.txt", obey_robots=False)
        if result is None:
            return None
        if 400 <= result.status < 500:  # noqa: PLR2004 - HTTP status classes
            return Protego.parse("")
        if not 200 <= result.status < 300:  # noqa: PLR2004 - HTTP status classes
            return None
        rules = Protego.parse(result.text)
        delay = rules.crawl_delay(self._user_agent)
        if delay is not None:
            if delay > MAX_CRAWL_DELAY_S:
                return None
            self._crawl_delay[host] = max(self._crawl_delay.get(host, 0.0), float(delay))
        return rules

    # -- discovery ------------------------------------------------------------

    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None:
        """Verify a menu URL for a resolved website, honouring robots + rate limit.

        Fetches the homepage and sitemap for candidate signals, then GETs each
        ranked candidate in order and returns the first that is robots-allowed
        and resolves to a 200 HTML page. Candidates are built from the
        homepage's final (post-redirect) URL.
        """
        homepage = self.fetch(website)
        base = website
        homepage_html = None
        if homepage is not None and homepage.status == 200 and _is_html(homepage):  # noqa: PLR2004
            base = homepage.url
            homepage_html = homepage.text

        sitemap = self.fetch(urljoin(base, "/sitemap.xml"))
        sitemap_xml = sitemap.text if sitemap and sitemap.status == 200 else None  # noqa: PLR2004

        candidates = ordered_menu_candidates(
            base, homepage_html=homepage_html, sitemap_xml=sitemap_xml
        )
        well_known = {url.rstrip("/") for url in path_candidates(base)}
        for candidate in candidates:
            result = self.fetch(candidate)
            if result is None or result.status != 200 or not _is_html(result):  # noqa: PLR2004
                continue
            signal = "well_known" if candidate.rstrip("/") in well_known else "crawled"
            return MenuUrlDiscovery(menu_url=result.url, signal=signal)
        return None


def _read_capped(response: httpx.Response) -> bytes | None:
    """The body, or ``None`` once it exceeds :data:`MAX_BODY_BYTES`."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _decode(body: bytes, encoding: str | None) -> str:
    try:
        return body.decode(encoding or "utf-8", errors="replace")
    except LookupError:  # unknown charset in the Content-Type header
        return body.decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class _Redirect:
    location: str


class _Blocked:
    """Sentinel: robots.txt disallowed a hop."""


class _Miss:
    """Sentinel distinguishing a cache miss from a cached negative result."""


_BLOCKED = _Blocked()
_MISS = _Miss()
