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

Menu-page verification (ADR-0010 Amendment 3, review session S4): a candidate
is accepted only once it is fetched and checked, never on "200 HTML" alone.
:func:`SiteFetcher.discover_menu_url` rejects a candidate that redirects back
to the homepage, probes one random path per site to detect a catch-all/
soft-404 host (which makes a well-known path's URL-path signal worthless), and
requires the fetched page's own title/heading/path to carry a menu word
(:func:`apps.discovery.menu_url.page_menu_signal`) with body content that
actually differs from the homepage's. A website on a known platform host
(Toast, Square, Facebook, …) is never probed at its own well-known paths — the
page itself is the candidate (signal ``"platform"``); an own-site venue with
no verified menu falls back to a homepage link into one of those platforms.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import ipaddress
import json
import os
import socket
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx
from protego import Protego

from apps.discovery.menu_url import (
    MAX_PLATFORM_CANDIDATES,
    MAX_SITEMAP_CHILDREN,
    is_platform_venue_page,
    menu_links_from_sitemap,
    ordered_menu_candidates,
    page_menu_signal,
    path_candidates,
    platform_links_from_html,
    platform_signal,
    same_resource,
    same_site,
    sitemap_index_children,
)

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
    # "well_known" (a known path) | "crawled" (sitemap or anchor) | "platform"
    # (the venue's own site is a shared platform host, or a homepage link
    # into one, D3.5)
    signal: str


def _is_html(result: FetchResult) -> bool:
    ctype = result.content_type.lower()
    return "html" in ctype or ctype == ""


def _resolve_host(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


def _random_token() -> str:
    return uuid.uuid4().hex


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
        random_token: Callable[[], str] = _random_token,
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
        self._random_token = random_token
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
                is_gz_url = url.lower().split("?", 1)[0].endswith(".gz")
                if is_gz_url and body.startswith(_GZIP_MAGIC):
                    # R75: a gzipped sitemap. Decompress with its own cap so a
                    # small compressed payload can't expand into a memory bomb.
                    # Served with Content-Encoding: gzip, httpx has already
                    # decoded it (no magic bytes), so it passes through as-is.
                    body = _gunzip_capped(body, MAX_BODY_BYTES)
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

        A website already on a shared platform host (Toast, Square, Facebook,
        …) is never probed at its own well-known paths (R33): the page itself
        is the candidate, verified only by fetching it (owner decision D3.5a).

        Otherwise: fetch the homepage and sitemap(s) for candidate signals,
        probe one random path to detect a catch-all/soft-404 host (R08), then
        GET each ranked candidate in order and accept the first that is
        robots-allowed, resolves to a 200 HTML page distinct from the
        homepage, and whose own content carries a menu word
        (:func:`apps.discovery.menu_url.page_menu_signal`). If nothing
        verifies, fall back to a homepage link into a known platform host
        (D3.5b). Candidates are built from the homepage's final
        (post-redirect) URL.
        """
        if platform_signal(website):
            if not is_platform_venue_page(website):
                return None  # a platform's root belongs to the platform (R33)
            result = self.fetch(website)
            if result is not None and result.status == 200 and _is_html(result):  # noqa: PLR2004
                return MenuUrlDiscovery(menu_url=result.url, signal="platform")
            return None

        homepage = self.fetch(website)
        base = website
        homepage_html: str | None = None
        homepage_hash: str | None = None
        if homepage is not None and homepage.status == 200 and _is_html(homepage):  # noqa: PLR2004
            base = homepage.url
            homepage_html = homepage.text
            homepage_hash = _body_hash(homepage.text)

        sitemap_matches = self._sitemap_menu_matches(base)
        candidates = ordered_menu_candidates(
            base, homepage_html=homepage_html, extra_sitemap_matches=tuple(sitemap_matches)
        )
        well_known = {url.rstrip("/") for url in path_candidates(base)}
        is_catch_all: bool | None = None  # probed lazily: only a 200 well-known path needs it

        for candidate in candidates:
            result = self.fetch(candidate)
            if result is None or result.status != 200 or not _is_html(result):  # noqa: PLR2004
                continue
            if same_resource(result.url, base):
                continue  # the candidate just redirected back to the homepage (R08)
            is_well_known = candidate.rstrip("/") in well_known
            if is_well_known and is_catch_all is None:
                is_catch_all = self._is_catch_all_site(base)
            trust_path = not (is_well_known and bool(is_catch_all))
            if not page_menu_signal(result.text, result.url, trust_path=trust_path):
                continue
            if homepage_hash is not None and _body_hash(result.text) == homepage_hash:
                continue  # identical body to the homepage: a catch-all/soft-404 answer
            return MenuUrlDiscovery(
                menu_url=result.url, signal="well_known" if is_well_known else "crawled"
            )

        if homepage_html is not None:
            for platform_url in platform_links_from_html(homepage_html, base)[
                :MAX_PLATFORM_CANDIDATES
            ]:
                result = self.fetch(platform_url)
                if result is not None and result.status == 200 and _is_html(result):  # noqa: PLR2004
                    return MenuUrlDiscovery(menu_url=result.url, signal="platform")
        return None

    def _is_catch_all_site(self, base_url: str) -> bool:
        """True when a random, almost-certainly-nonexistent path 200s as HTML.

        Such a site answers 200 for any path (an SPA fallback or a soft-404
        page), so a well-known candidate's URL-path signal is worthless there
        (R08): ``/menu`` trivially contains "menu" by construction regardless
        of whether the site has one.
        """
        probe = urljoin(base_url, f"/helios-probe-{self._random_token()}")
        result = self.fetch(probe)
        return result is not None and result.status == 200 and _is_html(result)  # noqa: PLR2004

    def _sitemap_menu_matches(self, base_url: str) -> list[str]:
        """Same-site menu-matching URLs from every sitemap document for a site (R75).

        Sitemap sources are the site's robots.txt ``Sitemap:`` lines when it
        declares any, else the ``/sitemap.xml`` convention. A sitemap index's
        children are expanded (never treated as page candidates themselves),
        each fetch (top-level or child) counting against
        :data:`MAX_SITEMAP_CHILDREN` so a hostile or huge sitemap can't fan
        out unboundedly.
        """
        matches: list[str] = []
        fetched = 0
        for sitemap_url in self._sitemap_sources(base_url):
            if fetched >= MAX_SITEMAP_CHILDREN:
                break
            result = self.fetch(sitemap_url)
            fetched += 1
            if result is None or result.status != 200:  # noqa: PLR2004
                continue
            matches.extend(menu_links_from_sitemap(result.text, base_url))
            for child in sitemap_index_children(result.text, base_url):
                if fetched >= MAX_SITEMAP_CHILDREN:
                    break
                child_result = self.fetch(child)
                fetched += 1
                if child_result is None or child_result.status != 200:  # noqa: PLR2004
                    continue
                matches.extend(menu_links_from_sitemap(child_result.text, base_url))
        return matches

    def _sitemap_sources(self, base_url: str) -> list[str]:
        """Same-site sitemap document URLs: robots ``Sitemap:`` lines, else the default."""
        split = urlsplit(base_url)
        origin = f"{split.scheme}://{split.netloc}"
        rules = self._robots.get(origin)
        if rules is not None:
            declared = [url for url in rules.sitemaps if same_site(url, base_url)]
            if declared:
                return declared[:MAX_SITEMAP_CHILDREN]
        return [urljoin(base_url, "/sitemap.xml")]


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


_GZIP_MAGIC = b"\x1f\x8b"


def _gunzip_capped(data: bytes, cap: int) -> bytes | None:
    """Decompress gzip ``data``, or ``None`` past ``cap`` decompressed bytes.

    Reads in chunks and stops as soon as the cap is crossed, rather than
    decompressing everything first, so a small, hostile ``.xml.gz`` cannot
    expand into a memory bomb (R75).
    """
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = gz.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except OSError:  # not actually gzip, or a truncated/corrupt stream
        return None


def _body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Redirect:
    location: str


class _Blocked:
    """Sentinel: robots.txt disallowed a hop."""


class _Miss:
    """Sentinel distinguishing a cache miss from a cached negative result."""


_BLOCKED = _Blocked()
_MISS = _Miss()
