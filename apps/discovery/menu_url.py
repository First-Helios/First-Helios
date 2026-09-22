"""Pure menu-URL candidate generation from a site's own signals.

No I/O: every function takes strings already fetched (homepage HTML, sitemap
XML, a base URL) and returns candidate menu URLs in priority order. The I/O
layer (:mod:`apps.discovery.web_client`) fetches those inputs, verifies which
candidate actually resolves, and honours robots.txt and rate limits. Keeping
this module pure and dependency-free (stdlib only) makes the lexicon and
ranking exhaustively unit-testable without a network (ADR-0010 §3).

Menu-URL grain is per-site (ADR-0010, owner decision 3): candidates are always
restricted to the same registrable site as the resolved website, so crawling a
chain's brand site yields that chain's menu and never wanders off-host.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

# Well-known menu paths, tried before any crawled signal and in this order.
MENU_PATHS: tuple[str, ...] = ("/menu", "/menus", "/food", "/our-menu")

# Anchor text / URL-path tokens that denote a menu link. Matched on word-ish
# boundaries via the normalized token set, so "menus" and "dinner menu" hit but
# "documentation" does not.
_MENU_TERMS: frozenset[str] = frozenset(
    {"menu", "menus", "food", "carte", "eats"},
)

# Phrases that look menu-ish but are navigation chrome, not a menu page.
_NEGATIVE_SUBSTRINGS: tuple[str, ...] = (
    "menu icon",
    "toggle menu",
    "open menu",
    "close menu",
    "main menu",
    "nav menu",
    "skip to",
)

# Bound the number of candidates the I/O layer will verify per site, so a page
# stuffed with menu-ish links cannot fan out into hundreds of fetches.
MAX_CANDIDATES = 8


def _host(url: str) -> str:
    """Return a comparable registrable host: lowercased, ``www.`` stripped."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    """True when two absolute URLs share a registrable host (``www.`` ignored)."""
    host_a, host_b = _host(a), _host(b)
    return bool(host_a) and host_a == host_b


def _tokens(value: str) -> set[str]:
    """Lowercase alphanumeric word tokens of a string (path separators split)."""
    out: list[str] = []
    current: list[str] = []
    for char in value.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return set(out)


def looks_like_menu(text: str, href: str) -> bool:
    """True when an anchor's text or URL path signals a menu, and is not chrome."""
    lowered = text.strip().lower()
    if any(bad in lowered for bad in _NEGATIVE_SUBSTRINGS):
        return False
    path_tokens = _tokens(urlsplit(href).path)
    return bool(_MENU_TERMS & (_tokens(text) | path_tokens))


class _AnchorCollector(HTMLParser):
    """Collect ``(href, text)`` for every ``<a>`` with an ``href``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._flush()
        href = next((value for name, value in attrs if name == "href"), None)
        self._href = href
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._flush()

    def _flush(self) -> None:
        if self._href is not None and self._href.strip():
            self.anchors.append((self._href.strip(), "".join(self._text).strip()))
        self._href = None
        self._text = []

    def close(self) -> None:
        super().close()
        self._flush()


def menu_links_from_html(html: str, base_url: str) -> list[str]:
    """Same-site absolute menu-candidate URLs from a page's anchors, in order."""
    parser = _AnchorCollector()
    parser.feed(html)
    parser.close()
    out: list[str] = []
    for href, text in parser.anchors:
        if not looks_like_menu(text, href):
            continue
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).scheme in {"http", "https"} and same_site(absolute, base_url):
            out.append(absolute)
    return out


def menu_links_from_sitemap(sitemap_xml: str, base_url: str) -> list[str]:
    """Same-site ``<loc>`` URLs whose path signals a menu, in document order.

    Namespace-agnostic (matches any ``loc`` local-name) so a plain sitemap and
    a namespaced one both work; malformed XML yields no candidates. A sitemap
    that declares a DTD or entities is rejected outright: it is untrusted
    third-party input and stdlib XML parsing is vulnerable to entity-expansion
    (billion-laughs) attacks, which those declarations are the vector for.
    """
    lowered = sitemap_xml.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return []
    try:
        root = ET.fromstring(sitemap_xml)  # noqa: S314 - DTD/entities rejected above
    except ET.ParseError:
        return []
    out: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag != "loc" or not element.text:
            continue
        loc = element.text.strip()
        if not loc or not same_site(loc, base_url):
            continue
        if _MENU_TERMS & _tokens(urlsplit(loc).path):
            out.append(loc)
    return out


def path_candidates(base_url: str) -> list[str]:
    """The well-known menu paths joined onto a site's root."""
    return [urljoin(base_url, path) for path in MENU_PATHS]


def _dedupe_key(url: str) -> str:
    """Collapse trailing-slash and fragment differences for dedupe only."""
    split = urlsplit(url)
    path = split.path.rstrip("/") or "/"
    return f"{split.scheme}://{_host(url)}{path}?{split.query}"


def ordered_menu_candidates(
    base_url: str,
    *,
    homepage_html: str | None = None,
    sitemap_xml: str | None = None,
) -> list[str]:
    """Menu-URL candidates in verification priority, deduped and capped.

    Priority: well-known paths, then sitemap matches, then homepage anchors.
    Well-known paths rank first because they are the strongest convention;
    sitemap entries are author-declared; anchors are the noisiest signal.
    """
    ordered = list(path_candidates(base_url))
    if sitemap_xml:
        ordered += menu_links_from_sitemap(sitemap_xml, base_url)
    if homepage_html:
        ordered += menu_links_from_html(homepage_html, base_url)

    seen: set[str] = set()
    unique: list[str] = []
    for url in ordered:
        key = _dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(url)
    return unique[:MAX_CANDIDATES]
