"""apps.menu_pipeline.backup_manifest (ADR-0031 D1, D2): the facts a restore is checked against."""

from __future__ import annotations

import json
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

import pytest

from apps.menu_pipeline import backup_manifest
from apps.menu_pipeline.backup_manifest import differences, facts, main

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

NIGHT = {"alembic_version": "9b1e5d3c7a20", "current_menu_rows": 99408, "venues_with_menu": 1233}


def test_differences_name_each_key_that_differs() -> None:
    assert differences(NIGHT, dict(NIGHT)) == []
    found = NIGHT | {"current_menu_rows": 99000, "extra": 1}
    assert differences(found, NIGHT) == [
        "current_menu_rows: 99000 != 99408",
        "extra: 1 != None",
    ]


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Databases by name, read without a server."""
    databases: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(backup_manifest, "_read_only", lambda name: nullcontext(name))
    monkeypatch.setattr(backup_manifest, "facts", lambda name: databases[name])
    return databases


def _manifest(tmp_path: Path, **databases: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"commit": "0219809", "databases": databases}), encoding="utf-8")
    return path


def test_prints_each_database(
    fake_db: dict[str, dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    fake_db.update(helios=NIGHT, helios_work=NIGHT | {"current_menu_rows": 1})
    main(["--db", "helios", "--db=helios_work"])
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"helios": NIGHT, "helios_work": NIGHT | {"current_menu_rows": 1}}


def test_expect_matches_a_restore_under_another_name(
    fake_db: dict[str, dict[str, Any]], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_db["helios_drill"] = dict(NIGHT)
    main(
        [
            "--db",
            "helios_drill",
            "--expect",
            str(_manifest(tmp_path, helios=NIGHT)),
            "--as",
            "helios",
        ]
    )
    assert "match: helios_drill equals helios" in capsys.readouterr().out


def test_expect_fails_on_a_difference(
    fake_db: dict[str, dict[str, Any]], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_db["helios"] = NIGHT | {"venues_with_menu": 1200}
    with pytest.raises(SystemExit) as exit_info:
        main(["--db", "helios", "--expect", str(_manifest(tmp_path, helios=NIGHT))])
    assert exit_info.value.code == 1
    assert "mismatch venues_with_menu: 1200 != 1233" in capsys.readouterr().out


def test_expect_needs_the_entry_and_one_database(
    fake_db: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    fake_db.update(helios=NIGHT, helios_work=NIGHT)
    manifest = _manifest(tmp_path, helios_work=NIGHT)
    with pytest.raises(SystemExit, match="has no database 'helios'"):
        main(["--db", "helios", "--expect", str(manifest)])
    with pytest.raises(SystemExit):
        main(["--db", "helios", "--db", "helios_work", "--expect", str(manifest)])


def test_the_manifest_sql_runs_on_the_schema(session: Session) -> None:
    """A schema change that breaks the manifest's SQL fails here, not on a backup night."""
    found = facts(session)
    assert set(found) == {
        "alembic_version",
        "current_menu_rows",
        "venues_with_menu",
        "newest_effective",
    }
    assert found["current_menu_rows"] >= 0 and found["venues_with_menu"] >= 0
