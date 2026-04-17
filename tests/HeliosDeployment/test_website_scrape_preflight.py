from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from core.database import LocalEmployer, RestaurantURL
from scripts.check_website_scrape_preflight import build_canary_command, build_preflight_report


def _build_employer(employer_id: int, name: str) -> LocalEmployer:
    return LocalEmployer(
        id=employer_id,
        raw_name=name,
        name=name,
        fingerprint=name.lower().replace(" ", "-"),
        address=f"{employer_id} Main St, Austin, TX",
        industry="food_full_service",
        region="austin_tx",
        source="manual",
        is_active=True,
    )


def _write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "hint_registry.v1",
                "hints": [
                    {
                        "id": "hint_demo",
                        "brand": "demo",
                        "hint_type": "corporate_promo_slug",
                        "slug": "/promotions",
                        "target_domain": "demo.com",
                        "source": "manual_replay",
                        "first_seen": "2026-04-01",
                        "last_verified": "2026-04-10",
                        "expires_at": "2099-01-01",
                        "verified_against_url": "https://demo.com/promotions",
                    }
                ],
            }
        )
    )


def test_build_canary_command_uses_expected_flags():
    command = build_canary_command(region="austin_tx", canary_sites=5, skip_checked_days=0)
    assert "--max-sites 5" in command
    assert "--skip-checked-days 0" in command
    assert "--dry-run" in command
    assert "--region austin_tx" in command


def test_build_preflight_report_passes_local_checks(engine, monkeypatch, tmp_path):
    registry_path = tmp_path / "registry.json"
    cache_dir = tmp_path / "cache"
    debug_dir = tmp_path / "debug"
    _write_registry(registry_path)

    with Session(engine) as session:
        session.add(_build_employer(1, "Alpha Cafe"))
        session.add(
            RestaurantURL(
                local_employer_id=1,
                url="https://alpha.example.com",
                source="manual",
                is_active=True,
                last_checked=None,
            )
        )
        session.commit()

    monkeypatch.setattr("scripts.check_website_scrape_preflight.init_db", lambda: engine)
    monkeypatch.setattr(
        "scripts.check_website_scrape_preflight.get_session",
        lambda eng: Session(bind=eng),
    )

    report = build_preflight_report(
        region="austin_tx",
        max_sites=10,
        skip_checked_days=0,
        registry_path=registry_path,
        cache_dir=cache_dir,
        debug_dir=debug_dir,
    )

    statuses = {check["name"]: check["status"] for check in report["checks"]}
    assert report["ready"] is True
    assert statuses["imports"] == "pass"
    assert statuses["hint_registry"] == "pass"
    assert statuses["target_query"] == "pass"


def test_build_preflight_report_warns_when_target_query_empty(engine, monkeypatch, tmp_path):
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path)

    monkeypatch.setattr("scripts.check_website_scrape_preflight.init_db", lambda: engine)
    monkeypatch.setattr(
        "scripts.check_website_scrape_preflight.get_session",
        lambda eng: Session(bind=eng),
    )

    report = build_preflight_report(
        region="austin_tx",
        max_sites=10,
        skip_checked_days=0,
        registry_path=registry_path,
        cache_dir=tmp_path / "cache",
        debug_dir=tmp_path / "debug",
    )

    statuses = {check["name"]: check["status"] for check in report["checks"]}
    assert report["ready"] is True
    assert statuses["target_query"] == "warn"


def test_build_preflight_report_blocks_on_remote_ssh_failure(engine, monkeypatch, tmp_path):
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path)

    with Session(engine) as session:
        session.add(_build_employer(1, "Alpha Cafe"))
        session.add(
            RestaurantURL(
                local_employer_id=1,
                url="https://alpha.example.com",
                source="manual",
                is_active=True,
                last_checked=None,
            )
        )
        session.commit()

    monkeypatch.setattr("scripts.check_website_scrape_preflight.init_db", lambda: engine)
    monkeypatch.setattr(
        "scripts.check_website_scrape_preflight.get_session",
        lambda eng: Session(bind=eng),
    )
    monkeypatch.setattr("scripts.check_website_scrape_preflight.shutil.which", lambda _cmd: "/usr/bin/ssh")

    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["ssh"], returncode=255, stdout="", stderr="network unreachable")

    monkeypatch.setattr("scripts.check_website_scrape_preflight.subprocess.run", _fake_run)

    report = build_preflight_report(
        region="austin_tx",
        max_sites=10,
        skip_checked_days=0,
        remote_host="orangepi@192.168.1.191",
        registry_path=registry_path,
        cache_dir=tmp_path / "cache",
        debug_dir=tmp_path / "debug",
    )

    statuses = {check["name"]: check["status"] for check in report["checks"]}
    assert report["ready"] is False
    assert statuses["remote_ssh"] == "fail"
