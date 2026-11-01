"""The wrong-place page check ``place-v1`` (ADR-0015 Amendment 2).

The page verifier decides whether a page is a menu, not whose menu it is: a
platform's sitemap or a lapsed domain can hand a venue another restaurant's
menu (Jefes in Austin showed a Galloway, NJ takeout's). :func:`place_verdict`
says whether a page belongs to another place than its venue's metro.

A page is **wrong-place** when it does not name the venue's metro and shows
evidence of another place:

* *mentions* are "City, ST" and "City, ST 12345" (ST a US state code). An
  all-caps city counts only with a ZIP ("SEAFOOD, OR EGGS" is no Oregon), and a
  mention followed by "!" or a lower-case word is a name ("Buffalo, TX hot");
* a mention is *foreign* when its ZIP is outside the area's postcodes, its state
  is not the venue's, or it is in the venue's state and contains no area
  locality ("Downtown Austin, TX" is metro, "Southlake, TX" is not);
* the metro is *named* by the venue's locality as a word on the page or in the
  URL, an area locality written "City, <venue state>", or an area postcode;
* evidence **E1** ``url_place``: the URL path names a foreign place, a foreign
  ZIP closing a slug or up to four path tokens equal to a gazetteer city;
  **E2** ``address``: a foreign "City, ST 12345" on a page naming at most two
  foreign places with a ZIP, except on a chain page (its lone out-of-town
  address is the head office); **E3** ``dominant``: one foreign place outside
  chrome and wine sections named at least twice, on a page with at most two
  foreign places outside chrome.

Without the metro named, any evidence decides. With it, E1 alone still does when
the URL path does not name the metro: another location's page of a chain whose
location list includes the metro. Wine appellations, brewery towns and chain
location lists are many places, sit in chrome, or include the metro.

**Another location's page** (ADR-0025 D2′, :func:`other_location_places`) is
narrower and same-metro: an own-site menu page whose URL path names a place (an
area locality or a gazetteer city, a run of up to four path tokens) that is
neither the venue's locality nor the metro's principal city, on a URL that does
not name the venue's locality. Salt Lick's ``/round-rock-menu`` stored for its
airport venue is one. Suburb sites call themselves "Austin", so the principal
city says nothing.

The area (:class:`PlaceArea`) is data, never a hand-made list: the Overture POI
localities and postcodes, the principal city (the most common POI locality), a
gazetteer of foreign places named on the stored menu pages (mostly chains'
location lists), and the chain pages (one menu URL saved for several venues whose
names share their first word). See :func:`load_place_area`.
"""

from __future__ import annotations

import gzip
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from sqlalchemy import select

from packages.helios_core.provenance.models import (
    Capture,
    Source,
    SourceRecord,
    SourceRecordVersion,
)
from packages.helios_parsing.output import wine_section

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime
    from pathlib import Path

    from sqlalchemy.orm import Session

    from packages.helios_parsing.segment import Block

# place-v1 (ADR-0015 Amendment 2) plus another location's page (ADR-0025 D2′).
PLACE_CHECK = "place-v2"

# Localities need this many POIs to define the area: a typo'd or stray locality
# would otherwise make its name "metro".
MIN_LOCALITY_POIS = 3

# The US state codes (and DC), as a regex alternation.
_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|"
    "NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
_CITY = r"[A-Z][A-Za-z.'’]+(?:[ -](?:[A-Z][A-Za-z.'’]+|de|del|la|of))*"
_PLACE = re.compile(rf"\b({_CITY}),\s*({_STATES})\b(?:\.?,?\s+(\d{{5}})(?:-\d{{4}})?)?(?![A-Za-z])")
_NAME_AFTER = re.compile(r"^\s*(!|[a-z])")  # "Aloha, NY! Pizza", "Buffalo, TX hot"
_URL_ZIP = re.compile(r"(?<=[a-z]-)(\d{5})(?=/|$|\?|#)")  # "…-galloway-08205/"
_TOKEN = re.compile(r"[a-z0-9]+")
_MAX_URL_RUN = 4  # tokens in a URL city ("rancho-santa-margarita")
_MAX_PLACES = 2  # more foreign places than this is a list, not this page's place
_MIN_REPEATS = 2
# (ADR-0025 D2′) a URL place shorter than this is too likely a word: the rule as
# D1 measured it.
_MIN_URL_PLACE = 4


def slug(text: str) -> str:
    """Lower-case alphanumeric tokens joined by "-" ("College Station" -> "college-station")."""
    return "-".join(_TOKEN.findall(text.lower()))


@dataclass(frozen=True, slots=True)
class VenuePlace:
    """The venue's own address fields, from its Overture record."""

    locality: str | None
    region: str | None
    postcode: str | None


@dataclass(frozen=True, slots=True)
class PlaceArea:
    """The discovery area, the gazetteer and the chain pages (see the module docstring)."""

    localities: frozenset[str]  # lower case
    postcodes: frozenset[str]  # five digits
    regions: frozenset[str] = frozenset()  # the area's state codes, for the gazetteer
    gazetteer: frozenset[str] = frozenset()  # slugs of foreign cities named on stored pages
    chain_urls: frozenset[str] = frozenset()
    principal: str | None = None  # the metro's principal city: the most common locality

    def names(self) -> re.Pattern[str]:
        return _names_pattern(self.localities)


_PATTERNS: dict[frozenset[str], re.Pattern[str]] = {}


def _names_pattern(localities: frozenset[str]) -> re.Pattern[str]:
    pattern = _PATTERNS.get(localities)
    if pattern is None:
        names = sorted(localities, key=lambda name: (-len(name), name))
        alternation = "|".join(re.escape(name) for name in names) or r"(?!x)x"
        pattern = re.compile(rf"(?i)\b({alternation})\b")
        _PATTERNS[localities] = pattern
    return pattern


@dataclass(frozen=True, slots=True)
class Mention:
    """One "City, ST [ZIP]" on a page."""

    city: str
    state: str
    zip: str | None
    chrome: bool
    wine: bool  # under a wine-list heading (ADR-0013 Amendment 15)

    @property
    def place(self) -> str:
        return f"{self.city}, {self.state}"


@dataclass(frozen=True, slots=True)
class PlaceVerdict:
    """Whether the page is another place's, and the evidence that decided it."""

    wrong: bool
    metro_named: bool
    evidence: tuple[str, ...] = ()


def mentions(blocks: Sequence[Block]) -> list[Mention]:
    """Every place-shaped mention, in page order; names and all-caps words are not places."""
    found: list[Mention] = []
    heading: str | None = None
    for block in blocks:
        if block.heading:
            heading = block.text
        for match in _PLACE.finditer(block.text):
            city, state, zip_code = match.group(1), match.group(2), match.group(3)
            if not zip_code and (
                _NAME_AFTER.match(block.text[match.end() : match.end() + 12])
                or not any(c.islower() for c in city)
            ):
                continue
            found.append(Mention(city, state, zip_code, block.in_chrome, wine_section(heading)))
    return found


def _in_area(mention: Mention, area: PlaceArea, regions: Iterable[str]) -> bool:
    if mention.zip:
        return mention.zip in area.postcodes
    return mention.state in regions and area.names().search(mention.city) is not None


def foreign_slugs(blocks: Sequence[Block], area: PlaceArea) -> set[str]:
    """The gazetteer's contribution of one stored page: foreign cities outside wine lists."""
    return {
        slug(m.city) for m in mentions(blocks) if not m.wine and not _in_area(m, area, area.regions)
    }


def _url_path(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url).lower()


def place_verdict(
    url: str, blocks: Sequence[Block], venue: VenuePlace, area: PlaceArea
) -> PlaceVerdict:
    """``place-v1``: is this page another place's than the venue's metro?"""
    region = venue.region or ""
    names = area.names()
    own = (venue.locality or "").strip().lower()
    found = mentions(blocks)
    foreign = [m for m in found if not _in_area(m, area, (region,))]
    text_metro = any(_in_area(m, area, (region,)) for m in found) or (
        bool(own) and any(own in _hits(names, block.text) for block in blocks)
    )
    url_metro = bool(names.search(re.sub(r"[-_/.]", " ", url)))

    metro_slugs = {slug(name) for name in area.localities}
    gazetteer = area.gazetteer | {slug(m.city) for m in foreign if not m.wine}
    tokens = _TOKEN.findall(_url_path(url))
    url_places = sorted(
        {
            run
            for i in range(len(tokens))
            for j in range(i + 1, min(i + _MAX_URL_RUN, len(tokens)) + 1)
            if (run := "-".join(tokens[i:j])) in gazetteer and run not in metro_slugs
        }
    )
    url_zips = [z for z in _URL_ZIP.findall(url.lower()) if z not in area.postcodes]
    e1 = [*url_places, *url_zips]

    zipped = {(m.city, m.state) for m in foreign if m.zip}
    e2 = 0 < len(zipped) <= _MAX_PLACES and url not in area.chain_urls
    body = Counter(m.place for m in foreign if not m.chrome and not m.wine)
    top = body.most_common(1)
    e3 = bool(top) and top[0][1] >= _MIN_REPEATS and len(body) <= _MAX_PLACES

    evidence = tuple(
        name for name, held in (("url_place", bool(e1)), ("address", e2), ("dominant", e3)) if held
    )
    # Without the metro named any evidence decides; with it, only a URL naming another
    # place whose path names no metro locality (another location's page of a chain).
    wrong = bool(evidence) if not text_metro and not url_metro else bool(e1) and not url_metro
    return PlaceVerdict(wrong=wrong, metro_named=text_metro or url_metro, evidence=evidence)


def _hits(names: re.Pattern[str], text: str) -> set[str]:
    return {match.group(1).lower() for match in names.finditer(text)}


def other_location_places(url: str, venue: VenuePlace, area: PlaceArea) -> tuple[str, ...]:
    """ADR-0025 D2′: the places an own-site page's URL names that make it another location's.

    The URL path's runs of up to four tokens that are an area locality or a
    gazetteer city, at least :data:`_MIN_URL_PLACE` characters and not all
    digits. Empty when the URL names none, names the venue's own locality, or
    names only the metro's principal city. Without the venue's locality nothing
    is judged. The caller applies it to own-site pages only: a platform page is
    matched to its venue by address (ADR-0015 item 5).
    """
    own = slug(venue.locality or "")
    if not own:
        return ()
    places = {slug(name) for name in area.localities} | area.gazetteer
    tokens = _TOKEN.findall(urlsplit(url).path.lower())
    named = {
        run
        for i in range(len(tokens))
        for j in range(i + 1, min(i + _MAX_URL_RUN, len(tokens)) + 1)
        if (run := "-".join(tokens[i:j])) in places
        and len(run) >= _MIN_URL_PLACE
        and not run.isdigit()
    }
    if own in named:
        return ()
    return tuple(sorted(named - {slug(area.principal or "")}))


PlaceFailure = Literal["wrong_place", "other_location"]


def place_failure(
    url: str, blocks: Sequence[Block], venue: VenuePlace, area: PlaceArea, *, own_site: bool
) -> PlaceFailure | None:
    """The check ``place-v2``: why a verified menu page is not the venue's, or ``None``.

    ``wrong_place`` when ``place-v1`` reads it as another metro's (ADR-0015
    Amendment 2); else ``other_location`` when it is an own-site page whose URL
    names another location of the metro (ADR-0025 D2′).
    """
    if place_verdict(url, blocks, venue, area).wrong:
        return "wrong_place"
    if own_site and other_location_places(url, venue, area):
        return "other_location"
    return None


# --------------------------------------------------------------------------- #
# The area, from the database and the stored bundles.
# --------------------------------------------------------------------------- #


def _latest_payloads(session: Session, namespace: str) -> Iterable[tuple[str, dict[str, object]]]:
    """Each record's latest Version payload in ``namespace``, as (external key, payload)."""
    rows = session.execute(
        select(SourceRecord.external_key, SourceRecordVersion.source_payload)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .where(Source.namespace == namespace)
        .distinct(SourceRecord.id)
        .order_by(SourceRecord.id, SourceRecordVersion.id.desc())
    )
    for key, payload in rows:
        if isinstance(payload, dict):
            yield str(key), payload


def overture_address(payload: dict[str, object]) -> dict[str, object]:
    """The first address of an Overture POI payload ({} when it has none)."""
    addresses = payload.get("addresses")
    first = addresses[0] if isinstance(addresses, list) and addresses else None
    return first if isinstance(first, dict) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def venue_place(payload: dict[str, object]) -> VenuePlace:
    address = overture_address(payload)
    return VenuePlace(
        _text(address.get("locality")), _text(address.get("region")), _text(address.get("postcode"))
    )


def stored_pages(session: Session) -> Iterable[tuple[str, str, str, datetime]]:
    """Each ``menu-page`` record's latest Version: (key, menu URL, bundle path, fetched at)."""
    rows = session.execute(
        select(
            SourceRecord.external_key,
            SourceRecordVersion.source_payload,
            Capture.bundle_path,
            Capture.fetched_at,
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .where(Source.namespace == "menu-page")
        .distinct(SourceRecord.id)
        .order_by(SourceRecord.id, SourceRecordVersion.id.desc())
    )
    for key, payload, bundle_path, fetched_at in rows:
        url = payload.get("menu_url") if isinstance(payload, dict) else None
        if isinstance(url, str) and bundle_path:
            yield str(key), url, str(bundle_path), fetched_at


def read_blocks(base_dir: Path, bundle_path: str) -> tuple[Block, ...] | None:
    """A stored bundle's blocks, or ``None`` when it can't be read."""
    from apps.menu_pipeline.bundle import Bundle

    try:
        return Bundle.from_json(gzip.decompress((base_dir / bundle_path).read_bytes())).blocks
    except (OSError, ValueError):
        return None


def load_place_area(session: Session, *, base_dir: Path) -> PlaceArea:
    """The area from the latest Overture Versions, the gazetteer from the stored menu pages."""
    localities: Counter[str] = Counter()
    regions: Counter[str] = Counter()
    postcodes: set[str] = set()
    names: dict[str, str] = {}
    for gers, payload in _latest_payloads(session, "overture"):
        place = venue_place(payload)
        if place.locality:
            localities[place.locality.lower()] += 1
        if place.region:
            regions[place.region] += 1
        if place.postcode:
            postcodes.add(place.postcode[:5])
        names[gers] = str(payload.get("name") or "")
    principal = min(localities.items(), key=lambda item: (-item[1], item[0]), default=None)
    area = PlaceArea(
        localities=frozenset(n for n, c in localities.items() if c >= MIN_LOCALITY_POIS),
        postcodes=frozenset(postcodes),
        regions=frozenset(r for r, c in regions.items() if c >= MIN_LOCALITY_POIS),
        principal=principal[0] if principal else None,
    )

    by_url: dict[str, set[tuple[str, str]]] = {}
    for key, payload in _latest_payloads(session, "menu-url-discovery"):
        url = payload.get("menu_url")
        if isinstance(url, str):
            gers = key.split("|", 1)[0]
            first = (_TOKEN.findall(names.get(gers, "").lower()) or [""])[0]
            by_url.setdefault(url, set()).add((gers, first))
    chain_urls = frozenset(
        url
        for url, venues in by_url.items()
        if len({gers for gers, _ in venues}) >= _MIN_REPEATS
        and len({first for _, first in venues}) == 1
    )

    gazetteer: set[str] = set()
    seen: set[str] = set()
    for _, _, bundle_path, _ in stored_pages(session):
        if bundle_path in seen:
            continue
        seen.add(bundle_path)
        blocks = read_blocks(base_dir, bundle_path)
        if blocks is not None:
            gazetteer |= foreign_slugs(blocks, area)
    return PlaceArea(
        localities=area.localities,
        postcodes=area.postcodes,
        regions=area.regions,
        gazetteer=frozenset(gazetteer),
        chain_urls=chain_urls,
        principal=area.principal,
    )
