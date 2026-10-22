"""Reviewed Gold name-column SQL, and a round trip that keeps every row (ADR-0006 Amendment 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.gold.catalog import refresh_full_catalog
from test.menu_support import aggregate
from test.provider_support import migrate, seed_scope

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

PARENT = "68146a4c5fc5"
HEAD = "c95d883737db"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
E = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
NAMES = {"section_name", "item_name"}


def _sql(direction: str, boundary: str) -> str:
    return "\n".join(
        line.rstrip() for line in migrate(direction, boundary, "--sql").splitlines()
    ).rstrip()


def test_gold_names_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        sql = _sql(direction, boundary)
        assert (SQL_DIR / f"2026-10-22-p8-3-gold-names-{direction}.sql").read_text().rstrip() == sql
        assert "CASCADE" not in sql
        assert "DEFAULT" not in sql  # nullable, no default: catalog-only, no rewrite
        assert sql.count("ALTER TABLE gold.current_menu") == 1


def _columns(connection: Connection) -> set[str]:
    return {c["name"] for c in inspect(connection).get_columns("current_menu", schema="gold")}


def _tables(connection: Connection) -> dict[str, int]:
    names = connection.scalars(
        text(
            "SELECT schemaname || '.' || tablename FROM pg_tables "
            "WHERE schemaname IN ('bronze', 'identity', 'menu', 'gold') ORDER BY 1"
        )
    ).all()
    return {name: connection.scalar(text(f"SELECT count(*) FROM {name}")) or 0 for name in names}


def test_populated_round_trip_keeps_every_row(historical_database_engine: Engine) -> None:
    engine = historical_database_engine
    migrate("upgrade", HEAD)
    with Session(engine) as setup, setup.begin():
        scope = seed_scope(setup)
    with Session(engine) as setup, setup.begin():
        persist_menu(setup, aggregate(scope, shared=True))  # Organizations always operate
    with Session(engine) as setup, setup.begin():
        assert refresh_full_catalog(setup, effective_instant=E) >= 1
    with engine.connect() as connection:
        before = _tables(connection)
        named = connection.execute(
            text("SELECT id, section_name, item_name FROM gold.current_menu ORDER BY id")
        ).all()
    assert before["gold.current_menu"] >= 1
    assert all(row.section_name == "Food" for row in named)

    migrate("downgrade", PARENT)
    with engine.connect() as connection:
        assert not NAMES & _columns(connection)
        assert _tables(connection) == before  # dropping the columns removes no row

    migrate("upgrade", HEAD)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert _columns(connection) >= NAMES
        assert _tables(connection) == before
        # Existing rows read null until the next refresh.
        after = connection.execute(
            text("SELECT id, section_name, item_name FROM gold.current_menu ORDER BY id")
        ).all()
        assert [tuple(row) for row in after] == [(row.id, None, None) for row in named]
