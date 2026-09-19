"""Real connections, observed blocking, both race orders and whole retries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from packages.helios_core.domains.menu.commands import persist_menu, read_aggregate
from packages.helios_core.domains.menu.contracts import MenuAggregate, MenuConflictError
from packages.helios_core.identity import SubjectNotEligibleError, rebuild_identity_projections
from packages.helios_core.provenance import Source, SourceRecordVersion
from test.menu_support import aggregate, force, inherited, raw_page, raw_page_support, successor
from test.test_menu_replay import menu_scopes as menu_scopes
from test.test_provider_concurrency import limits, mutate, wait_blocked

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import sessionmaker

    from test.provider_support import ScopeFixture


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
def test_menu_scope_races_both_orders(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], change: str, admit_first: bool
) -> None:
    factory, scope = menu_scopes
    ready = Event()
    pids = []

    def worker() -> bool:
        with factory() as session:
            limits(session)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            try:
                if admit_first:
                    mutate(session, scope, change)
                else:
                    persist_menu(session, aggregate(scope))
                force(session)
                session.commit()
                return True
            except SubjectNotEligibleError:
                session.rollback()
                return False

    with factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
        limits(first)
        if admit_first:
            result = persist_menu(first, aggregate(scope))
        else:
            mutate(first, scope, change)
        future = pool.submit(worker)
        try:
            assert ready.wait(5)
            wait_blocked(factory, pids[0])
        finally:
            first.commit()
        assert future.result(timeout=15) is admit_first
    with factory() as reader:
        if admit_first:
            assert read_aggregate(reader, result.page_id)[0] == aggregate(scope)
        else:
            assert (
                reader.scalar(
                    text("SELECT count(*) FROM menu.menu_page WHERE source_record_id=:r"),
                    {"r": scope.establishment.source_record_id},
                )
                == 0
            )


@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_concurrent_replay_is_one_aggregate_or_payload_conflict(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], conflict: bool, reverse: bool
) -> None:
    factory, scope = menu_scopes
    original = aggregate(scope)
    changed = (
        replace(original, prices=(replace(original.prices[0], amount_minor=1200),))
        if conflict
        else original
    )
    values = [original, changed]
    if reverse:
        values.reverse()
    ready = Event()
    pids = []

    def worker() -> int | None:
        with factory() as session:
            limits(session)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            try:
                result = persist_menu(session, values[1])
                session.commit()
                assert result.replayed
                return result.page_id
            except MenuConflictError:
                session.rollback()
                return None

    with factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
        result = persist_menu(first, values[0])
        future = pool.submit(worker)
        try:
            assert ready.wait(5)
            wait_blocked(factory, pids[0])
        finally:
            first.commit()
        assert future.result(timeout=15) == (None if conflict else result.page_id)
    with factory() as reader:
        assert (
            reader.scalar(
                text("SELECT count(*) FROM menu.menu_page WHERE source_record_id=:r"),
                {"r": scope.establishment.source_record_id},
            )
            == 1
        )


@pytest.mark.parametrize("reverse", [False, True])
def test_competing_successors_do_not_rewrite_intent(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], reverse: bool
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as setup:
        base = persist_menu(setup, value)
    one = successor(value, base.page_id)
    two = replace(one, prices=(replace(one.prices[0], amount_minor=1234),))
    if reverse:
        one, two = two, one
    ready = Event()
    pids = []

    def worker() -> None:
        with factory() as session:
            limits(session)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            with pytest.raises(MenuConflictError):
                persist_menu(session, two)
            session.rollback()

    with factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
        persist_menu(first, one)
        future = pool.submit(worker)
        try:
            assert ready.wait(5)
            wait_blocked(factory, pids[0])
        finally:
            first.commit()
        future.result(timeout=15)
    with factory() as reader:
        assert (
            reader.scalar(
                text("SELECT count(*) FROM menu.menu_page WHERE supersedes_page_id=:p"),
                {"p": base.page_id},
            )
            == 1
        )


@pytest.mark.parametrize("admit_first", [False, True])
def test_pin_withdrawal_race_both_orders(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], admit_first: bool
) -> None:
    factory, scope = menu_scopes
    shared = aggregate(scope, shared=True)
    with factory.begin() as setup:
        base = persist_menu(setup, shared)
    local = inherited(aggregate(scope), base)
    withdrawal = MenuAggregate(
        page=replace(successor(shared, base.page_id).page, operation="withdrawal")
    )
    ready = Event()
    pids = []

    def worker() -> bool:
        with factory() as session:
            limits(session)
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            try:
                persist_menu(session, withdrawal if admit_first else local)
                force(session)
                session.commit()
                return True
            except DBAPIError as error:
                assert not admit_first and error.orig.diag.constraint_name == "ck_menu_base"  # type: ignore[union-attr]
                session.rollback()
                return False

    with factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
        persist_menu(first, local if admit_first else withdrawal)
        future = pool.submit(worker)
        try:
            assert ready.wait(5)
            wait_blocked(factory, pids[0])
        finally:
            first.commit()
        assert future.result(timeout=15) is admit_first


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("change", ["base_withdrawal", "remap", "unassign", "correction"])
def test_stale_snapshot_full_40001_rollback_and_retry(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
    disposable_database_engine: Engine,
    isolation: str,
    raw: bool,
    change: str,
) -> None:
    factory, scope = menu_scopes
    shared = aggregate(scope, shared=True)
    with factory.begin() as setup:
        base = persist_menu(setup, shared)
    value = inherited(aggregate(scope), base)
    marker = f"menu-retry-{uuid4().hex}"
    with (
        disposable_database_engine.connect().execution_options(
            isolation_level=isolation
        ) as connection,
        Session(connection) as stale,
    ):
        limits(stale)
        stale.add(Source(namespace=marker, kind="rollback-probe"))
        stale.flush()
        with factory.begin() as writer:
            if change == "base_withdrawal":
                persist_menu(
                    writer,
                    MenuAggregate(
                        page=replace(successor(shared, base.page_id).page, operation="withdrawal")
                    ),
                )
            elif change == "correction":
                persist_menu(writer, successor(shared, base.page_id))
            else:
                mutate(writer, scope, change)
        with pytest.raises(DBAPIError) as error:
            if raw:
                raw_page(stale, value)
            else:
                persist_menu(stale, value)
        assert getattr(error.value.orig, "sqlstate", None) == "40001"
        stale.rollback()
        assert (
            stale.scalar(
                text("SELECT count(*) FROM bronze.source WHERE namespace=:n"), {"n": marker}
            )
            == 0
        )
        if change == "correction":
            # Ordinary supersession preserves the old pin after a fresh snapshot.
            if raw:
                page = raw_page(stale, value)
                raw_page_support(stale, page, scope.local_input.evidence_id)
            else:
                persist_menu(stale, value)
            force(stale)
            stale.commit()
        else:
            with pytest.raises((DBAPIError, SubjectNotEligibleError)):
                raw_page(stale, value) if raw else persist_menu(stale, value)
            stale.rollback()


def test_composed_deadlock_rolls_back_entire_menu_attempt(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    barrier = Barrier(2)
    token = uuid4().hex

    def worker(index: int) -> str:
        marker = f"menu-deadlock-{token}-{index}"
        value = aggregate(scope, root=f"root-{index}")
        with factory() as session:
            limits(session)
            session.add(Source(namespace=marker, kind="rollback-probe"))
            session.flush()
            if index == 0:
                session.execute(
                    text("SELECT id FROM identity.subject WHERE id=:id FOR NO KEY UPDATE"),
                    {"id": scope.establishment.subject_id},
                )
            else:
                session.execute(
                    text("SELECT id FROM bronze.source_record WHERE id=:id FOR NO KEY UPDATE"),
                    {"id": scope.establishment.source_record_id},
                )
            barrier.wait(timeout=5)
            try:
                persist_menu(session, value)
                session.commit()
                return "committed"
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "40P01"
                session.rollback()
        with factory.begin() as retry:
            assert (
                retry.scalar(
                    text("SELECT count(*) FROM bronze.source WHERE namespace=:n"), {"n": marker}
                )
                == 0
            )
            assert (
                retry.scalar(
                    text(
                        "SELECT count(*) FROM menu.menu_page WHERE source_record_id=:r AND root_key=:k"
                    ),
                    {"r": scope.establishment.source_record_id, "k": value.page.root_key},
                )
                == 0
            )
            persist_menu(retry, value)
            retry.add(Source(namespace=marker, kind="whole-transaction-retry"))
            force(retry)
        return "retried"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, i) for i in range(2)]
        assert sorted(f.result(timeout=20) for f in futures) == ["committed", "retried"]


def test_bronze_fk_and_projection_rebuild_boundaries(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    with factory() as admitting:
        persist_menu(admitting, aggregate(scope))
        with factory.begin() as bronze:
            limits(bronze)
            original = bronze.get(SourceRecordVersion, scope.local_input.source_record_version_id)
            assert original
            bronze.add(
                SourceRecordVersion(
                    source_record_id=original.source_record_id,
                    source_id=original.source_id,
                    capture_id=original.capture_id,
                    observed_at=original.observed_at,
                    content_hash="concurrent",
                    source_payload={},
                )
            )
        with factory() as rebuilding, pytest.raises(DBAPIError):
            rebuild_identity_projections(rebuilding)
        admitting.commit()
    with factory.begin() as rebuilding:
        rebuild_identity_projections(rebuilding)
