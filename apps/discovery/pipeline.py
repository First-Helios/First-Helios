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
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

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
from packages.helios_core.provenance.contracts import BronzeObservation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.overture import OverturePoi
    from packages.helios_core.geo import NominatimClient

DEFAULT_DEDUPE_RADIUS_M = 50.0
_COORD_QUANTUM = Decimal("0.000001")  # Place stores Numeric(9, 6)


@dataclass(slots=True)
class DiscoveryReport:
    """Counts from one discovery run; totals reconcile to ``fetched``."""

    fetched: int = 0
    reused: int = 0
    minted: int = 0
    deduped: int = 0
    ambiguous: int = 0
    needs_review: int = 0
    skipped: int = 0
    geocoded: int = 0
    minted_subject_ids: list[int] = field(default_factory=list)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _observation(poi: OverturePoi, *, observed_at: datetime, release: str) -> BronzeObservation:
    payload_json = json.dumps(poi.raw, sort_keys=True, default=str)
    content_hash = _sha(payload_json)
    excerpt = f"{poi.name}\x1f{poi.primary_category or ''}"
    return BronzeObservation(
        source_namespace="overture",
        source_kind="poi_snapshot",
        external_key=poi.gers_id,
        observed_at=observed_at,
        content_hash=content_hash,
        source_payload=poi.raw,
        evidence_locator=f"overture:place:{poi.gers_id}",
        evidence_excerpt_hash=_sha(excerpt),
        # No canonical_url: a brand website is not an Establishment identity key.
        canonical_url=None,
        endpoint_kind="https",
        capture_content_hash=content_hash,
        bundle_path=release,
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
    rows = session.execute(
        select(Establishment.subject_id, Place.latitude, Place.longitude)
        .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
        .join(Place, Place.subject_id == Establishment.place_subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .where(
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
) -> DiscoveryReport:
    """Admit POIs to Bronze and resolve/mint/dedupe them. Flushes; caller commits.

    ``on_batch`` (the CLI passes ``session.commit``) runs after every
    ``batch_size`` POIs, bounding what one crash (e.g. a Nominatim error) can lose.
    """
    report = DiscoveryReport()
    for poi in pois:
        if on_batch is not None and report.fetched and report.fetched % batch_size == 0:
            on_batch()
        report.fetched += 1
        name = poi.name.strip()
        if not name:
            report.skipped += 1
            continue

        result = resolve_source_record_observation(
            session,
            observation=_observation(poi, observed_at=observed_at, release=release),
            decided_at=decided_at,
        )
        if result.state == "resolved":
            report.reused += 1
            continue
        if result.state == "needs_review":
            report.needs_review += 1
            continue

        fingerprint = name_fingerprint(name) or name
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
    return report
