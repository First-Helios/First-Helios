"""Polite, disk-cached site fetcher + menu-URL discovery orchestration.

Mirrors :mod:`packages.helios_core.geo`: a real User-Agent, one request per
second per host, and every response (including failures) cached on disk so a
re-run never re-fetches. robots.txt is honoured before any candidate is
fetched. The httpx client is injectable, so tests replay from a mock transport
and CI makes no live network calls (ADR-0010 §3).

The pure candidate logic lives in :mod:`apps.discovery.menu_url`; this module
only fetches inputs, verifies which candidate actually resolves, and records
which signal produced it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from apps.discovery.menu_url import ordered_menu_candidates, path_candidates

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One cached HTTP response reduced to what discovery needs."""

    url: str
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


class SiteFetcher:
    """Disk-cached, per-host rate-limited fetcher that honours robots.txt."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        user_agent: str,
        min_interval_s: float = 1.0,
        timeout_s: float = 15.0,
        client: httpx.Client | None = None,
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
            follow_redirects=True,
        )
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}

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
        path = self._cache_path(url)
        if not path.exists():
            return _MISS
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = payload.get("result")
        if result is None:
            return None
        return FetchResult(
            url=str(result["url"]),
            status=int(result["status"]),
            text=str(result["text"]),
            content_type=str(result["content_type"]),
        )

    def _write_cache(self, url: str, result: FetchResult | None) -> None:
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
        self._cache_path(url).write_text(json.dumps({"result": body}), encoding="utf-8")

    # -- fetching -------------------------------------------------------------

    def _throttle(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is None:
            return
        wait = self._min_interval_s - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)

    def fetch(self, url: str) -> FetchResult | None:
        """GET a URL through the disk cache; ``None`` on a network/HTTP error."""
        cached = self._read_cache(url)
        if not isinstance(cached, _Miss):
            return cached
        host = urlsplit(url).hostname or ""
        self._throttle(host)
        try:
            response = self._client.get(url)
        except httpx.HTTPError:
            self._write_cache(url, None)
            return None
        finally:
            self._last_request_at[host] = time.monotonic()
        result = FetchResult(
            url=str(response.url),
            status=response.status_code,
            text=response.text,
            content_type=response.headers.get("content-type", ""),
        )
        self._write_cache(url, result)
        return result

    # -- robots ---------------------------------------------------------------

    def allowed(self, url: str) -> bool:
        """Whether robots.txt permits our User-Agent to fetch ``url``.

        A missing or unreadable robots.txt is treated as allow-all, per the
        robots convention. robots.txt itself is fetched through the cache (so
        tests can supply it) but is never gated on robots.
        """
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            robots = self.fetch(urljoin(origin, "/robots.txt"))
            if robots is not None and robots.status == 200:
                parser.parse(robots.text.splitlines())
            else:
                parser.parse([])  # allow-all
            self._robots[origin] = parser
        return parser.can_fetch(self._user_agent, url)

    def _fetch_if_allowed(self, url: str) -> FetchResult | None:
        return self.fetch(url) if self.allowed(url) else None

    # -- discovery ------------------------------------------------------------

    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None:
        """Verify a menu URL for a resolved website, honouring robots + rate limit.

        Fetches the homepage and sitemap for candidate signals, then GETs each
        ranked candidate in order and returns the first that is robots-allowed
        and resolves to a 200 HTML page.
        """
        homepage = self._fetch_if_allowed(website)
        homepage_html = (
            homepage.text if homepage and homepage.status == 200 and _is_html(homepage) else None
        )

        sitemap = self._fetch_if_allowed(urljoin(website, "/sitemap.xml"))
        sitemap_xml = sitemap.text if sitemap and sitemap.status == 200 else None

        candidates = ordered_menu_candidates(
            website, homepage_html=homepage_html, sitemap_xml=sitemap_xml
        )
        well_known = {url.rstrip("/") for url in path_candidates(website)}
        for candidate in candidates:
            if not self.allowed(candidate):
                continue
            result = self.fetch(candidate)
            if result is None or result.status != 200 or not _is_html(result):
                continue
            signal = "well_known" if candidate.rstrip("/") in well_known else "crawled"
            return MenuUrlDiscovery(menu_url=result.url, signal=signal)
        return None


class _Miss:
    """Sentinel distinguishing a cache miss from a cached negative result."""


_MISS = _Miss()
