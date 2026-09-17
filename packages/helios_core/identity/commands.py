"""Transactional commands published by the shared Identity module.

Commands flush but never commit.  The caller owns the surrounding transaction,
which lets provenance, identity, and a future vertical write atomically.
Database triggers repeat the transition and lineage checks so bypassing these
commands cannot bypass an invariant.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from packages.helios_core.identity.contracts import (
    DeterministicResolutionResult,
    SubjectNotEligibleError,
    lock_subject_readiness_inputs,
    subject_meets_readiness_policy,
)
from packages.helios_core.identity.models import (
    Adjudication,
    CurrentResolution,
    Establishment,
    Organization,
    Place,
    ResolutionEvent,
    ResolutionEvidence,
    Subject,
    SubjectChange,
    SubjectChangeEvidence,
    SubjectChangeMember,
    SubjectCurrentness,
    SubjectLineage,
)
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    lock_source_record,
    persist_source_record_observation,
    source_record_ids_for_canonical_url,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class DecisionMetadata:
    """Audit fields required on every Identity decision."""

    confidence: Decimal
    method: str
    method_version: str
    actor_class: str
    decided_at: datetime
    effective_at: datetime

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("decision confidence must be between 0 and 1")
        if not self.method or self.method != self.method.strip():
            raise ValueError("decision method must be nonblank and trimmed")
        if not self.method_version or self.method_version != self.method_version.strip():
            raise ValueError("decision method_version must be nonblank and trimmed")
        if self.actor_class not in {"rule", "model", "migration", "human"}:
            raise ValueError("decision actor_class is not allowed")


def _lock_identity_maintenance(session: Session) -> None:
    """Coordinate Identity writes with an exclusive projection rebuild."""
    session.execute(text("SELECT pg_advisory_xact_lock_shared(48454, 2)"))


def create_place(
    session: Session,
    *,
    address: str | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
) -> Subject:
    """Create a provisional Place Subject and its required typed grain."""
    _lock_identity_maintenance(session)
    subject = Subject(kind="place")
    session.add(subject)
    session.flush()
    session.add(
        Place(
            subject_id=subject.id,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )
    )
    session.flush()
    return subject


def create_organization(
    session: Session,
    *,
    canonical_name: str | None = None,
    name_fingerprint: str | None = None,
    organization_kind: str = "operating_identity",
) -> Subject:
    """Create a provisional Organization Subject and its typed grain."""
    _lock_identity_maintenance(session)
    subject = Subject(kind="organization")
    session.add(subject)
    session.flush()
    session.add(
        Organization(
            subject_id=subject.id,
            canonical_name=canonical_name,
            name_fingerprint=name_fingerprint,
            organization_kind=organization_kind,
        )
    )
    session.flush()
    return subject


def create_establishment(
    session: Session,
    *,
    organization_subject_id: int,
    place_subject_id: int,
    valid_from: datetime,
    valid_to: datetime | None = None,
    operating_status: str = "unknown",
) -> Subject:
    """Create a provisional Establishment linking typed Organization/Place."""
    _lock_identity_maintenance(session)
    subject = Subject(kind="establishment")
    session.add(subject)
    session.flush()
    session.add(
        Establishment(
            subject_id=subject.id,
            organization_subject_id=organization_subject_id,
            place_subject_id=place_subject_id,
            valid_from=valid_from,
            valid_to=valid_to,
            operating_status=operating_status,
        )
    )
    session.flush()
    return subject


def mark_subject_eligible(session: Session, subject_id: int) -> Subject:
    """Mark a current Subject eligible only after the Step 4 feature policy."""
    _lock_identity_maintenance(session)
    subject, currentness, locked_subject_ids = lock_subject_readiness_inputs(
        session,
        subject_id,
    )
    if subject is None or currentness is None or not currentness.is_current:
        raise SubjectNotEligibleError(f"Subject {subject_id} is missing or retired")
    if not subject_meets_readiness_policy(
        session,
        subject_id,
        lock_features=True,
        locked_subject_ids=locked_subject_ids,
    ):
        raise SubjectNotEligibleError(
            f"Subject {subject_id} lacks meaningful typed identity features"
        )
    subject.readiness = "eligible"
    session.flush()
    return subject


def _refresh_subject_readiness(session: Session, subject_id: int) -> None:
    """Keep stored readiness aligned with the current typed feature policy."""
    subject = session.get(Subject, subject_id)
    if subject is None or subject.kind != "organization":
        return
    readiness = (
        "eligible"
        if subject_meets_readiness_policy(
            session,
            subject_id,
            lock_features=True,
        )
        else "provisional"
    )
    if subject.readiness != readiness:
        subject.readiness = readiness
        session.flush()


def create_adjudication(
    session: Session,
    *,
    actor: str,
    rationale: str,
    decided_at: datetime,
) -> Adjudication:
    """Append immutable human rationale for one or more decisions."""
    if not actor or actor != actor.strip():
        raise ValueError("adjudication actor must be nonblank and trimmed")
    if not rationale or rationale != rationale.strip() or len(rationale) > 4000:
        raise ValueError(
            "adjudication rationale must be nonblank, trimmed, and at most 4000 characters"
        )
    adjudication = Adjudication(
        actor=actor,
        rationale=rationale,
        decided_at=decided_at,
    )
    session.add(adjudication)
    session.flush()
    return adjudication


def _lock_source_resolution(session: Session, source_record_id: int) -> None:
    if not lock_source_record(session, source_record_id):
        raise ValueError(f"Source Record {source_record_id} does not exist")


def _require_decision_support(
    evidence_ids: Sequence[int],
    adjudication_id: int | None,
) -> None:
    if not evidence_ids and adjudication_id is None:
        raise ValueError("an Identity decision requires Evidence or Adjudication")


def _lock_resolution_subjects(
    session: Session,
    from_subject_id: int | None,
    to_subject_id: int | None,
) -> None:
    subject_ids = sorted(
        subject_id for subject_id in {from_subject_id, to_subject_id} if subject_id is not None
    )
    if subject_ids:
        session.execute(
            select(Subject.id)
            .where(Subject.id.in_(subject_ids))
            .order_by(Subject.id)
            .with_for_update()
        )


def _validate_resolution_transition(
    session: Session,
    *,
    source_record_id: int,
    operation: str,
    from_subject_id: int | None,
    to_subject_id: int | None,
) -> None:
    current = session.execute(
        select(CurrentResolution.state, CurrentResolution.subject_id).where(
            CurrentResolution.source_record_id == source_record_id
        )
    ).one_or_none()

    if to_subject_id is not None:
        target_is_current = session.scalar(
            select(SubjectCurrentness.is_current)
            .where(SubjectCurrentness.subject_id == to_subject_id)
            .with_for_update(read=True)
        )
        if target_is_current is not True:
            raise ValueError(f"resolution target Subject {to_subject_id} is not current")

    if operation == "open":
        if current is not None:
            raise ValueError(f"Source Record {source_record_id} is already in resolution")
    elif operation == "assign":
        if (
            current is None
            or current.state not in {"unresolved", "needs_review"}
            or current.subject_id is not None
        ):
            raise ValueError("assign requires unresolved or needs_review current state")
    elif operation in {"remap", "unassign"}:
        if current is None or current.state != "resolved" or current.subject_id != from_subject_id:
            raise ValueError(f"{operation} must name the current Subject")
        if operation == "remap" and from_subject_id == to_subject_id:
            raise ValueError("remap requires a different target Subject")
    else:  # pragma: no cover - private callers use the four fixed operations
        raise ValueError(f"unknown resolution operation {operation!r}")


def _record_resolution(
    session: Session,
    *,
    source_record_id: int,
    operation: str,
    from_subject_id: int | None,
    to_subject_id: int | None,
    decision: DecisionMetadata,
    evidence_ids: Sequence[int],
    adjudication_id: int | None,
) -> ResolutionEvent:
    _require_decision_support(evidence_ids, adjudication_id)
    _lock_identity_maintenance(session)
    _lock_resolution_subjects(session, from_subject_id, to_subject_id)
    _lock_source_resolution(session, source_record_id)
    _validate_resolution_transition(
        session,
        source_record_id=source_record_id,
        operation=operation,
        from_subject_id=from_subject_id,
        to_subject_id=to_subject_id,
    )
    event = ResolutionEvent(
        source_record_id=source_record_id,
        operation=operation,
        from_subject_id=from_subject_id,
        to_subject_id=to_subject_id,
        adjudication_id=adjudication_id,
        confidence=decision.confidence,
        method=decision.method,
        method_version=decision.method_version,
        actor_class=decision.actor_class,
        decided_at=decision.decided_at,
        effective_at=decision.effective_at,
    )
    session.add(event)
    session.flush()
    session.add_all(
        ResolutionEvidence(
            resolution_event_id=event.id,
            evidence_id=evidence_id,
        )
        for evidence_id in dict.fromkeys(evidence_ids)
    )
    session.flush()
    for subject_id in sorted(
        subject_id for subject_id in {from_subject_id, to_subject_id} if subject_id is not None
    ):
        _refresh_subject_readiness(session, subject_id)
    return event


def admit_source_record(
    session: Session,
    *,
    source_record_id: int,
    decision: DecisionMetadata,
    evidence_ids: Sequence[int] = (),
    adjudication_id: int | None = None,
) -> ResolutionEvent:
    """Append Open and materialize explicit indexed ``unresolved`` state."""
    return _record_resolution(
        session,
        source_record_id=source_record_id,
        operation="open",
        from_subject_id=None,
        to_subject_id=None,
        decision=decision,
        evidence_ids=evidence_ids,
        adjudication_id=adjudication_id,
    )


def assign_source_record(
    session: Session,
    *,
    source_record_id: int,
    to_subject_id: int,
    decision: DecisionMetadata,
    evidence_ids: Sequence[int] = (),
    adjudication_id: int | None = None,
) -> ResolutionEvent:
    """Assign an unresolved or needs-review record to a current Subject."""
    return _record_resolution(
        session,
        source_record_id=source_record_id,
        operation="assign",
        from_subject_id=None,
        to_subject_id=to_subject_id,
        decision=decision,
        evidence_ids=evidence_ids,
        adjudication_id=adjudication_id,
    )


def remap_source_record(
    session: Session,
    *,
    source_record_id: int,
    from_subject_id: int,
    to_subject_id: int,
    decision: DecisionMetadata,
    evidence_ids: Sequence[int] = (),
    adjudication_id: int | None = None,
) -> ResolutionEvent:
    """Move a resolved record from its named current Subject to another."""
    return _record_resolution(
        session,
        source_record_id=source_record_id,
        operation="remap",
        from_subject_id=from_subject_id,
        to_subject_id=to_subject_id,
        decision=decision,
        evidence_ids=evidence_ids,
        adjudication_id=adjudication_id,
    )


def unassign_source_record(
    session: Session,
    *,
    source_record_id: int,
    from_subject_id: int,
    decision: DecisionMetadata,
    evidence_ids: Sequence[int] = (),
    adjudication_id: int | None = None,
) -> ResolutionEvent:
    """Remove a known-wrong mapping and expose ``needs_review`` state."""
    return _record_resolution(
        session,
        source_record_id=source_record_id,
        operation="unassign",
        from_subject_id=from_subject_id,
        to_subject_id=None,
        decision=decision,
        evidence_ids=evidence_ids,
        adjudication_id=adjudication_id,
    )


def _deterministic_decision(
    *,
    method: str,
    decided_at: datetime,
    effective_at: datetime,
) -> DecisionMetadata:
    return DecisionMetadata(
        confidence=Decimal("1"),
        method=method,
        method_version="1",
        actor_class="rule",
        decided_at=decided_at,
        effective_at=effective_at,
    )


def _current_subject_ids_for_source_records(
    session: Session,
    source_record_ids: Sequence[int],
) -> tuple[int, ...]:
    if not source_record_ids:
        return ()
    subject_ids = session.scalars(
        select(CurrentResolution.subject_id)
        .join(
            SubjectCurrentness,
            SubjectCurrentness.subject_id == CurrentResolution.subject_id,
        )
        .where(
            CurrentResolution.source_record_id.in_(source_record_ids),
            CurrentResolution.state == "resolved",
            CurrentResolution.subject_id.is_not(None),
            SubjectCurrentness.is_current,
        )
        .distinct()
        .order_by(CurrentResolution.subject_id)
    )
    return tuple(subject_id for subject_id in subject_ids if subject_id is not None)


def _current_lineage_successor_ids(
    session: Session,
    subject_id: int,
) -> tuple[int, ...]:
    """Return every current terminal successor reachable from a retired Subject."""
    successors = (
        select(SubjectLineage.successor_subject_id.label("subject_id"))
        .where(SubjectLineage.predecessor_subject_id == subject_id)
        .cte("lineage_successors", recursive=True)
    )
    successors = successors.union(
        select(SubjectLineage.successor_subject_id).join(
            successors,
            SubjectLineage.predecessor_subject_id == successors.c.subject_id,
        )
    )
    statement = (
        select(successors.c.subject_id)
        .join(
            SubjectCurrentness,
            SubjectCurrentness.subject_id == successors.c.subject_id,
        )
        .where(SubjectCurrentness.is_current)
        .distinct()
        .order_by(successors.c.subject_id)
    )
    return tuple(session.scalars(statement))


def _lock_resolution_subjects_for_update(
    session: Session,
    subject_ids: Sequence[int],
) -> set[int]:
    if not subject_ids:
        return set()
    return set(
        session.scalars(
            select(Subject.id)
            .where(Subject.id.in_(sorted(set(subject_ids))))
            .order_by(Subject.id)
            .with_for_update()
        )
    )


def resolve_source_record_observation(
    session: Session,
    *,
    observation: BronzeObservation,
    decided_at: datetime,
) -> DeterministicResolutionResult:
    """Persist Bronze first, then apply exact-key/URL resolution atomically.

    Existing ``(source, external_key)`` resolution always wins.  URL-only
    assignment is allowed only when the exact canonical endpoint currently
    identifies one distinct current Subject.  Ambiguous or unmatched records
    remain explicitly unresolved, and a prior unassignment remains
    ``needs_review`` until a caller makes an explicit assignment decision.
    """
    persisted = persist_source_record_observation(session, observation)

    # The provenance command holds the endpoint's NO KEY UPDATE lock when a
    # URL is present. That prevents another deterministic resolver from
    # adding a same-URL record while this transaction selects its lock set.
    # Read likely targets before Source Record locks so every Identity writer
    # retains the established Subject -> Source Record ordering.
    prior = session.get(CurrentResolution, persisted.source_record_id)
    url_source_record_ids: tuple[int, ...] = ()
    url_target_id: int | None = None
    if persisted.canonical_url is not None and (prior is None or prior.state == "unresolved"):
        url_source_record_ids = source_record_ids_for_canonical_url(
            session, persisted.canonical_url
        )
        url_subject_ids = _current_subject_ids_for_source_records(session, url_source_record_ids)
        if len(url_subject_ids) == 1:
            url_target_id = url_subject_ids[0]

    retired_successor_ids: tuple[int, ...] = ()
    if prior is not None and prior.state == "resolved" and prior.subject_id is not None:
        prior_is_current = session.scalar(
            select(SubjectCurrentness.is_current).where(
                SubjectCurrentness.subject_id == prior.subject_id
            )
        )
        if prior_is_current is False:
            retired_successor_ids = _current_lineage_successor_ids(session, prior.subject_id)

    subjects_to_lock = {
        subject_id
        for subject_id in (
            *retired_successor_ids,
            prior.subject_id if prior is not None and prior.state == "resolved" else None,
            url_target_id,
        )
        if subject_id is not None
    }
    _lock_identity_maintenance(session)
    locked_subject_ids = _lock_resolution_subjects_for_update(session, sorted(subjects_to_lock))
    # Explicit assign/remap/unassign commands lock their owning Source Record.
    # Lock every record observed at this URL in stable order so none can
    # introduce a second Subject between the uniqueness check and URL assign.
    source_record_ids_to_lock = sorted(set(url_source_record_ids) | {persisted.source_record_id})
    for source_record_id in source_record_ids_to_lock:
        _lock_source_resolution(session, source_record_id)
    current = session.scalar(
        select(CurrentResolution)
        .where(CurrentResolution.source_record_id == persisted.source_record_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    appended_event_ids: list[int] = []
    if current is not None and current.state == "resolved":
        subject_id = current.subject_id
        subject_is_current = (
            session.scalar(
                select(SubjectCurrentness.is_current).where(
                    SubjectCurrentness.subject_id == subject_id
                )
            )
            if subject_id is not None
            else False
        )
        if subject_id is not None and subject_is_current and subject_id in locked_subject_ids:
            _refresh_subject_readiness(session, subject_id)
            return DeterministicResolutionResult(
                source_id=persisted.source_id,
                source_record_id=persisted.source_record_id,
                source_record_version_id=persisted.source_record_version_id,
                capture_id=persisted.capture_id,
                evidence_id=persisted.evidence_id,
                state="resolved",
                subject_id=subject_id,
                match_basis="external_key",
                appended_event_ids=(),
                source_record_created=persisted.source_record_created,
                observation_created=persisted.observation_created,
            )

        if subject_id is None:
            raise RuntimeError("resolved projection has no Subject")
        stable_successors = _current_lineage_successor_ids(session, subject_id)
        if len(stable_successors) == 1 and stable_successors[0] in locked_subject_ids:
            successor_id = stable_successors[0]
            remapped = remap_source_record(
                session,
                source_record_id=persisted.source_record_id,
                from_subject_id=subject_id,
                to_subject_id=successor_id,
                decision=_deterministic_decision(
                    method="exact-key-lineage-successor",
                    decided_at=decided_at,
                    effective_at=observation.observed_at,
                ),
                evidence_ids=[persisted.evidence_id],
            )
            return DeterministicResolutionResult(
                source_id=persisted.source_id,
                source_record_id=persisted.source_record_id,
                source_record_version_id=persisted.source_record_version_id,
                capture_id=persisted.capture_id,
                evidence_id=persisted.evidence_id,
                state="resolved",
                subject_id=successor_id,
                match_basis="external_key_lineage",
                appended_event_ids=(remapped.id,),
                source_record_created=persisted.source_record_created,
                observation_created=persisted.observation_created,
            )

        unassigned = unassign_source_record(
            session,
            source_record_id=persisted.source_record_id,
            from_subject_id=subject_id,
            decision=_deterministic_decision(
                method="exact-key-retired-subject",
                decided_at=decided_at,
                effective_at=observation.observed_at,
            ),
            evidence_ids=[persisted.evidence_id],
        )
        return DeterministicResolutionResult(
            source_id=persisted.source_id,
            source_record_id=persisted.source_record_id,
            source_record_version_id=persisted.source_record_version_id,
            capture_id=persisted.capture_id,
            evidence_id=persisted.evidence_id,
            state="needs_review",
            subject_id=None,
            match_basis=None,
            appended_event_ids=(unassigned.id,),
            source_record_created=persisted.source_record_created,
            observation_created=persisted.observation_created,
        )

    if current is not None and current.state == "needs_review":
        return DeterministicResolutionResult(
            source_id=persisted.source_id,
            source_record_id=persisted.source_record_id,
            source_record_version_id=persisted.source_record_version_id,
            capture_id=persisted.capture_id,
            evidence_id=persisted.evidence_id,
            state="needs_review",
            subject_id=None,
            match_basis=None,
            appended_event_ids=(),
            source_record_created=persisted.source_record_created,
            observation_created=persisted.observation_created,
        )

    if current is None:
        opened = admit_source_record(
            session,
            source_record_id=persisted.source_record_id,
            decision=_deterministic_decision(
                method="deterministic-admission",
                decided_at=decided_at,
                effective_at=observation.observed_at,
            ),
            evidence_ids=[persisted.evidence_id],
        )
        appended_event_ids.append(opened.id)

    # Re-check after all URL-associated Source Record locks. Only the one
    # Subject locked before those records may be used; a changed, newly
    # ambiguous, or unexpectedly expanded candidate set remains unresolved.
    stable_url_target_id: int | None = None
    if url_target_id is not None and persisted.canonical_url is not None:
        current_url_source_record_ids = source_record_ids_for_canonical_url(
            session,
            persisted.canonical_url,
        )
        current_url_subject_ids = _current_subject_ids_for_source_records(
            session,
            current_url_source_record_ids,
        )
        if current_url_source_record_ids == url_source_record_ids and current_url_subject_ids == (
            url_target_id,
        ):
            stable_url_target_id = url_target_id

    if stable_url_target_id is not None:
        assigned = assign_source_record(
            session,
            source_record_id=persisted.source_record_id,
            to_subject_id=stable_url_target_id,
            decision=_deterministic_decision(
                method="exact-canonical-url",
                decided_at=decided_at,
                effective_at=observation.observed_at,
            ),
            evidence_ids=[persisted.evidence_id],
        )
        appended_event_ids.append(assigned.id)
        _refresh_subject_readiness(session, stable_url_target_id)
        state = "resolved"
        subject_id = stable_url_target_id
        match_basis = "canonical_url"
    else:
        state = "unresolved"
        subject_id = None
        match_basis = None

    return DeterministicResolutionResult(
        source_id=persisted.source_id,
        source_record_id=persisted.source_record_id,
        source_record_version_id=persisted.source_record_version_id,
        capture_id=persisted.capture_id,
        evidence_id=persisted.evidence_id,
        state=state,
        subject_id=subject_id,
        match_basis=match_basis,
        appended_event_ids=tuple(appended_event_ids),
        source_record_created=persisted.source_record_created,
        observation_created=persisted.observation_created,
    )


def _validate_subject_change_shape(
    operation: str,
    input_subject_ids: Sequence[int],
    output_subject_ids: Sequence[int],
) -> None:
    if len(set(input_subject_ids)) != len(input_subject_ids) or len(set(output_subject_ids)) != len(
        output_subject_ids
    ):
        raise ValueError("Subject-change members must be distinct within each role")

    input_count = len(input_subject_ids)
    output_count = len(output_subject_ids)
    if operation == "merge":
        valid = input_count >= 2 and output_count == 1
    elif operation == "split":
        valid = input_count == 1 and output_count >= 2
        if set(input_subject_ids) & set(output_subject_ids):
            raise ValueError("split outputs must be distinct from the input")
    elif operation == "retire":
        valid = input_count == 1 and output_count == 0
    else:
        raise ValueError(f"unknown Subject-change operation {operation!r}")
    if not valid:
        raise ValueError(
            f"invalid {operation} member cardinality: {input_count} inputs, {output_count} outputs"
        )


def record_subject_change(
    session: Session,
    *,
    operation: str,
    input_subject_ids: Sequence[int],
    output_subject_ids: Sequence[int],
    decision: DecisionMetadata,
    evidence_ids: Sequence[int] = (),
    adjudication_id: int | None = None,
) -> SubjectChange:
    """Append and atomically apply a merge, split, or retirement.

    Locking every member in stable ID order prevents two overlapping changes
    from observing each other's inputs as current.
    """
    _require_decision_support(evidence_ids, adjudication_id)
    _validate_subject_change_shape(
        operation,
        input_subject_ids,
        output_subject_ids,
    )
    _lock_identity_maintenance(session)
    member_ids = sorted(set(input_subject_ids) | set(output_subject_ids))
    subjects = list(
        session.scalars(
            select(Subject).where(Subject.id.in_(member_ids)).order_by(Subject.id).with_for_update()
        )
    )
    by_id = {subject.id: subject for subject in subjects}
    missing = set(member_ids) - set(by_id)
    if missing:
        raise ValueError(f"Unknown Subject members: {sorted(missing)}")
    if len({subject.kind for subject in subjects}) != 1:
        raise ValueError("a Subject change must contain one Subject kind")

    currentness_rows = list(
        session.scalars(
            select(SubjectCurrentness)
            .where(SubjectCurrentness.subject_id.in_(member_ids))
            .order_by(SubjectCurrentness.subject_id)
            .with_for_update()
        )
    )
    currentness_by_id = {row.subject_id: row for row in currentness_rows}
    invalid_inputs = [
        subject_id
        for subject_id in input_subject_ids
        if subject_id not in currentness_by_id or not currentness_by_id[subject_id].is_current
    ]
    if invalid_inputs:
        raise ValueError(f"every Subject-change input must be current: {sorted(invalid_inputs)}")
    invalid_members = [
        subject_id
        for subject_id in member_ids
        if subject_id not in currentness_by_id or not currentness_by_id[subject_id].is_current
    ]
    if invalid_members:
        raise ValueError(f"every Subject-change member must be current: {sorted(invalid_members)}")

    change = SubjectChange(
        operation=operation,
        adjudication_id=adjudication_id,
        confidence=decision.confidence,
        method=decision.method,
        method_version=decision.method_version,
        actor_class=decision.actor_class,
        decided_at=decision.decided_at,
        effective_at=decision.effective_at,
    )
    session.add(change)
    session.flush()

    for role, ids in (
        ("input", dict.fromkeys(input_subject_ids)),
        ("output", dict.fromkeys(output_subject_ids)),
    ):
        session.add_all(
            SubjectChangeMember(
                subject_change_id=change.id,
                subject_id=subject_id,
                subject_kind=by_id[subject_id].kind,
                role=role,
            )
            for subject_id in ids
        )
    session.add_all(
        SubjectChangeEvidence(
            subject_change_id=change.id,
            evidence_id=evidence_id,
        )
        for evidence_id in dict.fromkeys(evidence_ids)
    )
    session.flush()

    # The deferred trigger is also guaranteed to fire at COMMIT for raw SQL
    # writers.  Firing it now gives command callers the updated projections
    # before the transaction ends.
    session.execute(text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply DEFERRED"))
    return change


def rebuild_identity_projections(session: Session) -> None:
    """Reconstruct all mutable Identity projections from append-only events."""
    session.execute(text("SELECT identity.rebuild_identity_projections()"))
    session.flush()
