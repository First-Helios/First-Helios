"""Database-backed tests for the ORM models.

These exercise the Postgres service that CI spins up. If no database is
reachable (or the DB name doesn't end with `_test`, unless
`HELIOS_ALLOW_NONTEST_DB=1`), the tests skip rather than fail.
Each test runs inside a transaction that is rolled back on teardown, so it
never leaves rows behind or drops the migrated schema of a dev database.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.helios_core.db.models import Venue

_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://helios:helios@localhost:5432/helios"
)
# CI passes a bare postgresql:// URL; pin the psycopg (v3) driver explicitly
# since psycopg2 is not installed.
if _DATABASE_URL.startswith("postgresql://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

_db_name = _DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
if not (_db_name.endswith("_test") or os.environ.get("HELIOS_ALLOW_NONTEST_DB") == "1"):
    pytest.skip(
        "Refusing to run DB tests against a non-test database. "
        "Use a *_test DB name or set HELIOS_ALLOW_NONTEST_DB=1.",
        allow_module_level=True,
    )

_migrations_applied = False
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(_DATABASE_URL)
    try:
        connection = engine.connect()
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"database unreachable: {exc}")

    # Apply all Alembic migrations so the test exercises the real migration
    # path and CI will catch broken or missing migrations.
    global _migrations_applied
    if not _migrations_applied:
        try:
            subprocess.run(
                ["alembic", "-c", str(_ALEMBIC_INI), "upgrade", "head"],
                check=True,
                cwd=_REPO_ROOT,
                env={**os.environ, "DATABASE_URL": _DATABASE_URL},
            )
        except Exception:
            connection.close()
            engine.dispose()
            raise
        _migrations_applied = True

    outer = connection.begin()
    sess = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        connection.close()
        engine.dispose()


def test_venue_round_trip(session: Session) -> None:
    venue = Venue(
        name="Torchy's Tacos",
        address="1822 S Congress Ave, Austin, TX 78704",
    )
    session.add(venue)
    session.commit()
    session.refresh(venue)

    assert venue.id is not None
    assert venue.created_at is not None
    assert venue.updated_at is not None

    fetched = session.query(Venue).filter_by(name="Torchy's Tacos").one()
    assert fetched.address is not None
    assert fetched.address.endswith("Austin, TX 78704")
