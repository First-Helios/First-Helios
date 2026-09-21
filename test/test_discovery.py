"""Discovery pipeline behavior against a real migrated database (ADR-0009).

Covers Bronze-first admission, conservative mint/dedupe, the chain
no-over-merge guarantee, idempotent re-ingest, and the ambiguous-match guard.
No network or DuckDB: POIs are injected directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select

from apps.discovery.overture import OverturePoi
from apps.discovery.pipeline import DiscoveryReport, run_discovery
from packages.helios_core.identity.commands import (
    create_establishment,
    create_organization,
    create_place,
)
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


def _poi(
    name: str,
    latitude: float | None,
    longitude: float | None,
    *,
    gers_id: str | None = None,
    website: str | None = None,
) -> OverturePoi:
    gers = gers_id or f"gers-{uuid4().hex}"
    raw = {"id": gers, "name": name, "lat": latitude, "lon": longitude}
    if website is not None:
        raw["website"] = website
    return OverturePoi(
        gers_id=gers,
        name=name,
        primary_category="restaurant",
        alternate_categories=(),
        websites=(website,) if website else (),
        address=f"{name} address",
        latitude=latitude,
        longitude=longitude,
        confidence=0.9,
        raw=raw,
    )


def _run(session: Session, pois: list[OverturePoi]) -> DiscoveryReport:
    return run_discovery(
        session,
        pois,
        decided_at=_NOW,
        observed_at=_NOW,
        release="test-release-2026-01-01",
    )


def _current_establishment_count(session: Session, fingerprint: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Establishment)
            .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
            .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
            .where(
                Organization.name_fingerprint == fingerprint,
                SubjectCurrentness.is_current.is_(True),
            )
        )
        or 0
    )


def _resolution_subject(session: Session, external_key: str) -> int | None:
    return session.scalar(
        select(CurrentResolution.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == "overture", SourceRecord.external_key == external_key)
    )


def test_discovery_mints_distinct_venues_bronze_first(session: Session) -> None:
    pois = [
        _poi("Franklin Barbecue", 30.2701, -97.7313),
        _poi("Home Slice Pizza", 30.2489, -97.7500),
    ]
    report = _run(session, pois)

    assert (report.fetched, report.minted, report.deduped, report.reused) == (2, 2, 0, 0)
    # Both are served-able: current Establishments exist for each fingerprint.
    assert _current_establishment_count(session, "franklin barbecue") == 1
    assert _current_establishment_count(session, "home slice pizza") == 1
    # Bronze provenance: one overture Source, one Source Record per POI.
    source_id = session.scalar(select(Source.id).where(Source.namespace == "overture"))
    assert source_id is not None
    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceRecord)
            .where(SourceRecord.source_id == source_id)
        )
        == 2
    )


def test_rerun_of_same_release_is_idempotent(session: Session) -> None:
    pois = [_poi("Kerbey Lane Cafe", 30.3079, -97.7559, gers_id="gers-kerbey")]
    first = _run(session, pois)
    assert first.minted == 1

    second = _run(session, [_poi("Kerbey Lane Cafe", 30.3079, -97.7559, gers_id="gers-kerbey")])
    assert (second.fetched, second.minted, second.reused) == (1, 0, 1)
    assert _current_establishment_count(session, "kerbey lane cafe") == 1


def test_two_chain_locations_do_not_merge(session: Session) -> None:
    # Same brand + same website, far apart: must stay two Establishments.
    pois = [
        _poi("Torchy's Tacos", 30.2515, -97.7548, website="https://torchystacos.com"),
        _poi("Torchy's Tacos", 30.4000, -97.7000, website="https://torchystacos.com"),
    ]
    report = _run(session, pois)

    assert (report.minted, report.deduped, report.ambiguous) == (2, 0, 0)
    assert _current_establishment_count(session, "torchys tacos") == 2


def test_near_duplicate_within_radius_is_deduped(session: Session) -> None:
    # ~33 m apart (0.0003 deg lat), same name -> second assigns to the first.
    first_poi = _poi("Veracruz All Natural", 30.2596, -97.7248, gers_id="gers-vera-1")
    second_poi = _poi("Veracruz All Natural", 30.25990, -97.7248, gers_id="gers-vera-2")
    report = _run(session, [first_poi, second_poi])

    assert (report.minted, report.deduped, report.ambiguous) == (1, 1, 0)
    assert _current_establishment_count(session, "veracruz all natural") == 1
    subject_one = _resolution_subject(session, "gers-vera-1")
    subject_two = _resolution_subject(session, "gers-vera-2")
    assert subject_one is not None
    assert subject_one == subject_two


def test_blank_name_is_skipped(session: Session) -> None:
    report = _run(session, [_poi("   ", 30.25, -97.75)])
    assert (report.fetched, report.skipped, report.minted) == (1, 1, 0)


def test_ambiguous_match_is_left_unresolved(session: Session) -> None:
    # Two current same-fingerprint Establishments within 50 m, created directly so
    # neither deduped the other; a POI at that point must not auto-merge.
    for lat in (30.3000, 30.30030):
        organization = create_organization(
            session, canonical_name="Ambiguous Grill", name_fingerprint="ambiguous grill"
        )
        place = create_place(
            session, address="somewhere", latitude=_dec(lat), longitude=_dec(-97.7)
        )
        create_establishment(
            session,
            organization_subject_id=organization.id,
            place_subject_id=place.id,
            valid_from=_NOW,
        )

    report = _run(session, [_poi("Ambiguous Grill", 30.3000, -97.7000, gers_id="gers-ambig")])

    assert (report.minted, report.deduped, report.ambiguous) == (0, 0, 1)
    assert _resolution_subject(session, "gers-ambig") is None  # unresolved
    assert _current_establishment_count(session, "ambiguous grill") == 2  # unchanged


def _dec(value: float) -> Decimal:
    return Decimal(str(value))
