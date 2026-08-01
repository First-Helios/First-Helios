"""Shared fixtures for database-backed tests.

The guard and the transaction-per-test fixture live here rather than in a
single test module so every DB test inherits the same safety properties:

- **Never run against a non-test database.** The DB name must end in `_test`
  unless `HELIOS_ALLOW_NONTEST_DB=1` says otherwise. A schema test that drops
  or rolls back against someone's dev database is a bad afternoon.
- **Never leave rows behind.** Each test runs inside a transaction that is
  rolled back on teardown, so tests neither pollute each other nor destroy the
  migrated schema of a long-lived database.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.helios_core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

DATABASE_URL = get_settings().database_url

_db_name = DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
IS_TEST_DATABASE = _db_name.endswith("_test") or os.environ.get("HELIOS_ALLOW_NONTEST_DB") == "1"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_migrations_applied = False


@pytest.fixture
def session() -> Iterator[Session]:
    """A rolled-back session against the migrated schema."""
    if not IS_TEST_DATABASE:
        pytest.skip(
            "Refusing to run DB tests against a non-test database. "
            "Use a *_test DB name or set HELIOS_ALLOW_NONTEST_DB=1."
        )

    engine = create_engine(DATABASE_URL)
    try:
        connection = engine.connect()
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(f"database unreachable: {exc}")

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
