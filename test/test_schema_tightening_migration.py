"""S14 schema-tightening SQL in both directions, and a data-preserving round trip."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.helios_core.provenance.contracts import persist_source_record_observation
from test.provider_support import migrate, observation

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

SQL_DIRECTORY = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
PREFIX = "2026-09-22-s14-schema-tightening"
GOLD = "5f3a9c1e7b24"
TIGHTENED = "12a76ebed458"

_CHECKS = """
    SELECT n.nspname || '.' || c.relname || '.' || con.conname || ' ' || pg_get_constraintdef(con.oid)
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE con.contype = 'c' AND n.nspname IN ('bronze', 'identity', 'menu', 'gold')
    ORDER BY 1
"""
_TRIGGERS = """
    SELECT pg_get_triggerdef(t.oid)
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE NOT t.tgisinternal AND n.nspname = 'bronze'
    ORDER BY 1
"""


def _schema(connection: Connection) -> tuple[list[str], list[str]]:
    return (
        list(connection.scalars(text(_CHECKS))),
        list(connection.scalars(text(_TRIGGERS))),
    )


def _bronze_counts(connection: Connection) -> dict[str, int | None]:
    return {
        table: connection.scalar(text(f"SELECT count(*) FROM bronze.{table}"))
        for table in ("source", "source_endpoint", "source_record", "capture", "evidence")
    }


def test_schema_tightening_sql_artifacts_match_fresh_generation() -> None:
    for direction, boundary in (
        ("upgrade", f"{GOLD}:{TIGHTENED}"),
        ("downgrade", f"{TIGHTENED}:{GOLD}"),
    ):
        sql = migrate(direction, boundary, "--sql")
        assert (SQL_DIRECTORY / f"{PREFIX}-{direction}.sql").read_text().rstrip() == sql.rstrip()
        # Constraints and triggers only: nothing is dropped with its data.
        assert "CASCADE" not in sql
        assert "DROP TABLE" not in sql
        assert "DROP COLUMN" not in sql
        assert "ALTER COLUMN" not in sql


def test_downgrade_restores_previous_schema_and_keeps_rows(
    disposable_database_engine: Engine,
) -> None:
    engine = disposable_database_engine
    migrate("upgrade", "head")
    with Session(engine) as setup, setup.begin():
        persist_source_record_observation(setup, observation())
    try:
        migrate("downgrade", GOLD)
        with engine.connect() as connection:
            previous = _schema(connection)
            before = _bronze_counts(connection)
            assert connection.scalar(text("SELECT to_regproc('bronze.whitespace')")) is None
        migrate("upgrade", TIGHTENED)
        with engine.connect() as connection:
            tightened = _schema(connection)
            assert _bronze_counts(connection) == before
        assert tightened != previous
        migrate("downgrade", GOLD)
        with engine.connect() as connection:
            assert _schema(connection) == previous
            assert _bronze_counts(connection) == before
    finally:
        migrate("upgrade", "head")
