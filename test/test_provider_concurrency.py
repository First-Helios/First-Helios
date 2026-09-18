"""Real commits and blocking proofs for the provider prerequisite only."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from packages.helios_core.identity import (
    SubjectNotEligibleError,
    create_establishment,
    mark_subject_eligible,
    rebuild_identity_projections,
    record_subject_change,
    remap_source_record,
    unassign_source_record,
)
from packages.helios_core.identity.contracts import require_resolved_scopes
from packages.helios_core.provenance import Source, SourceRecordVersion
from test.provider_support import ScopeFixture, decision, migrate, seed_scope

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture(name="scopes")
def provider_scopes(
    disposable_database_engine: Engine,
) -> tuple[sessionmaker[Session], ScopeFixture]:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    with factory.begin() as session:
        fixture = seed_scope(session)
    return factory, fixture


def limits(session: Session) -> None:
    session.execute(text("SET LOCAL lock_timeout = '8s'"))
    session.execute(text("SET LOCAL statement_timeout = '12s'"))


def wait_blocked(factory: sessionmaker[Session], pid: int) -> None:
    deadline = time.monotonic() + 5
    with factory() as observer:
        while time.monotonic() < deadline:
            if observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
            ):
                return
            time.sleep(0.01)
    pytest.fail(f"connection {pid} did not block as expected")


def mutate(session: Session, fixture: ScopeFixture, change: str) -> None:
    if change in {"readiness", "parent_readiness"}:
        target = fixture.establishment.subject_id if change == "readiness" else fixture.place_id
        session.execute(
            text("UPDATE identity.subject SET readiness='provisional' WHERE id=:id"), {"id": target}
        )
    elif change == "parent_feature":
        session.execute(
            text("UPDATE identity.place SET address=NULL WHERE subject_id=:id"),
            {"id": fixture.place_id},
        )
    elif change == "organization_feature":
        session.execute(
            text(
                "UPDATE identity.organization SET canonical_name=NULL, "
                "name_fingerprint=NULL WHERE subject_id=:id"
            ),
            {"id": fixture.organization.subject_id},
        )
    elif change in {"unassign", "readiness_proof"}:
        request = fixture.organization if change == "readiness_proof" else fixture.establishment
        unassign_source_record(
            session,
            source_record_id=request.source_record_id,
            from_subject_id=request.subject_id,
            decision=decision(),
            evidence_ids=(fixture.local_input.evidence_id,),
        )
    elif change == "remap":
        other = create_establishment(
            session,
            organization_subject_id=fixture.organization.subject_id,
            place_subject_id=fixture.place_id,
            valid_from=decision().effective_at,
        )
        mark_subject_eligible(session, other.id)
        remap_source_record(
            session,
            source_record_id=fixture.establishment.source_record_id,
            from_subject_id=fixture.establishment.subject_id,
            to_subject_id=other.id,
            decision=decision(),
            evidence_ids=(fixture.local_input.evidence_id,),
        )
    elif change in {"retire", "parent_retire", "split", "merge"}:
        target = (
            fixture.organization.subject_id
            if change == "parent_retire"
            else fixture.establishment.subject_id
        )
        inputs = [target]
        outputs = []
        if change in {"split", "merge"}:
            for _ in range(2 if change == "split" else 1):
                other = create_establishment(
                    session,
                    organization_subject_id=fixture.organization.subject_id,
                    place_subject_id=fixture.place_id,
                    valid_from=decision().effective_at,
                )
                outputs.append(other.id)
            if change == "merge":
                inputs.extend(outputs)  # Other is the surviving merge input.
        record_subject_change(
            session,
            operation=change if change in {"merge", "split"} else "retire",
            input_subject_ids=inputs,
            output_subject_ids=outputs,
            decision=decision(),
            evidence_ids=(fixture.local_input.evidence_id,),
        )
    else:
        raise AssertionError(change)


@pytest.mark.parametrize(
    "change",
    [
        "readiness",
        "parent_readiness",
        "parent_feature",
        "organization_feature",
        "unassign",
        "readiness_proof",
        "remap",
        "retire",
        "parent_retire",
        "split",
        "merge",
    ],
)
@pytest.mark.parametrize("admit_first", [True, False])
def test_scope_change_races_in_both_orders(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
    change: str,
    admit_first: bool,
) -> None:
    factory, fixture = scopes
    started = Event()
    worker_pids: list[int] = []

    def worker() -> bool:
        with factory() as session:
            limits(session)
            worker_pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            started.set()
            if admit_first:
                mutate(session, fixture, change)
                session.commit()
                return True
            try:
                require_resolved_scopes(session, (fixture.establishment,))
                session.commit()
                return True
            except SubjectNotEligibleError:
                session.rollback()
                return False

    with factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
        limits(first)
        if admit_first:
            admitted = require_resolved_scopes(first, (fixture.establishment,))
            assert admitted[0].subject_id == fixture.establishment.subject_id
        else:
            mutate(first, fixture, change)
        future = pool.submit(worker)
        try:
            assert started.wait(5)
            wait_blocked(factory, worker_pids[0])
        finally:
            first.commit()
        assert future.result(timeout=15) is admit_first
    with factory() as after, pytest.raises(SubjectNotEligibleError):
        require_resolved_scopes(after, (fixture.establishment,))


def test_reversed_batches_serialize_as_one_union(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory.begin() as setup:
        other = seed_scope(setup)
    ready = Event()
    pids: list[int] = []

    def reversed_batch() -> None:
        with factory.begin() as session:
            limits(session)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = require_resolved_scopes(session, (other.establishment, fixture.establishment))
            assert result[0].subject_id == other.establishment.subject_id

    with factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
        require_resolved_scopes(first, (fixture.establishment, other.establishment))
        future = pool.submit(reversed_batch)
        try:
            assert ready.wait(5)
            wait_blocked(factory, pids[0])
        finally:
            first.commit()
        future.result(timeout=15)


def test_guard_locks_are_compatible_with_bronze_fk_inserts(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory() as admitting:
        require_resolved_scopes(admitting, (fixture.establishment, fixture.organization))
        with factory.begin() as writer:
            limits(writer)
            original = writer.get(SourceRecordVersion, fixture.local_input.source_record_version_id)
            assert original is not None
            writer.add(
                SourceRecordVersion(
                    source_id=original.source_id,
                    source_record_id=original.source_record_id,
                    capture_id=original.capture_id,
                    observed_at=original.observed_at,
                    content_hash="concurrent-fk",
                    source_payload={},
                )
            )


def test_projection_rebuild_cannot_cross_admission(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory() as admitting:
        require_resolved_scopes(admitting, (fixture.establishment,))
        with factory() as rebuilding, pytest.raises(DBAPIError):
            rebuild_identity_projections(rebuilding)
        admitting.commit()
    with factory.begin() as rebuilding:
        rebuild_identity_projections(rebuilding)
    with factory() as admitting:
        assert require_resolved_scopes(admitting, (fixture.establishment,))


def test_whole_transaction_retry_after_composed_lock_deadlock(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    barrier = Barrier(2)
    token = uuid4().hex

    def contender(index: int) -> tuple[str, str]:
        marker = f"retry-{token}-{index}"
        with factory() as session:
            limits(session)
            session.add(Source(namespace=marker, kind="rollback-probe"))
            session.flush()
            if index == 0:
                session.execute(
                    text("SELECT id FROM identity.subject WHERE id=:id FOR NO KEY UPDATE"),
                    {"id": fixture.establishment.subject_id},
                )
            else:
                session.execute(
                    text("SELECT id FROM bronze.source_record WHERE id=:id FOR NO KEY UPDATE"),
                    {"id": fixture.establishment.source_record_id},
                )
            barrier.wait(timeout=5)
            try:
                require_resolved_scopes(session, (fixture.establishment,))
                session.commit()
                return "committed", marker
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "40P01"
                session.rollback()
        # Start again from an empty transaction: the failed attempt's marker is gone.
        with factory.begin() as retry:
            assert (
                retry.scalar(
                    text("SELECT count(*) FROM bronze.source WHERE namespace=:n"), {"n": marker}
                )
                == 0
            )
            assert require_resolved_scopes(retry, (fixture.establishment,))
            retry.add(Source(namespace=marker, kind="whole-transaction-retry"))
        return "retried", marker

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(contender, index) for index in range(2)]
        outcomes = [future.result(timeout=20) for future in futures]
    assert sorted(state for state, _ in outcomes) == ["committed", "retried"]
    with factory() as session:
        for _, marker in outcomes:
            assert (
                session.scalar(
                    text("SELECT count(*) FROM bronze.source WHERE namespace=:n"), {"n": marker}
                )
                == 1
            )


def test_serialization_failure_propagates_and_retry_revalidates(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
    disposable_database_engine: Engine,
) -> None:
    factory, fixture = scopes
    with (
        disposable_database_engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        Session(connection) as stale,
    ):
        stale.execute(
            text("SELECT readiness FROM identity.subject WHERE id=:id"),
            {"id": fixture.establishment.subject_id},
        )
        with factory.begin() as writer:
            mutate(writer, fixture, "readiness")
        with pytest.raises(DBAPIError) as error:
            require_resolved_scopes(stale, (fixture.establishment,))
        assert getattr(error.value.orig, "sqlstate", None) == "40001"
        stale.rollback()
        with pytest.raises(SubjectNotEligibleError):
            require_resolved_scopes(stale, (fixture.establishment,))
