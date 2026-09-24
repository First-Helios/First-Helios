"""Discovery write paths through a real commit (R29).

The ``session`` fixture wraps each test in a savepoint that is rolled back, so
deferred constraint triggers (``ct_subject_exact_typed_grain``,
``ct_resolution_event_support``, ...) never fire there. These tests commit the
way the CLIs do (``on_batch=session.commit`` plus a final commit), so a write
the triggers reject fails here instead of first failing in production. Rows
carry UUID tokens so they never collide with other committed test data.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.discovery.overture import OverturePoi
from apps.discovery.pipeline import run_discovery
from apps.discovery.url_pipeline import MENU_URL_NAMESPACE, WEBSITE_NAMESPACE, resolve_urls
from apps.discovery.web_client import MenuUrlDiscovery
from packages.helios_core.config import get_database_url
from packages.helios_core.identity.models import CurrentResolution, Establishment
from packages.helios_core.provenance.models import Source, SourceRecord

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NOW = datetime.now(UTC)


@pytest.fixture
def committed(disposable_database_engine: Engine) -> Iterator[sessionmaker[Session]]:
    subprocess.run(
        ["alembic", "-c", str(_REPO_ROOT / "alembic.ini"), "upgrade", "head"],
        check=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "DATABASE_URL": get_database_url()},
    )
    yield sessionmaker(bind=disposable_database_engine, expire_on_commit=False)


def _poi(name: str, lat: float, lon: float, *, website: str | None = None) -> OverturePoi:
    gers = f"commit-{uuid4().hex}"
    websites = (website,) if website else ()
    return OverturePoi(
        gers_id=gers,
        name=name,
        primary_category="restaurant",
        alternate_categories=(),
        websites=websites,
        address=f"{name} address",
        latitude=lat,
        longitude=lon,
        confidence=0.9,
        # The URL pipeline reads websites back from this saved Bronze payload.
        raw={"id": gers, "name": name, "lat": lat, "lon": lon, "websites": list(websites)},
    )


def _discover(session: Session, pois: list[OverturePoi]) -> None:
    run_discovery(
        session,
        pois,
        decided_at=_NOW,
        observed_at=_NOW,
        release="commit-test-2026-01-01",
        batch_size=2,
        on_batch=session.commit,
    )
    session.commit()


def _resolved_subject(session: Session, namespace: str, external_key: str) -> int | None:
    return session.scalar(
        select(CurrentResolution.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(
            Source.namespace == namespace,
            SourceRecord.external_key == external_key,
            CurrentResolution.state == "resolved",
        )
    )


def test_discovery_mint_dedupe_and_rerun_commit(committed: sessionmaker[Session]) -> None:
    token = uuid4().hex
    first = _poi(f"Commit Grill {token}", 30.2701, -97.7313)
    twin = _poi(f"Commit Grill {token}", 30.27015, -97.7313)  # ~6 m away: dedupes
    other = _poi(f"Commit Cafe {token}", 30.2489, -97.7500)
    pois = [first, twin, other]

    with committed() as session:
        _discover(session, pois)
    with committed() as session:
        _discover(session, pois)  # a committed rerun reuses every record

    with committed() as reader:
        subjects = [_resolved_subject(reader, "overture", p.gers_id) for p in pois]
        assert None not in subjects
        assert subjects[0] == subjects[1] != subjects[2]
        # Each resolves onto a current Establishment, not a bare Organization.
        assert all(reader.get(Establishment, subject) is not None for subject in subjects)


class _Resolver:
    def __init__(self, website: str, menu_url: str) -> None:
        self._website = website
        self._menu_url = menu_url

    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None:
        if website != self._website:
            return None  # other committed venues in a shared *_test database
        return MenuUrlDiscovery(menu_url=self._menu_url, signal="crawled")


def test_resolve_urls_commits_website_and_menu_url(committed: sessionmaker[Session]) -> None:
    token = uuid4().hex
    website = f"https://c{token[:16]}.example.com/"
    poi = _poi(f"Commit Kitchen {token}", 30.3079, -97.7559, website=website)
    with committed() as session:
        _discover(session, [poi])

    resolver = _Resolver(website, f"{website}menu")
    with committed() as session:
        resolve_urls(
            session,
            resolver=resolver,
            registry={},
            decided_at=_NOW,
            observed_at=_NOW,
            batch_size=2,
            on_batch=session.commit,
        )
        session.commit()

    with committed() as reader:
        establishment = reader.get(
            Establishment, _resolved_subject(reader, "overture", poi.gers_id)
        )
        assert establishment is not None
        organization = establishment.organization_subject_id
        assert _resolved_subject(reader, WEBSITE_NAMESPACE, poi.gers_id) == organization
        assert _resolved_subject(reader, MENU_URL_NAMESPACE, poi.gers_id) == organization
