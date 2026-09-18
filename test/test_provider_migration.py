"""Seeded provider rows and exact schema preservation at the new boundary."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from packages.helios_core.identity import (
    SubjectName,
    create_adjudication,
    create_organization,
    record_subject_change,
)
from test.provider_support import HEAD, PARENT, PROVIDER_FUNCTIONS, decision, migrate, seed_scope
from test.test_legacy_identity_reset import _function_definitions, _schema_signature

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

SQL_DIRECTORY = Path(__file__).resolve().parents[1] / "docs/reviews/sql"


def sequence_state(connection: Connection) -> dict[str, tuple[int, bool]]:
    return {
        f"{schema}.{sequence}": tuple(
            connection.execute(
                text(f'SELECT last_value, is_called FROM "{schema}"."{sequence}"')
            ).one()
        )
        for schema in ("bronze", "identity")
        for sequence in inspect(connection).get_sequence_names(schema=schema)
    }


def provider_rows(connection: Connection) -> dict[str, list[str]]:
    """Compare every column of every row, not only counts or selected IDs."""
    return {
        f"{schema}.{table}": list(
            connection.scalars(
                text(
                    f'SELECT to_jsonb(t)::text FROM "{schema}"."{table}" t ORDER BY to_jsonb(t)::text'
                )
            )
        )
        for schema in ("bronze", "identity")
        for table in inspect(connection).get_table_names(schema=schema)
    }


def signatures(connection: Connection) -> dict[str, dict[str, object]]:
    return {schema: _schema_signature(connection, schema) for schema in ("bronze", "identity")}


@pytest.mark.parametrize("concrete_sql", [False, True], ids=["alembic", "sql-artifacts"])
def test_seeded_provider_upgrade_downgrade_reupgrade(
    disposable_database_engine: Engine, concrete_sql: bool
) -> None:
    engine = disposable_database_engine

    def apply(direction: str) -> None:
        target = PARENT if direction == "downgrade" else HEAD
        if concrete_sql:
            sql = (SQL_DIRECTORY / f"0002-step-5-provider-{direction}.sql").read_text()
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql(sql)
        else:
            migrate(direction, target)
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM public.alembic_version")) == target
            )

    migrate("upgrade", "head")
    with Session(engine) as setup, setup.begin():
        fixture = seed_scope(setup)
        setup.add(
            SubjectName(
                subject_id=fixture.organization.subject_id,
                subject_kind="organization",
                name="Migration fixture",
                name_kind="alias",
                name_fingerprint="migration-fixture",
                evidence_id=fixture.shared_input.evidence_id,
            )
        )
        adjudication = create_adjudication(
            setup,
            actor="migration-fixture",
            rationale="preserve complete history",
            decided_at=decision().decided_at,
        )
        other = create_organization(setup)
        record_subject_change(
            setup,
            operation="merge",
            input_subject_ids=(fixture.organization.subject_id, other.id),
            output_subject_ids=(fixture.organization.subject_id,),
            decision=decision(),
            adjudication_id=adjudication.id,
            evidence_ids=(fixture.shared_input.evidence_id,),
        )
    with engine.connect() as connection:
        seeded = provider_rows(connection)
        sequences = sequence_state(connection)
        assert len(seeded) == 21
        assert all(seeded.values()), "seed all six Bronze and fifteen Identity tables"
    try:
        apply("downgrade")
        with engine.connect() as connection:
            parent = signatures(connection)
            assert provider_rows(connection) == seeded
            assert sequence_state(connection) == sequences
        apply("upgrade")
        with engine.connect() as connection:
            head = signatures(connection)
            assert provider_rows(connection) == seeded
            assert sequence_state(connection) == sequences
            for schema in ("bronze", "identity"):
                for part in ("tables", "views", "sequences", "triggers"):
                    assert parent[schema][part] == head[schema][part]
                old_functions = _function_definitions(parent[schema])
                new_functions = _function_definitions(head[schema])
                assert new_functions.keys() == old_functions.keys() | PROVIDER_FUNCTIONS[schema]
                assert {name: new_functions[name] for name in old_functions} == old_functions
        apply("downgrade")
        with engine.connect() as connection:
            assert signatures(connection) == parent
            assert provider_rows(connection) == seeded
            assert sequence_state(connection) == sequences
        apply("upgrade")
        with engine.connect() as connection:
            assert signatures(connection) == head
            assert provider_rows(connection) == seeded
            assert sequence_state(connection) == sequences
    finally:
        migrate("upgrade", "head")


def test_provider_offline_sql_is_available_in_both_directions() -> None:
    upgrade = migrate("upgrade", f"{PARENT}:{HEAD}", "--sql")
    downgrade = migrate("downgrade", f"{HEAD}:{PARENT}", "--sql")
    for direction, generated in (("upgrade", upgrade), ("downgrade", downgrade)):
        artifact = (SQL_DIRECTORY / f"0002-step-5-provider-{direction}.sql").read_text()
        assert artifact.rstrip() == generated.rstrip()
    for schema, functions in PROVIDER_FUNCTIONS.items():
        for function in functions:
            assert f"CREATE FUNCTION {schema}.{function}(" in upgrade
            assert f"DROP FUNCTION {schema}.{function}(" in downgrade
    assert "CREATE TABLE" not in upgrade
    assert "DROP TABLE" not in downgrade
    assert "CASCADE" not in downgrade
