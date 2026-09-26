"""Database-enforced invariants for Plan 0002 Step 2 Identity."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from packages.helios_core.identity import (
    CurrentResolution,
    DecisionMetadata,
    Establishment,
    Place,
    ResolutionEvent,
    ResolutionEvidence,
    Subject,
    SubjectChange,
    SubjectChangeMember,
    SubjectCurrentness,
    SubjectLineage,
    SubjectName,
    SubjectNotEligibleError,
    admit_source_record,
    assign_source_record,
    create_adjudication,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
    rebuild_identity_projections,
    record_subject_change,
    remap_source_record,
    require_eligible_subject,
    unassign_source_record,
)
from packages.helios_core.provenance import (
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)
from test.guard_support import raises_guard

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _decision(confidence: str = "0.86") -> DecisionMetadata:
    now = datetime.now(UTC)
    return DecisionMetadata(
        confidence=Decimal(confidence),
        method="test-rule",
        method_version="1",
        actor_class="rule",
        decided_at=now,
        effective_at=now,
    )


def _adjudication(session: Session) -> int:
    return create_adjudication(
        session,
        actor="test-reviewer",
        rationale="Focused database invariant test.",
        decided_at=datetime.now(UTC),
    ).id


def _record_and_evidence(session: Session) -> tuple[SourceRecord, Evidence]:
    token = uuid4().hex
    source = Source(namespace=f"identity-test-{token}", kind="fixture")
    session.add(source)
    session.flush()
    record = SourceRecord(source_id=source.id, external_key=f"record-{token}")
    session.add(record)
    session.flush()
    version = SourceRecordVersion(
        source_id=source.id,
        source_record_id=record.id,
        observed_at=datetime.now(UTC),
        content_hash=f"sha256:{token}",
        source_payload={"id": token},
    )
    session.add(version)
    session.flush()
    evidence = Evidence(
        source_record_version_id=version.id,
        locator="$.id",
        excerpt_hash=f"sha256:evidence-{token}",
    )
    session.add(evidence)
    session.commit()
    return record, evidence


def _check_deferred(session: Session) -> None:
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _raw_resolution_event(
    session: Session,
    *,
    source_record_id: int,
    operation: str,
    from_subject_id: int | None = None,
    to_subject_id: int | None = None,
    confidence: str = "0.86",
    method: str = "test-rule",
    method_version: str = "1",
    actor_class: str = "rule",
    adjudication_id: int | None = None,
) -> ResolutionEvent:
    now = datetime.now(UTC)
    event = ResolutionEvent(
        source_record_id=source_record_id,
        operation=operation,
        from_subject_id=from_subject_id,
        to_subject_id=to_subject_id,
        adjudication_id=adjudication_id,
        confidence=Decimal(confidence),
        method=method,
        method_version=method_version,
        actor_class=actor_class,
        decided_at=now,
        effective_at=now,
    )
    session.add(event)
    session.flush()
    return event


def _raw_subject_change(
    session: Session,
    *,
    operation: str,
    inputs: list[Subject],
    outputs: list[Subject],
    confidence: str = "0.86",
    method: str = "test-rule",
    method_version: str = "1",
    actor_class: str = "rule",
    adjudication_id: int | None = None,
) -> SubjectChange:
    now = datetime.now(UTC)
    change = SubjectChange(
        operation=operation,
        adjudication_id=adjudication_id,
        confidence=Decimal(confidence),
        method=method,
        method_version=method_version,
        actor_class=actor_class,
        decided_at=now,
        effective_at=now,
    )
    session.add(change)
    session.flush()
    session.add_all(
        [
            SubjectChangeMember(
                subject_change_id=change.id,
                subject_id=subject.id,
                subject_kind=subject.kind,
                role=role,
            )
            for role, subjects in (("input", inputs), ("output", outputs))
            for subject in subjects
        ]
    )
    session.flush()
    return change


def test_subject_requires_exactly_one_typed_grain_at_constraint_boundary(
    session: Session,
) -> None:
    session.add(Subject(kind="place"))
    session.flush()

    with pytest.raises(DBAPIError, match="exactly one matching typed grain"):
        session.execute(text("SET CONSTRAINTS identity.ct_subject_exact_typed_grain IMMEDIATE"))
    session.rollback()


def test_typed_grain_kind_must_match_subject(session: Session) -> None:
    subject = Subject(kind="organization")
    session.add(subject)
    session.flush()
    session.add(Place(subject_id=subject.id))

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_typed_grain_cannot_move_between_subjects(session: Session) -> None:
    first = create_place(session)
    second = create_place(session)
    _check_deferred(session)

    with pytest.raises(DBAPIError, match="Subject identity is immutable"):
        session.execute(
            text(
                """
                UPDATE identity.place
                SET subject_id = :second_id
                WHERE subject_id = :first_id
                """
            ),
            {"first_id": first.id, "second_id": second.id},
        )
    session.rollback()


def test_establishment_requires_typed_organization_and_place(session: Session) -> None:
    organization = create_organization(session, canonical_name="Acme", name_fingerprint="acme")
    place = create_place(session, address="100 Test St")
    establishment = create_establishment(
        session,
        organization_subject_id=organization.id,
        place_subject_id=place.id,
        valid_from=datetime.now(UTC),
    )
    _check_deferred(session)
    assert session.get(Establishment, establishment.id) is not None

    invalid = Subject(kind="establishment")
    session.add(invalid)
    session.flush()
    session.add(
        Establishment(
            subject_id=invalid.id,
            organization_subject_id=place.id,
            place_subject_id=organization.id,
            valid_from=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_establishment_grain_references_and_typed_row_are_immutable(
    session: Session,
) -> None:
    first_organization = create_organization(session)
    second_organization = create_organization(session)
    place = create_place(session)
    establishment = create_establishment(
        session,
        organization_subject_id=first_organization.id,
        place_subject_id=place.id,
        valid_from=datetime.now(UTC),
    )
    _check_deferred(session)

    with pytest.raises(DBAPIError, match="organization and Place are immutable"):
        session.execute(
            text(
                """
                UPDATE identity.establishment
                SET organization_subject_id = :organization_subject_id
                WHERE subject_id = :subject_id
                """
            ),
            {
                "organization_subject_id": second_organization.id,
                "subject_id": establishment.id,
            },
        )
    session.rollback()

    subject = create_place(session)
    _check_deferred(session)
    with pytest.raises(DBAPIError, match="typed grain cannot be deleted"):
        session.execute(
            text("DELETE FROM identity.place WHERE subject_id = :subject_id"),
            {"subject_id": subject.id},
        )
    session.rollback()

    create_place(session)
    _check_deferred(session)
    with pytest.raises(DBAPIError, match="typed grains cannot be truncated"):
        session.execute(text("TRUNCATE identity.establishment"))
    session.rollback()


def test_establishment_effective_interval_and_operating_state_are_independent(
    session: Session,
) -> None:
    organization = create_organization(session)
    place = create_place(session)
    invalid = Subject(kind="establishment")
    session.add(invalid)
    session.flush()
    now = datetime.now(UTC)
    session.add(
        Establishment(
            subject_id=invalid.id,
            organization_subject_id=organization.id,
            place_subject_id=place.id,
            valid_from=now,
            valid_to=now,
            operating_status="closed",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    organization = create_organization(session)
    place = create_place(session)
    establishment = create_establishment(
        session,
        organization_subject_id=organization.id,
        place_subject_id=place.id,
        valid_from=datetime.now(UTC),
        operating_status="closed",
    )
    _check_deferred(session)
    currentness = session.get(SubjectCurrentness, establishment.id)
    assert currentness is not None and currentness.is_current


def test_subject_names_are_typed_aliases_with_optional_evidence(session: Session) -> None:
    organization = create_organization(session)
    session.add(
        SubjectName(
            subject_id=organization.id,
            subject_kind="organization",
            name="Acme Foods",
            name_fingerprint="acme foods",
            name_kind="alias",
        )
    )
    _check_deferred(session)
    session.commit()

    session.add(
        SubjectName(
            subject_id=organization.id,
            subject_kind="organization",
            name="Bad Kind",
            name_fingerprint="bad kind",
            name_kind="attribute",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_readiness_contract_rejects_provisional_and_retired_subjects(
    session: Session,
) -> None:
    first = create_place(session, address="100 Ready St")
    second = create_place(session, address="200 Survivor St")
    _check_deferred(session)

    with pytest.raises(SubjectNotEligibleError):
        require_eligible_subject(session, first.id)
    mark_subject_eligible(session, first.id)
    assert (
        require_eligible_subject(
            session,
            first.id,
            allowed_kinds={"place"},
        ).id
        == first.id
    )

    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[first.id, second.id],
        output_subject_ids=[second.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    with pytest.raises(SubjectNotEligibleError):
        require_eligible_subject(session, first.id)


def test_subject_readiness_rejects_unknown_database_state(session: Session) -> None:
    subject = create_place(session)
    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE identity.subject SET readiness = 'automatic' WHERE id = :subject_id"),
            {"subject_id": subject.id},
        )
    session.rollback()


def test_resolution_state_machine_and_projection(session: Session) -> None:
    record, evidence = _record_and_evidence(session)
    first = create_organization(session)
    second = create_organization(session)
    _check_deferred(session)

    opened = admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    _check_deferred(session)
    current = session.get(CurrentResolution, record.id)
    assert current is not None
    assert (current.state, current.subject_id, current.last_event_id) == (
        "unresolved",
        None,
        opened.id,
    )

    assigned = assign_source_record(
        session,
        source_record_id=record.id,
        to_subject_id=first.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    _check_deferred(session)
    session.expire(current)
    assert (current.state, current.subject_id, current.last_event_id) == (
        "resolved",
        first.id,
        assigned.id,
    )

    remapped = remap_source_record(
        session,
        source_record_id=record.id,
        from_subject_id=first.id,
        to_subject_id=second.id,
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    _check_deferred(session)
    session.expire(current)
    assert (current.subject_id, current.last_event_id) == (second.id, remapped.id)

    unassigned = unassign_source_record(
        session,
        source_record_id=record.id,
        from_subject_id=second.id,
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    _check_deferred(session)
    session.expire(current)
    assert (current.state, current.subject_id, current.last_event_id) == (
        "needs_review",
        None,
        unassigned.id,
    )
    rebuild_identity_projections(session)
    session.expire(current)
    assert (current.state, current.subject_id, current.last_event_id) == (
        "needs_review",
        None,
        unassigned.id,
    )


def test_resolution_rejects_invalid_transition_and_incomplete_decision(
    session: Session,
) -> None:
    record, evidence = _record_and_evidence(session)
    target = create_place(session)
    _check_deferred(session)
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    _check_deferred(session)

    with pytest.raises(ValueError, match="already in resolution"):
        admit_source_record(
            session,
            source_record_id=record.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )

    with pytest.raises(DBAPIError, match="already in resolution"):
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="open",
            adjudication_id=_adjudication(session),
        )
    session.rollback()

    other_record, _ = _record_and_evidence(session)
    with pytest.raises(ValueError, match="requires Evidence or Adjudication"):
        admit_source_record(
            session,
            source_record_id=other_record.id,
            decision=_decision(),
        )
    _raw_resolution_event(
        session,
        source_record_id=other_record.id,
        operation="open",
    )
    with pytest.raises(DBAPIError, match="requires Evidence or Adjudication"):
        session.execute(text("SET CONSTRAINTS identity.ct_resolution_event_support IMMEDIATE"))
    session.rollback()

    assert target.id is not None


def test_resolution_rejects_overwrite_and_wrong_current_subject(
    session: Session,
) -> None:
    record, evidence = _record_and_evidence(session)
    first = create_place(session)
    second = create_place(session)
    _check_deferred(session)
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    assign_source_record(
        session,
        source_record_id=record.id,
        to_subject_id=first.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    _check_deferred(session)

    with pytest.raises(ValueError, match="assign requires"):
        assign_source_record(
            session,
            source_record_id=record.id,
            to_subject_id=second.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )

    with pytest.raises(DBAPIError, match="assign requires"):
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="assign",
            to_subject_id=second.id,
            adjudication_id=_adjudication(session),
        )
    session.rollback()

    other_record, other_evidence = _record_and_evidence(session)
    first = create_place(session)
    second = create_place(session)
    _check_deferred(session)
    admit_source_record(
        session,
        source_record_id=other_record.id,
        decision=_decision(),
        evidence_ids=[other_evidence.id],
    )
    assign_source_record(
        session,
        source_record_id=other_record.id,
        to_subject_id=first.id,
        decision=_decision(),
        evidence_ids=[other_evidence.id],
    )
    _check_deferred(session)
    with pytest.raises(ValueError, match="must name the current Subject"):
        unassign_source_record(
            session,
            source_record_id=other_record.id,
            from_subject_id=second.id,
            decision=_decision(),
            evidence_ids=[other_evidence.id],
        )
    with pytest.raises(DBAPIError, match="must name the current Subject"):
        _raw_resolution_event(
            session,
            source_record_id=other_record.id,
            operation="unassign",
            from_subject_id=second.id,
            adjudication_id=_adjudication(session),
        )
    session.rollback()


def test_resolution_rejects_a_retired_target_in_command_and_database(
    session: Session,
) -> None:
    record, evidence = _record_and_evidence(session)
    retired = create_place(session)
    survivor = create_place(session)
    _check_deferred(session)
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[retired.id, survivor.id],
        output_subject_ids=[survivor.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )

    with pytest.raises(ValueError, match="target Subject .* is not current"):
        assign_source_record(
            session,
            source_record_id=record.id,
            to_subject_id=retired.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )
    with pytest.raises(DBAPIError, match="target Subject .* is not current"):
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="assign",
            to_subject_id=retired.id,
            adjudication_id=_adjudication(session),
        )
    session.rollback()


@pytest.mark.parametrize("confidence", ["-0.01", "1.01"])
def test_resolution_confidence_rejects_out_of_range(
    session: Session,
    confidence: str,
) -> None:
    record, _ = _record_and_evidence(session)
    with pytest.raises(IntegrityError):
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="open",
            confidence=confidence,
            adjudication_id=_adjudication(session),
        )
    session.rollback()


@pytest.mark.parametrize("confidence", ["0", "1"])
def test_resolution_confidence_accepts_boundaries(
    session: Session,
    confidence: str,
) -> None:
    record, evidence = _record_and_evidence(session)
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(confidence),
        evidence_ids=[evidence.id],
    )
    _check_deferred(session)


def test_resolution_operation_shape_is_database_enforced(session: Session) -> None:
    record, _ = _record_and_evidence(session)
    target = create_place(session)
    _check_deferred(session)
    with pytest.raises(IntegrityError):
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="open",
            to_subject_id=target.id,
            adjudication_id=_adjudication(session),
        )
    session.rollback()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("method", " "),
        ("method_version", ""),
        ("actor_class", "service"),
    ],
)
def test_resolution_metadata_is_bounded_in_command_and_database(
    session: Session,
    field: str,
    value: str,
) -> None:
    decision_values: dict[str, object] = {
        "confidence": Decimal("0.5"),
        "method": "test-rule",
        "method_version": "1",
        "actor_class": "rule",
        "decided_at": datetime.now(UTC),
        "effective_at": datetime.now(UTC),
    }
    decision_values[field] = value
    with pytest.raises(ValueError):
        DecisionMetadata(**decision_values)  # type: ignore[arg-type]

    record, _ = _record_and_evidence(session)
    raw_values = {
        "method": "test-rule",
        "method_version": "1",
        "actor_class": "rule",
    }
    raw_values[field] = value
    with pytest.raises(IntegrityError):
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="open",
            method=raw_values["method"],
            method_version=raw_values["method_version"],
            actor_class=raw_values["actor_class"],
            adjudication_id=_adjudication(session),
        )
    session.rollback()


def test_adjudication_requires_bounded_human_metadata(session: Session) -> None:
    with pytest.raises(ValueError):
        create_adjudication(
            session,
            actor="reviewer",
            rationale="x" * 4001,
            decided_at=datetime.now(UTC),
        )
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO identity.adjudication (actor, rationale, decided_at)
                VALUES ('reviewer', :rationale, now())
                """
            ),
            {"rationale": "x" * 4001},
        )
    session.rollback()


def test_decision_times_are_required_by_both_event_tables(session: Session) -> None:
    record, _ = _record_and_evidence(session)
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO identity.resolution_event (
                    source_record_id,
                    operation,
                    confidence,
                    method,
                    method_version,
                    actor_class,
                    decided_at
                )
                VALUES (
                    :record_id,
                    'open',
                    0.5,
                    'test-rule',
                    '1',
                    'rule',
                    now()
                )
                """
            ),
            {"record_id": record.id},
        )
    session.rollback()

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO identity.subject_change (
                    operation,
                    confidence,
                    method,
                    method_version,
                    actor_class,
                    decided_at
                )
                VALUES (
                    'retire',
                    0.5,
                    'test-rule',
                    '1',
                    'rule',
                    now()
                )
                """
            )
        )
    session.rollback()


def test_resolution_aggregate_and_projection_reject_direct_mutation(
    session: Session,
) -> None:
    record, evidence = _record_and_evidence(session)
    event = admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    _check_deferred(session)
    session.commit()

    for statement, message in (
        (
            "UPDATE identity.resolution_event SET method = 'changed' WHERE id = :id",
            r"identity\.resolution_event is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.resolution_evidence WHERE resolution_event_id = :id",
            r"identity\.resolution_evidence is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.current_resolution SET state = 'needs_review' "
            "WHERE source_record_id = :record_id",
            "current-resolution row must match authoritative history",
        ),
    ):
        with raises_guard(message):
            session.execute(
                text(statement),
                {"id": event.id, "record_id": record.id},
            )
            session.commit()
        session.rollback()

    session.execute(text("SET LOCAL helios.identity_projection_write = 'allowed'"))
    with pytest.raises(DBAPIError, match="must match authoritative history"):
        session.execute(
            text(
                """
                UPDATE identity.current_resolution
                SET state = 'needs_review',
                    subject_id = NULL
                WHERE source_record_id = :record_id
                """
            ),
            {"record_id": record.id},
        )
    session.rollback()

    session.execute(text("CREATE TEMP TABLE projection_attack (source_record_id bigint)"))
    session.execute(
        text(
            """
            CREATE FUNCTION pg_temp.attack_projection()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                UPDATE identity.current_resolution
                SET state = 'needs_review',
                    subject_id = NULL
                WHERE source_record_id = NEW.source_record_id;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TRIGGER trg_projection_attack
            AFTER INSERT ON projection_attack
            FOR EACH ROW
            EXECUTE FUNCTION pg_temp.attack_projection()
            """
        )
    )
    with pytest.raises(DBAPIError, match="must match authoritative history"):
        session.execute(
            text("INSERT INTO projection_attack (source_record_id) VALUES (:record_id)"),
            {"record_id": record.id},
        )
    session.rollback()

    with pytest.raises(DBAPIError, match="derived Identity projection"):
        session.execute(text("TRUNCATE identity.current_resolution"))
    session.rollback()


def test_resolution_rebuild_uses_locked_sequence_not_caller_event_id(
    session: Session,
) -> None:
    record, evidence = _record_and_evidence(session)
    first = create_place(session)
    second = create_place(session)
    _check_deferred(session)
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    assign_source_record(
        session,
        source_record_id=record.id,
        to_subject_id=first.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    decision = _decision()
    remap = ResolutionEvent(
        id=-1,
        source_record_id=record.id,
        operation="remap",
        from_subject_id=first.id,
        to_subject_id=second.id,
        confidence=decision.confidence,
        method=decision.method,
        method_version=decision.method_version,
        actor_class=decision.actor_class,
        decided_at=decision.decided_at,
        effective_at=decision.effective_at,
    )
    session.add(remap)
    session.flush()
    session.add(
        ResolutionEvidence(
            resolution_event_id=remap.id,
            evidence_id=evidence.id,
        )
    )
    session.flush()
    _check_deferred(session)
    assert remap.sequence_no == 3

    rebuild_identity_projections(session)
    current = session.get(CurrentResolution, record.id)
    assert current is not None
    assert (current.subject_id, current.last_event_id) == (second.id, remap.id)


def test_merge_split_retire_and_rebuildable_lineage(session: Session) -> None:
    survivor = create_organization(session)
    loser = create_organization(session)
    split_input = create_place(session)
    split_first = create_place(session)
    split_second = create_place(session)
    retired = create_place(session)
    _check_deferred(session)

    merge = record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[survivor.id, loser.id],
        output_subject_ids=[survivor.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    split = record_subject_change(
        session,
        operation="split",
        input_subject_ids=[split_input.id],
        output_subject_ids=[split_first.id, split_second.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    retirement = record_subject_change(
        session,
        operation="retire",
        input_subject_ids=[retired.id],
        output_subject_ids=[],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )

    loser_state = session.get(SubjectCurrentness, loser.id)
    survivor_state = session.get(SubjectCurrentness, survivor.id)
    assert loser_state is not None and not loser_state.is_current
    assert loser_state.retired_by_change_id == merge.id
    assert survivor_state is not None and survivor_state.is_current
    assert session.scalar(
        select(SubjectLineage).where(
            SubjectLineage.subject_change_id == split.id,
            SubjectLineage.predecessor_subject_id == split_input.id,
            SubjectLineage.successor_subject_id == split_first.id,
        )
    )
    retired_state = session.get(SubjectCurrentness, retired.id)
    assert retired_state is not None
    assert retired_state.retired_by_change_id == retirement.id

    before = set(
        session.execute(
            select(
                SubjectLineage.subject_change_id,
                SubjectLineage.predecessor_subject_id,
                SubjectLineage.successor_subject_id,
            )
        ).all()
    )
    rebuild_identity_projections(session)
    after = set(
        session.execute(
            select(
                SubjectLineage.subject_change_id,
                SubjectLineage.predecessor_subject_id,
                SubjectLineage.successor_subject_id,
            )
        ).all()
    )
    assert after == before
    rebuilt_loser_state = session.get(SubjectCurrentness, loser.id)
    assert rebuilt_loser_state is not None
    assert not rebuilt_loser_state.is_current


def test_rebuild_allows_a_split_output_to_participate_later(
    session: Session,
) -> None:
    predecessor = create_place(session)
    first_output = create_place(session)
    second_output = create_place(session)
    later_loser = create_place(session)
    _check_deferred(session)

    record_subject_change(
        session,
        operation="split",
        input_subject_ids=[predecessor.id],
        output_subject_ids=[first_output.id, second_output.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[first_output.id, later_loser.id],
        output_subject_ids=[first_output.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )

    rebuild_identity_projections(session)
    predecessor_state = session.get(SubjectCurrentness, predecessor.id)
    first_output_state = session.get(SubjectCurrentness, first_output.id)
    second_output_state = session.get(SubjectCurrentness, second_output.id)
    later_loser_state = session.get(SubjectCurrentness, later_loser.id)
    assert predecessor_state is not None
    assert not predecessor_state.is_current
    assert first_output_state is not None
    assert first_output_state.is_current
    assert second_output_state is not None
    assert second_output_state.is_current
    assert later_loser_state is not None
    assert not later_loser_state.is_current


def test_rebuild_cannot_seal_a_pending_invalid_subject_change(
    session: Session,
) -> None:
    first = create_place(session)
    second = create_place(session)
    _check_deferred(session)
    decision = _decision()
    change = SubjectChange(
        operation="merge",
        adjudication_id=_adjudication(session),
        confidence=decision.confidence,
        method=decision.method,
        method_version=decision.method_version,
        actor_class=decision.actor_class,
        decided_at=decision.decided_at,
        effective_at=decision.effective_at,
    )
    session.add(change)
    session.flush()
    session.add_all(
        (
            SubjectChangeMember(
                subject_change_id=change.id,
                subject_id=first.id,
                subject_kind="place",
                role="input",
            ),
            SubjectChangeMember(
                subject_change_id=change.id,
                subject_id=second.id,
                subject_kind="place",
                role="output",
            ),
        )
    )
    session.flush()

    with pytest.raises(DBAPIError, match="invalid merge member cardinality"):
        rebuild_identity_projections(session)
    session.rollback()


def test_merge_requires_an_existing_survivor_to_be_an_input(
    session: Session,
) -> None:
    survivor = create_place(session)
    first_loser = create_place(session)
    second_loser = create_place(session)
    third_loser = create_place(session)
    _check_deferred(session)
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[survivor.id, first_loser.id],
        output_subject_ids=[survivor.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )

    with pytest.raises(DBAPIError, match="existing merge survivor"):
        record_subject_change(
            session,
            operation="merge",
            input_subject_ids=[second_loser.id, third_loser.id],
            output_subject_ids=[survivor.id],
            decision=_decision(),
            adjudication_id=_adjudication(session),
        )
    session.rollback()


def test_new_merge_output_can_be_resolved_before_the_change(session: Session) -> None:
    record, evidence = _record_and_evidence(session)
    first_input = create_place(session)
    second_input = create_place(session)
    new_output = create_place(session)
    _check_deferred(session)
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    assign_source_record(
        session,
        source_record_id=record.id,
        to_subject_id=new_output.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )

    change = record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[first_input.id, second_input.id],
        output_subject_ids=[new_output.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )

    assert change.id is not None
    output_state = session.get(SubjectCurrentness, new_output.id)
    assert output_state is not None and output_state.is_current


@pytest.mark.parametrize(
    ("operation", "input_count", "output_count"),
    [
        ("merge", 1, 1),
        ("split", 1, 1),
        ("retire", 1, 1),
    ],
)
def test_subject_change_rejects_invalid_cardinality(
    session: Session,
    operation: str,
    input_count: int,
    output_count: int,
) -> None:
    inputs = [create_place(session) for _ in range(input_count)]
    outputs = [create_place(session) for _ in range(output_count)]
    _check_deferred(session)

    with pytest.raises(ValueError, match="invalid .* member cardinality"):
        record_subject_change(
            session,
            operation=operation,
            input_subject_ids=[subject.id for subject in inputs],
            output_subject_ids=[subject.id for subject in outputs],
            decision=_decision(),
            adjudication_id=_adjudication(session),
        )

    _raw_subject_change(
        session,
        operation=operation,
        inputs=inputs,
        outputs=outputs,
        adjudication_id=_adjudication(session),
    )
    with pytest.raises(DBAPIError, match="invalid .* member cardinality"):
        session.execute(
            text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE")
        )
    session.rollback()


def test_subject_change_rejects_mixed_kinds_and_retired_inputs(
    session: Session,
) -> None:
    place = create_place(session)
    organization = create_organization(session)
    output = create_place(session)
    _check_deferred(session)
    with pytest.raises(ValueError, match="one Subject kind"):
        record_subject_change(
            session,
            operation="merge",
            input_subject_ids=[place.id, organization.id],
            output_subject_ids=[output.id],
            decision=_decision(),
            adjudication_id=_adjudication(session),
        )
    session.rollback()

    place = create_place(session)
    organization = create_organization(session)
    output = create_place(session)
    _raw_subject_change(
        session,
        operation="merge",
        inputs=[place, organization],
        outputs=[output],
        adjudication_id=_adjudication(session),
    )
    with pytest.raises(DBAPIError, match="one Subject kind"):
        session.execute(
            text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE")
        )
    session.rollback()

    first = create_place(session)
    second = create_place(session)
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[first.id, second.id],
        output_subject_ids=[first.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    with pytest.raises(ValueError, match="input must be current|member must be current"):
        record_subject_change(
            session,
            operation="retire",
            input_subject_ids=[second.id],
            output_subject_ids=[],
            decision=_decision(),
            adjudication_id=_adjudication(session),
        )

    _raw_subject_change(
        session,
        operation="retire",
        inputs=[second],
        outputs=[],
        adjudication_id=_adjudication(session),
    )
    with pytest.raises(DBAPIError, match="input must be current|member must be current"):
        session.execute(
            text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE")
        )
    session.rollback()


def test_subject_change_requires_support_and_rejects_lineage_cycle(
    session: Session,
) -> None:
    unsupported = create_place(session)
    _check_deferred(session)
    with pytest.raises(ValueError, match="requires Evidence or Adjudication"):
        record_subject_change(
            session,
            operation="retire",
            input_subject_ids=[unsupported.id],
            output_subject_ids=[],
            decision=_decision(),
        )

    _raw_subject_change(
        session,
        operation="retire",
        inputs=[unsupported],
        outputs=[],
    )
    with pytest.raises(DBAPIError, match="requires Evidence or Adjudication"):
        session.execute(
            text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE")
        )
    session.rollback()

    predecessor = create_place(session)
    successor = create_place(session)
    third = create_place(session)
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[predecessor.id, successor.id],
        output_subject_ids=[successor.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    session.commit()

    with pytest.raises(ValueError, match="input must be current|member must be current"):
        record_subject_change(
            session,
            operation="merge",
            input_subject_ids=[predecessor.id, successor.id, third.id],
            output_subject_ids=[predecessor.id],
            decision=_decision(),
            adjudication_id=_adjudication(session),
        )

    _raw_subject_change(
        session,
        operation="merge",
        inputs=[predecessor, successor, third],
        outputs=[predecessor],
        adjudication_id=_adjudication(session),
    )
    with pytest.raises(DBAPIError, match="lineage cycle"):
        session.execute(
            text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE")
        )
    session.rollback()


@pytest.mark.parametrize("confidence", ["-0.01", "1.01"])
def test_subject_change_confidence_rejects_out_of_range(
    session: Session,
    confidence: str,
) -> None:
    subject = create_place(session)
    _check_deferred(session)
    with pytest.raises(IntegrityError):
        _raw_subject_change(
            session,
            operation="retire",
            inputs=[subject],
            outputs=[],
            confidence=confidence,
            adjudication_id=_adjudication(session),
        )
    session.rollback()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("method", ""),
        ("method_version", " "),
        ("actor_class", "operator"),
    ],
)
def test_subject_change_metadata_is_database_enforced(
    session: Session,
    field: str,
    value: str,
) -> None:
    subject = create_place(session)
    _check_deferred(session)
    values = {
        "method": "test-rule",
        "method_version": "1",
        "actor_class": "rule",
    }
    values[field] = value
    with pytest.raises(IntegrityError):
        _raw_subject_change(
            session,
            operation="retire",
            inputs=[subject],
            outputs=[],
            method=values["method"],
            method_version=values["method_version"],
            actor_class=values["actor_class"],
            adjudication_id=_adjudication(session),
        )
    session.rollback()


def test_subject_history_and_referenced_subject_reject_deletion(session: Session) -> None:
    record, evidence = _record_and_evidence(session)
    first = create_place(session)
    second = create_place(session)
    late_member = create_place(session)
    adjudication_id = _adjudication(session)
    event = admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    change = record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[first.id, second.id],
        output_subject_ids=[first.id],
        decision=_decision(),
        evidence_ids=[evidence.id],
        adjudication_id=adjudication_id,
    )
    session.commit()

    for statement, message in (
        (
            "UPDATE identity.resolution_event SET method = method WHERE id = :event_id",
            r"identity\.resolution_event is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.resolution_event WHERE id = :event_id",
            r"identity\.resolution_event is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.resolution_evidence SET evidence_id = evidence_id "
            "WHERE resolution_event_id = :event_id",
            r"identity\.resolution_evidence is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.resolution_evidence WHERE resolution_event_id = :event_id",
            r"identity\.resolution_evidence is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.subject_change_member SET role = role WHERE subject_change_id = :id",
            r"identity\.subject_change_member is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.subject_change_member WHERE subject_change_id = :id",
            r"identity\.subject_change_member is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.subject_change_evidence SET evidence_id = evidence_id "
            "WHERE subject_change_id = :id",
            r"identity\.subject_change_evidence is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.subject_change_evidence WHERE subject_change_id = :id",
            r"identity\.subject_change_evidence is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.subject_change SET method = 'changed' WHERE id = :id",
            r"identity\.subject_change is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.subject_change WHERE id = :id",
            r"identity\.subject_change is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.adjudication SET rationale = 'changed' WHERE id = :adjudication_id",
            r"identity\.adjudication is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.adjudication WHERE id = :adjudication_id",
            r"identity\.adjudication is append-only and cannot be delete",
        ),
        (
            "DELETE FROM identity.subject WHERE id = :subject_id",
            "Identity Subjects are retired, not deleted",
        ),
        (
            "UPDATE identity.applied_subject_change SET subject_change_id = subject_change_id "
            "WHERE subject_change_id = :id",
            r"identity\.applied_subject_change is append-only and cannot be update",
        ),
        (
            "DELETE FROM identity.applied_subject_change WHERE subject_change_id = :id",
            r"identity\.applied_subject_change is append-only and cannot be delete",
        ),
        (
            "UPDATE identity.subject SET kind = 'organization' WHERE id = :subject_id",
            "Subject kind is immutable",
        ),
    ):
        with raises_guard(message):
            session.execute(
                text(statement),
                {
                    "id": change.id,
                    "event_id": event.id,
                    "adjudication_id": adjudication_id,
                    "subject_id": first.id,
                },
            )
            session.commit()
        session.rollback()

    with pytest.raises(DBAPIError, match="only be inserted with their parent"):
        session.add(
            SubjectChangeMember(
                subject_change_id=change.id,
                subject_id=late_member.id,
                subject_kind="place",
                role="input",
            )
        )
        session.flush()
    session.rollback()


@pytest.mark.parametrize(
    "table",
    [
        # Leaf tables: no FK points at them, so the trigger is the only guard.
        "resolution_evidence",
        "subject_change_member",
        "subject_change_evidence",
        "applied_subject_change",
    ],
)
def test_identity_history_leaf_tables_reject_truncate(session: Session, table: str) -> None:
    with raises_guard(rf"identity\.{table} is append-only and cannot be truncate"):
        session.execute(text(f"TRUNCATE identity.{table}"))
    session.rollback()


@pytest.mark.parametrize("table", ["adjudication", "resolution_event", "subject_change"])
def test_identity_history_parent_tables_reject_truncate_cascade(
    session: Session, table: str
) -> None:
    # Without CASCADE an FK refuses first; CASCADE reaches the trigger.
    with raises_guard(rf"identity\.{table} is append-only and cannot be truncate"):
        session.execute(text(f"TRUNCATE identity.{table} CASCADE"))
    session.rollback()


def test_subject_projections_reject_tampering(session: Session) -> None:
    survivor = create_place(session)
    retired = create_place(session)
    _check_deferred(session)
    change = record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[survivor.id, retired.id],
        output_subject_ids=[survivor.id],
        decision=_decision(),
        adjudication_id=_adjudication(session),
    )
    session.commit()
    params = {"retired": retired.id, "survivor": survivor.id, "change": change.id}

    for statement, message in (
        (
            "UPDATE identity.subject_currentness SET is_current = true, "
            "retired_by_change_id = NULL, retirement_reason = NULL "
            "WHERE subject_id = :retired",
            "Subject-currentness row must match authoritative history",
        ),
        (
            "UPDATE identity.subject_currentness SET subject_id = :survivor "
            "WHERE subject_id = :retired",
            "Subject-currentness projection key is immutable",
        ),
        (
            "DELETE FROM identity.subject_currentness WHERE subject_id = :retired",
            r"identity\.subject_currentness is a derived Identity projection",
        ),
        (
            "TRUNCATE identity.subject_currentness",
            r"identity\.subject_currentness is a derived Identity projection",
        ),
        (
            "UPDATE identity.subject_lineage SET successor_subject_id = :retired "
            "WHERE predecessor_subject_id = :retired",
            "Subject-lineage projection rows are immutable",
        ),
        (
            "DELETE FROM identity.subject_lineage WHERE predecessor_subject_id = :retired",
            r"identity\.subject_lineage is a derived Identity projection",
        ),
        (
            "TRUNCATE identity.subject_lineage",
            r"identity\.subject_lineage is a derived Identity projection",
        ),
        (
            "INSERT INTO identity.subject_lineage (subject_change_id, predecessor_subject_id, "
            "predecessor_subject_kind, successor_subject_id, successor_subject_kind) "
            "VALUES (:change, :survivor, 'place', :retired, 'place')",
            "Subject-lineage row must match authoritative history",
        ),
    ):
        with raises_guard(message):
            session.execute(text(statement), params)
            session.commit()
        session.rollback()

    currentness = session.get(SubjectCurrentness, retired.id, populate_existing=True)
    assert currentness is not None
    assert not currentness.is_current


def test_remap_rejects_same_target_and_wrong_current_subject(session: Session) -> None:
    record, evidence = _record_and_evidence(session)
    current = create_place(session)
    other = create_place(session)
    _check_deferred(session)
    admit_source_record(
        session,
        source_record_id=record.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    assign_source_record(
        session,
        source_record_id=record.id,
        to_subject_id=current.id,
        decision=_decision(),
        evidence_ids=[evidence.id],
    )
    session.commit()

    with pytest.raises(ValueError, match="remap requires a different target Subject"):
        remap_source_record(
            session,
            source_record_id=record.id,
            from_subject_id=current.id,
            to_subject_id=current.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )
    with pytest.raises(IntegrityError) as same_target:
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="remap",
            from_subject_id=current.id,
            to_subject_id=current.id,
            adjudication_id=_adjudication(session),
        )
    assert (
        getattr(getattr(same_target.value.orig, "diag", None), "constraint_name", None)
        == "ck_resolution_event_operation_shape"
    )
    session.rollback()

    with pytest.raises(ValueError, match="remap must name the current Subject"):
        remap_source_record(
            session,
            source_record_id=record.id,
            from_subject_id=other.id,
            to_subject_id=current.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )
    with pytest.raises(IntegrityError, match="remap must name the current Subject") as wrong:
        _raw_resolution_event(
            session,
            source_record_id=record.id,
            operation="remap",
            from_subject_id=other.id,
            to_subject_id=current.id,
            adjudication_id=_adjudication(session),
        )
    assert (
        getattr(getattr(wrong.value.orig, "diag", None), "constraint_name", None)
        == "ct_resolution_transition"
    )
    session.rollback()

    current_row = session.get(CurrentResolution, record.id, populate_existing=True)
    assert current_row is not None
    assert (current_row.state, current_row.subject_id) == ("resolved", current.id)
