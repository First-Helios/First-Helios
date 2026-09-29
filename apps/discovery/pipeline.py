"""Seed discovered Overture POIs into Bronze + Identity via published commands.

For each POI: persist a Bronze observation and run deterministic resolution. A
record already resolved by its stable GERS key is a no-op (monthly re-ingest is
idempotent). An unresolved record is deduped conservatively against current
Establishments by name fingerprint **and** lat/lon proximity (ADR-0009 §2,
ADR-0004 §3): a single match within the radius is assigned; no match mints a new
Place + Organization + Establishment; more than one match is left unresolved for
human review, because a wrong merge is expensive and a duplicate is not.

The Overture observation carries **no canonical URL** — a shared brand website is
an Organization-level signal, never an Establishment identity key, so two
locations of one chain never collapse into one venue (ADR-0009 hazard note).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from apps.discovery.lifecycle import (
    LifecycleReport,
    lock_lifecycle,
    project_observation,
    winning_version,
)
from apps.discovery.location_overrides import effective_location, located
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    assign_source_record,
    create_establishment,
    create_organization,
    create_place,
    resolve_source_record_observation,
)
from packages.helios_core.identity.models import (
    Establishment,
    Organization,
    Place,
    SubjectCurrentness,
)
from packages.helios_core.identity.normalize import name_fingerprint, within_radius_m
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    persist_source_record_observation,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.location_overrides import OverrideState
    from apps.discovery.overture import OverturePoi
    from packages.helios_core.geo import NominatimClient

DEFAULT_DEDUPE_RADIUS_M = 50.0
_COORD_QUANTUM = Decimal("0.000001")  # Place stores Numeric(9, 6)
_MAX_NAME_LENGTH = 255  # Organization canonical_name and name_fingerprint


@dataclass(slots=True)
class DiscoveryReport:
    """Counts from one discovery run; totals reconcile to ``fetched``."""

    lifecycle: LifecycleReport = field(default_factory=LifecycleReport)
    fetched: int = 0
    reused: int = 0
    minted: int = 0
    deduped: int = 0
    ambiguous: int = 0
    needs_review: int = 0
    skipped: int = 0
    geocoded: int = 0
    overrides_applied: int = 0
    override_stale: int = 0
    override_unmatched: int = 0
    minted_subject_ids: list[int] = field(default_factory=list)
    stale_override_ids: list[str] = field(default_factory=list)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _observation(poi: OverturePoi, *, observed_at: datetime, release: str) -> BronzeObservation:
    payload_json = json.dumps(poi.raw, sort_keys=True, default=str)
    content_hash = _sha(payload_json)
    return BronzeObservation(
        source_namespace="overture",
        source_kind="poi_snapshot",
        external_key=poi.gers_id,
        observed_at=observed_at,
        content_hash=content_hash,
        source_payload=poi.raw,
        evidence_locator="$['name','primary_category']",
        # Identity matching stays opt-in; a release endpoint never identifies a venue.
        source_url=release,
        capture_content_hash=content_hash,
    )


def _decision(method: str, *, decided_at: datetime, effective_at: datetime) -> DecisionMetadata:
    return DecisionMetadata(
        confidence=Decimal("1"),
        method=method,
        method_version="1",
        actor_class="rule",
        decided_at=decided_at,
        effective_at=effective_at,
    )


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_COORD_QUANTUM)


def _resolve_coordinates(
    poi: OverturePoi,
    geocoder: NominatimClient | None,
) -> tuple[float | None, float | None, bool]:
    """Return ``(lat, lon, geocoded)``; gap-fill via Nominatim only when needed."""
    if poi.latitude is not None and poi.longitude is not None:
        return poi.latitude, poi.longitude, False
    if geocoder is not None and poi.address:
        point = geocoder.geocode(poi.address)
        if point is not None:
            return point.latitude, point.longitude, True
    return None, None, False


def _dedupe_candidates(
    session: Session,
    *,
    fingerprint: str,
    latitude: float,
    longitude: float,
    radius_m: float,
) -> list[int]:
    """Current Establishment subject ids matching name fingerprint within radius."""
    org_current = aliased(SubjectCurrentness)
    place_current = aliased(SubjectCurrentness)
    rows = session.execute(
        select(Establishment.subject_id, Place.latitude, Place.longitude)
        .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
        .join(Place, Place.subject_id == Establishment.place_subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .join(org_current, org_current.subject_id == Organization.subject_id)
        .join(place_current, place_current.subject_id == Place.subject_id)
        .where(
            org_current.is_current.is_(True),
            place_current.is_current.is_(True),
            Establishment.operating_status != "closed",
            or_(Establishment.valid_to.is_(None), Establishment.valid_to > func.now()),
            Organization.name_fingerprint == fingerprint,
            SubjectCurrentness.is_current.is_(True),
            Place.latitude.is_not(None),
            Place.longitude.is_not(None),
        )
    ).all()
    return [
        subject_id
        for subject_id, place_lat, place_lon in rows
        if within_radius_m(latitude, longitude, float(place_lat), float(place_lon), radius_m)
    ]


def _mint_establishment(
    session: Session,
    *,
    poi: OverturePoi,
    fingerprint: str,
    latitude: float | None,
    longitude: float | None,
    valid_from: datetime,
) -> int:
    organization = create_organization(
        session,
        canonical_name=poi.name.strip(),
        name_fingerprint=fingerprint,
        organization_kind="operating_identity",
    )
    place = create_place(
        session,
        address=poi.address,
        latitude=_to_decimal(latitude) if latitude is not None else None,
        longitude=_to_decimal(longitude) if longitude is not None else None,
    )
    establishment = create_establishment(
        session,
        organization_subject_id=organization.id,
        place_subject_id=place.id,
        valid_from=valid_from,
    )
    return establishment.id


def run_discovery(
    session: Session,
    pois: Iterable[OverturePoi],
    *,
    decided_at: datetime,
    observed_at: datetime,
    release: str,
    geocoder: NominatimClient | None = None,
    dedupe_radius_m: float = DEFAULT_DEDUPE_RADIUS_M,
    batch_size: int = 100,
    on_batch: Callable[[], None] | None = None,
    overrides: Mapping[str, OverrideState] | None = None,
) -> DiscoveryReport:
    """Admit POIs to Bronze and resolve/mint/dedupe them. Flushes; caller commits.

    ``on_batch`` (the CLI passes ``session.commit``) runs after every
    ``batch_size`` POIs, bounding what one crash (e.g. a Nominatim error) can lose.
    ``overrides`` (from ``persist_overrides``) moves a record to its effective
    location before minting, dedupe and lifecycle projection (ADR-0014); Bronze
    keeps the Overture payload as observed.
    """
    report = DiscoveryReport()
    overrides = overrides or {}
    seen: set[str] = set()
    lock_lifecycle(session)
    for observed in pois:
        if on_batch is not None and report.fetched and report.fetched % batch_size == 0:
            on_batch()
            lock_lifecycle(session)
        report.fetched += 1
        seen.add(observed.gers_id)
        override = overrides.get(observed.gers_id)
        location = effective_location(observed, override)
        report.overrides_applied += int(location.applied)
        if location.stale:
            report.override_stale += 1
            report.stale_override_ids.append(observed.gers_id)
        poi = located(observed, location)
        # A name with no letters or digits has no match key; skip it rather than
        # fall back to the raw string, which would bypass normalization (R18).
        fingerprint = name_fingerprint(poi.name)
        # A name that doesn't fit the Organization columns would abort the whole
        # transaction at flush; skip it like a nameless POI (R63).
        if not fingerprint or max(len(poi.name.strip()), len(fingerprint)) > _MAX_NAME_LENGTH:
            reason = (
                "blank_name"
                if not poi.name.strip()
                else "name_without_letters_or_digits"
                if not fingerprint
                else "name_too_long"
            )
            persist_source_record_observation(
                session,
                replace(
                    _observation(poi, observed_at=observed_at, release=release),
                    capture_outcome="rejected",
                    reason_code=reason,
                ),
            )
            report.skipped += 1
            continue

        result = resolve_source_record_observation(
            session,
            observation=_observation(poi, observed_at=observed_at, release=release),
            decided_at=decided_at,
        )
        winner = winning_version(session, result.source_record_id)
        if winner is None:
            report.lifecycle.skip(f"record {result.source_record_id}: conflicting latest release")
            report.ambiguous += 1
            continue
        if winner.id != result.source_record_version_id:
            report.reused += 1
            continue
        if result.state == "resolved":
            with session.begin_nested():
                project_observation(
                    session,
                    poi=poi,
                    record_id=result.source_record_id,
                    version_id=result.source_record_version_id,
                    evidence_id=result.evidence_id,
                    decided_at=decided_at,
                    report=report.lifecycle,
                    override=override,
                    override_applied=location.applied,
                )
            report.reused += 1
            continue
        if result.state == "needs_review":
            report.needs_review += 1
            continue

        latitude, longitude, geocoded = _resolve_coordinates(poi, geocoder)
        if geocoded:
            report.geocoded += 1

        candidates: list[int] = []
        if latitude is not None and longitude is not None:
            candidates = _dedupe_candidates(
                session,
                fingerprint=fingerprint,
                latitude=latitude,
                longitude=longitude,
                radius_m=dedupe_radius_m,
            )
        if len(candidates) > 1:
            report.ambiguous += 1
            continue  # leave unresolved for human review

        if len(candidates) == 1:
            assign_source_record(
                session,
                source_record_id=result.source_record_id,
                to_subject_id=candidates[0],
                decision=_decision(
                    "overture-dedupe-assign", decided_at=decided_at, effective_at=observed_at
                ),
                evidence_ids=[result.evidence_id],
            )
            report.deduped += 1
            continue

        establishment_id = _mint_establishment(
            session,
            poi=poi,
            fingerprint=fingerprint,
            latitude=latitude,
            longitude=longitude,
            valid_from=observed_at,
        )
        assign_source_record(
            session,
            source_record_id=result.source_record_id,
            to_subject_id=establishment_id,
            decision=_decision(
                "overture-mint-assign", decided_at=decided_at, effective_at=observed_at
            ),
            evidence_ids=[result.evidence_id],
        )
        report.minted += 1
        report.minted_subject_ids.append(establishment_id)
    report.override_unmatched = sum(
        1 for gers, state in overrides.items() if state.entry is not None and gers not in seen
    )
    return report
