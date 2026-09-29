"""Conservative Overture projections and completion-gated absence (ADR-0012).

Commands flush; callers commit batches. The maintenance lock precedes the
lifecycle lock and Identity locks. Multi-command batches can still deadlock
with independent Identity writers; roll back and retry the whole batch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from apps.discovery.models import DiscoveryLifecycleState, DiscoveryReleaseCompletion
from apps.discovery.overture import OvertureConfig
from packages.helios_core.identity.commands import (
    create_establishment,
    create_organization,
    create_place,
    record_subject_change,
    refresh_subject_readiness,
    remap_source_record,
)
from packages.helios_core.identity.contracts import lock_subject_readiness_inputs
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    Organization,
    Place,
    Subject,
    SubjectChangeEvidence,
    SubjectCurrentness,
    SubjectLineage,
)
from packages.helios_core.identity.normalize import name_fingerprint, within_radius_m
from packages.helios_core.provenance.contracts import canonicalize_source_url
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.location_overrides import OverrideState
    from apps.discovery.overture import OverturePoi

RELOCATION_RADIUS_M = 50.0
MISSING_RELEASES = 2
COUNT_FLOOR = 0.9
FILTER_POLICY = "food-primary-or-restaurant-v1"


@dataclass
class LifecycleReport:
    updated: int = 0
    relocated: int = 0
    rebranded: int = 0
    closed: int = 0
    reopened: int = 0
    rehomed: int = 0
    retired: int = 0
    promoted: int = 0
    demoted: int = 0
    lifecycle_skipped: int = 0
    reasons: list[str] = field(default_factory=list)
    version_ids: list[int] = field(default_factory=list)
    closed_venues: list[tuple[int, str]] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.lifecycle_skipped += 1
        self.reasons.append(reason)


def lock_lifecycle(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock_shared(48454, 2)"))
    session.execute(text("SELECT pg_advisory_xact_lock(48454, 13)"))


def coverage(config: OvertureConfig) -> tuple[str, dict[str, object]]:
    value: dict[str, object] = {
        "bbox": asdict(config.bbox),
        "categories": sorted(set(config.food_categories)),
        "filter_policy": FILTER_POLICY,
    }
    key = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return key, value


def record_completion(
    session: Session,
    *,
    config: OvertureConfig,
    release_at: datetime,
    poi_count: int,
    expected_predecessor: str | None = None,
) -> None:
    """Call ONLY after iterator exhaustion and commit of all its observations.

    Conflicting retry counts/predecessors remain durable rows. Closure rejects
    the entire release if there is more than one claim, including on later runs.
    """
    lock_lifecycle(session)
    if release_at.utcoffset() is None or poi_count < 0:
        raise ValueError("completion requires an aware release instant and nonnegative count")
    key, value = coverage(config)
    endpoint = canonicalize_source_url(config.release)
    predecessor = canonicalize_source_url(expected_predecessor) if expected_predecessor else None
    session.execute(
        insert(DiscoveryReleaseCompletion)
        .values(
            release_endpoint=endpoint,
            release_at=release_at,
            coverage_key=key,
            coverage=value,
            poi_count=poi_count,
            predecessor=predecessor,
        )
        .on_conflict_do_nothing()
    )
    session.flush()


def winning_version(session: Session, record_id: int) -> SourceRecordVersion | None:
    rows = list(
        session.scalars(
            select(SourceRecordVersion)
            .join(Capture, Capture.id == SourceRecordVersion.capture_id)
            .where(
                SourceRecordVersion.source_record_id == record_id, Capture.outcome == "succeeded"
            )
            .order_by(SourceRecordVersion.observed_at.desc(), SourceRecordVersion.id)
        )
    )
    if not rows:
        return None
    latest = [v for v in rows if v.observed_at == rows[0].observed_at]
    if len({v.content_hash for v in latest}) != 1:
        return None
    return latest[0]


def overture_records(session: Session, subject_id: int) -> list[int]:
    return list(
        session.scalars(
            select(SourceRecord.id)
            .join(Source)
            .join(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
            .where(
                Source.namespace == "overture",
                CurrentResolution.state == "resolved",
                CurrentResolution.subject_id == subject_id,
            )
        )
    )


def _is_current(session: Session, subject_id: int) -> bool:
    return (
        session.scalar(
            select(SubjectCurrentness.is_current).where(SubjectCurrentness.subject_id == subject_id)
        )
        is True
    )


def _owned(session: Session, est: Establishment, record_id: int) -> bool:
    if overture_records(session, est.subject_id) != [record_id]:
        return False
    return (
        session.scalar(
            select(Establishment.subject_id)
            .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
            .where(
                SubjectCurrentness.is_current.is_(True),
                Establishment.subject_id != est.subject_id,
                Establishment.operating_status != "closed",
                or_(
                    Establishment.organization_subject_id == est.organization_subject_id,
                    Establishment.place_subject_id == est.place_subject_id,
                ),
            )
            .limit(1)
        )
        is None
    )


def _closure(session: Session, subject_id: int) -> DiscoveryLifecycleState | None:
    return session.scalar(
        select(DiscoveryLifecycleState)
        .where(
            DiscoveryLifecycleState.subject_id == subject_id,
            DiscoveryLifecycleState.action.in_(("closed", "reopened")),
        )
        .order_by(DiscoveryLifecycleState.id.desc())
        .limit(1)
    )


def project_observation(
    session: Session,
    *,
    poi: OverturePoi,
    record_id: int,
    version_id: int,
    evidence_id: int,
    decided_at: datetime,
    report: LifecycleReport,
    override: OverrideState | None = None,
    override_applied: bool = False,
) -> None:
    """Project the winning Overture Version onto its owned venue.

    ``poi`` is already at its effective location (ADR-0014). ``override`` is the
    record's latest override Version, if any; a Version not yet projected
    re-opens an already projected release, and ``override_applied`` says the
    point came from it.
    """
    from apps.discovery.pipeline import _decision, _to_decimal

    lock_lifecycle(session)
    version = winning_version(session, record_id)
    if version is None:
        report.skip(f"record {record_id}: conflicting latest release")
        return
    if version.id != version_id:
        return  # backfill or equivalent retry; never project an incoming older row
    resolution = session.get(CurrentResolution, record_id, populate_existing=True)
    if resolution is None or resolution.state != "resolved" or resolution.subject_id is None:
        return
    lock_subject_readiness_inputs(session, resolution.subject_id)
    est = session.get(Establishment, resolution.subject_id, populate_existing=True)
    if est is None or not _is_current(session, est.subject_id):
        return
    if not all(
        _is_current(session, p) for p in (est.organization_subject_id, est.place_subject_id)
    ):
        report.skip(f"venue {est.subject_id}: parent needs lifecycle re-home")
        return
    # Presence may reopen only the exact inferred closure, and only after its horizon.
    closure = _closure(session, est.subject_id)
    if est.operating_status == "closed":
        if (
            closure is None
            or closure.action != "closed"
            or est.valid_to != closure.first_missing_at
            or version.observed_at <= closure.release_at
        ):
            report.skip(f"venue {est.subject_id}: manual/historical closure or old presence")
            return
        est.operating_status, est.valid_to = "unknown", None
        session.add(
            DiscoveryLifecycleState(
                subject_id=est.subject_id,
                release_at=version.observed_at,
                source_record_id=record_id,
                version_id=version.id,
                action="reopened",
            )
        )
        report.reopened += 1
    checkpoint = session.scalar(
        select(func.max(DiscoveryLifecycleState.release_at)).where(
            DiscoveryLifecycleState.source_record_id == record_id,
            DiscoveryLifecycleState.action == "projected",
        )
    )
    projected = checkpoint is not None and version.observed_at <= checkpoint
    override_pending = (
        override is not None
        and session.scalar(
            select(DiscoveryLifecycleState.id)
            .where(
                DiscoveryLifecycleState.source_record_id == override.record_id,
                DiscoveryLifecycleState.version_id == override.version_id,
            )
            .limit(1)
        )
        is None
    )
    if projected and not override_pending:
        session.flush()
        return
    if not _owned(session, est, record_id):
        report.skip(f"venue {est.subject_id}: shared source or active parent")
        return
    org = session.get(Organization, est.organization_subject_id, populate_existing=True)
    place = session.get(Place, est.place_subject_id, populate_existing=True)
    if org is None or place is None:
        return
    if poi.address != place.address and any(
        v is None for v in (poi.latitude, poi.longitude, place.latitude, place.longitude)
    ):
        report.skip(f"venue {est.subject_id}: address change without comparable coordinates")
        return
    fp = name_fingerprint(poi.name)
    rebrand = fp != org.name_fingerprint
    relocate = (
        poi.latitude is not None
        and poi.longitude is not None
        and place.latitude is not None
        and place.longitude is not None
    ) and not within_radius_m(
        float(poi.latitude),
        float(poi.longitude),
        float(place.latitude),
        float(place.longitude),
        RELOCATION_RADIUS_M,
    )
    # ADR-0014: an override, or its withdrawal against the Overture Version the
    # venue already reflects (projected, or minted from it), corrects our data;
    # the venue did not move, so the change is in place.
    if override_applied or (
        override_pending and (projected or version.observed_at <= est.valid_from)
    ):
        relocate = False
    if (rebrand or relocate) and version.observed_at <= est.valid_from:
        report.skip(f"venue {est.subject_id}: transition would have empty effective interval")
        return
    target = est.subject_id
    if rebrand or relocate:
        org_id = (
            create_organization(session, canonical_name=poi.name.strip(), name_fingerprint=fp).id
            if rebrand
            else org.subject_id
        )
        place_id = (
            create_place(
                session,
                address=poi.address,
                latitude=_to_decimal(poi.latitude) if poi.latitude is not None else None,
                longitude=_to_decimal(poi.longitude) if poi.longitude is not None else None,
            ).id
            if relocate
            else place.subject_id
        )
        est.operating_status, est.valid_to = "closed", version.observed_at
        target = create_establishment(
            session,
            organization_subject_id=org_id,
            place_subject_id=place_id,
            valid_from=version.observed_at,
        ).id
        remap_source_record(
            session,
            source_record_id=record_id,
            from_subject_id=est.subject_id,
            to_subject_id=target,
            evidence_ids=[evidence_id],
            decision=_decision(
                "overture-lifecycle-rebrand" if rebrand else "overture-lifecycle-relocate",
                decided_at=decided_at,
                effective_at=version.observed_at,
            ),
        )
        report.rebranded += int(rebrand)
        report.relocated += int(relocate)
    # Update surviving parents too (e.g. a display correction plus relocation).
    changed = False
    if not rebrand and org.canonical_name != poi.name.strip():
        org.canonical_name = poi.name.strip()
        changed = True
    if not relocate:
        for attr, value in (
            ("address", poi.address),
            ("latitude", _to_decimal(poi.latitude) if poi.latitude is not None else place.latitude),
            (
                "longitude",
                _to_decimal(poi.longitude) if poi.longitude is not None else place.longitude,
            ),
        ):
            if value is not None and getattr(place, attr) != value:
                setattr(place, attr, value)
                changed = True
    report.updated += int(changed)
    report.version_ids.append(version.id)
    session.add(
        DiscoveryLifecycleState(
            subject_id=target,
            source_record_id=record_id,
            version_id=version.id,
            release_at=version.observed_at,
            action="projected",
        )
    )
    if override is not None and override_pending:
        session.add(
            DiscoveryLifecycleState(
                subject_id=target,
                source_record_id=override.record_id,
                version_id=override.version_id,
                release_at=version.observed_at,
                action="projected",
            )
        )
    session.flush()


def _successors(session: Session, parent: int) -> set[int]:
    if _is_current(session, parent):
        return {parent}
    # Traverse lineage rather than assuming the merge's first survivor stayed current.
    found: set[int] = set()
    pending, seen = [parent], set()
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        for successor in session.scalars(
            select(SubjectLineage.successor_subject_id).where(
                SubjectLineage.predecessor_subject_id == item
            )
        ):
            if _is_current(session, successor):
                found.add(successor)
            else:
                pending.append(successor)
    return found


def _rehome(
    session: Session, est: Establishment, *, decided_at: datetime, report: LifecycleReport
) -> None:
    from apps.discovery.pipeline import _decision

    parents = (est.organization_subject_id, est.place_subject_id)
    if all(_is_current(session, parent) for parent in parents):
        return
    records = list(
        session.scalars(
            select(CurrentResolution.source_record_id).where(
                CurrentResolution.subject_id == est.subject_id,
                CurrentResolution.state == "resolved",
            )
        )
    )
    evidence: list[int] = []
    for record_id in records:
        version = winning_version(session, record_id)
        if version is not None:
            evidence.extend(
                session.scalars(
                    select(Evidence.id).where(Evidence.source_record_version_id == version.id)
                )
            )
    evidence.extend(
        session.scalars(
            select(SubjectChangeEvidence.evidence_id)
            .join(
                SubjectCurrentness,
                SubjectCurrentness.retired_by_change_id == SubjectChangeEvidence.subject_change_id,
            )
            .where(SubjectCurrentness.subject_id.in_(parents))
        )
    )
    evidence = list(dict.fromkeys(evidence))
    if not evidence:
        report.skip(f"venue {est.subject_id}: no Version Evidence for parent transition")
        return
    orgs, places = (_successors(session, p) for p in parents)
    if len(orgs) != 1 or len(places) != 1:
        record_subject_change(
            session,
            operation="retire",
            input_subject_ids=[est.subject_id],
            output_subject_ids=[],
            evidence_ids=evidence,
            decision=_decision(
                "overture-lifecycle-retire", decided_at=decided_at, effective_at=decided_at
            ),
        )
        report.retired += 1
        return
    successor = create_establishment(
        session,
        organization_subject_id=next(iter(orgs)),
        place_subject_id=next(iter(places)),
        valid_from=est.valid_from,
        valid_to=est.valid_to,
        operating_status=est.operating_status,
    )
    decision = _decision(
        "overture-lifecycle-rehome", decided_at=decided_at, effective_at=decided_at
    )
    for record in records:
        remap_source_record(
            session,
            source_record_id=record,
            from_subject_id=est.subject_id,
            to_subject_id=successor.id,
            evidence_ids=evidence,
            decision=decision,
        )
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[est.subject_id, successor.id],
        output_subject_ids=[successor.id],
        evidence_ids=evidence,
        decision=decision,
    )
    # Retain inferred closure origin through a parent re-home.
    closure = _closure(session, est.subject_id)
    if closure and closure.action == "closed" and est.valid_to == closure.first_missing_at:
        session.add(
            DiscoveryLifecycleState(
                subject_id=successor.id,
                action="closed",
                release_at=closure.release_at,
                first_missing_at=closure.first_missing_at,
            )
        )
    report.rehomed += 1


def refresh_readiness(
    session: Session,
    *,
    report: LifecycleReport,
    organization_id: int | None = None,
    batch_size: int = 100,
    on_batch: Callable[[], None] | None = None,
) -> None:
    """Parents before children; called by lifecycle and immediately after URL writes."""
    subjects = (
        select(Subject)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Subject.id)
        .where(SubjectCurrentness.is_current.is_(True))
    )
    if organization_id is not None:
        estates = list(
            session.scalars(
                select(Establishment).where(
                    Establishment.organization_subject_id == organization_id
                )
            )
        )
        ids = {
            organization_id,
            *(e.subject_id for e in estates),
            *(e.place_subject_id for e in estates),
        }
        subjects = subjects.where(Subject.id.in_(ids))
    rows = list(session.scalars(subjects))
    for n, subject in enumerate(sorted(rows, key=lambda s: (s.kind == "establishment", s.id)), 1):
        before = subject.readiness
        after = refresh_subject_readiness(session, subject.id).readiness
        report.promoted += int(before != after and after == "eligible")
        report.demoted += int(before != after and after == "provisional")
        if on_batch and n % batch_size == 0:
            on_batch()
            lock_lifecycle(session)


def _closure_window(
    session: Session, release: str, report: LifecycleReport
) -> list[DiscoveryReleaseCompletion]:
    key, _ = coverage(OvertureConfig())
    rows = list(
        session.scalars(
            select(DiscoveryReleaseCompletion)
            .where(DiscoveryReleaseCompletion.coverage_key == key)
            .order_by(DiscoveryReleaseCompletion.release_at.desc())
        )
    )
    endpoint = canonicalize_source_url(release)
    if not rows or rows[0].release_endpoint != endpoint:
        report.reasons.append("closure veto: absent full-coverage completion or old release")
        return []
    window: list[DiscoveryReleaseCompletion] = []
    for row in rows:
        if window and row.release_at == window[-1].release_at:
            report.reasons.append("closure veto: conflicting completion claims")
            return []
        window.append(row)
        if len(window) == MISSING_RELEASES + 1:
            # Also detect another claim at the baseline instant.
            if sum(r.release_at == row.release_at for r in rows) != 1:
                report.reasons.append("closure veto: conflicting baseline")
                return []
            break
    if len(window) != MISSING_RELEASES + 1:
        report.reasons.append("closure veto: two completed successors after baseline required")
        return []
    for newer, older in zip(window, window[1:], strict=False):
        if (
            newer.predecessor != older.release_endpoint
            or newer.poi_count < older.poi_count * COUNT_FLOOR
        ):
            report.reasons.append("closure veto: unknown/skipped predecessor or count anomaly")
            return []
    return window


def _close_missing(
    session: Session,
    release: str,
    report: LifecycleReport,
    *,
    batch_size: int,
    on_batch: Callable[[], None] | None,
) -> None:
    window = _closure_window(session, release, report)
    if not window:
        return
    newest, first_missing, baseline = window
    candidates = list(
        session.scalars(
            select(Establishment.subject_id)
            .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
            .where(
                SubjectCurrentness.is_current.is_(True), Establishment.operating_status != "closed"
            )
        )
    )
    for n, subject_id in enumerate(candidates, 1):
        if on_batch and n > 1 and (n - 1) % batch_size == 0:
            on_batch()
            lock_lifecycle(session)
            if not _closure_window(session, release, report):
                return
        lock_subject_readiness_inputs(session, subject_id)
        est = session.get(Establishment, subject_id, populate_existing=True)
        if (
            est is None
            or not _is_current(session, subject_id)
            or est.operating_status == "closed"
            or est.valid_to is not None
        ):
            continue
        records = overture_records(session, est.subject_id)
        if not records or est.valid_from >= first_missing.release_at:
            continue
        # ANY version proves presence, including rejected rows. Only successful
        # observations may change features; rejected observations must not cause closure.
        versions = session.execute(
            select(SourceRecordVersion.observed_at, SourceEndpoint.canonical_uri)
            .join(Capture, Capture.id == SourceRecordVersion.capture_id)
            .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
            .where(SourceRecordVersion.source_record_id.in_(records))
        ).all()
        if not versions or any(v.observed_at >= first_missing.release_at for v in versions):
            continue
        # No retroactive baseline for records never observed in a completed survey.
        if not any(
            v.observed_at == baseline.release_at and v.canonical_uri == baseline.release_endpoint
            for v in versions
        ):
            continue
        lock_subject_readiness_inputs(session, est.subject_id)
        est.operating_status, est.valid_to = "closed", first_missing.release_at
        session.add(
            DiscoveryLifecycleState(
                subject_id=est.subject_id,
                action="closed",
                release_at=newest.release_at,
                first_missing_at=first_missing.release_at,
            )
        )
        report.closed += 1
        report.closed_venues.append(
            (est.subject_id, max(v.observed_at for v in versions).isoformat())
        )
    session.flush()


def run_lifecycle(
    session: Session,
    *,
    release: str,
    decided_at: datetime,
    batch_size: int = 100,
    on_batch: Callable[[], None] | None = None,
) -> LifecycleReport:
    report = LifecycleReport()
    lock_lifecycle(session)
    ids = list(
        session.scalars(
            select(Establishment.subject_id)
            .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
            .where(SubjectCurrentness.is_current.is_(True))
        )
    )
    for n, subject_id in enumerate(ids, 1):
        with session.begin_nested():
            lock_subject_readiness_inputs(session, subject_id)
            est = session.get(Establishment, subject_id, populate_existing=True)
            if est is not None:
                _rehome(session, est, decided_at=decided_at, report=report)
        if on_batch and n % batch_size == 0:
            on_batch()
            lock_lifecycle(session)
    _close_missing(session, release, report, batch_size=batch_size, on_batch=on_batch)
    refresh_readiness(session, report=report, batch_size=batch_size, on_batch=on_batch)
    return report
