"""Reviewed area-kind SQL, its CHECKs, and a populated round trip (ADR-0007 Amendment 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import IntegrityError

from packages.helios_core.gold.models import PriceIndex
from test.provider_support import migrate

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import Session

PARENT = "c95d883737db"
HEAD = "d978bedc2523"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
E = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _sql(direction: str, boundary: str) -> str:
    return "\n".join(
        line.rstrip() for line in migrate(direction, boundary, "--sql").splitlines()
    ).rstrip()


def test_area_kinds_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        sql = _sql(direction, boundary)
        assert (SQL_DIR / f"2026-10-22-p8-5-area-kinds-{direction}.sql").read_text().rstrip() == sql
        assert "CASCADE" not in sql
        assert sql.count("TABLE gold.") == 1


def _row(area_kind: str, area_key: str, cell: tuple[Any, Any]) -> dict[str, Any]:
    """A one-venue ``gold.price_index`` row; ``cell`` is ``(cell_lat, cell_lon)``."""
    return {
        "area_kind": area_kind,
        "area_key": area_key,
        "cell_lat": cell[0],
        "cell_lon": cell[1],
        "category_kind": "all",
        "category_key": "all",
        "currency_code": "USD",
        "effective_instant": E,
        "venue_count": 1,
        "organization_venue_count": 0,
        "priced_count": 1,
        "unpriced_count": 0,
        "min_venues": 5,
        "low_sample": True,
        "p25_minor": 100,
        "median_minor": 100,
        "p75_minor": 100,
        "min_minor": 100,
        "max_minor": 100,
        "oldest_observed_at": E,
        "newest_observed_at": E,
        "refreshed_at": E,
    }


GRID = (Decimal("-89.95"), Decimal("179.90"))  # a corner no other test uses
ROWS = [
    _row("latlon_grid_0p01", "-89.95,179.90", GRID),
    _row("latlon_grid_0p05", "-89.95,179.90", GRID),
    _row("all", "all", (None, None)),
]


def _tables(connection: Connection) -> dict[str, int]:
    names = connection.scalars(
        text(
            "SELECT schemaname || '.' || tablename FROM pg_tables "
            "WHERE schemaname IN ('bronze', 'identity', 'menu', 'gold') ORDER BY 1"
        )
    ).all()
    return {name: connection.scalar(text(f"SELECT count(*) FROM {name}")) or 0 for name in names}


def _nullable(connection: Connection) -> dict[str, bool]:
    columns = inspect(connection).get_columns("price_index", schema="gold")
    return {c["name"]: c["nullable"] for c in columns if c["name"] in {"cell_lat", "cell_lon"}}


def _checks(connection: Connection) -> dict[str, str]:
    rows = connection.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'gold.price_index'::regclass AND contype = 'c' "
            "AND conname IN ('ck_gold_price_index_area', 'ck_gold_price_index_area_kind')"
        )
    ).tuples()
    return {str(name): str(definition) for name, definition in rows}


def test_populated_round_trip_keeps_the_0p01_rows(historical_database_engine: Engine) -> None:
    engine = historical_database_engine
    migrate("upgrade", HEAD)
    with engine.begin() as connection:
        connection.execute(insert(PriceIndex), ROWS)
        before = _tables(connection)
        assert _nullable(connection) == {"cell_lat": True, "cell_lon": True}
    assert before["gold.price_index"] == 3

    migrate("downgrade", PARENT)
    with engine.connect() as connection:
        kinds = connection.scalars(text("SELECT area_kind FROM gold.price_index")).all()
        assert kinds == ["latlon_grid_0p01"]
        after = _tables(connection)
        assert after == {**before, "gold.price_index": 1}  # every other table untouched
        assert _nullable(connection) == {"cell_lat": False, "cell_lon": False}
        checks = _checks(connection)
    assert set(checks) == {"ck_gold_price_index_area_kind"}
    assert "'latlon_grid_0p01'" in checks["ck_gold_price_index_area_kind"]
    assert "latlon_grid_0p05" not in checks["ck_gold_price_index_area_kind"]

    migrate("upgrade", HEAD)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert _tables(connection) == after
        assert set(_checks(connection)) == {
            "ck_gold_price_index_area",
            "ck_gold_price_index_area_kind",
        }


@pytest.mark.parametrize(
    ("row", "constraint"),
    [
        (_row("all", "all", GRID), "ck_gold_price_index_area"),
        (_row("all", "all", (None, GRID[1])), "ck_gold_price_index_area"),
        (_row("all", "x", (None, None)), "ck_gold_price_index_area"),
        (_row("latlon_grid_0p05", "-89.95,179.90", (None, None)), "ck_gold_price_index_area"),
        (_row("latlon_grid_0p01", "-89.95,179.90", (GRID[0], None)), "ck_gold_price_index_area"),
        (_row("latlon_grid_0p10", "-89.95,179.90", GRID), "ck_gold_price_index_area_kind"),
    ],
    ids=[
        "all-with-coordinates",
        "all-with-one-coordinate",
        "all-with-key-x",
        "0p05-without-coordinates",
        "0p01-with-one-coordinate",
        "unknown-kind",
    ],
)
def test_area_checks_reject(session: Session, row: dict[str, Any], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=rf"\b{constraint}\b"):
        session.execute(insert(PriceIndex), [row])
