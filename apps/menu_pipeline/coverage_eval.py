"""Collection-coverage harness: which of a site's menu pages and states the pipeline collects.

Session P8-21, measurement only: no pipeline change. Coverage is scored apart from
extraction (recall, wrong associations, false rejects, invented items are the extraction
harness's, ``packages.helios_parsing.evaluation``), so a page that is never collected is
counted here and not mistaken for an extraction miss.

A **site fixture** (``var/menu-eval/coverage/{real,synthetic}/<site>.json``) is one whole
website, reviewed by hand:

- ``menu_pages``: every page a person would read as the venue's menu, each with its
  ``states`` — ``static`` (in the page's HTML), ``tab:<name>`` / ``accordion`` (a panel in
  the page), ``script`` (loaded by JavaScript only), ``pdf``, ``image`` or
  ``platform:<host>`` — and a few ``sample_items`` printed in that state;
- ``other_location_pages``: menu pages of another location of a chain or group (collecting
  one is a wrong association);
- ``kinds``: what the site exercises (``separate_pages``, ``tabs``, ``accordion``,
  ``table``, ``shared_section_price``, ``options``, ``pdf``, ``multi_location``,
  ``platform``, ``script``, ``no_menu``);
- ``origin`` (``real`` / ``synthetic``) and ``split`` (``dev`` / ``held``): real sites are
  split by template group, so no template is on both sides; synthetic sites are reported
  apart.

What the pipeline collected for a site is a list of :class:`Captured` pages (discovery's
verified pages after the several-pages cap and duplicate rule, ADR-0022, and their HTML).
:func:`coverage_site` counts, :func:`coverage_metrics` turns summed counts into rates.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from apps.discovery.menu_url import same_resource
from apps.discovery.url_pipeline import MAX_MENU_PAGES, _duplicate_page, _page_blocks
from apps.discovery.web_client import CaptureFailure, MenuPdfLinked, MenuUrlDiscovery
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import norm_tokens

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from apps.discovery.web_client import SiteFetcher

STATE_KINDS = ("static", "tab", "accordion", "script", "pdf", "image", "platform")
STATE_SAMPLE_SHARE = 0.5  # a state is covered when this share of its sample items is collected


@dataclass(frozen=True, slots=True)
class ExpectedState:
    state: str  # "static" | "tab:<name>" | "accordion" | "script" | "pdf" | "image" | "platform:<host>"
    sample_items: tuple[str, ...]

    @property
    def kind(self) -> str:
        return self.state.split(":", 1)[0]


@dataclass(frozen=True, slots=True)
class ExpectedPage:
    url: str
    name: str
    states: tuple[ExpectedState, ...]
    location: str | None = None


@dataclass(frozen=True, slots=True)
class SiteFixture:
    site: str
    origin: str  # "real" | "synthetic"
    split: str  # "dev" | "held"
    website: str
    menu_pages: tuple[ExpectedPage, ...]
    other_location_pages: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    template: str = ""
    address: str | None = None


@dataclass(frozen=True, slots=True)
class Captured:
    """One page the pipeline collected for a site: its final URL and HTML."""

    url: str
    html: str
    rendered: bool = False


def site_fixture(obj: Mapping[str, Any]) -> SiteFixture:
    """A fixture from its JSON object."""
    return SiteFixture(
        site=str(obj["site"]),
        origin=str(obj["origin"]),
        split=str(obj.get("split") or "dev"),
        website=str(obj["website"]),
        menu_pages=tuple(
            ExpectedPage(
                url=str(p["url"]),
                name=str(p.get("name") or ""),
                location=p.get("location"),
                states=tuple(
                    ExpectedState(str(s["state"]), tuple(map(str, s.get("sample_items") or ())))
                    for s in p.get("states") or ()
                ),
            )
            for p in obj.get("menu_pages") or ()
        ),
        other_location_pages=tuple(map(str, obj.get("other_location_pages") or ())),
        kinds=tuple(map(str, obj.get("kinds") or ())),
        template=str(obj.get("template") or ""),
        address=obj.get("address"),
    )


def load_fixtures(folder: Path) -> list[SiteFixture]:
    """Every ``*.json`` fixture under ``folder``, in name order."""
    return [site_fixture(json.loads(p.read_text())) for p in sorted(folder.rglob("*.json"))]


def page_key(url: str) -> str:
    """A URL as a page identity: no scheme, no ``www.``, no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def _texts(html: str) -> list[set[str]]:
    return [set(norm_tokens(b.text)) for b in segment(html)]


def _printed(item: str, texts: Sequence[set[str]]) -> bool:
    want = set(norm_tokens(item))
    return bool(want) and any(want <= t for t in texts)


def coverage_site(
    fixture: SiteFixture, captured: Sequence[Captured], cost: Mapping[str, int] | None = None
) -> Counter[str]:
    """One site's coverage counts (sum sites, then :func:`coverage_metrics`).

    A page is *found* when a captured page has its identity (:func:`page_key`). A state
    is *covered* when at least :data:`STATE_SAMPLE_SHARE` of its sample items are printed in
    the captured page's blocks (a ``pdf``, ``image`` or ``platform`` state only through a
    captured page of its own). ``cost`` is added as ``cost:<name>``."""
    c: Counter[str] = Counter(sites=1)
    got = {page_key(p.url): p for p in captured}
    expected = {page_key(p.url) for p in fixture.menu_pages}
    other = {page_key(u) for u in fixture.other_location_pages}
    c["captured"] = len(got)
    c["captured_expected"] = len(set(got) & expected)
    c["captured_other_location"] = len(set(got) & other)
    c["captured_unexpected"] = len(set(got) - expected - other)
    if not fixture.menu_pages:
        c["sites_no_menu"] = 1
        c["sites_no_menu_clean"] = int(not got)
    else:
        c["sites_with_menu"] = 1
    found = 0
    for page in fixture.menu_pages:
        c["pages_expected"] += 1
        hit = got.get(page_key(page.url))
        found += hit is not None
        texts = _texts(hit.html) if hit is not None else []
        for state in page.states:
            c["states_expected"] += 1
            c[f"states_expected:{state.kind}"] += 1
            if hit is None or not state.sample_items:
                continue
            n = sum(_printed(item, texts) for item in state.sample_items)
            if n >= max(1, STATE_SAMPLE_SHARE * len(state.sample_items)):
                c["states_covered"] += 1
                c[f"states_covered:{state.kind}"] += 1
    c["pages_found"] = found
    if fixture.menu_pages:
        c["sites_any_page"] = int(found > 0)
        c["sites_all_pages"] = int(found == len(fixture.menu_pages))
    for kind in fixture.kinds:
        c[f"kind_sites:{kind}"] += 1
        c[f"kind_pages_expected:{kind}"] += len(fixture.menu_pages)
        c[f"kind_pages_found:{kind}"] += found
    for name, n in (cost or {}).items():
        c[f"cost:{name}"] += n
    return c


def collect_site(
    fetcher: SiteFetcher, fixture: SiteFixture, requests: Callable[[], int] = lambda: 0
) -> tuple[list[Captured], Counter[str]]:
    """What a first collection of ``fixture``'s website stores, replayed through ``fetcher``.

    Discovery (``SiteFetcher.discover_menu_attempt``) as the URL pipeline runs it, with no
    saved keys: own-site pages in rank order, a page that is the same resource as or a near
    copy of one already taken dropped, at most ``MAX_MENU_PAGES``; every verified platform
    page. A menu-named PDF is counted (``pdf_linked``), not read (ADR-0013 Amendment 3). The
    cost counts renders, and network requests as ``requests`` (the caller's counter, e.g. a
    counting transport) reports them."""
    calls_before = requests()
    found = fetcher.discover_menu_attempt(fixture.website, address=fixture.address)
    cost: Counter[str] = Counter()
    captured: list[Captured] = []
    taken: list[tuple[str, frozenset[str]]] = []
    if isinstance(found, CaptureFailure):
        cost[f"failure:{found.reason_code}"] += 1
        found = ()
    for item in found:
        if isinstance(item, MenuPdfLinked):
            cost["pdf_linked"] += 1
            continue
        if not isinstance(item, MenuUrlDiscovery):
            cost["platform_ambiguous"] += 1
            continue
        html = item.page_html or ""
        if item.signal != "platform":
            blocks = _page_blocks(item)
            if any(
                same_resource(item.menu_url, url) or _duplicate_page(blocks, other)
                for url, other in taken
            ):
                cost["duplicate_pages"] += 1
                continue
            if len(taken) >= MAX_MENU_PAGES:
                cost["over_cap_pages"] += 1
                continue
            taken.append((item.menu_url, blocks))
        captured.append(Captured(item.menu_url, html, rendered=item.render is not None))
        cost["renders"] += item.render is not None
    cost["requests"] = requests() - calls_before
    return captured, cost


def _rate(c: Mapping[str, int], num: str, den: str) -> float | None:
    return c.get(num, 0) / c[den] if c.get(den) else None


def coverage_metrics(c: Mapping[str, int]) -> dict[str, float | None]:
    """Coverage rates from summed :func:`coverage_site` counts."""
    out = {
        "venue_coverage": _rate(c, "sites_any_page", "sites_with_menu"),
        "complete_coverage": _rate(c, "sites_all_pages", "sites_with_menu"),
        "page_recall": _rate(c, "pages_found", "pages_expected"),
        "page_precision": _rate(c, "captured_expected", "captured"),
        "wrong_location_share": _rate(c, "captured_other_location", "captured"),
        "no_menu_clean": _rate(c, "sites_no_menu_clean", "sites_no_menu"),
        "state_coverage": _rate(c, "states_covered", "states_expected"),
    }
    for kind in STATE_KINDS:
        out[f"state_coverage:{kind}"] = _rate(
            c, f"states_covered:{kind}", f"states_expected:{kind}"
        )
    return out
