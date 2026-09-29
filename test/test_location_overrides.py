"""ADR-0014 location overrides: validation, and minting/dedupe/lifecycle on PostgreSQL."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.discovery.location_overrides import (
    DEFAULT_PATH,
    OVERRIDE_NAMESPACE,
    OverrideFile,
    OverrideState,
    effective_location,
    load_overrides,
    parse_overrides,
    persist_overrides,
)
from apps.discovery.models import DiscoveryLifecycleState
from apps.discovery.pipeline import run_discovery
from packages.helios_core.identity.models import Place, ResolutionEvent
from packages.helios_core.provenance.models import Source, SourceRecord, SourceRecordVersion
from test.provider_support import migrate
from test.test_venue_lifecycle import NOW, TIMES, mapped, poi, release

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine

    from apps.discovery.overture import OverturePoi
    from apps.discovery.pipeline import DiscoveryReport

BAD = (30.3, -97.7)  # the Overture point
GOOD = (30.315, -97.7)  # ~1.67 km north: the corrected point


def entry(key: str, **changes: Any) -> dict[str, Any]:  # noqa: ANN401 - raw YAML shape
    raw: dict[str, Any] = {
        "gers_id": key,
        "latitude": GOOD[0],
        "longitude": GOOD[1],
        "corrects": {"latitude": BAD[0], "longitude": BAD[1]},
        "evidence_url": "https://kitchen.example.com/locations/main",
        "basis": "official_pin",
        "reason": "Overture point 1.67 km from the corroborated address",
    }
    raw.update(changes)
    return raw


def override_file(*entries: dict[str, Any]) -> OverrideFile:
    return OverrideFile(
        entries=parse_overrides({"overrides": list(entries)}),
        content_hash="sha256:" + "0" * 64,
        source_url="repo:config/location_overrides.yaml",
    )


# --- validation (no database) -------------------------------------------------


def test_committed_file_is_valid_and_cites_the_repo() -> None:
    overrides = load_overrides(DEFAULT_PATH)
    assert overrides.source_url == "repo:config/location_overrides.yaml"
    assert overrides.content_hash.startswith("sha256:")
    for item in overrides.entries.values():
        assert (item.latitude, item.longitude) != (item.corrects_latitude, item.corrects_longitude)


def test_parse_quantizes_to_place_precision() -> None:
    parsed = parse_overrides(
        {"overrides": [entry("g1", latitude=30.31500049, address="1 Main St, Austin, TX")]}
    )
    assert parsed["g1"].latitude == Decimal("30.315000")
    assert parsed["g1"].corrects_longitude == Decimal("-97.700000")
    assert parsed["g1"].address == "1 Main St, Austin, TX"
    assert parse_overrides(None) == {} == parse_overrides({"overrides": []})


@pytest.mark.parametrize(
    "raw",
    [
        entry("g1", bogus=1),  # unknown key
        {k: v for k, v in entry("g1").items() if k != "corrects"},  # missing corrects
        entry("g1", gers_id=" g1"),  # untrimmed key
        entry("g1", latitude=True),  # bool is not a number
        entry("g1", latitude=float("nan")),  # not finite
        entry("g1", latitude=31.5),  # outside the metro bbox
        entry("g1", corrects={"latitude": 30.3}),  # incomplete corrects
        entry("g1", corrects={"latitude": GOOD[0], "longitude": GOOD[1]}),  # no-op
        entry("g1", basis="census"),  # one interpolating geocoder is not a basis
        entry("g1", evidence_url="ftp://example.com/x"),
        entry("g1", reason=""),
        entry("g1", address="  "),
        "not a mapping",
    ],
)
def test_malformed_entry_fails_closed(raw: object) -> None:
    with pytest.raises(ValueError, match="override"):
        parse_overrides({"overrides": [raw]})


def test_duplicate_and_malformed_documents_raise() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_overrides({"overrides": [entry("g1"), entry("g1")]})
    with pytest.raises(ValueError, match="mapping"):
        parse_overrides({"venues": []})
    with pytest.raises(ValueError, match="list"):
        parse_overrides({"overrides": {"g1": {}}})


def test_file_outside_repo_has_no_provenance(tmp_path: Path) -> None:
    path = tmp_path / "overrides.yaml"
    path.write_text("overrides: []\n", encoding="utf-8")
    assert load_overrides(path).source_url is None
    with pytest.raises(FileNotFoundError):
        load_overrides(tmp_path / "missing.yaml")


def test_effective_location_applies_only_while_corrects_matches() -> None:
    state = OverrideState(
        gers_id="g1",
        entry=override_file(entry("g1", address="2 Main St")).entries["g1"],
        record_id=1,
        version_id=1,
    )
    here = effective_location(poi(key="g1", lat=BAD[0], lon=BAD[1]), state)
    assert (here.latitude, here.longitude, here.address) == (*GOOD, "2 Main St")
    assert here.applied and not here.stale
    moved = effective_location(poi(key="g1", lat=30.33, lon=BAD[1]), state)
    assert (moved.latitude, moved.applied, moved.stale) == (30.33, False, True)
    withdrawn = OverrideState(gers_id="g1", entry=None, record_id=1, version_id=2)
    plain = effective_location(poi(key="g1"), withdrawn)
    assert (plain.latitude, plain.applied, plain.stale) == (BAD[0], False, False)


# --- PostgreSQL ------------------------------------------------------------------


@pytest.fixture
def session(historical_database_engine: Engine) -> Iterator[Session]:
    migrate("upgrade", "head")
    with Session(historical_database_engine) as session:
        yield session


def run(
    session: Session,
    rows: list[OverturePoi],
    n: int,
    overrides: OverrideFile | None = None,
    *,
    step: int = 0,
) -> DiscoveryReport:
    decided_at = NOW + timedelta(days=n, minutes=step)
    states = persist_overrides(session, overrides or override_file(), observed_at=decided_at)
    return run_discovery(
        session,
        rows,
        decided_at=decided_at,
        observed_at=TIMES[n],
        release=release(n),
        overrides=states,
    )


def place_point(session: Session, key: str) -> tuple[Decimal | None, Decimal | None, str | None]:
    place = session.get(Place, mapped(session, key).place_subject_id, populate_existing=True)
    assert place is not None
    return place.latitude, place.longitude, place.address


def test_minting_and_rebuild_use_the_override(session: Session) -> None:
    bad = poi(lat=BAD[0], lon=BAD[1], address="1500 S")
    report = run(session, [bad], 0, override_file(entry(bad.gers_id, address="1500 S Main St")))
    assert (report.minted, report.overrides_applied, report.override_stale) == (1, 1, 0)
    assert place_point(session, bad.gers_id) == (
        Decimal("30.315000"),
        Decimal("-97.700000"),
        "1500 S Main St",
    )
    # Bronze keeps the Overture observation as published.
    payload = session.scalar(
        select(SourceRecordVersion.source_payload)
        .join(SourceRecord)
        .join(Source)
        .where(Source.namespace == "overture", SourceRecord.external_key == bad.gers_id)
    )
    assert payload is not None and payload["latitude"] == BAD[0]


def test_dedupe_finds_the_twin_hidden_by_a_bad_point(session: Session) -> None:
    good = poi(name="P Kitchen", lat=GOOD[0], lon=GOOD[1])
    run(session, [good], 0)
    twin = poi(name="P. Kitchen", lat=BAD[0], lon=BAD[1])
    without = run(session, [twin], 1, step=1, overrides=None)
    assert (without.deduped, without.minted) == (0, 1)  # control: the bad point hides it
    fresh = poi(name="P. Kitchen", lat=BAD[0], lon=BAD[1])
    report = run(session, [fresh], 1, override_file(entry(fresh.gers_id)), step=2)
    assert (report.deduped, report.minted) == (1, 0)
    assert mapped(session, fresh.gers_id).subject_id == mapped(session, good.gers_id).subject_id


def test_existing_venue_is_corrected_in_place_not_relocated(session: Session) -> None:
    bad = poi(lat=BAD[0], lon=BAD[1])
    run(session, [bad], 0)
    before = mapped(session, bad.gers_id)
    events = session.scalar(select(func.count()).select_from(ResolutionEvent))
    overrides = override_file(entry(bad.gers_id))

    # Same release re-run: the new override Version re-opens the projection.
    report = run(session, [bad], 0, overrides, step=1)
    assert (report.lifecycle.relocated, report.lifecycle.updated) == (0, 1)
    after = mapped(session, bad.gers_id)
    assert (after.subject_id, after.place_subject_id) == (
        before.subject_id,
        before.place_subject_id,
    )
    assert place_point(session, bad.gers_id)[:2] == (Decimal("30.315000"), Decimal("-97.700000"))
    assert session.scalar(select(func.count()).select_from(ResolutionEvent)) == events

    # Idempotent: no new Bronze Version, no new journal row, no change.
    journal = session.scalar(select(func.count()).select_from(DiscoveryLifecycleState))
    again = run(session, [bad], 0, overrides, step=2)
    assert again.lifecycle.updated == again.lifecycle.relocated == 0
    assert session.scalar(select(func.count()).select_from(DiscoveryLifecycleState)) == journal
    versions = session.scalar(
        select(func.count())
        .select_from(SourceRecordVersion)
        .join(Source, Source.id == SourceRecordVersion.source_id)
        .where(Source.namespace == OVERRIDE_NAMESPACE)
    )
    assert versions == 1

    # The next release still carries the bad point: no false relocation.
    later = poi(key=bad.gers_id, lat=BAD[0], lon=BAD[1])
    nxt = run(session, [later], 1, overrides)
    assert nxt.lifecycle.relocated == 0
    assert mapped(session, bad.gers_id).subject_id == before.subject_id
    assert place_point(session, bad.gers_id)[0] == Decimal("30.315000")


def test_withdrawal_reverts_in_place_and_keeps_history(session: Session) -> None:
    bad = poi(lat=BAD[0], lon=BAD[1])
    run(session, [bad], 0, override_file(entry(bad.gers_id)))
    subject = mapped(session, bad.gers_id).subject_id
    report = run(session, [bad], 0, override_file(), step=1)
    assert report.lifecycle.relocated == 0
    assert mapped(session, bad.gers_id).subject_id == subject
    assert place_point(session, bad.gers_id)[0] == Decimal("30.300000")
    payloads = session.scalars(
        select(SourceRecordVersion.source_payload)
        .join(Source, Source.id == SourceRecordVersion.source_id)
        .where(Source.namespace == OVERRIDE_NAMESPACE)
        .order_by(SourceRecordVersion.observed_at)
    ).all()
    assert [p.get("withdrawn", False) for p in payloads] == [False, True]
    # A second empty run appends nothing.
    run(session, [bad], 0, override_file(), step=2)
    assert (
        len(
            session.scalars(
                select(SourceRecordVersion.id)
                .join(Source, Source.id == SourceRecordVersion.source_id)
                .where(Source.namespace == OVERRIDE_NAMESPACE)
            ).all()
        )
        == 2
    )


@pytest.mark.parametrize(
    ("new_lat", "relocated"),
    [(30.3151, 0), (30.34, 1)],  # Overture fixed it (near the override) / the venue moved
)
def test_upstream_drift_disables_the_override(
    session: Session, new_lat: float, relocated: int
) -> None:
    bad = poi(lat=BAD[0], lon=BAD[1])
    overrides = override_file(entry(bad.gers_id))
    run(session, [bad], 0, overrides)
    drifted = poi(key=bad.gers_id, lat=new_lat, lon=BAD[1])
    report = run(session, [drifted], 1, overrides)
    assert (report.override_stale, report.overrides_applied) == (1, 0)
    assert report.stale_override_ids == [bad.gers_id]
    assert report.lifecycle.relocated == relocated
    assert place_point(session, bad.gers_id)[0] == Decimal(f"{new_lat:.6f}")


def test_unmatched_override_is_counted(session: Session) -> None:
    report = run(session, [poi()], 0, override_file(entry("not-in-this-release")))
    assert (report.override_unmatched, report.overrides_applied) == (1, 0)


def test_persist_requires_repo_provenance(session: Session) -> None:
    bare = OverrideFile(entries=parse_overrides({"overrides": [entry("g1")]}), source_url=None)
    with pytest.raises(ValueError, match="provenance"):
        persist_overrides(session, bare, observed_at=NOW)
