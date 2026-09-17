"""Published contracts for consumers of shared Identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    Organization,
    Place,
    Subject,
    SubjectCurrentness,
)

if TYPE_CHECKING:
    from collections.abc import Collection

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


def _subject_meets_readiness_policy(
    session: Session,
    subject: Subject,
    *,
    evaluating: frozenset[int] = frozenset(),
    lock_features: bool = False,
    locked_subject_ids: frozenset[int] | None = None,
) -> bool:
    """Evaluate meaningful typed identity features for one Subject."""
    if subject.id in evaluating:
        return False
    evaluating = evaluating | {subject.id}

    if subject.kind == "place":
        place = (
            session.scalar(
                select(Place)
                .where(Place.subject_id == subject.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if lock_features
            else session.get(Place, subject.id)
        )
        return place is not None and (
            (place.address is not None and bool(place.address.strip()))
            or (place.latitude is not None and place.longitude is not None)
        )

    if subject.kind == "organization":
        organization = (
            session.scalar(
                select(Organization)
                .where(Organization.subject_id == subject.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if lock_features
            else session.get(Organization, subject.id)
        )
        if (
            organization is None
            or organization.canonical_name is None
            or organization.name_fingerprint is None
        ):
            return False
        # A name/fingerprint pair is deliberately non-unique. A current
        # resolved source key supplies the second identity feature.
        return (
            session.scalar(
                select(CurrentResolution.source_record_id)
                .where(
                    CurrentResolution.subject_id == subject.id,
                    CurrentResolution.state == "resolved",
                )
                .limit(1)
            )
            is not None
        )

    if subject.kind == "establishment":
        establishment = (
            session.scalar(
                select(Establishment)
                .where(Establishment.subject_id == subject.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if lock_features
            else session.get(Establishment, subject.id)
        )
        if establishment is None:
            return False
        parent_ids = {
            establishment.organization_subject_id,
            establishment.place_subject_id,
        }
        if locked_subject_ids is not None and not parent_ids <= locked_subject_ids:
            # An Establishment parent changed after the dependency lock set
            # was selected. Refuse eligibility rather than accepting a parent
            # whose Subject row is not protected for this transaction.
            return False
        parents = {
            parent.id: parent
            for parent in session.scalars(select(Subject).where(Subject.id.in_(parent_ids)))
        }
        current_parent_ids = set(
            session.scalars(
                select(SubjectCurrentness.subject_id).where(
                    SubjectCurrentness.subject_id.in_(parent_ids),
                    SubjectCurrentness.is_current,
                )
            )
        )
        return (
            set(parents) == parent_ids
            and current_parent_ids == parent_ids
            and all(parent.readiness == "eligible" for parent in parents.values())
            and all(
                _subject_meets_readiness_policy(
                    session,
                    parent,
                    evaluating=evaluating,
                    lock_features=lock_features,
                    locked_subject_ids=locked_subject_ids,
                )
                for parent in parents.values()
            )
        )

    return False  # pragma: no cover - the database constrains Subject.kind


def subject_meets_readiness_policy(
    session: Session,
    subject_id: int,
    *,
    lock_features: bool = False,
    locked_subject_ids: frozenset[int] | None = None,
) -> bool:
    """Return whether a current Subject passes the Step 4 feature policy."""
    subject = session.get(Subject, subject_id)
    currentness = session.get(SubjectCurrentness, subject_id)
    return (
        subject is not None
        and currentness is not None
        and currentness.is_current
        and _subject_meets_readiness_policy(
            session,
            subject,
            lock_features=lock_features,
            locked_subject_ids=locked_subject_ids,
        )
    )


def lock_subject_readiness_inputs(
    session: Session,
    subject_id: int,
) -> tuple[Subject | None, SubjectCurrentness | None, frozenset[int]]:
    """Lock one Subject and every Subject dependency used by its policy."""
    subject_kind = session.scalar(select(Subject.kind).where(Subject.id == subject_id))
    subject_ids_to_lock = {subject_id}
    if subject_kind == "establishment":
        establishment = session.get(Establishment, subject_id)
        if establishment is not None:
            subject_ids_to_lock.update(
                {
                    establishment.organization_subject_id,
                    establishment.place_subject_id,
                }
            )

    subjects = {
        subject.id: subject
        for subject in session.scalars(
            select(Subject)
            .where(Subject.id.in_(sorted(subject_ids_to_lock)))
            .order_by(Subject.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    currentness_rows = {
        row.subject_id: row
        for row in session.scalars(
            select(SubjectCurrentness)
            .where(SubjectCurrentness.subject_id.in_(sorted(subject_ids_to_lock)))
            .order_by(SubjectCurrentness.subject_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    return (
        subjects.get(subject_id),
        currentness_rows.get(subject_id),
        frozenset(subjects),
    )


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
    subject, currentness, locked_subject_ids = lock_subject_readiness_inputs(
        session,
        subject_id,
    )
    if (
        subject is None
        or subject.readiness != "eligible"
        or currentness is None
        or not currentness.is_current
        or (allowed_kinds is not None and subject.kind not in allowed_kinds)
        or not _subject_meets_readiness_policy(
            session,
            subject,
            lock_features=True,
            locked_subject_ids=locked_subject_ids,
        )
    ):
        raise SubjectNotEligibleError(
            f"Subject {subject_id} is not current, eligible, and of an allowed kind"
        )
    return EligibleSubject(id=subject.id, kind=subject.kind)
