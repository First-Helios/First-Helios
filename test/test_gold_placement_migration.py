"""Reviewed price-index placement SQL, its CHECKs, and a populated round trip (ADR-0020 §2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from packages.helios_core.gold.models import PriceIndex, PriceIndexPlacement
from test.provider_support import migrate

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import Session

PARENT = "d978bedc2523"
HEAD = "13081a087231"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
E = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _sql(direction: str, boundary: str) -> str:
    return "\n".join(
        line.rstrip() for line in migrate(direction, boundary, "--sql").splitlines()
    ).rstrip()


def test_placement_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        sql = _sql(direction, boundary)
        path = SQL_DIR / f"2026-10-23-p8-9-price-index-placement-{direction}.sql"
        assert path.read_text().rstrip() == sql
        assert "CASCADE" not in sql
        assert "ALTER TABLE" not in sql  # additive: no existing table changes
        assert sql.count("TABLE gold.") == 1


def _placement(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "subject_id": 11,
        "subject_kind": "establishment",
        "source_record_id": 21,
        "venue_id": 11,
        "latitude": "30.267153",
        "longitude": "-97.743057",
        "via_organization": False,
        "effective_instant": E,
        "refreshed_at": E,
    }
    row.update(overrides)
    return row


_INDEX_ROW = {
    "area_kind": "all",
    "area_key": "all",
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


def _tables(connection: Connection) -> dict[str, int]:
    names = connection.scalars(
        text(
            "SELECT schemaname || '.' || tablename FROM pg_tables "
            "WHERE schemaname IN ('bronze', 'identity', 'menu', 'gold') ORDER BY 1"
        )
    ).all()
    return {name: connection.scalar(text(f"SELECT count(*) FROM {name}")) or 0 for name in names}


def test_populated_round_trip_touches_only_the_new_table(
    historical_database_engine: Engine,
) -> None:
    engine = historical_database_engine
    migrate("upgrade", HEAD)
    with engine.begin() as connection:
        connection.execute(insert(PriceIndex), [_INDEX_ROW])
        connection.execute(
            insert(PriceIndexPlacement),
            [
                _placement(),
                _placement(
                    subject_id=12,
                    subject_kind="organization",
                    venue_id=13,
                    via_organization=True,
                ),
            ],
        )
        before = _tables(connection)
    assert before["gold.price_index_placement"] == 2

    migrate("downgrade", PARENT)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('gold.price_index_placement')")) is None
        after = _tables(connection)
    expected = {k: n for k, n in before.items() if k != "gold.price_index_placement"}
    assert after == expected  # gold.price_index's row and every other table untouched

    migrate("upgrade", HEAD)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert _tables(connection) == {**expected, "gold.price_index_placement": 0}


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"subject_kind": "place"}, "ck_gold_price_index_placement_scope"),
        ({"via_organization": True}, "ck_gold_price_index_placement_venue"),
        (
            {"subject_kind": "organization", "venue_id": 99},
            "ck_gold_price_index_placement_venue",
        ),
        ({"venue_id": 99}, "ck_gold_price_index_placement_venue"),
        ({"latitude": "90.000001"}, "ck_gold_price_index_placement_point"),
        ({"longitude": "-180.000001"}, "ck_gold_price_index_placement_point"),
        ({"effective_instant": "infinity"}, "ck_gold_price_index_placement_times"),
    ],
    ids=[
        "unknown-scope",
        "establishment-via-organization",
        "organization-not-flagged",
        "establishment-elsewhere",
        "latitude",
        "longitude",
        "infinite-instant",
    ],
)
def test_placement_checks_reject(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=rf"\b{constraint}\b"):
        session.execute(insert(PriceIndexPlacement), [_placement(**overrides)])


def test_one_row_per_family(session: Session) -> None:
    session.execute(insert(PriceIndexPlacement), [_placement(subject_id=-1, venue_id=-1)])
    with pytest.raises(IntegrityError, match=r"\buq_gold_price_index_placement\b"):
        session.execute(
            insert(PriceIndexPlacement), [_placement(subject_id=-1, venue_id=-1, latitude="1")]
        )
