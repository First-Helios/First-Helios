"""Migration coverage for the intentionally destructive Plan 0002 Step 3 reset.

The seeded legacy rows in this test are expected to be permanently discarded.
Downgrade recreates only their former schema shape; it does not and cannot
restore the deleted application data.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from packages.helios_core.config import get_database_url
from test.provider_support import PROVIDER_FUNCTIONS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Connection, Engine

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
PRE_RESET_REVISION = "3f8b2c1d9a74"
LEGACY_SCHEMAS = ("raw", "canonical", "mart")
LEGACY_TABLES = (
    "venue_site",
    "site_identity",
    "venue_source",
    "venue_alias",
    "venue",
    "brand",
)


def _run_alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), *arguments],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": get_database_url()},
        capture_output=True,
        text=True,
    )


def _schema_exists(connection: Connection, schema: str) -> bool:
    return bool(
        connection.scalar(
            text("SELECT to_regnamespace(:schema_name) IS NOT NULL"),
            {"schema_name": schema},
        )
    )


def _table_exists(connection: Connection, table: str) -> bool:
    return bool(
        connection.scalar(
            text("SELECT to_regclass(:qualified_name) IS NOT NULL"),
            {"qualified_name": f"canonical.{table}"},
        )
    )


def _legacy_row_counts(connection: Connection) -> dict[str, int]:
    return {
        table: connection.execute(text(f"SELECT count(*) FROM canonical.{table}")).scalar_one()
        for table in LEGACY_TABLES
    }


def _table_signature(connection: Connection, schema: str, table: str) -> dict[str, object]:
    inspector = inspect(connection)
    return {
        "columns": [
            (
                column["name"],
                str(column["type"]),
                column["nullable"],
                str(column["default"]),
            )
            for column in inspector.get_columns(table, schema=schema)
        ],
        "primary_key": inspector.get_pk_constraint(table, schema=schema),
        "unique_constraints": sorted(
            (
                constraint["name"],
                tuple(constraint["column_names"]),
            )
            for constraint in inspector.get_unique_constraints(table, schema=schema)
        ),
        "check_constraints": sorted(
            (
                constraint["name"],
                constraint["sqltext"],
            )
            for constraint in inspector.get_check_constraints(table, schema=schema)
        ),
        "foreign_keys": sorted(
            (
                foreign_key["name"],
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_schema"],
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspector.get_foreign_keys(table, schema=schema)
        ),
        "indexes": sorted(
            (
                index["name"],
                tuple(index["column_names"]),
                index["unique"],
                str(index["dialect_options"].get("postgresql_where")),
            )
            for index in inspector.get_indexes(table, schema=schema)
        ),
    }


def _schema_signature(connection: Connection, schema: str) -> dict[str, object]:
    inspector = inspect(connection)
    tables = sorted(inspector.get_table_names(schema=schema))
    functions = connection.execute(
        text(
            """
            SELECT
                procedure.proname,
                pg_get_function_identity_arguments(procedure.oid),
                pg_get_functiondef(procedure.oid)
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = :schema
              AND procedure.prokind = 'f'
            ORDER BY procedure.proname, procedure.oid
            """
        ),
        {"schema": schema},
    ).all()
    triggers = connection.execute(
        text(
            """
            SELECT
                relation.relname,
                trigger.tgname,
                pg_get_triggerdef(trigger.oid)
            FROM pg_trigger AS trigger
            JOIN pg_class AS relation
              ON relation.oid = trigger.tgrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = :schema
              AND NOT trigger.tgisinternal
            ORDER BY relation.relname, trigger.tgname
            """
        ),
        {"schema": schema},
    ).all()
    return {
        "tables": {table: _table_signature(connection, schema, table) for table in tables},
        "views": sorted(inspector.get_view_names(schema=schema)),
        "sequences": sorted(inspector.get_sequence_names(schema=schema)),
        "functions": [tuple(row) for row in functions],
        "triggers": [tuple(row) for row in triggers],
    }


def _schema_row_counts(connection: Connection, schema: str) -> dict[str, int]:
    return {
        table: connection.execute(text(f"SELECT count(*) FROM {schema}.{table}")).scalar_one()
        for table in inspect(connection).get_table_names(schema=schema)
    }


def _function_definitions(signature: dict[str, object]) -> dict[str, str]:
    functions = cast("list[tuple[str, str, str]]", signature["functions"])
    return {name: definition for name, _, definition in functions}


def _legacy_schema_signature(connection: Connection) -> dict[str, object]:
    return {
        "raw": _schema_signature(connection, "raw"),
        "canonical": _schema_signature(connection, "canonical"),
        "mart": _schema_signature(connection, "mart"),
    }


def _seed_pre_reset_state(connection: Connection) -> tuple[str, int]:
    token = uuid4().hex
    brand_id = connection.execute(
        text(
            """
            INSERT INTO canonical.brand (name, name_fingerprint)
            VALUES (:name, :fingerprint)
            RETURNING id
            """
        ),
        {"name": f"Legacy Brand {token}", "fingerprint": f"legacy-brand-{token}"},
    ).scalar_one()
    venue_id = connection.execute(
        text(
            """
            INSERT INTO canonical.venue (name, brand_id)
            VALUES (:name, :brand_id)
            RETURNING id
            """
        ),
        {"name": f"Legacy Venue {token}", "brand_id": brand_id},
    ).scalar_one()
    connection.execute(
        text(
            """
            INSERT INTO canonical.venue_alias (
                venue_id, alias, alias_fingerprint, source
            )
            VALUES (:venue_id, :alias, :fingerprint, 'manual')
            """
        ),
        {
            "venue_id": venue_id,
            "alias": f"Legacy Alias {token}",
            "fingerprint": f"legacy-alias-{token}",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO canonical.venue_source (
                venue_id, source, external_id, raw_identity
            )
            VALUES (:venue_id, 'manual', :external_id, '{"legacy": true}')
            """
        ),
        {"venue_id": venue_id, "external_id": f"legacy-source-{token}"},
    )
    site_identity_id = connection.execute(
        text(
            """
            INSERT INTO canonical.site_identity (url_canonical)
            VALUES (:url)
            RETURNING id
            """
        ),
        {"url": f"https://legacy-{token}.example.test"},
    ).scalar_one()
    connection.execute(
        text(
            """
            INSERT INTO canonical.venue_site (
                venue_id, site_identity_id, resolution_method
            )
            VALUES (:venue_id, :site_identity_id, 'manual')
            """
        ),
        {"venue_id": venue_id, "site_identity_id": site_identity_id},
    )

    bronze_namespace = f"step3-preserved-{token}"
    connection.execute(
        text(
            """
            INSERT INTO bronze.source (namespace, kind)
            VALUES (:namespace, 'migration-test')
            """
        ),
        {"namespace": bronze_namespace},
    )
    subject_id = connection.execute(
        text(
            """
            INSERT INTO identity.subject (kind)
            VALUES ('place')
            RETURNING id
            """
        )
    ).scalar_one()
    connection.execute(
        text(
            """
            INSERT INTO identity.place (subject_id, address)
            VALUES (:subject_id, 'Step 3 preserved place')
            """
        ),
        {"subject_id": subject_id},
    )
    return bronze_namespace, subject_id


def _assert_foundations_preserved(
    connection: Connection,
    bronze_namespace: str,
    subject_id: int,
) -> None:
    assert (
        connection.scalar(
            text("SELECT count(*) FROM bronze.source WHERE namespace = :namespace"),
            {"namespace": bronze_namespace},
        )
        == 1
    )
    assert (
        connection.scalar(
            text("SELECT count(*) FROM identity.place WHERE subject_id = :subject_id"),
            {"subject_id": subject_id},
        )
        == 1
    )
    assert connection.scalar(
        text(
            """
            SELECT is_current
            FROM identity.subject_currentness
            WHERE subject_id = :subject_id
            """
        ),
        {"subject_id": subject_id},
    )
    assert connection.scalar(
        text("SELECT to_regprocedure('bronze.reject_provenance_mutation()') IS NOT NULL")
    )
    assert connection.scalar(
        text("SELECT to_regprocedure('identity.rebuild_identity_projections()') IS NOT NULL")
    )


@pytest.fixture
def migration_engine(disposable_database_engine: Engine) -> Iterator[Engine]:
    yield disposable_database_engine


def test_seeded_legacy_upgrade_downgrade_and_reupgrade(
    migration_engine: Engine,
) -> None:
    try:
        # Build the comparison fixture from historical migrations only. This
        # keeps downgrade validation independent of the new downgrade code.
        _run_alembic("downgrade", "base")
        _run_alembic("upgrade", PRE_RESET_REVISION)

        with migration_engine.begin() as connection:
            assert all(_schema_exists(connection, schema) for schema in LEGACY_SCHEMAS)
            assert all(_table_exists(connection, table) for table in LEGACY_TABLES)
            assert _legacy_row_counts(connection) == dict.fromkeys(LEGACY_TABLES, 0)
            pre_reset_schema = _legacy_schema_signature(connection)
            bronze_namespace, subject_id = _seed_pre_reset_state(connection)
            foundation_schema = {
                schema: _schema_signature(connection, schema) for schema in ("bronze", "identity")
            }
            foundation_rows = {
                schema: _schema_row_counts(connection, schema) for schema in ("bronze", "identity")
            }
            assert _legacy_row_counts(connection) == dict.fromkeys(LEGACY_TABLES, 1)

        upgrade = _run_alembic("upgrade", "head")
        migration_output = f"{upgrade.stdout}\n{upgrade.stderr}"
        for table in LEGACY_TABLES:
            assert f"canonical.{table}=1" in migration_output

        with migration_engine.connect() as connection:
            assert not any(_schema_exists(connection, schema) for schema in LEGACY_SCHEMAS)
            assert not any(_table_exists(connection, table) for table in LEGACY_TABLES)
            _assert_foundations_preserved(connection, bronze_namespace, subject_id)
            corrected_foundation_schema = {
                schema: _schema_signature(connection, schema) for schema in ("bronze", "identity")
            }
            for schema in ("bronze", "identity"):
                for component in ("tables", "views", "sequences", "triggers"):
                    assert (
                        corrected_foundation_schema[schema][component]
                        == foundation_schema[schema][component]
                    )
                original_functions = _function_definitions(foundation_schema[schema])
                corrected_functions = _function_definitions(corrected_foundation_schema[schema])
                assert (
                    corrected_functions.keys()
                    == original_functions.keys() | PROVIDER_FUNCTIONS[schema]
                )
                for name, definition in original_functions.items():
                    if schema == "identity" and name == "protect_typed_grain_key":
                        continue
                    assert corrected_functions[name] == definition
            original_functions = _function_definitions(foundation_schema["identity"])
            corrected_functions = _function_definitions(corrected_foundation_schema["identity"])
            assert (
                original_functions["protect_typed_grain_key"]
                != corrected_functions["protect_typed_grain_key"]
            )
            assert {
                schema: _schema_row_counts(connection, schema) for schema in ("bronze", "identity")
            } == foundation_rows

        _run_alembic("downgrade", PRE_RESET_REVISION)
        with migration_engine.connect() as connection:
            assert all(_schema_exists(connection, schema) for schema in LEGACY_SCHEMAS)
            assert all(_table_exists(connection, table) for table in LEGACY_TABLES)
            assert _legacy_row_counts(connection) == dict.fromkeys(LEGACY_TABLES, 0)
            assert _legacy_schema_signature(connection) == pre_reset_schema
            _assert_foundations_preserved(connection, bronze_namespace, subject_id)
            assert {
                schema: _schema_signature(connection, schema) for schema in ("bronze", "identity")
            } == foundation_schema
            assert {
                schema: _schema_row_counts(connection, schema) for schema in ("bronze", "identity")
            } == foundation_rows

        reupgrade = _run_alembic("upgrade", "head")
        reupgrade_output = f"{reupgrade.stdout}\n{reupgrade.stderr}"
        for table in LEGACY_TABLES:
            assert f"canonical.{table}=0" in reupgrade_output

        with migration_engine.connect() as connection:
            assert not any(_schema_exists(connection, schema) for schema in LEGACY_SCHEMAS)
            assert not any(_table_exists(connection, table) for table in LEGACY_TABLES)
            _assert_foundations_preserved(connection, bronze_namespace, subject_id)
            assert {
                schema: _schema_signature(connection, schema) for schema in ("bronze", "identity")
            } == corrected_foundation_schema
            assert {
                schema: _schema_row_counts(connection, schema) for schema in ("bronze", "identity")
            } == foundation_rows
    finally:
        # Restore to head and fail loudly if that breaks: a silently half-migrated
        # database would surface as unrelated failures in later tests.
        _run_alembic("downgrade", "base")
        _run_alembic("upgrade", "head")
