"""Reviewed price-index SQL and a round trip that leaves every other table alone."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text

from test.provider_support import migrate

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

PARENT = "5a91ef3ff9d8"
HEAD = "7c2e4b9d1f3a"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
E = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _sql(direction: str, boundary: str) -> str:
    return "\n".join(
        line.rstrip() for line in migrate(direction, boundary, "--sql").splitlines()
    ).rstrip()


def test_price_index_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        sql = _sql(direction, boundary)
        assert (SQL_DIR / f"2026-09-30-g1-price-index-{direction}.sql").read_text().rstrip() == sql
        assert "CASCADE" not in sql
        assert sql.count("TABLE gold.") == 1


def _tables(connection: Connection) -> dict[str, int]:
    names = connection.scalars(
        text(
            "SELECT schemaname || '.' || tablename FROM pg_tables "
            "WHERE schemaname IN ('bronze', 'identity', 'menu', 'gold') ORDER BY 1"
        )
    ).all()
    return {name: connection.scalar(text(f"SELECT count(*) FROM {name}")) or 0 for name in names}


def test_populated_round_trip(historical_database_engine: Engine) -> None:
    engine = historical_database_engine
    migrate("upgrade", HEAD)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO gold.price_index (area_kind, area_key, cell_lat, cell_lon, "
                "category_kind, category_key, currency_code, effective_instant, venue_count, "
                "organization_venue_count, priced_count, unpriced_count, min_venues, low_sample, "
                "refreshed_at) VALUES ('latlon_grid_0p01', '30.26,-97.75', 30.26, -97.75, "
                "'all', 'all', 'USD', :e, 0, 0, 0, 1, 5, true, :e)"
            ),
            {"e": E},
        )
        before = _tables(connection)
    assert before["gold.price_index"] == 1
    migrate("downgrade", PARENT)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('gold.price_index')")) is None
        after = _tables(connection)
    assert after == {name: n for name, n in before.items() if name != "gold.price_index"}
    migrate("upgrade", HEAD)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert connection.scalar(text("SELECT count(*) FROM gold.price_index")) == 0
