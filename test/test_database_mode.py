"""The real database entrypoints must never silently skip in strict mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from test import conftest as fixtures

_TARGETS = [
    "test/test_db.py::test_bronze_and_identity_round_trip",
    "test/test_identity_concurrency.py::test_competing_assignments_serialize_on_source_record",
    "test/test_healthz.py::test_readyz_ok_when_db_reachable",
    "test/test_legacy_identity_reset.py::test_seeded_legacy_upgrade_downgrade_and_reupgrade",
]


@pytest.mark.parametrize(
    ("strict", "url", "override", "expected"),
    [
        (
            True,
            "postgresql+psycopg:///helios_test?host=/nonexistent-helios-socket",
            None,
            "4 errors",
        ),
        (
            False,
            "postgresql+psycopg:///helios_test?host=/nonexistent-helios-socket",
            None,
            "4 skipped",
        ),
        (True, "postgresql+psycopg:///helios", None, "4 errors"),
        (False, "postgresql+psycopg:///helios", None, "4 skipped"),
        (True, "postgresql+psycopg:///helios_test", "1", "4 errors"),
        (True, "postgresql+psycopg:///helios_test", "0", "4 errors"),
        (True, "sqlite:///helios_test", None, "4 errors"),
        (True, "not-a-url", None, "4 errors"),
        # Unset DATABASE_URL: no default target exists (R09).
        (True, None, None, "4 errors"),
        (False, None, None, "4 skipped"),
    ],
)
def test_database_mode_at_all_entrypoints(
    strict: bool, url: str | None, override: str | None, expected: str
) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DATABASE_URL", "HELIOS_ALLOW_NONTEST_DB", "PYTEST_ADDOPTS"}
    }
    env["HELIOS_STRICT_DB_TESTS"] = "1" if strict else "0"
    if url is not None:
        env["DATABASE_URL"] = url
    if override is not None:
        env["HELIOS_ALLOW_NONTEST_DB"] = override
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", "--no-cov", *_TARGETS],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode == (1 if strict else 0), output
    assert expected in output, output
    if strict:
        assert "skipped" not in output, output


@pytest.mark.parametrize(
    ("url", "actual", "strict", "override", "disposable", "outcome"),
    [
        (
            "postgresql+psycopg:///helios_test?host=%2Ftmp%2Fsocket",
            "helios_test",
            True,
            None,
            True,
            "ok",
        ),
        ("postgresql+psycopg:///helios_test?dbname=helios", "helios", True, None, False, "fail"),
        ("postgresql+psycopg:///helios_test?dbname=helios", "helios", False, None, False, "skip"),
        ("postgresql+psycopg:///helios?host=/tmp/fake_test", "helios", True, None, False, "fail"),
        ("postgresql+psycopg:///helios", "helios", False, "1", False, "ok"),
        ("postgresql+psycopg:///helios", "helios", False, "1", True, "fail"),
    ],
)
def test_database_target_and_optional_override(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    actual: str,
    strict: bool,
    override: str | None,
    disposable: bool,
    outcome: str,
) -> None:
    monkeypatch.setattr(fixtures, "DATABASE_URL", url)
    monkeypatch.setenv("HELIOS_STRICT_DB_TESTS", "1" if strict else "0")
    monkeypatch.delenv("HELIOS_ALLOW_NONTEST_DB", raising=False)
    if override is not None:
        monkeypatch.setenv("HELIOS_ALLOW_NONTEST_DB", override)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = actual
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(fixtures, "create_engine", create_engine)
    iterator = fixtures._database_engine(disposable=disposable)
    if outcome == "ok":
        assert next(iterator) is engine
        with pytest.raises(StopIteration):
            next(iterator)
    else:
        with pytest.raises(pytest.fail.Exception if outcome == "fail" else pytest.skip.Exception):
            next(iterator)
    if create_engine.called:
        engine.dispose.assert_called_once()
