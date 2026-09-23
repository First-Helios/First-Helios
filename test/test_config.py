"""DATABASE_URL has no default: an unset variable must fail, never pick a target (R09)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from packages.helios_core.config import DatabaseUrlNotSetError, get_database_url, get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_or_blank_database_url_raises(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)

    assert get_settings().database_url is None
    with pytest.raises(DatabaseUrlNotSetError, match="DATABASE_URL is not set"):
        get_database_url()


def test_set_database_url_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:5432/helios_test")

    assert get_database_url() == "postgresql+psycopg://u:p@db.example:5432/helios_test"


def test_alembic_refuses_to_run_without_database_url() -> None:
    env = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_REPO_ROOT / "alembic.ini"), "current"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "DATABASE_URL is not set" in result.stderr
