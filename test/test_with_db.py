"""Pointing a CLI or a PostgreSQL tool at another database of the same server (ADR-0030)."""

from __future__ import annotations

import runpy
import sys

import pytest

from apps.menu_pipeline import with_db

_URL = "postgresql+psycopg://helios:s3cret@db.local:5433/helios"


def test_database_url_changes_only_the_name() -> None:
    assert (
        with_db.database_url(_URL, "helios_work")
        == "postgresql+psycopg://helios:s3cret@db.local:5433/helios_work"
    )


def test_pg_environment() -> None:
    assert with_db.pg_environment(_URL, "helios_laptop") == {
        "PGHOST": "db.local",
        "PGPORT": "5433",
        "PGUSER": "helios",
        "PGPASSWORD": "s3cret",
        "PGDATABASE": "helios_laptop",
    }


def test_pg_mode_passes_the_connection_in_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", _URL)
    check = 'test "$PGDATABASE" = helios_next && test "$PGPASSWORD" = s3cret && test "$1" = -Fc'
    with pytest.raises(SystemExit) as stopped:
        with_db.main(["helios_next", "--pg", "sh", "-c", check, "sh", "-Fc"])
    assert stopped.value.code == 0


def test_module_mode_rewrites_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _URL)
    seen: list[tuple[str, list[str]]] = []

    def run_module(module: str, **_: object) -> None:
        import os  # noqa: PLC0415 - read inside the patched call

        seen.append((os.environ["DATABASE_URL"], list(sys.argv)))

    monkeypatch.setattr(runpy, "run_module", run_module)
    monkeypatch.setattr(sys, "argv", ["with_db"])
    with_db.main(["helios_work", "-m", "apps.menu_pipeline.extract", "--no-model"])

    assert seen == [
        (
            "postgresql+psycopg://helios:s3cret@db.local:5433/helios_work",
            ["apps.menu_pipeline.extract", "--no-model"],
        )
    ]


@pytest.mark.parametrize("argv", [[], ["helios_work"], ["helios_work", "-x", "tool"]])
def test_usage(argv: list[str]) -> None:
    with pytest.raises(SystemExit, match="usage"):
        with_db.main(argv)
