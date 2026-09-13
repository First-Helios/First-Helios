"""Published contracts for consumers of shared Identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from packages.helios_core.identity.models import Subject, SubjectCurrentness

if TYPE_CHECKING:
    from collections.abc import Collection

    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class EligibleSubject:
    """An immutable, validated reference safe for a vertical write."""

    id: int
    kind: str


class SubjectNotEligibleError(ValueError):
    """Raised when a vertical attempts to use an ineligible Subject."""


def require_eligible_subject(
    session: Session,
    subject_id: int,
    *,
    allowed_kinds: Collection[str] | None = None,
) -> EligibleSubject:
    """Lock and validate a Subject for a same-transaction vertical write.

    The Subject lock conflicts with merge, split, and retirement processing,
    so eligibility cannot become stale before the caller's transaction
    commits.
    """
    session.execute(text("SELECT pg_advisory_xact_lock_shared(48454, 2)"))
    subject = session.scalar(select(Subject).where(Subject.id == subject_id).with_for_update())
    currentness = session.scalar(
        select(SubjectCurrentness)
        .where(SubjectCurrentness.subject_id == subject_id)
        .with_for_update()
    )
    if (
        subject is None
        or subject.readiness != "eligible"
        or currentness is None
        or not currentness.is_current
        or (allowed_kinds is not None and subject.kind not in allowed_kinds)
    ):
        raise SubjectNotEligibleError(
            f"Subject {subject_id} is not current, eligible, and of an allowed kind"
        )
    return EligibleSubject(id=subject.id, kind=subject.kind)
