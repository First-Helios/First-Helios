"""Website + menu-URL resolution against a real migrated database (ADR-0010).

Covers Bronze-first website/menu-URL persistence assigned to the Organization
Subject, the chain no-collapse guarantee (per-GERS records), idempotent re-run
(reuse, no re-crawl), the registry override path, and the no-website tail. The
menu-URL resolver is a fake, so there is no network or DuckDB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from apps.discovery.overture import OverturePoi
from apps.discovery.pipeline import run_discovery
from apps.discovery.registry import RegistryEntry
from apps.discovery.url_pipeline import (
    MENU_URL_NAMESPACE,
    WEBSITE_NAMESPACE,
    UrlDiscoveryReport,
    resolve_urls,
)
from apps.discovery.web_client import MenuUrlDiscovery
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    Organization,
    SubjectCurrentness,
)
from packages.helios_core.provenance.models import Source, SourceRecord

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_NOW = datetime.now(UTC)


class _FakeResolver:
    """A menu-URL resolver that records calls and returns a canned result."""

    def __init__(self, menu_url: str | None, *, signal: str = "crawled") -> None:
        self._menu_url = menu_url
        self._signal = signal
        self.calls: list[str] = []

    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None:
        self.calls.append(website)
        if self._menu_url is None:
            return None
        return MenuUrlDiscovery(menu_url=self._menu_url, signal=self._signal)


def _poi(
    name: str,
    lat: float,
    lon: float,
    *,
    gers_id: str,
    websites: tuple[str, ...] = (),
) -> OverturePoi:
    raw = {"id": gers_id, "name": name, "lat": lat, "lon": lon, "websites": list(websites)}
    return OverturePoi(
        gers_id=gers_id,
        name=name,
        primary_category="restaurant",
        alternate_categories=(),
        websites=websites,
        address=f"{name} address",
        latitude=lat,
        longitude=lon,
        confidence=0.9,
        raw=raw,
    )


def _seed(session: Session, pois: list[OverturePoi]) -> None:
    run_discovery(session, pois, decided_at=_NOW, observed_at=_NOW, release="test-2026-01-01")


def _resolve(
    session: Session,
    resolver: _FakeResolver,
    registry: dict[str, RegistryEntry] | None = None,
) -> UrlDiscoveryReport:
    return resolve_urls(
        session,
        resolver=resolver,
        registry=registry or {},
        decided_at=_NOW,
        observed_at=_NOW,
    )


def _org_subject(session: Session, fingerprint: str) -> int:
    subject = session.scalar(
        select(Establishment.organization_subject_id)
        .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .where(
            Organization.name_fingerprint == fingerprint, SubjectCurrentness.is_current.is_(True)
        )
    )
    assert subject is not None
    return subject


def _url_record_subject(session: Session, namespace: str, external_key: str) -> int | None:
    return session.scalar(
        select(CurrentResolution.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(
            Source.namespace == namespace,
            SourceRecord.external_key == external_key,
            CurrentResolution.state == "resolved",
        )
    )


def test_resolves_website_and_menu_url_onto_the_organization(session: Session) -> None:
    _seed(
        session,
        [_poi("Kerbey Lane", 30.30, -97.75, gers_id="g1", websites=("https://kerbey.com",))],
    )
    resolver = _FakeResolver("https://kerbey.com/menu")

    report = _resolve(session, resolver)

    assert (report.venues, report.websites_resolved, report.menu_urls_found) == (1, 1, 1)
    assert report.without_website == 0
    org = _org_subject(session, "kerbey lane")
    assert _url_record_subject(session, WEBSITE_NAMESPACE, "g1") == org
    assert _url_record_subject(session, MENU_URL_NAMESPACE, "g1") == org
    # The resolver saw the canonicalized website.
    assert resolver.calls == ["https://kerbey.com/"]


def test_rerun_reuses_and_does_not_recrawl(session: Session) -> None:
    _seed(
        session,
        [_poi("Home Slice", 30.24, -97.75, gers_id="g2", websites=("https://homeslice.com",))],
    )
    resolver = _FakeResolver("https://homeslice.com/menu")

    _resolve(session, resolver)
    second = _resolve(session, resolver)

    assert (second.websites_resolved, second.websites_reused) == (0, 1)
    assert (second.menu_urls_found, second.menu_urls_reused) == (0, 1)
    assert resolver.calls == ["https://homeslice.com/"], "menu discovery must not run twice"


def test_venue_without_website_is_reported_and_not_crawled(session: Session) -> None:
    _seed(session, [_poi("No Site Diner", 30.31, -97.70, gers_id="g3")])
    resolver = _FakeResolver("https://should-not-be-used.com/menu")

    report = _resolve(session, resolver)

    assert (report.venues, report.without_website, report.menu_urls_found) == (1, 1, 0)
    assert resolver.calls == []
    assert _url_record_subject(session, WEBSITE_NAMESPACE, "g3") is None


def test_registry_menu_url_override_skips_the_crawl(session: Session) -> None:
    _seed(
        session,
        [_poi("Torchys", 30.25, -97.75, gers_id="g4", websites=("https://torchystacos.com",))],
    )
    resolver = _FakeResolver(None)  # would return no menu if called
    registry = {
        "torchystacos.com": RegistryEntry(
            host="torchystacos.com",
            website=None,
            menu_url="https://torchystacos.com/menu",
            location_unique=False,
        )
    }

    report = _resolve(session, resolver, registry)

    assert (report.websites_resolved, report.menu_urls_found) == (1, 1)
    assert resolver.calls == [], "a registry menu URL must not trigger a crawl"
    org = _org_subject(session, "torchys")
    assert _url_record_subject(session, MENU_URL_NAMESPACE, "g4") == org


def test_two_chain_locations_get_independent_website_records(session: Session) -> None:
    _seed(
        session,
        [
            _poi("Torchys", 30.25, -97.75, gers_id="c1", websites=("https://torchystacos.com",)),
            _poi("Torchys", 30.40, -97.70, gers_id="c2", websites=("https://torchystacos.com",)),
        ],
    )
    report = _resolve(session, _FakeResolver("https://torchystacos.com/menu"))

    assert report.websites_resolved == 2
    subject_one = _url_record_subject(session, WEBSITE_NAMESPACE, "c1")
    subject_two = _url_record_subject(session, WEBSITE_NAMESPACE, "c2")
    assert subject_one is not None and subject_two is not None
    assert subject_one != subject_two, "a shared brand site must not collapse two chain venues"
