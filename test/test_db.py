"""Database-backed tests for the ORM models.

These exercise the Postgres service that CI spins up. If no database is
reachable (e.g. a bare local checkout), the tests skip rather than fail.

Each test runs inside a transaction that is rolled back on teardown, so it
never leaves rows behind or drops the migrated schema of a dev database.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.helios_core.db.base import Base
from packages.helios_core.db.models import Venue

_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://helios:helios@localhost:5432/helios"
)
# CI passes a bare postgresql:// URL; pin the psycopg (v3) driver explicitly
# since psycopg2 is not installed.
if _DATABASE_URL.startswith("postgresql://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(_DATABASE_URL, future=True)
    try:
        connection = engine.connect()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database unreachable: {exc}")

    # Ensure the schema exists (no-op against a migrated dev DB; creates the
    # tables on CI's empty database). Committed so it survives the rollback.
    Base.metadata.create_all(connection)
    connection.commit()

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
