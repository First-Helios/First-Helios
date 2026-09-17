"""Database fixtures: optional locally, mandatory with HELIOS_STRICT_DB_TESTS=1.

Strict and destructive tests require a disposable PostgreSQL *_test database
and forbid HELIOS_ALLOW_NONTEST_DB. Ordinary optional tests retain the explicit
non-test override. Savepoint tests roll back rows; concurrency tests commit and
migration tests rebuild the database, so acceptance always needs disposable data.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from packages.helios_core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

DATABASE_URL = get_settings().database_url

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_migrations_applied = False


def _unavailable(reason: str) -> None:
    if os.environ.get("HELIOS_STRICT_DB_TESTS") == "1":
        pytest.fail(f"strict database testing: {reason}", pytrace=False)
    pytest.skip(reason)


def _database_engine(*, disposable: bool) -> Iterator[Engine]:
    strict = os.environ.get("HELIOS_STRICT_DB_TESTS") == "1"
    override = os.environ.get("HELIOS_ALLOW_NONTEST_DB")
    if (strict or disposable) and override is not None:
        pytest.fail("database tests must not use HELIOS_ALLOW_NONTEST_DB", pytrace=False)
    url = None
    with suppress(ArgumentError):
        url = make_url(DATABASE_URL)
    if url is None:
        _unavailable("DATABASE_URL is not a valid SQLAlchemy URL")
        return
    if url.get_backend_name() != "postgresql":
        _unavailable("database tests require PostgreSQL")
    if not (url.database or "").endswith("_test") and not (
        override == "1" and not strict and not disposable
    ):
        _unavailable("database tests require a disposable *_test database")

    # Validate the driver's actual target too: query parameters/service settings
    # must not redirect a harmless-looking URL to a different database.
    engine = None
    connection_failed = False
    try:
        engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
        with engine.connect() as connection:
            actual_name = connection.scalar(text("SELECT current_database()"))
    except Exception:
        if engine is not None:
            engine.dispose()
        connection_failed = True
    if connection_failed:
        # Driver errors can include credentials; keep the failure actionable but safe.
        _unavailable("database unreachable or unsuitable; check DATABASE_URL and PostgreSQL")
        return
    assert engine is not None
    try:
        if actual_name != url.database:
            _unavailable("connected database differs from DATABASE_URL database name")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def database_engine() -> Iterator[Engine]:
    yield from _database_engine(disposable=False)


@pytest.fixture
def disposable_database_engine() -> Iterator[Engine]:
    yield from _database_engine(disposable=True)


@pytest.fixture
def session(database_engine: Engine) -> Iterator[Session]:
    """A rolled-back session against the migrated schema."""
    connection = database_engine.connect()

    # Apply all Alembic migrations so the tests exercise the real migration
    # path -- CI then catches a broken or missing migration, not just a broken
    # model. Done once per session, not per test.
    global _migrations_applied
    if not _migrations_applied:
        try:
            subprocess.run(
                ["alembic", "-c", str(_ALEMBIC_INI), "upgrade", "head"],
                check=True,
                cwd=_REPO_ROOT,
                env={**os.environ, "DATABASE_URL": DATABASE_URL},
            )
        except Exception:
            connection.close()
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
