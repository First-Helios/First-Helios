"""Both concrete SQL directions, seeded Menu and complete provider preservation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.contracts import ModifierInput, VariantInput
from packages.helios_core.identity import (
    SubjectName,
    create_adjudication,
    create_organization,
    record_subject_change,
)
from test.menu_support import HEAD, PARENT, aggregate, force
from test.provider_support import decision, migrate, seed_scope
from test.test_legacy_identity_reset import _schema_signature
from test.test_provider_migration import provider_rows, sequence_state, signatures

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

SQL_DIRECTORY = Path(__file__).resolve().parents[1] / "docs/reviews/sql"


@pytest.mark.parametrize("concrete_sql", [False, True], ids=["alembic", "sql-artifacts"])
def test_seeded_menu_round_trip_preserves_all_providers(
    disposable_database_engine: Engine, concrete_sql: bool
) -> None:
    engine = disposable_database_engine

    def apply(direction: str) -> None:
        target = PARENT if direction == "downgrade" else HEAD
        if concrete_sql:
            sql = (SQL_DIRECTORY / f"0002-step-5-menu-{direction}.sql").read_text()
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql(sql)
        else:
            migrate(direction, target)
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM public.alembic_version")) == target
            )

    migrate("upgrade", "head")
    migrate("downgrade", PARENT)
    with Session(engine) as setup, setup.begin():
        scope = seed_scope(setup)
        setup.add(
            SubjectName(
                subject_id=scope.organization.subject_id,
                subject_kind="organization",
                name="Menu migration",
                name_kind="alias",
                name_fingerprint="migration",
                evidence_id=scope.shared_input.evidence_id,
            )
        )
        adjudication = create_adjudication(
            setup, actor="menu-test", rationale="preservation", decided_at=decision().decided_at
        )
        other = create_organization(setup)
        record_subject_change(
            setup,
            operation="merge",
            input_subject_ids=(scope.organization.subject_id, other.id),
            output_subject_ids=(scope.organization.subject_id,),
            decision=decision(),
            adjudication_id=adjudication.id,
            evidence_ids=(scope.shared_input.evidence_id,),
        )
    with engine.connect() as connection:
        rows = provider_rows(connection)
        sequences = sequence_state(connection)
        objects = signatures(connection)
        assert len(rows) == 21 and all(rows.values())
    try:
        apply("upgrade")
        with engine.connect() as connection:
            empty = _schema_signature(connection, "menu")
            assert len(inspect(connection).get_table_names(schema="menu")) == 9
            assert [
                tuple(row) for row in connection.execute(text("SELECT * FROM menu.currency"))
            ] == [("USD", 2)]
        value = aggregate(scope)
        evidence = (scope.local_input.evidence_id,)
        value = replace(
            value,
            variants=(
                VariantInput(
                    variant_key="large",
                    item_key="burger",
                    label="Large",
                    position=0,
                    effect="replace",
                    support_kind="direct",
                    evidence_ids=evidence,
                ),
            ),
            modifiers=(
                ModifierInput(
                    modifier_key="extra",
                    item_key="burger",
                    label="Extra",
                    required=False,
                    position=0,
                    effect="replace",
                    support_kind="direct",
                    evidence_ids=evidence,
                ),
            ),
        )
        with Session(engine) as writer, writer.begin():
            persist_menu(writer, value)
            force(writer)
        with engine.connect() as connection:
            for table in inspect(connection).get_table_names(schema="menu"):
                assert connection.scalar(text(f"SELECT count(*) FROM menu.{table}")) > 0
            assert provider_rows(connection) == rows and sequence_state(connection) == sequences
            assert signatures(connection) == objects
        apply("downgrade")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regnamespace('menu')")) is None
            assert provider_rows(connection) == rows and sequence_state(connection) == sequences
            assert signatures(connection) == objects
        apply("upgrade")
        with engine.connect() as connection:
            assert _schema_signature(connection, "menu") == empty
            assert [
                tuple(row) for row in connection.execute(text("SELECT * FROM menu.currency"))
            ] == [("USD", 2)]
            for table in inspect(connection).get_table_names(schema="menu"):
                if table != "currency":
                    assert connection.scalar(text(f"SELECT count(*) FROM menu.{table}")) == 0
            assert provider_rows(connection) == rows and sequence_state(connection) == sequences
            assert signatures(connection) == objects
    finally:
        migrate("upgrade", "head")


def test_menu_sql_artifacts_match_fresh_generation() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        sql = migrate(direction, boundary, "--sql")
        assert (
            SQL_DIRECTORY / f"0002-step-5-menu-{direction}.sql"
        ).read_text().rstrip() == sql.rstrip()
        assert "CASCADE" not in sql
        if direction == "upgrade":
            assert sql.count("CREATE TABLE menu.") == 9
        else:
            assert sql.count("DROP TABLE menu.") == 9
