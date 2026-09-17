"""Real-transaction concurrency checks for Identity serialization.

These tests need separate database connections, so unlike the savepoint
fixture they commit uniquely named immutable fixture rows to the disposable
``*_test`` database. CI creates that database afresh for the job.
"""

from __future__ import annotations

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from packages.helios_core.config import get_settings
from packages.helios_core.identity import (
    CurrentResolution,
    DecisionMetadata,
    ResolutionEvent,
    ResolutionEvidence,
    SubjectChange,
    SubjectChangeEvidence,
    SubjectChangeMember,
    SubjectCurrentness,
    admit_source_record,
    assign_source_record,
    create_adjudication,
    create_organization,
    create_place,
    mark_subject_eligible,
    rebuild_identity_projections,
    record_subject_change,
    require_eligible_subject,
    resolve_source_record_observation,
)
from packages.helios_core.provenance import (
    BronzeObservation,
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

DATABASE_URL = get_settings().database_url
_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def concurrent_sessions(disposable_database_engine: Engine) -> Iterator[sessionmaker[Session]]:
    engine = disposable_database_engine
    subprocess.run(
        ["alembic", "-c", str(_REPO_ROOT / "alembic.ini"), "upgrade", "head"],
        check=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
    )
    yield sessionmaker(bind=engine, expire_on_commit=False)


def _decision() -> DecisionMetadata:
    now = datetime.now(UTC)
    return DecisionMetadata(
        confidence=Decimal("0.9"),
        method="concurrency-test",
        method_version="1",
        actor_class="rule",
        decided_at=now,
        effective_at=now,
    )


def _source_fixture(session: Session) -> tuple[SourceRecord, Evidence]:
    token = uuid4().hex
    source = Source(namespace=f"concurrency-{token}", kind="fixture")
    session.add(source)
    session.flush()
    record = SourceRecord(source_id=source.id, external_key=token)
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


def _bronze_observation(
    namespace: str,
    external_key: str,
    *,
    canonical_url: str | None = None,
) -> BronzeObservation:
    token = uuid4().hex
    return BronzeObservation(
        source_namespace=namespace,
        source_kind="concurrency-fixture",
        external_key=external_key,
        observed_at=datetime.now(UTC),
        content_hash=f"sha256:record-{token}",
        source_payload={"id": external_key, "token": token},
        evidence_locator="$",
        evidence_excerpt_hash=f"sha256:evidence-{token}",
        canonical_url=canonical_url,
        endpoint_kind="https",
        capture_content_hash=f"sha256:capture-{token}",
    )


def test_competing_assignments_serialize_on_source_record(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        record, evidence = _source_fixture(setup)
        first = create_organization(setup)
        second = create_organization(setup)
        setup.commit()
        admit_source_record(
            setup,
            source_record_id=record.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )
        setup.commit()
        record_id = record.id
        evidence_id = evidence.id
        target_ids = (first.id, second.id)

    barrier = Barrier(2)

    def assign(target_id: int) -> str:
        with concurrent_sessions() as worker:
            barrier.wait()
            try:
                assign_source_record(
                    worker,
                    source_record_id=record_id,
                    to_subject_id=target_id,
                    decision=_decision(),
                    evidence_ids=[evidence_id],
                )
                worker.commit()
            except (DBAPIError, ValueError):
                worker.rollback()
                return "rejected"
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assign, target_ids))
    assert sorted(results) == ["committed", "rejected"]

    with concurrent_sessions() as verify:
        current = verify.get(CurrentResolution, record_id)
        assert current is not None
        assert current.state == "resolved"
        assert current.subject_id in target_ids
        assign_count = verify.scalar(
            select(func.count())
            .select_from(ResolutionEvent)
            .where(
                ResolutionEvent.source_record_id == record_id,
                ResolutionEvent.operation == "assign",
            )
        )
        assert assign_count == 1


def test_resolution_lock_is_compatible_with_concurrent_bronze_version_fks(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        record, evidence = _source_fixture(setup)
        first = create_organization(setup)
        second = create_organization(setup)
        setup.commit()
        admit_source_record(
            setup,
            source_record_id=record.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )
        setup.commit()
        record_id = record.id
        source_id = record.source_id
        evidence_id = evidence.id
        target_ids = (first.id, second.id)

    barrier = Barrier(2)

    def append_then_assign(target_id: int) -> str:
        with concurrent_sessions() as worker:
            token = uuid4().hex
            worker.add(
                SourceRecordVersion(
                    source_id=source_id,
                    source_record_id=record_id,
                    observed_at=datetime.now(UTC),
                    content_hash=f"sha256:{token}",
                    source_payload={"id": token},
                )
            )
            worker.flush()
            barrier.wait()
            try:
                assign_source_record(
                    worker,
                    source_record_id=record_id,
                    to_subject_id=target_id,
                    decision=_decision(),
                    evidence_ids=[evidence_id],
                )
                worker.commit()
            except ValueError:
                worker.rollback()
                return "rejected"
            except DBAPIError as exc:
                worker.rollback()
                return str(getattr(exc.orig, "sqlstate", None))
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append_then_assign, target_ids))
    assert sorted(results) == ["committed", "rejected"]
    assert "40P01" not in results


def test_subject_change_then_resolution_uses_one_cross_workflow_lock_order(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        record, evidence = _source_fixture(setup)
        retiring = create_place(setup)
        survivor = create_place(setup)
        adjudication = create_adjudication(
            setup,
            actor="cross-workflow-reviewer",
            rationale="Merge the duplicate and resolve the owning source record.",
            decided_at=datetime.now(UTC),
        )
        setup.commit()
        admit_source_record(
            setup,
            source_record_id=record.id,
            decision=_decision(),
            evidence_ids=[evidence.id],
        )
        setup.commit()
        record_id = record.id
        evidence_id = evidence.id
        retiring_id = retiring.id
        survivor_id = survivor.id
        adjudication_id = adjudication.id

    change_applied = Event()
    assignment_pid_ready = Event()
    assignment_pid: list[int] = []

    def competing_assignment() -> str:
        with concurrent_sessions() as worker:
            assert change_applied.wait(timeout=5)
            backend_pid = worker.scalar(select(func.pg_backend_pid()))
            assert backend_pid is not None
            assignment_pid.append(backend_pid)
            assignment_pid_ready.set()
            try:
                assign_source_record(
                    worker,
                    source_record_id=record_id,
                    to_subject_id=retiring_id,
                    decision=_decision(),
                    evidence_ids=[evidence_id],
                )
                worker.commit()
            except ValueError:
                worker.rollback()
                return "rejected"
            except DBAPIError as exc:
                worker.rollback()
                return str(getattr(exc.orig, "sqlstate", None))
            return "committed"

    def merge_then_assign() -> str:
        with concurrent_sessions() as worker:
            record_subject_change(
                worker,
                operation="merge",
                input_subject_ids=[retiring_id, survivor_id],
                output_subject_ids=[survivor_id],
                decision=_decision(),
                adjudication_id=adjudication_id,
            )
            change_applied.set()
            assert assignment_pid_ready.wait(timeout=5)

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                wait_event_type = worker.scalar(
                    text(
                        """
                        SELECT wait_event_type
                        FROM pg_stat_activity
                        WHERE pid = :pid
                        """
                    ),
                    {"pid": assignment_pid[0]},
                )
                if wait_event_type == "Lock":
                    break
                time.sleep(0.01)
            else:
                worker.rollback()
                return "assignment-did-not-block"

            try:
                assign_source_record(
                    worker,
                    source_record_id=record_id,
                    to_subject_id=survivor_id,
                    decision=_decision(),
                    evidence_ids=[evidence_id],
                )
                worker.commit()
            except (DBAPIError, ValueError) as exc:
                worker.rollback()
                if isinstance(exc, DBAPIError):
                    return str(getattr(exc.orig, "sqlstate", None))
                return "rejected"
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        competing = pool.submit(competing_assignment)
        composed = pool.submit(merge_then_assign)
        results = [competing.result(timeout=10), composed.result(timeout=10)]

    assert sorted(results) == ["committed", "rejected"]
    assert "40P01" not in results


def test_overlapping_subject_changes_lock_members_in_stable_order(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        first = create_place(setup)
        shared = create_place(setup)
        third = create_place(setup)
        first_adjudication = create_adjudication(
            setup,
            actor="reviewer-one",
            rationale="First overlapping merge.",
            decided_at=datetime.now(UTC),
        )
        second_adjudication = create_adjudication(
            setup,
            actor="reviewer-two",
            rationale="Second overlapping merge.",
            decided_at=datetime.now(UTC),
        )
        setup.commit()
        first_id, shared_id, third_id = first.id, shared.id, third.id
        adjudication_ids = (first_adjudication.id, second_adjudication.id)

    barrier = Barrier(2)
    changes = (
        ([first_id, shared_id], [first_id], adjudication_ids[0]),
        ([shared_id, third_id], [third_id], adjudication_ids[1]),
    )

    def merge(args: tuple[list[int], list[int], int]) -> str:
        inputs, outputs, adjudication_id = args
        with concurrent_sessions() as worker:
            barrier.wait()
            try:
                record_subject_change(
                    worker,
                    operation="merge",
                    input_subject_ids=inputs,
                    output_subject_ids=outputs,
                    decision=_decision(),
                    adjudication_id=adjudication_id,
                )
                worker.commit()
            except (DBAPIError, ValueError):
                worker.rollback()
                return "rejected"
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(merge, changes))
    assert sorted(results) == ["committed", "rejected"]

    with concurrent_sessions() as verify:
        change_count = verify.scalar(
            select(func.count())
            .select_from(SubjectChange)
            .where(SubjectChange.adjudication_id.in_(adjudication_ids))
        )
        shared_currentness = verify.get(SubjectCurrentness, shared_id)
        assert change_count == 1
        assert shared_currentness is not None
        assert not shared_currentness.is_current


def test_raw_overlapping_subject_changes_serialize_without_lock_upgrade_deadlock(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        first = create_place(setup)
        shared = create_place(setup)
        third = create_place(setup)
        adjudications = [
            create_adjudication(
                setup,
                actor=f"raw-reviewer-{index}",
                rationale="Exercise deferred database locking without commands.",
                decided_at=datetime.now(UTC),
            )
            for index in (1, 2)
        ]
        setup.commit()
        first_id, shared_id, third_id = first.id, shared.id, third.id
        adjudication_ids = [adjudication.id for adjudication in adjudications]

    barrier = Barrier(2)
    changes = (
        ([first_id, shared_id], first_id, adjudication_ids[0]),
        ([shared_id, third_id], third_id, adjudication_ids[1]),
    )

    def raw_merge(args: tuple[list[int], int, int]) -> str:
        inputs, output, adjudication_id = args
        with concurrent_sessions() as worker:
            now = datetime.now(UTC)
            change = SubjectChange(
                operation="merge",
                adjudication_id=adjudication_id,
                confidence=Decimal("0.9"),
                method="raw-concurrency-test",
                method_version="1",
                actor_class="rule",
                decided_at=now,
                effective_at=now,
            )
            worker.add(change)
            worker.flush()
            worker.add_all(
                [
                    SubjectChangeMember(
                        subject_change_id=change.id,
                        subject_id=subject_id,
                        subject_kind="place",
                        role="input",
                    )
                    for subject_id in inputs
                ]
                + [
                    SubjectChangeMember(
                        subject_change_id=change.id,
                        subject_id=output,
                        subject_kind="place",
                        role="output",
                    )
                ]
            )
            worker.flush()
            barrier.wait()
            try:
                worker.execute(
                    text("SET CONSTRAINTS identity.ct_subject_change_complete_and_apply IMMEDIATE")
                )
                worker.commit()
            except DBAPIError as exc:
                worker.rollback()
                return str(getattr(exc.orig, "sqlstate", None))
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(raw_merge, changes))
    assert sorted(results) == ["23514", "committed"]
    assert "40P01" not in results


def test_committed_subjects_are_not_new_change_outputs(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        subjects = [create_place(setup) for _ in range(6)]
        merge_adjudication = create_adjudication(
            setup,
            actor="merge-reviewer",
            rationale="Committed output must be recorded as a survivor.",
            decided_at=datetime.now(UTC),
        )
        split_adjudication = create_adjudication(
            setup,
            actor="split-reviewer",
            rationale="Split outputs must be created with the change.",
            decided_at=datetime.now(UTC),
        )
        setup.commit()
        subject_ids = [subject.id for subject in subjects]
        merge_adjudication_id = merge_adjudication.id
        split_adjudication_id = split_adjudication.id

    with concurrent_sessions() as merge_session:
        with pytest.raises(DBAPIError, match="existing merge survivor"):
            record_subject_change(
                merge_session,
                operation="merge",
                input_subject_ids=subject_ids[:2],
                output_subject_ids=[subject_ids[2]],
                decision=_decision(),
                adjudication_id=merge_adjudication_id,
            )
        merge_session.rollback()

    with concurrent_sessions() as split_session:
        with pytest.raises(DBAPIError, match="split outputs must be new"):
            record_subject_change(
                split_session,
                operation="split",
                input_subject_ids=[subject_ids[3]],
                output_subject_ids=subject_ids[4:],
                decision=_decision(),
                adjudication_id=split_adjudication_id,
            )
        split_session.rollback()


def test_eligibility_gate_locks_subject_against_retirement(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        guarded = create_place(setup, address="100 Guarded St")
        survivor = create_place(setup)
        adjudication = create_adjudication(
            setup,
            actor="retirement-reviewer",
            rationale="Concurrent retirement must wait for the gated write.",
            decided_at=datetime.now(UTC),
        )
        mark_subject_eligible(setup, guarded.id)
        setup.commit()
        guarded_id = guarded.id
        survivor_id = survivor.id
        adjudication_id = adjudication.id

    with concurrent_sessions() as gated_write:
        require_eligible_subject(gated_write, guarded_id)

        def attempt_retirement() -> str:
            with concurrent_sessions() as worker:
                worker.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    record_subject_change(
                        worker,
                        operation="merge",
                        input_subject_ids=[guarded_id, survivor_id],
                        output_subject_ids=[survivor_id],
                        decision=_decision(),
                        adjudication_id=adjudication_id,
                    )
                    worker.commit()
                except DBAPIError:
                    worker.rollback()
                    return "blocked"
                return "committed"

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(attempt_retirement).result(timeout=5) == "blocked"


def test_eligibility_gate_locks_typed_features(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        guarded = create_place(setup, address="200 Guarded Feature St")
        mark_subject_eligible(setup, guarded.id)
        setup.commit()
        guarded_id = guarded.id

    with concurrent_sessions() as gated_write:
        require_eligible_subject(gated_write, guarded_id)

        def remove_only_feature() -> str:
            with concurrent_sessions() as worker:
                worker.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    worker.execute(
                        text(
                            """
                            UPDATE identity.place
                            SET address = NULL
                            WHERE subject_id = :subject_id
                            """
                        ),
                        {"subject_id": guarded_id},
                    )
                    worker.commit()
                except DBAPIError:
                    worker.rollback()
                    return "blocked"
                return "committed"

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(remove_only_feature).result(timeout=5) == "blocked"


def test_decision_members_reject_late_insert_after_commit(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    with concurrent_sessions() as setup:
        record, first_evidence = _source_fixture(setup)
        version = setup.get(SourceRecordVersion, first_evidence.source_record_version_id)
        assert version is not None
        second_evidence = Evidence(
            source_record_version_id=version.id,
            locator="$.second",
            excerpt_hash=f"sha256:{uuid4().hex}",
        )
        first = create_place(setup)
        second = create_place(setup)
        late_member = create_place(setup)
        adjudication = create_adjudication(
            setup,
            actor="aggregate-reviewer",
            rationale="Seal the Subject-change aggregate.",
            decided_at=datetime.now(UTC),
        )
        setup.add(second_evidence)
        setup.flush()
        event = admit_source_record(
            setup,
            source_record_id=record.id,
            decision=_decision(),
            evidence_ids=[first_evidence.id],
        )
        change = record_subject_change(
            setup,
            operation="merge",
            input_subject_ids=[first.id, second.id],
            output_subject_ids=[first.id],
            decision=_decision(),
            adjudication_id=adjudication.id,
        )
        setup.commit()
        event_id = event.id
        change_id = change.id
        second_evidence_id = second_evidence.id
        late_member_id = late_member.id

    for late_row in (
        ResolutionEvidence(
            resolution_event_id=event_id,
            evidence_id=second_evidence_id,
        ),
        SubjectChangeEvidence(
            subject_change_id=change_id,
            evidence_id=second_evidence_id,
        ),
        SubjectChangeMember(
            subject_change_id=change_id,
            subject_id=late_member_id,
            subject_kind="place",
            role="input",
        ),
    ):
        with concurrent_sessions() as writer:
            writer.add(late_row)
            with pytest.raises(DBAPIError, match="only be inserted with their parent"):
                writer.flush()
            writer.rollback()


def test_projection_rebuild_fails_fast_while_an_identity_writer_is_active(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    writer_ready = Event()
    release_writer = Event()

    def hold_identity_writer() -> None:
        with concurrent_sessions() as writer:
            create_place(writer)
            writer_ready.set()
            assert release_writer.wait(timeout=5)
            writer.rollback()

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(hold_identity_writer)
        assert writer_ready.wait(timeout=5)
        try:
            with concurrent_sessions() as rebuild:
                create_place(rebuild)
                with pytest.raises(
                    DBAPIError,
                    match="only be rebuilt without concurrent writers",
                ) as exc_info:
                    rebuild_identity_projections(rebuild)
                assert getattr(exc_info.value.orig, "sqlstate", None) == "55000"
                rebuild.rollback()
        finally:
            release_writer.set()
        writer.result(timeout=5)


def test_concurrent_reobservation_reuses_one_external_key_and_open_event(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    token = uuid4().hex
    namespace = f"concurrent-step4-key-{token}"
    barrier = Barrier(2)

    def observe() -> tuple[str, int | None]:
        with concurrent_sessions() as worker:
            barrier.wait()
            try:
                result = resolve_source_record_observation(
                    worker,
                    observation=_bronze_observation(namespace, "same-key"),
                    decided_at=datetime.now(UTC),
                )
                worker.commit()
            except (DBAPIError, ValueError):
                worker.rollback()
                return ("rejected", None)
            return (result.state, result.source_record_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: observe(), range(2)))

    assert [state for state, _ in results] == ["unresolved", "unresolved"]
    record_ids = {record_id for _, record_id in results}
    assert len(record_ids) == 1
    record_id = record_ids.pop()
    assert record_id is not None

    with concurrent_sessions() as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(SourceRecordVersion)
                .where(SourceRecordVersion.source_record_id == record_id)
            )
            == 2
        )
        assert (
            verify.scalar(
                select(func.count())
                .select_from(ResolutionEvent)
                .where(
                    ResolutionEvent.source_record_id == record_id,
                    ResolutionEvent.operation == "open",
                )
            )
            == 1
        )


def test_concurrent_identical_retry_reuses_one_bronze_observation(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    token = uuid4().hex
    observation = _bronze_observation(
        f"concurrent-step4-retry-{token}",
        "same-key",
    )
    barrier = Barrier(2)

    def observe() -> tuple[bool, int, int, int]:
        with concurrent_sessions() as worker:
            barrier.wait()
            result = resolve_source_record_observation(
                worker,
                observation=observation,
                decided_at=datetime.now(UTC),
            )
            worker.commit()
            return (
                result.observation_created,
                result.capture_id,
                result.source_record_version_id,
                result.evidence_id,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: observe(), range(2)))

    assert sorted(created for created, *_ in results) == [False, True]
    assert len({result[1:] for result in results}) == 1


def test_concurrent_exact_url_matches_serialize_and_resolve_consistently(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    token = uuid4().hex
    namespace = f"concurrent-step4-url-{token}"
    url = f"https://concurrent-{token}.example.test/"
    with concurrent_sessions() as setup:
        anchor = resolve_source_record_observation(
            setup,
            observation=_bronze_observation(
                namespace,
                "anchor",
                canonical_url=url,
            ),
            decided_at=datetime.now(UTC),
        )
        target = create_organization(setup)
        assign_source_record(
            setup,
            source_record_id=anchor.source_record_id,
            to_subject_id=target.id,
            decision=_decision(),
            evidence_ids=[anchor.evidence_id],
        )
        setup.commit()
        target_id = target.id

    barrier = Barrier(2)

    def observe(external_key: str) -> tuple[str, int | None]:
        with concurrent_sessions() as worker:
            barrier.wait()
            try:
                result = resolve_source_record_observation(
                    worker,
                    observation=_bronze_observation(
                        namespace,
                        external_key,
                        canonical_url=url,
                    ),
                    decided_at=datetime.now(UTC),
                )
                worker.commit()
            except (DBAPIError, ValueError):
                worker.rollback()
                return ("rejected", None)
            return (result.state, result.subject_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(observe, ("candidate-1", "candidate-2")))

    assert results == [("resolved", target_id), ("resolved", target_id)]


def test_url_resolution_serializes_against_explicit_same_url_assignment(
    concurrent_sessions: sessionmaker[Session],
) -> None:
    token = uuid4().hex
    namespace = f"concurrent-step4-explicit-url-{token}"
    url = f"https://explicit-{token}.example.test/"
    with concurrent_sessions() as setup:
        anchor = resolve_source_record_observation(
            setup,
            observation=_bronze_observation(
                namespace,
                "anchor",
                canonical_url=url,
            ),
            decided_at=datetime.now(UTC),
        )
        explicit_candidate = resolve_source_record_observation(
            setup,
            observation=_bronze_observation(
                namespace,
                "explicit-candidate",
                canonical_url=url,
            ),
            decided_at=datetime.now(UTC),
        )
        first_subject = create_organization(setup)
        second_subject = create_organization(setup)
        assign_source_record(
            setup,
            source_record_id=anchor.source_record_id,
            to_subject_id=first_subject.id,
            decision=_decision(),
            evidence_ids=[anchor.evidence_id],
        )
        setup.commit()
        explicit_candidate_id = explicit_candidate.source_record_id
        explicit_evidence_id = explicit_candidate.evidence_id
        second_subject_id = second_subject.id

    resolver_pid_ready = Event()
    resolver_pid: list[int] = []

    def resolve_candidate() -> tuple[str, int | None, int]:
        with concurrent_sessions() as worker:
            backend_pid = worker.scalar(select(func.pg_backend_pid()))
            assert backend_pid is not None
            resolver_pid.append(backend_pid)
            resolver_pid_ready.set()
            result = resolve_source_record_observation(
                worker,
                observation=_bronze_observation(
                    namespace,
                    "url-candidate",
                    canonical_url=url,
                ),
                decided_at=datetime.now(UTC),
            )
            worker.commit()
            return (result.state, result.subject_id, result.source_record_id)

    with concurrent_sessions() as explicit_writer:
        assign_source_record(
            explicit_writer,
            source_record_id=explicit_candidate_id,
            to_subject_id=second_subject_id,
            decision=_decision(),
            evidence_ids=[explicit_evidence_id],
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(resolve_candidate)
            assert resolver_pid_ready.wait(timeout=5)

            blocked = False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                wait_event_type = explicit_writer.scalar(
                    text(
                        """
                        SELECT wait_event_type
                        FROM pg_stat_activity
                        WHERE pid = :pid
                        """
                    ),
                    {"pid": resolver_pid[0]},
                )
                if wait_event_type == "Lock":
                    blocked = True
                    break
                time.sleep(0.01)

            explicit_writer.commit()
            result = future.result(timeout=10)

    assert blocked, "URL resolver did not lock every same-URL Source Record"
    assert result[:2] == ("unresolved", None)
    with concurrent_sessions() as verify:
        current = verify.get(CurrentResolution, result[2])
        assert current is not None
        assert (current.state, current.subject_id) == ("unresolved", None)
