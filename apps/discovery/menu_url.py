"""Pure menu-URL candidate generation from a site's own signals.

No I/O: every function takes strings already fetched (homepage HTML, sitemap
XML, a base URL) and returns candidate menu URLs in priority order. The I/O
layer (:mod:`apps.discovery.web_client`) fetches those inputs, verifies which
candidate actually resolves, and honours robots.txt and rate limits. Keeping
this module pure and dependency-free (stdlib only) makes the lexicon and
ranking exhaustively unit-testable without a network (ADR-0010 §3).

Menu-URL grain is per-site (ADR-0010, owner decision 3; records are per venue,
Amendment 2): own-site candidates are restricted to the resolved website's host,
so crawling a chain's brand site yields that chain's menu and never wanders
off-host. "Same site" compares hosts lowercased with a leading ``www.`` removed;
it is not a registrable-domain (public-suffix) check, so ``order.example.com``
counts as a different site from ``example.com``. Ordering-platform venue pages
are the one deliberate exception (:func:`platform_links_from_html`).

Verification (ADR-0010 Amendment 3 / owner decisions D3.4-D3.5, review session
S4): a candidate is not "any 200 HTML page". A real menu page must (a) not be
the homepage itself under another name (``#``, a bare anchor, a redirect back
to `/`), (b) carry a menu word in its URL path, ``<title>``, or first heading
(subject to a blocklist that vetoes lookalikes like "menu-of-services"), and
(c) have body content that actually differs from the homepage's — all cheap,
deterministic, dependency-free checks; a content classifier is deferred to
Phase 5 (the page classifier in ADR-0013, Proposed; see the checklist's D3.4
note). Shared platform hosts (Toast, Square, Facebook, …) are handled
separately (D3.5): never probed at their own root paths, used as the menu URL
directly when the venue's website already is one, and otherwise taken from the
homepage's links beside the own-site menu. Either way the fetched platform page
must pass the same page check as an own-site candidate (ADR-0015 item 4).
"""

from __future__ import annotations

import re
from html import unescape
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

# Whole-token lookalikes that veto an otherwise-matching page or link (R34):
# "/menu-of-services" and "/wp-admin/nav-menus.php" both contain a menu term
# but are a services page and a CMS admin screen, not a menu.
_BLOCKLIST_TERMS: frozenset[str] = frozenset(
    {
        "admin",
        "wp",
        "services",
        "service",
        "safety",
        "careers",
        "career",
        "policy",
        "policies",
        "donation",
        "donations",
        "bank",
    },
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

# Bound sitemap-index expansion and multi-sitemap fan-out (R75): never follow
# more than this many child/declared sitemap documents for one site.
MAX_SITEMAP_CHILDREN = 5

# Bound the ordering platforms whose homepage links are tried per site (D3.5b).
MAX_PLATFORM_CANDIDATES = 3

# Bound the pages fetched for one platform when a (chain) homepage links several
# venue pages on it; they are tried best address match first (ADR-0015 item 5).
MAX_CHAIN_CANDIDATES = 3

_TOKEN_SPLIT = re.compile(r"[^0-9a-z]+")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]*>")

# Shared food-ordering / social platforms whose own pages are accepted as a
# venue's menu source (owner decision D3.5): a website hosted here is never
# probed at its own well-known root paths (R33); the venue's page on it (a
# non-root path) is itself the menu URL.
ORDERING_PLATFORM_HOSTS: frozenset[str] = frozenset(
    {
        "toasttab.com",
        "toast.app",
        "squareup.com",
        "square.site",
        "clover.com",
        "cloveronline.com",
        "doordash.com",
        "ubereats.com",
        "grubhub.com",
    },
)
# A platform serving venue pages under a second domain: both share one record
# key (owner decisions S6f: Toast links can redirect to ``toast.app``, Clover
# links to ``<venue>.cloveronline.com``).
PLATFORM_HOST_ALIASES: dict[str, str] = {
    "toast.app": "toasttab.com",
    "cloveronline.com": "clover.com",
}
SOCIAL_PLATFORM_HOSTS: frozenset[str] = frozenset(
    {"facebook.com", "instagram.com", "linktr.ee"},
)
PLATFORM_HOSTS: frozenset[str] = ORDERING_PLATFORM_HOSTS | SOCIAL_PLATFORM_HOSTS

_HEADING_TAGS: frozenset[str] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def _host(url: str) -> str:
    """Return a comparable host: lowercased, a leading ``www.`` stripped."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    """True when two absolute URLs share a host (a leading ``www.`` ignored)."""
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


def _dedupe_key(url: str) -> str:
    """Collapse trailing-slash and fragment differences for comparison only."""
    split = urlsplit(url)
    path = split.path.rstrip("/") or "/"
    return f"{split.scheme}://{_host(url)}{path}?{split.query}"


def same_resource(a: str, b: str) -> bool:
    """True when two URLs point at the same page, ignoring trailing slash and fragment.

    Used to reject a "menu" link that is really the homepage under another
    name: a bare ``#``, a same-page anchor (``/#menu``), or a link that is
    textually identical to the homepage once the fragment is dropped (R08).
    """
    return _dedupe_key(a) == _dedupe_key(b)


def looks_like_menu(text: str, href: str) -> bool:
    """True when an anchor's text or URL path signals a menu, and is not chrome.

    Whole-token match against the menu lexicon; a blocklisted token (R34, e.g.
    "services", "safety", "policy") vetoes the match even when a menu term is
    also present, so "menu-of-services" and "Food Bank Donations" are rejected.
    """
    lowered = text.strip().lower()
    if any(bad in lowered for bad in _NEGATIVE_SUBSTRINGS):
        return False
    tokens = _tokens(text) | _tokens(urlsplit(href).path)
    if tokens & _BLOCKLIST_TERMS:
        return False
    return bool(_MENU_TERMS & tokens)


def _on_hosts(url: str, domains: frozenset[str]) -> bool:
    host = _host(url)
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def ordering_platform_host(url: str) -> str | None:
    """Stable platform record suffix, shared by www/order/venue subdomains and aliases."""
    host = _host(url)
    domain = next(
        (
            domain
            for domain in sorted(ORDERING_PLATFORM_HOSTS, key=len, reverse=True)
            if host == domain or host.endswith("." + domain)
        ),
        None,
    )
    return PLATFORM_HOST_ALIASES.get(domain, domain) if domain else None


def platform_signal(url: str) -> bool:
    """True when a URL's host is on, or a subdomain of, a known platform (D3.5)."""
    return _on_hosts(url, PLATFORM_HOSTS)


def is_platform_venue_page(url: str, *, ordering_only: bool = False) -> bool:
    """True for a venue's own page on a platform: a platform host and a non-root path.

    A platform's root (``https://www.facebook.com/``) belongs to the platform,
    not any venue (R33). ``ordering_only`` restricts to ordering platforms: a
    homepage's social-icon links (Facebook, Instagram) are on nearly every
    restaurant site and are not a menu, so they never serve as a fallback.
    """
    domains = ORDERING_PLATFORM_HOSTS if ordering_only else PLATFORM_HOSTS
    return _on_hosts(url, domains) and urlsplit(url).path.strip("/") != ""


class _AnchorCollector(HTMLParser):
    """Collect ``(href, text)`` for every ``<a>`` with an ``href``, plus ``<base href>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self.base_href: str | None = None
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "base" and self.base_href is None:
            # Only the first <base href> counts (HTML spec).
            self.base_href = next((value for name, value in attrs if name == "href"), None)
            return
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


def _resolve_link_base(base_url: str, parser: _AnchorCollector) -> str:
    if parser.base_href and parser.base_href.strip():
        declared = urljoin(base_url, parser.base_href.strip())
        if urlsplit(declared).scheme in {"http", "https"}:
            return declared
    return base_url


def menu_links_from_html(html: str, base_url: str) -> list[str]:
    """Same-site absolute menu-candidate URLs from a page's anchors, in order.

    ``base_url`` is the page's own (post-redirect) URL: also the page whose
    identity a candidate must *not* collapse to (R08) — a bare ``#``, a
    same-page anchor, or a link that resolves back to the homepage is dropped,
    not just off-site or chrome-labelled links. Relative links resolve against
    the page's ``<base href>`` when it has an http(s) one, but must still land
    on the page's site.
    """
    parser = _AnchorCollector()
    parser.feed(html)
    parser.close()
    link_base = _resolve_link_base(base_url, parser)
    out: list[str] = []
    for href, text in parser.anchors:
        if not href or href.startswith("#"):
            continue
        if not looks_like_menu(text, href):
            continue
        absolute = urljoin(link_base, href)
        if urlsplit(absolute).scheme not in {"http", "https"}:
            continue
        if not same_site(absolute, base_url) or same_resource(absolute, base_url):
            continue
        out.append(absolute)
    return out


def menu_pdf_links(html: str, base_url: str) -> list[str]:
    """Absolute URLs of the page's menu-named PDF links, in order (ADR-0013 Amendment 3).

    A link counts when its path ends in ``.pdf`` and its text or path carries a
    menu word (:func:`looks_like_menu`, blocklist included). Any host counts:
    menu PDFs are often on a site builder's file CDN. Only counted, never fetched.
    """
    parser = _AnchorCollector()
    parser.feed(html)
    parser.close()
    link_base = _resolve_link_base(base_url, parser)
    out: list[str] = []
    for href, text in parser.anchors:
        absolute = urljoin(link_base, href)
        split = urlsplit(absolute)
        if split.scheme not in {"http", "https"} or not split.path.lower().endswith(".pdf"):
            continue
        if looks_like_menu(text, absolute) and absolute not in out:
            out.append(absolute)
    return out


def platform_links_by_host(html: str, base_url: str) -> dict[str, list[str]]:
    """Homepage-anchor URLs to venue pages on each ordering platform, in order.

    Unlike :func:`menu_links_from_html` these deliberately leave the page's own
    site (that is the point): a homepage link to ``toasttab.com/<venue>`` or a
    DoorDash store page is a candidate (owner decision D3.5b), still subject to
    the fetched page's content check. Social links and platform roots (a
    "Powered by Toast" footer) are skipped. Keys are platform record suffixes
    (:func:`ordering_platform_host`), so ``order.toasttab.com`` and
    ``www.toasttab.com`` links share one key; each key lists its distinct pages,
    so a chain homepage linking one page per location shows up as several.
    """
    parser = _AnchorCollector()
    parser.feed(html)
    parser.close()
    link_base = _resolve_link_base(base_url, parser)
    out: dict[str, list[str]] = {}
    for href, _text in parser.anchors:
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(link_base, href)
        if urlsplit(absolute).scheme not in {"http", "https"}:
            continue
        key = ordering_platform_host(absolute)
        if key is None or not is_platform_venue_page(absolute, ordering_only=True):
            continue
        links = out.setdefault(key, [])
        if not any(same_resource(absolute, seen) for seen in links):
            links.append(absolute)
    return out


def platform_links_from_html(html: str, base_url: str) -> list[str]:
    """The first venue-page link to each ordering platform, in homepage order.

    A venue has one menu record per platform host (ADR-0011 §7).
    """
    return [links[0] for links in platform_links_by_host(html, base_url).values()]


_DIRECTIONS = frozenset(
    {"n", "s", "e", "w", "ne", "nw", "se", "sw", "north", "south", "east", "west"}
)


def _address_parts(address: str | None) -> tuple[str, str] | None:
    """(house number, street name token) of a street line, e.g. ``("1501", "6th")``."""
    if not address:
        return None
    words = _ordered_tokens(address.split(",")[0])
    if len(words) < 2 or not words[0][0].isdigit():  # noqa: PLR2004
        return None
    name = next((word for word in words[1:] if word not in _DIRECTIONS), None)
    return (words[0], name) if name else None


def _ordered_tokens(value: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(value.lower()) if token]


def _page_text(html: str) -> str:
    return unescape(_TAG.sub(" ", _SCRIPT_STYLE.sub(" ", html)))


def address_on_page(html: str, address: str | None) -> bool:
    """True when a page shows the venue's house number followed by its street name.

    The chain-homepage guard (ADR-0015 item 5) uses it to tell one location's
    platform page from its siblings' without a manual entry.
    """
    parts = _address_parts(address)
    if parts is None:
        return False
    house, name = parts
    words = _ordered_tokens(_page_text(html))
    for index, word in enumerate(words):
        if word == house:
            # Only a direction ("E", "East") may sit between the number and the name.
            following = (token for token in words[index + 1 :] if token not in _DIRECTIONS)
            if next(following, None) == name:
                return True
    return False


def rank_by_address(urls: list[str], address: str | None) -> list[str]:
    """Order candidate URLs by how many of the address's parts their path names."""
    parts = set(_address_parts(address) or ())
    return sorted(urls, key=lambda url: -len(parts & _tokens(urlsplit(url).path)))


class _PageSignalParser(HTMLParser):
    """Collect a page's ``<title>`` text and its first heading's text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.first_heading: str | None = None
        self._target: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "title" and self.title is None:
            self._target = "title"
            self._buf = []
        elif tag in _HEADING_TAGS and self.first_heading is None:
            self._target = "heading"
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._target is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._target == "title":
            self.title = "".join(self._buf).strip()
            self._target = None
        elif tag in _HEADING_TAGS and self._target == "heading":
            self.first_heading = "".join(self._buf).strip()
            self._target = None


def page_menu_signal(html: str, url: str, *, trust_path: bool = True) -> bool:
    """True when a *fetched* page's own content signals a real menu page.

    Checks the URL path, ``<title>``, and first heading for a whole-token menu
    match, vetoed by the same blocklist as :func:`looks_like_menu` (R34,
    D3.4). This checks the page the crawler actually landed on, never the
    anchor text that pointed at it, so a mislabeled link (`<a href="/order">
    Order Menu</a>` landing on a page titled "Order Online") is rejected.

    ``trust_path=False`` drops the URL-path signal: a well-known path like
    ``/menu`` always contains a menu word by construction, so on a site
    already shown to answer 200 for *any* path (catch-all / soft-404, R08)
    that signal carries no information and only the title/heading count.
    """
    parser = _PageSignalParser()
    parser.feed(html)
    parser.close()
    tokens = _tokens(parser.title or "") | _tokens(parser.first_heading or "")
    if trust_path:
        tokens |= _tokens(urlsplit(url).path)
    if tokens & _BLOCKLIST_TERMS:
        return False
    return bool(tokens & _MENU_TERMS)


def _parse_sitemap(sitemap_xml: str) -> tuple[str, list[str]] | None:
    """``(root tag local-name, [<loc> texts in document order])``.

    ``None`` for malformed XML or a document that declares a DTD/entities: a
    sitemap is untrusted third-party input, and stdlib XML parsing is
    vulnerable to entity-expansion (billion-laughs) attacks, which those
    declarations are the vector for.
    """
    lowered = sitemap_xml.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return None
    try:
        root = ET.fromstring(sitemap_xml)  # noqa: S314 - DTD/entities rejected above
    except ET.ParseError:
        return None
    kind = root.tag.rsplit("}", 1)[-1].lower()
    locs = [
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "loc" and (element.text or "").strip()
    ]
    return (kind, locs)


def menu_links_from_sitemap(sitemap_xml: str, base_url: str) -> list[str]:
    """Same-site ``<loc>`` URLs from a *urlset* sitemap whose path signals a menu.

    Namespace-agnostic (matches any ``loc`` local-name) so a plain sitemap and
    a namespaced one both work. A **sitemap index**'s ``<loc>`` entries name
    child sitemap *documents*, not pages — those are never candidates here
    (R75); see :func:`sitemap_index_children` for expanding them. A link that
    resolves to the homepage itself is dropped, same as an anchor (R08), and a
    blocklisted path is rejected even when a menu term also matches (R34).
    """
    parsed = _parse_sitemap(sitemap_xml)
    if parsed is None:
        return []
    kind, locs = parsed
    if kind == "sitemapindex":
        return []
    out: list[str] = []
    for loc in locs:
        if not same_site(loc, base_url) or same_resource(loc, base_url):
            continue
        path_tokens = _tokens(urlsplit(loc).path)
        if path_tokens & _BLOCKLIST_TERMS:
            continue
        if _MENU_TERMS & path_tokens:
            out.append(loc)
    return out


def sitemap_index_children(sitemap_xml: str, base_url: str) -> list[str]:
    """Same-site child-sitemap URLs from a sitemap *index* document, capped (R75)."""
    parsed = _parse_sitemap(sitemap_xml)
    if parsed is None:
        return []
    kind, locs = parsed
    if kind != "sitemapindex":
        return []
    out: list[str] = []
    for loc in locs:
        if same_site(loc, base_url):
            out.append(loc)
        if len(out) >= MAX_SITEMAP_CHILDREN:
            break
    return out


def path_candidates(base_url: str) -> list[str]:
    """The well-known menu paths joined onto a site's root."""
    return [urljoin(base_url, path) for path in MENU_PATHS]


def ordered_menu_candidates(
    base_url: str,
    *,
    homepage_html: str | None = None,
    sitemap_xml: str | None = None,
    extra_sitemap_matches: tuple[str, ...] = (),
) -> list[str]:
    """Menu-URL candidates in verification priority, deduped and capped.

    Priority: well-known paths, then sitemap matches, then homepage anchors.
    Well-known paths rank first because they are the strongest convention;
    sitemap entries are author-declared; anchors are the noisiest signal.

    ``sitemap_xml`` is one already-fetched sitemap document; the I/O layer
    passes any *additional* same-site menu matches it collected from a
    sitemap index's children or robots.txt's declared ``Sitemap:`` documents
    (R75) via ``extra_sitemap_matches`` — already extracted through
    :func:`menu_links_from_sitemap`, so this function only merges and ranks.

    Sitemap and anchor matches are interleaved rather than concatenated: a
    site with many sitemap matches (e.g. a blog's tagged posts) would
    otherwise fill every slot under :data:`MAX_CANDIDATES` before a homepage
    anchor is ever tried (R34).
    """
    ordered: list[str] = []
    seen: set[str] = set()
    home_key = _dedupe_key(base_url)

    def add(url: str) -> None:
        key = _dedupe_key(url)
        if key in seen or key == home_key:
            return
        seen.add(key)
        ordered.append(url)

    for path in path_candidates(base_url):
        add(path)

    sitemap_matches: list[str] = (
        menu_links_from_sitemap(sitemap_xml, base_url) if sitemap_xml else []
    )
    sitemap_matches.extend(extra_sitemap_matches)
    anchor_matches = menu_links_from_html(homepage_html, base_url) if homepage_html else []

    site_i, anchor_i = 0, 0
    while (site_i < len(sitemap_matches) or anchor_i < len(anchor_matches)) and len(
        ordered
    ) < MAX_CANDIDATES:
        if site_i < len(sitemap_matches):
            add(sitemap_matches[site_i])
            site_i += 1
            if len(ordered) >= MAX_CANDIDATES:
                break
        if anchor_i < len(anchor_matches):
            add(anchor_matches[anchor_i])
            anchor_i += 1

    return ordered[:MAX_CANDIDATES]
