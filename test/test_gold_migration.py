"""Both concrete Gold SQL directions and Menu preservation across the boundary."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from packages.helios_core.domains.menu.commands import persist_menu
from test.menu_support import aggregate
from test.provider_support import migrate, seed_scope

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

SQL_DIRECTORY = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
MENU = "d83f0a21c592"
GOLD = "5f3a9c1e7b24"


def _menu_counts(connection: Connection) -> dict[str, int | None]:
    return {
        table: connection.scalar(text(f"SELECT count(*) FROM menu.{table}"))
        for table in inspect(connection).get_table_names(schema="menu")
    }


def test_gold_sql_artifacts_match_fresh_generation() -> None:
    for direction, boundary in (("upgrade", f"{MENU}:{GOLD}"), ("downgrade", f"{GOLD}:{MENU}")):
        sql = migrate(direction, boundary, "--sql")
        assert (
            SQL_DIRECTORY / f"0002-step-6-gold-{direction}.sql"
        ).read_text().rstrip() == sql.rstrip()
        assert "CASCADE" not in sql
        if direction == "upgrade":
            assert sql.count("CREATE TABLE gold.") == 1
        else:
            assert sql.count("DROP TABLE gold.") == 1


def test_gold_downgrade_and_reupgrade_preserve_menu(disposable_database_engine: Engine) -> None:
    engine = disposable_database_engine
    migrate("upgrade", "head")
    with Session(engine) as setup, setup.begin():
        scope = seed_scope(setup)
    # Menu admission consumes already committed input; persist after the seed
    # commits.
    with Session(engine) as setup, setup.begin():
        persist_menu(setup, aggregate(scope))
    with engine.connect() as connection:
        before = _menu_counts(connection)
        assert before["menu_page"] and before["menu_page"] >= 1
        assert connection.scalar(text("SELECT to_regnamespace('gold')")) is not None
    try:
        migrate("downgrade", MENU)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regnamespace('gold')")) is None
            assert connection.scalar(text("SELECT version_num FROM public.alembic_version")) == MENU
            assert _menu_counts(connection) == before
        migrate("upgrade", "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM public.alembic_version")) == GOLD
            assert connection.scalar(text("SELECT count(*) FROM gold.current_menu")) == 0
            assert _menu_counts(connection) == before
    finally:
        migrate("upgrade", "head")
