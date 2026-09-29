"""A crashed iterator must never seal partial commits as a complete survey."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.discovery import __main__ as cli
from apps.discovery.models import DiscoveryReleaseCompletion
from apps.discovery.pipeline import run_discovery
from packages.helios_core.provenance.models import SourceRecordVersion
from test.provider_support import migrate
from test.test_venue_lifecycle import TIMES, complete, ingest, poi, release, sweep

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

    from apps.discovery.overture import OvertureConfig, OverturePoi


def test_crash_after_95_percent_committed_does_not_enable_closure(
    historical_database_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate("upgrade", "head")
    factory = sessionmaker(historical_database_engine)
    with factory.begin() as session:
        ingest(session, [poi()], 0)
        complete(session, 0)
        complete(session, 1, predecessor=0)

    def broken(_config: OvertureConfig) -> Iterator[OverturePoi]:
        for _ in range(96):
            yield poi(name="")  # source-faithful rejection still counts as surveyed presence
        raise RuntimeError("acquisition interrupted at 96/100")

    def small_batches(*args, **kwargs):  # type: ignore[no-untyped-def]
        return run_discovery(*args, **kwargs, batch_size=5)

    monkeypatch.setattr(cli, "read_overture_pois", broken)
    monkeypatch.setattr(cli, "run_discovery", small_batches)
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "discovery",
            "--release",
            release(2),
            "--expected-predecessor",
            release(1),
            "--no-geocode",
        ],
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        cli.main()
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceRecordVersion)
                .where(SourceRecordVersion.observed_at == TIMES[2])
            )
            == 95
        )
        assert session.scalar(select(func.count()).select_from(DiscoveryReleaseCompletion)) == 2
        report = sweep(session, 2)
        assert report.closed == 0
        assert "completion" in report.reasons[0]


def test_cli_seals_only_exhausted_release_and_runs_readiness(
    historical_database_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.helios_core.identity.models import Subject

    migrate("upgrade", "head")
    factory = sessionmaker(historical_database_engine)
    row = poi()
    monkeypatch.setattr(cli, "read_overture_pois", lambda _config: iter([row]))
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr(sys, "argv", ["discovery", "--release", release(0), "--no-geocode"])
    cli.main()
    cli.main()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DiscoveryReleaseCompletion)) == 1
        completion = session.scalar(select(DiscoveryReleaseCompletion))
        assert completion and completion.poi_count == 1 and completion.completed_at
        assert (
            session.scalar(select(Subject.readiness).where(Subject.kind == "place")) == "eligible"
        )


def test_release_without_publication_date_is_refused() -> None:
    with pytest.raises(ValueError, match="stable"):
        cli._observed_at("s3://bucket/latest/")
