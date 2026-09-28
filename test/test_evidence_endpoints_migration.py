"""S6 SQL snapshots, explicit rebuild refusal, empty round trip, and DB guards."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from test.provider_support import migrate

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

PARENT = "12a76ebed458"
HEAD = "c91a6f02de73"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"


def test_evidence_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        assert (
            SQL_DIR / f"2026-09-27-s6-provenance-{direction}.sql"
        ).read_text().rstrip() == migrate(direction, boundary, "--sql").rstrip()


def test_empty_round_trip(historical_database_engine: Engine) -> None:
    migrate("upgrade", HEAD)
    migrate("downgrade", PARENT)
    migrate("upgrade", HEAD)
    with historical_database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


@pytest.mark.parametrize("legacy_capture", [True, False])
def test_legacy_rows_refuse_upgrade_atomically(
    historical_database_engine: Engine, legacy_capture: bool
) -> None:
    migrate("upgrade", PARENT)
    with historical_database_engine.begin() as connection:
        source = connection.scalar(
            text(
                "INSERT INTO bronze.source(namespace, kind) VALUES ('legacy', 'fixture') RETURNING id"
            )
        )
        if legacy_capture:
            connection.execute(
                text(
                    "INSERT INTO bronze.capture(source_id, fetched_at, outcome) VALUES (:s, now(), 'succeeded')"
                ),
                {"s": source},
            )
        else:
            record = connection.scalar(
                text(
                    "INSERT INTO bronze.source_record(source_id, external_key) VALUES (:s, 'legacy') RETURNING id"
                ),
                {"s": source},
            )
            version = connection.scalar(
                text(
                    "INSERT INTO bronze.source_record_version(source_id, source_record_id, observed_at, content_hash, source_payload) VALUES (:s, :r, now(), 'hash', '{}') RETURNING id"
                ),
                {"s": source, "r": record},
            )
            connection.execute(
                text(
                    "INSERT INTO bronze.evidence(source_record_version_id, locator, excerpt_hash) VALUES (:v, 'overture:legacy', 'hash')"
                ),
                {"v": version},
            )
    with pytest.raises(subprocess.CalledProcessError) as error:
        migrate("upgrade", HEAD)
    assert "pre-ADR-0011 Bronze rows" in error.value.stderr
    with historical_database_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PARENT
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema='bronze' AND column_name='ingested_at'"
                )
            )
            == 0
        )


def test_populated_downgrade_refuses_data_loss(historical_database_engine: Engine) -> None:
    migrate("upgrade", HEAD)
    with historical_database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO bronze.source(namespace, kind) VALUES ('keep', 'fixture')")
        )
    with pytest.raises(subprocess.CalledProcessError) as error:
        migrate("downgrade", PARENT)
    assert "downgrade requires an empty Bronze database" in error.value.stderr
