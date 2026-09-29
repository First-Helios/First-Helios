"""Reviewed S13 SQL, immutable evidence, and safe migration boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from test.provider_support import migrate
from test.test_venue_lifecycle import complete, ingest, poi

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

PARENT = "c91a6f02de73"
HEAD = "5a91ef3ff9d8"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"


def test_lifecycle_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        assert (
            SQL_DIR / f"2026-09-28-s13-lifecycle-{direction}.sql"
        ).read_text().rstrip() == "\n".join(
            line.rstrip() for line in migrate(direction, boundary, "--sql").splitlines()
        ).rstrip()


def test_empty_round_trip(historical_database_engine: Engine) -> None:
    migrate("upgrade", HEAD)
    migrate("downgrade", PARENT)
    migrate("upgrade", HEAD)
    with historical_database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


def test_populated_downgrade_preserves_history(historical_database_engine: Engine) -> None:
    migrate("upgrade", HEAD)
    with historical_database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO bronze.discovery_release_completion(release_endpoint, release_at, coverage_key, coverage, poi_count) VALUES ('s3://fixture/release/', now(), 'fixture', '{}', 0)"
            )
        )
    with pytest.raises(subprocess.CalledProcessError) as error:
        migrate("downgrade", PARENT)
    assert "populated lifecycle history cannot be downgraded" in error.value.stderr
    with historical_database_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT count(*) FROM bronze.discovery_release_completion")) == 1
        )


@pytest.mark.parametrize("table", ["discovery_release_completion", "discovery_lifecycle_state"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_lifecycle_evidence_is_append_only(session: Session, table: str, action: str) -> None:
    first = poi()
    ingest(session, [first], 0)
    ingest(session, [first], 1)
    complete(session, 1)
    sql = (
        f"{action} bronze.{table}"
        if action == "TRUNCATE"
        else f"DELETE FROM bronze.{table}"
        if action == "DELETE"
        else f"UPDATE bronze.{table} SET id=id"
    )
    with pytest.raises(DBAPIError) as error, session.begin_nested():
        session.execute(text(sql))
    assert error.value.orig.sqlstate == "55000"  # type: ignore[union-attr]
