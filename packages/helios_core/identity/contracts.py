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


# The admission predicate of ``identity.require_resolved_scopes`` evaluated per
# request as a plain read: the same STABLE helper functions, no lock step, no
# RAISE. ``txid_current_if_assigned`` (unlike ``txid_current``) never assigns a
# transaction ID, so the check also works in a read-only transaction.
_CURRENT_SCOPES_SQL = text("""
    SELECT r.ordinal, s.id AS subject_id, s.kind::text AS kind,
           r.record_id AS source_record_id, r.event_id AS resolution_event_id,
           e.organization_subject_id, e.place_subject_id,
           e.valid_from, e.valid_to, e.operating_status::text AS operating_status
    FROM unnest(CAST(:subjects AS bigint[]), CAST(:records AS bigint[]),
                CAST(:events AS bigint[])) WITH ORDINALITY
         AS r(subject_id, record_id, event_id, ordinal)
    JOIN identity.subject s ON s.id = r.subject_id
    LEFT JOIN identity.establishment e ON e.subject_id = s.id
    WHERE s.kind IN ('organization', 'establishment')
      AND s.readiness = 'eligible'
      AND identity.subject_feature_ready(s.id)
      AND NOT identity.has_pending_lineage(identity.scope_dependencies(ARRAY[s.id]))
      AND EXISTS (
          SELECT 1 FROM identity.current_resolution c
          JOIN identity.resolution_event ev ON ev.id = c.last_event_id
          WHERE c.subject_id = s.id
            AND c.source_record_id = r.record_id AND c.state = 'resolved'
            AND c.last_event_id = r.event_id
            AND ev.source_record_id = r.record_id
            AND ev.to_subject_id = r.subject_id
            AND ev.created_transaction_id IS DISTINCT FROM txid_current_if_assigned()
      )
""")


def current_resolved_scopes(
    session: Session, requests: Collection[ResolvedScopeRequest]
) -> tuple[ResolvedScope | None, ...]:
    """Read-only per-request eligibility for selection, in caller request order.

    Each entry is the ``ResolvedScope`` that :func:`require_resolved_scopes`
    would admit for that request alone, or ``None`` when the exact
    subject/record/event mapping is not current and eligible (remap, retirement,
    pending lineage, or an ineligible parent). It takes no locks and never
    raises on ineligibility, so a read path can neither abort its transaction
    nor block Identity writers. It grants no write admission: a vertical write
    must still go through :func:`require_resolved_scopes`.
    """
    batch = tuple(requests)
    if not batch:
        return ()
    session.flush()
    rows = (
        session.execute(
            _CURRENT_SCOPES_SQL,
            {
                "subjects": [r.subject_id for r in batch],
                "records": [r.source_record_id for r in batch],
                "events": [r.resolution_event_id for r in batch],
            },
        )
        .mappings()
        .all()
    )
    by_ordinal = {
        row["ordinal"]: ResolvedScope(**{k: v for k, v in row.items() if k != "ordinal"})
        for row in rows
    }
    return tuple(by_ordinal.get(ordinal) for ordinal in range(1, len(batch) + 1))
