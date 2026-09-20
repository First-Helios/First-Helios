"""Published contracts for consumers of shared Identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from packages.helios_core.identity.models import (
    Subject,
    SubjectCurrentness,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class EligibleSubject:
    """An immutable, validated reference safe for a vertical write."""

    id: int
    kind: str


@dataclass(frozen=True, slots=True)
class DeterministicResolutionResult:
    """Outcome of one Bronze-first deterministic resolution attempt."""

    source_id: int
    source_record_id: int
    source_record_version_id: int
    capture_id: int
    evidence_id: int
    state: str
    subject_id: int | None
    match_basis: str | None
    appended_event_ids: tuple[int, ...]
    source_record_created: bool
    observation_created: bool


class SubjectNotEligibleError(ValueError):
    """Raised when a vertical attempts to use an ineligible Subject."""


def subject_meets_readiness_policy(
    session: Session,
    subject_id: int,
    *,
    lock_features: bool = False,
    locked_subject_ids: frozenset[int] | None = None,
) -> bool:
    """Evaluate the shared SQL feature predicate, without requiring root eligibility.

    Promotion and admission use the same predicate. Read-only evaluation does
    not grant write admission. Locking callers retain locks until transaction end.
    """
    session.flush()
    if lock_features:
        dependencies = _lock_scope_inputs(session, (subject_id,))
        if locked_subject_ids is not None and not dependencies <= locked_subject_ids:
            return False
    return bool(
        session.scalar(
            text("SELECT identity.subject_feature_ready(:subject)"),
            {"subject": subject_id},
        )
    )


def _lock_scope_inputs(session: Session, subject_ids: Collection[int]) -> frozenset[int]:
    session.flush()
    return frozenset(
        session.execute(
            text(
                "SELECT identity.lock_scope_inputs(CAST(:subjects AS bigint[]), ARRAY[]::bigint[])"
            ),
            {"subjects": list(subject_ids)},
        ).scalar_one()
    )


def lock_subject_readiness_inputs(
    session: Session,
    subject_id: int,
) -> tuple[Subject | None, SubjectCurrentness | None, frozenset[int]]:
    """Keep the existing promotion API while delegating lock order to Identity SQL."""
    locked = _lock_scope_inputs(session, (subject_id,))
    return (
        session.get(Subject, subject_id, populate_existing=True),
        session.get(SubjectCurrentness, subject_id, populate_existing=True),
        locked,
    )


def require_eligible_subject(
    session: Session,
    subject_id: int,
    *,
    allowed_kinds: Collection[str] | None = None,
) -> EligibleSubject:
    """Validate one current eligible Subject; use the batch guard for resolved scopes."""
    subject, currentness, locked = lock_subject_readiness_inputs(session, subject_id)
    pending = session.scalar(
        text("SELECT identity.has_pending_lineage(CAST(:subjects AS bigint[]))"),
        {"subjects": sorted(locked)},
    )
    if (
        subject is None
        or subject.readiness != "eligible"
        or currentness is None
        or not currentness.is_current
        or pending
        or (allowed_kinds is not None and subject.kind not in allowed_kinds)
        or not subject_meets_readiness_policy(session, subject_id)
    ):
        raise SubjectNotEligibleError(
            f"Subject {subject_id} is not current, eligible, and of an allowed kind"
        )
    return EligibleSubject(id=subject.id, kind=subject.kind)


@dataclass(frozen=True, slots=True)
class ResolvedScopeRequest:
    """One expected current mapping; submit all local/base requests as one batch."""

    subject_id: int
    source_record_id: int
    resolution_event_id: int


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    """Admission-time scope and parents; operating state is not a readiness rule."""

    subject_id: int
    kind: str
    source_record_id: int
    resolution_event_id: int
    organization_subject_id: int | None
    place_subject_id: int | None
    valid_from: datetime | None
    valid_to: datetime | None
    operating_status: str | None


def require_resolved_scopes(
    session: Session, requests: Collection[ResolvedScopeRequest]
) -> tuple[ResolvedScope, ...]:
    """Lock and admit a complete scope batch, preserving caller request order.

    Input Bronze and resolution decisions must already be committed. Mixed
    persist/resolve/admit orchestration is outside this contract. No commit is
    performed; locks last until the caller ends the transaction. A later ordered
    scope change does not retroactively invalidate this successful admission.

    SQLSTATE 40001/40P01 require rollback and retry of the WHOLE transaction;
    they are deliberately not converted to eligibility failures or retried here.
    Mutable resolution proofs are locked as well as Subjects/Source Records,
    so a stale Repeatable Read/Serializable snapshot fails with 40001.
    A SQL rejection also requires rollback (or a caller-owned savepoint).
    """
    batch = tuple(requests)
    if not batch:
        raise ValueError("scope admission requires a nonempty batch")
    for request in batch:
        for value in (request.subject_id, request.source_record_id, request.resolution_event_id):
            if type(value) is not int or value <= 0:
                raise ValueError("scope admission requires positive integer IDs")
    session.flush()
    try:
        rows = (
            session.execute(
                text(
                    "SELECT * FROM identity.require_resolved_scopes("
                    "CAST(:subjects AS bigint[]), CAST(:records AS bigint[]), CAST(:events AS bigint[]))"
                ),
                {
                    "subjects": [r.subject_id for r in batch],
                    "records": [r.source_record_id for r in batch],
                    "events": [r.resolution_event_id for r in batch],
                },
            )
            .mappings()
            .all()
        )
    except DBAPIError as exc:
        if (
            getattr(exc.orig, "sqlstate", None) == "23514"
            and getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == "ck_resolved_scope_admission"
        ):
            raise SubjectNotEligibleError("scope batch failed current admission") from exc
        raise
    return tuple(ResolvedScope(**row) for row in rows)
