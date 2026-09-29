"""Website + menu-URL resolution against a real migrated database (ADR-0010).

Covers Bronze-first website/menu-URL persistence assigned to the Organization
Subject, the chain no-collapse guarantee (per-GERS records), idempotent re-run
(reuse, no re-crawl), the registry override path, and the no-website tail, plus
the ADR-0010 Amendment 2 re-run rules (needs_review, registry/website
supersession, no duplicate versions, --limit progress, batch commits). The
menu-URL resolver is a fake, so there is no network or DuckDB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from apps.discovery.overture import OverturePoi
from apps.discovery.pipeline import run_discovery
from apps.discovery.registry import RegistryEntry
from apps.discovery.url_pipeline import (
    MENU_URL_NAMESPACE,
    WEBSITE_NAMESPACE,
    UrlDiscoveryReport,
    _coerce_website,
    resolve_urls,
)
from apps.discovery.web_client import CaptureFailure, MenuUrlDiscovery
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    record_subject_change,
    unassign_source_record,
)
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    Organization,
    ResolutionEvent,
    SubjectCurrentness,
)
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def isolate_existing_venues(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reports must not depend on committed fixtures from earlier test modules."""
    if "session" not in request.fixturenames:
        return
    import apps.discovery.url_pipeline as pipeline

    session = request.getfixturevalue("session")
    existing = set(session.scalars(select(Establishment.subject_id)))
    original = pipeline.iter_venues_to_resolve

    def selected(session: Session, *, page_size: int = 100) -> Iterator[pipeline.VenueToResolve]:
        for venue in original(session, page_size=page_size):
            if venue.establishment_subject_id not in existing:
                yield venue

    monkeypatch.setattr(pipeline, "iter_venues_to_resolve", selected)


_NOW = datetime.now(UTC)


class _FakeResolver:
    verifier = "s4-v1"
    """A menu-URL resolver that records calls and returns canned results.

    ``platform_urls`` are extra verified ordering-platform pages returned after
    the own-site menu, as the real fetcher does since S6b.
    """

    def __init__(
        self,
        menu_url: str | None,
        *,
        signal: str = "crawled",
        platform_urls: tuple[str, ...] = (),
    ) -> None:
        self._menu_url = menu_url
        self._signal = signal
        self._platform_urls = platform_urls
        self.calls: list[str] = []
        self.verified: list[str] = []

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        self.verified.append(menu_url)
        found = self.discover_menu_attempt(website)
        if isinstance(found, CaptureFailure):
            return found
        return next((item for item in found if item.menu_url == menu_url), found[0])

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery, ...] | CaptureFailure:
        self.calls.append(website)
        found = tuple(
            MenuUrlDiscovery(
                menu_url=url,
                signal=signal,
                fetched_at=_NOW,
                content_hash="sha256:fixture-page",
                found_via=None if signal != "platform" else website,
            )
            for url, signal in (
                *(((self._menu_url, self._signal),) if self._menu_url else ()),
                *((url, "platform") for url in self._platform_urls),
            )
        )
        return found or CaptureFailure("failed", "no_menu_found", _NOW)


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
    run_discovery(
        session,
        pois,
        decided_at=_NOW,
        observed_at=_NOW,
        release="s3://overturemaps-us-west-2/release/2026-01-01.0/theme=places/type=place/*",
    )


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
            content_hash="sha256:fixture-registry",
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


# --- Review remediation S3 (R04, R07, R15, R16, R32, R57, R73) -------------------

_LATER = _NOW + timedelta(days=30)


def _decision(method: str) -> DecisionMetadata:
    return DecisionMetadata(
        confidence=Decimal("1"),
        method=method,
        method_version="1",
        actor_class="human",
        decided_at=_NOW,
        effective_at=_NOW,
    )


def _resolve_at(
    session: Session,
    resolver: _FakeResolver,
    *,
    at: datetime,
    registry: dict[str, RegistryEntry] | None = None,
    limit: int | None = None,
) -> UrlDiscoveryReport:
    return resolve_urls(
        session,
        resolver=resolver,
        registry=registry or {},
        decided_at=at,
        observed_at=at,
        limit=limit,
    )


def _record(session: Session, namespace: str, external_key: str) -> CurrentResolution:
    current = session.scalar(
        select(CurrentResolution)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == namespace, SourceRecord.external_key == external_key)
    )
    assert current is not None
    return current


def _versions(session: Session, namespace: str, external_key: str) -> list[dict[str, object]]:
    """Every saved payload for one URL record, oldest observation first."""
    return list(
        session.scalars(
            select(SourceRecordVersion.source_payload)
            .join(SourceRecord, SourceRecord.id == SourceRecordVersion.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Source.namespace == namespace, SourceRecord.external_key == external_key)
            .order_by(SourceRecordVersion.observed_at, SourceRecordVersion.id)
        )
    )


def _any_evidence_id(session: Session) -> int:
    evidence_id = session.scalar(select(Evidence.id).limit(1))
    assert evidence_id is not None
    return evidence_id


def _human_unassign(session: Session, namespace: str, external_key: str) -> None:
    current = _record(session, namespace, external_key)
    assert current.state == "resolved" and current.subject_id is not None
    unassign_source_record(
        session,
        source_record_id=current.source_record_id,
        from_subject_id=current.subject_id,
        decision=_decision("human-unassign"),
        evidence_ids=[_any_evidence_id(session)],
    )


def test_needs_review_website_is_never_reassigned_or_crawled(session: Session) -> None:
    _seed(session, [_poi("Kerbey Lane", 30.30, -97.75, gers_id="r1", websites=("kerbey.com",))])
    resolver = _FakeResolver("https://kerbey.com/menu")
    _resolve_at(session, resolver, at=_NOW)
    _human_unassign(session, WEBSITE_NAMESPACE, "r1")

    report = _resolve_at(session, resolver, at=_LATER)

    assert _record(session, WEBSITE_NAMESPACE, "r1").state == "needs_review"
    assert (report.needs_review, report.websites_resolved) == (1, 0)
    assert resolver.calls == ["https://kerbey.com/"], "a disputed website must not be crawled"


def test_needs_review_menu_url_is_never_reassigned(session: Session) -> None:
    _seed(session, [_poi("Home Slice", 30.24, -97.75, gers_id="r2", websites=("homeslice.com",))])
    _resolve_at(session, _FakeResolver("https://homeslice.com/"), at=_NOW)
    _human_unassign(session, MENU_URL_NAMESPACE, "r2")
    resolver = _FakeResolver("https://homeslice.com/menu")

    report = _resolve_at(session, resolver, at=_LATER)

    assert _record(session, MENU_URL_NAMESPACE, "r2").state == "needs_review"
    assert (report.needs_review, report.menu_urls_found) == (1, 0)
    assert resolver.calls == [], "a disputed menu URL must not trigger a crawl"


def test_venue_on_retired_organization_is_counted_not_crashed(session: Session) -> None:
    _seed(session, [_poi("Gone Cafe", 30.26, -97.74, gers_id="r3", websites=("gone.com",))])
    record_subject_change(
        session,
        operation="retire",
        input_subject_ids=[_org_subject(session, "gone cafe")],
        output_subject_ids=[],
        decision=_decision("human-retire"),
        evidence_ids=[_any_evidence_id(session)],
    )
    resolver = _FakeResolver("https://gone.com/menu")

    report = _resolve_at(session, resolver, at=_NOW)

    assert (report.venues, report.org_not_current) == (1, 1)
    assert _versions(session, WEBSITE_NAMESPACE, "r3") == []
    assert resolver.calls == []


def test_registry_menu_url_replaces_a_saved_one(session: Session) -> None:
    _seed(session, [_poi("Torchys", 30.25, -97.75, gers_id="r4", websites=("torchystacos.com",))])
    _resolve_at(session, _FakeResolver("https://torchystacos.com/"), at=_NOW)
    registry = {
        "torchystacos.com": RegistryEntry(
            content_hash="sha256:fixture-registry",
            host="torchystacos.com",
            website=None,
            menu_url="https://torchystacos.com/menu",
            location_unique=False,
        )
    }
    resolver = _FakeResolver(None)

    report = _resolve_at(session, resolver, at=_LATER, registry=registry)

    assert (report.menu_urls_updated, report.menu_urls_found) == (1, 0)
    assert resolver.calls == []
    menus = [payload["menu_url"] for payload in _versions(session, MENU_URL_NAMESPACE, "r4")]
    assert menus == ["https://torchystacos.com/", "https://torchystacos.com/menu"]
    menu_record = _record(session, MENU_URL_NAMESPACE, "r4")
    assert (menu_record.state, menu_record.subject_id) == (
        "resolved",
        _org_subject(session, "torchys"),
    )

    again = _resolve_at(session, resolver, at=_LATER + timedelta(days=30), registry=registry)
    assert (again.menu_urls_updated, again.menu_urls_reused) == (0, 1)
    assert len(_versions(session, MENU_URL_NAMESPACE, "r4")) == 2


def test_registry_website_overrides_overture_and_drives_the_crawl(session: Session) -> None:
    _seed(session, [_poi("Veracruz", 30.27, -97.72, gers_id="r9", websites=("veracruz.com",))])
    registry = {
        "veracruz.com": RegistryEntry(
            content_hash="sha256:fixture-registry",
            host="veracruz.com",
            website="https://veracruzallnatural.com/",  # parse_registry canonicalizes
            menu_url=None,
            location_unique=True,
        )
    }
    resolver = _FakeResolver("https://veracruzallnatural.com/menu")

    _resolve_at(session, resolver, at=_NOW, registry=registry)

    assert _versions(session, WEBSITE_NAMESPACE, "r9") == [
        {
            "website": "https://veracruzallnatural.com/",
            "origin": "registry",
            "host": "veracruzallnatural.com",
            "location_unique": True,
        }
    ]
    assert resolver.calls == ["https://veracruzallnatural.com/"]


def _seed_website(session: Session, gers_id: str, website: str, *, at: datetime) -> None:
    run_discovery(
        session,
        [_poi("Veracruz", 30.27, -97.72, gers_id=gers_id, websites=(website,))],
        decided_at=at,
        observed_at=at,
        release="s3://overturemaps-us-west-2/release/2026-01-01.0/theme=places/type=place/*",
    )


def test_website_change_rediscovers_the_menu_url(session: Session) -> None:
    _seed_website(session, "r5", "https://old-veracruz.com", at=_NOW)
    _resolve_at(session, _FakeResolver("https://old-veracruz.com/menu"), at=_NOW)
    _seed_website(session, "r5", "https://veracruz.com", at=_LATER)
    resolver = _FakeResolver("https://veracruz.com/menu")

    report = _resolve_at(session, resolver, at=_LATER)

    assert (report.websites_updated, report.menu_urls_updated) == (1, 1)
    assert resolver.calls == ["https://veracruz.com/"]
    menus = [payload["menu_url"] for payload in _versions(session, MENU_URL_NAMESPACE, "r5")]
    assert menus == ["https://old-veracruz.com/menu", "https://veracruz.com/menu"]
    assert _record(session, MENU_URL_NAMESPACE, "r5").state == "resolved"


def test_website_change_keeps_old_menu_url_when_rediscovery_finds_none(session: Session) -> None:
    _seed_website(session, "r6", "https://old-veracruz.com", at=_NOW)
    _resolve_at(session, _FakeResolver("https://old-veracruz.com/menu"), at=_NOW)
    _seed_website(session, "r6", "https://veracruz.com", at=_LATER)

    report = _resolve_at(session, _FakeResolver(None), at=_LATER)

    assert (report.menu_urls_absent, report.menu_urls_updated) == (1, 0)
    menus = [payload["menu_url"] for payload in _versions(session, MENU_URL_NAMESPACE, "r6")]
    assert menus == ["https://old-veracruz.com/menu"]


def test_later_rerun_appends_no_bronze_rows(session: Session) -> None:
    _seed(session, [_poi("Home Slice", 30.24, -97.75, gers_id="r7", websites=("homeslice.com",))])
    resolver = _FakeResolver("https://homeslice.com/menu")
    _resolve_at(session, resolver, at=_NOW)

    report = _resolve_at(session, resolver, at=_LATER)

    assert (report.websites_reused, report.menu_urls_reused) == (1, 1)
    assert len(_versions(session, WEBSITE_NAMESPACE, "r7")) == 1
    assert len(_versions(session, MENU_URL_NAMESPACE, "r7")) == 1


def _numbered_pois(prefix: str, count: int) -> list[OverturePoi]:
    return [
        _poi(
            f"{prefix} {index}",
            30.20 + index / 10,
            -97.60,
            gers_id=f"{prefix}{index}",
            websites=(f"{prefix}{index}.com",),
        )
        for index in range(count)
    ]


def test_limit_advances_past_venues_already_resolved(session: Session) -> None:
    _seed(session, _numbered_pois("limit", 3))
    resolver = _FakeResolver("https://example.com/menu")

    for run in range(3):
        _resolve_at(session, resolver, at=_NOW + timedelta(days=run), limit=1)

    for index in range(3):
        assert _record(session, MENU_URL_NAMESPACE, f"limit{index}").state == "resolved"
    assert len(resolver.calls) == 3


def test_latest_overture_version_is_chosen_by_observed_at_not_id(session: Session) -> None:
    _seed_website(session, "r8", "https://current.com", at=_LATER)
    _seed_website(session, "r8", "https://backfilled-older.com", at=_NOW)  # newer id, older date

    _resolve_at(session, _FakeResolver(None), at=_LATER)

    websites = [payload["website"] for payload in _versions(session, WEBSITE_NAMESPACE, "r8")]
    assert websites == ["https://current.com/"]


def test_establishment_with_two_overture_records_is_processed_once(session: Session) -> None:
    _seed(
        session,
        [
            _poi("Juans", 30.28, -97.73, gers_id="d1", websites=("juans.com",)),
            _poi("Juans", 30.28, -97.73, gers_id="d2", websites=("juans.com",)),
        ],
    )
    resolver = _FakeResolver("https://juans.com/menu")

    report = _resolve_at(session, resolver, at=_NOW)

    assert (report.venues, len(resolver.calls)) == (1, 1)
    assert _versions(session, WEBSITE_NAMESPACE, "d1") != []
    assert _versions(session, WEBSITE_NAMESPACE, "d2") == []


class _FailingResolver(_FakeResolver):
    def __init__(self, fail_on: str) -> None:
        super().__init__("https://example.com/menu")
        self._fail_on = fail_on

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery, ...] | CaptureFailure:
        if website == self._fail_on:
            raise RuntimeError("simulated crash mid-run")
        return super().discover_menu_attempt(website)


def test_batches_commit_so_a_crash_keeps_earlier_work(session: Session) -> None:
    _seed(session, _numbered_pois("batch", 5))
    session.commit()  # releases the fixture savepoint; the outer transaction still rolls back
    commits: list[int] = []

    def commit() -> None:
        commits.append(1)
        session.commit()

    with pytest.raises(RuntimeError, match="simulated crash"):
        resolve_urls(
            session,
            resolver=_FailingResolver("https://batch4.com/"),
            registry={},
            decided_at=_NOW,
            observed_at=_NOW,
            batch_size=2,
            on_batch=commit,
        )
    session.rollback()

    assert len(commits) == 2
    for index in range(4):
        assert _record(session, MENU_URL_NAMESPACE, f"batch{index}").state == "resolved"
    assert _versions(session, WEBSITE_NAMESPACE, "batch4") == []


# --- Review remediation S4 (R76) -------------------------------------------------


def test_coerce_website_rejects_a_retry_host_without_a_dot() -> None:
    # A typo'd single slash ('http:/site.com') parses on the https:// retry
    # as scheme https, host "http" -- a URL shape, but not a real website.
    assert _coerce_website("http:/site.com") is None


def test_coerce_website_still_fixes_a_bare_domain() -> None:
    assert _coerce_website("kerbey.com") == "https://kerbey.com/"
    assert _coerce_website("https://kerbey.com") == "https://kerbey.com/"


def test_coerce_website_rejects_garbage() -> None:
    assert _coerce_website("not a url") is None
    assert _coerce_website("") is None
    assert _coerce_website("   ") is None


# --- Review remediation S6b: platform menus alongside site menus (ADR-0011 §7) ---


def _bronze_row_counts(session: Session) -> tuple[int | None, ...]:
    return tuple(
        session.scalar(select(func.count()).select_from(model))
        for model in (SourceRecordVersion, Capture, Evidence, ResolutionEvent)
    )


def test_site_menu_and_toast_link_write_both_records_and_a_rerun_writes_nothing(
    session: Session, tmp_path: Path
) -> None:
    from test.test_web_client import _fetcher

    website = "https://s6b-kitchen.com/"
    toast = "https://order.toasttab.com/online/s6b-kitchen"
    routes = {
        "/robots.txt": (404, "", "text/plain"),
        "/": (
            200,
            f'<a href="/menu">Our Menu</a><a href="{toast}">Order Online</a>'
            '<a href="https://www.instagram.com/s6b">Instagram</a>',
            "text/html",
        ),
        "/menu": (200, "<title>Menu</title><p>Tacos $5</p>", "text/html"),
        toast: (200, "<title>S6b Kitchen | Menu</title>", "text/html"),
    }
    _seed(session, [_poi("S6b Kitchen", 30.29, -97.74, gers_id="p1", websites=(website,))])

    with _fetcher(tmp_path, routes) as fetcher:
        first = resolve_urls(
            session, resolver=fetcher, registry={}, decided_at=_NOW, observed_at=_NOW
        )

    org = _org_subject(session, "s6b kitchen")
    assert first.menu_urls_found == 2
    assert _url_record_subject(session, MENU_URL_NAMESPACE, "p1") == org
    assert _url_record_subject(session, MENU_URL_NAMESPACE, "p1|toasttab.com") == org
    (own,) = _versions(session, MENU_URL_NAMESPACE, "p1")
    (platform,) = _versions(session, MENU_URL_NAMESPACE, "p1|toasttab.com")
    assert (own["menu_url"], own["signal"], "platform" in own) == (
        "https://s6b-kitchen.com/menu",
        "well_known",
        False,
    )
    assert platform == {
        "menu_url": toast,
        "signal": "platform",
        "website": website,
        "found_via": website,
        "platform": "toasttab.com",
        "verifier": "s4-v1",
    }
    before = _bronze_row_counts(session)

    calls: list[str] = []
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        second = resolve_urls(
            session, resolver=fetcher, registry={}, decided_at=_LATER, observed_at=_LATER
        )

    assert (second.menu_urls_found, second.menu_urls_updated, second.menu_urls_reused) == (0, 0, 1)
    assert _bronze_row_counts(session) == before, "a re-run writes nothing"
    assert calls == [], "a saved menu for an unchanged website is not re-crawled"


def test_platform_menus_are_persisted_per_host(session: Session) -> None:
    _seed(session, [_poi("Multi", 30.28, -97.73, gers_id="p2", websites=("multi.com",))])
    resolver = _FakeResolver(
        "https://multi.com/menu",
        platform_urls=(
            "https://order.toasttab.com/online/multi",
            "https://www.doordash.com/store/multi-1/",
        ),
    )

    report = _resolve_at(session, resolver, at=_NOW)

    assert report.menu_urls_found == 3
    org = _org_subject(session, "multi")
    for key in ("p2", "p2|toasttab.com", "p2|doordash.com"):
        assert _url_record_subject(session, MENU_URL_NAMESPACE, key) == org
    assert _versions(session, MENU_URL_NAMESPACE, "p2|doordash.com")[0]["platform"] == (
        "doordash.com"
    )


def test_platform_only_menu_is_reused_without_a_recrawl(session: Session) -> None:
    _seed(session, [_poi("Toast Only", 30.27, -97.71, gers_id="p3", websites=("toastonly.com",))])
    resolver = _FakeResolver(None, platform_urls=("https://order.toasttab.com/online/only",))

    _resolve_at(session, resolver, at=_NOW)
    report = _resolve_at(session, resolver, at=_LATER)

    assert _versions(session, MENU_URL_NAMESPACE, "p3") == []
    assert len(_versions(session, MENU_URL_NAMESPACE, "p3|toasttab.com")) == 1
    assert report.menu_urls_reused == 1
    assert resolver.calls == ["https://toastonly.com/"]


def test_a_disputed_platform_key_is_kept_and_does_not_block_the_site_menu(
    session: Session,
) -> None:
    _seed_website(session, "p4", "https://old-p4.com", at=_NOW)
    toast = "https://order.toasttab.com/online/p4"
    _resolve_at(session, _FakeResolver("https://old-p4.com/menu", platform_urls=(toast,)), at=_NOW)
    _human_unassign(session, MENU_URL_NAMESPACE, "p4|toasttab.com")
    _seed_website(session, "p4", "https://p4.com", at=_LATER)
    resolver = _FakeResolver("https://p4.com/menu", platform_urls=(toast + "-new",))

    report = _resolve_at(session, resolver, at=_LATER)

    assert (report.menu_urls_updated, report.needs_review) == (1, 1)
    assert _record(session, MENU_URL_NAMESPACE, "p4|toasttab.com").state == "needs_review"
    assert [v["menu_url"] for v in _versions(session, MENU_URL_NAMESPACE, "p4|toasttab.com")] == [
        toast
    ], "the disputed platform record keeps its history and gets no new version"
    assert [v["menu_url"] for v in _versions(session, MENU_URL_NAMESPACE, "p4")] == [
        "https://old-p4.com/menu",
        "https://p4.com/menu",
    ]
