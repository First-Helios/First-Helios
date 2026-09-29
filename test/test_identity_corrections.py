"""S6e corrections applier: file validation, and merges/retirements on PostgreSQL."""

from __future__ import annotations

import sys
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.discovery import corrections as cli
from apps.discovery.corrections import (
    DEFAULT_PATH,
    CorrectionFile,
    CorrectionReport,
    apply_corrections,
    load_corrections,
    parse_corrections,
)
from apps.discovery.lifecycle import run_lifecycle
from apps.discovery.pipeline import run_discovery
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    create_adjudication,
    rebuild_identity_projections,
    record_subject_change,
)
from packages.helios_core.identity.models import (
    Adjudication,
    CurrentResolution,
    Establishment,
    Place,
    ResolutionEvent,
    SubjectChange,
    SubjectChangeEvidence,
    SubjectCurrentness,
    SubjectLineage,
)
from packages.helios_core.provenance.models import Source, SourceRecord
from test.provider_support import migrate
from test.test_venue_lifecycle import NOW, TIMES, poi, release

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine

    from apps.discovery.overture import OverturePoi
    from apps.discovery.pipeline import DiscoveryReport

URL = "https://kitchen.example.com/locations/main"
# One outlet listed twice ~734 m apart: beyond the dedupe radius, so discovery
# mints two venues (the precision review's "misplaced twin").
HERE = (30.3, -97.7)
TWIN = (30.3066, -97.7)


def merge(survivor: str, *merged: str, entry_id: str = "M1", **changes: Any) -> dict[str, Any]:  # noqa: ANN401 - raw YAML
    raw: dict[str, Any] = {
        "id": entry_id,
        "survivor": survivor,
        "merge": list(merged),
        "rationale": "same outlet on the official locator",
        "evidence_url": URL,
    }
    raw.update(changes)
    return raw


def retirement(gers: str, entry_id: str = "R1", **changes: Any) -> dict[str, Any]:  # noqa: ANN401 - raw YAML
    raw: dict[str, Any] = {
        "id": entry_id,
        "gers_id": gers,
        "rationale": "a school cafeteria, not a public venue",
        "evidence_url": URL,
    }
    raw.update(changes)
    return raw


def corrections_file(
    merges: list[dict[str, Any]] | None = None,
    retirements: list[dict[str, Any]] | None = None,
) -> CorrectionFile:
    parsed = parse_corrections({"merges": merges or [], "retirements": retirements or []})
    return CorrectionFile(*parsed, content_hash="sha256:" + "0" * 64)


# --- validation (no database) -------------------------------------------------


def test_committed_file_is_valid() -> None:
    loaded = load_corrections(DEFAULT_PATH)
    assert loaded.source_url == "repo:config/identity_corrections.yaml"
    assert loaded.content_hash.startswith("sha256:")
    assert {entry.id for entry in loaded.merges} >= {"D01", "D40"}


def test_parse_accepts_an_empty_or_null_document() -> None:
    assert parse_corrections(None) == ((), ())
    assert parse_corrections({"merges": None, "retirements": []}) == ((), ())
    merges, retirements = parse_corrections({"merges": [merge("s", "a", "b")]})
    assert merges[0].merged == ("a", "b") and retirements == ()


@pytest.mark.parametrize(
    ("merges", "retirements"),
    [
        ([merge("s", "a", bogus=1)], []),  # unknown key
        ([{k: v for k, v in merge("s", "a").items() if k != "rationale"}], []),
        ([merge("s")], []),  # nothing to merge
        ([merge("s", "a", merge="a")], []),  # not a list
        ([merge(" s", "a")], []),  # untrimmed key
        ([merge("s", "")], []),
        ([merge("s", "a", evidence_url="ftp://example.com/x")], []),
        ([merge("s", "a", rationale="x" * 2001)], []),
        ([merge("s", "a", id=" ")], []),
        (["not a mapping"], []),
        ([], [retirement("g", reason="extra")]),
        ([merge("s", "a"), merge("t", "b")], []),  # duplicate entry id
        ([merge("s", "a", "s")], []),  # survivor listed as merged
        ([merge("s", "a")], [retirement("a")]),  # merged and retired
        ([merge("s", "a"), merge("t", "a", entry_id="M2")], []),  # in two clusters
    ],
)
def test_malformed_file_fails_closed(
    merges: list[dict[str, Any]], retirements: list[dict[str, Any]]
) -> None:
    with pytest.raises(ValueError, match="correction"):
        parse_corrections({"merges": merges, "retirements": retirements})


def test_malformed_documents_raise() -> None:
    with pytest.raises(ValueError, match="mapping"):
        parse_corrections({"overrides": []})
    with pytest.raises(ValueError, match="list"):
        parse_corrections({"merges": {"M1": {}}})


def test_file_outside_repo_has_no_provenance(tmp_path: Path) -> None:
    path = tmp_path / "corrections.yaml"
    path.write_text("merges: []\n", encoding="utf-8")
    assert load_corrections(path).source_url is None
    with pytest.raises(FileNotFoundError):
        load_corrections(tmp_path / "missing.yaml")


# --- PostgreSQL ------------------------------------------------------------------


@pytest.fixture
def session(historical_database_engine: Engine) -> Iterator[Session]:
    migrate("upgrade", "head")
    with Session(historical_database_engine) as session:
        yield session


def discover(session: Session, rows: list[OverturePoi], n: int, step: int = 0) -> DiscoveryReport:
    return run_discovery(
        session,
        rows,
        decided_at=NOW + timedelta(days=n, minutes=step),
        observed_at=TIMES[n],
        release=release(n),
    )


def apply(session: Session, corrections: CorrectionFile, step: int = 0) -> CorrectionReport:
    return apply_corrections(
        session, corrections, actor="owner", decided_at=NOW + timedelta(days=30, minutes=step)
    )


def resolution(session: Session, gers: str) -> tuple[str, int | None]:
    row = session.execute(
        select(CurrentResolution.state, CurrentResolution.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == "overture", SourceRecord.external_key == gers)
    ).one()
    return row.state, row.subject_id


def venue(session: Session, gers: str) -> Establishment:
    state, subject_id = resolution(session, gers)
    assert state == "resolved"
    found = session.get(Establishment, subject_id, populate_existing=True)
    assert found is not None
    return found


def current(session: Session, subject_id: int) -> bool:
    return (
        session.scalar(
            select(SubjectCurrentness.is_current).where(SubjectCurrentness.subject_id == subject_id)
        )
        is True
    )


def successor(session: Session, subject_id: int) -> int | None:
    return session.scalar(
        select(SubjectLineage.successor_subject_id).where(
            SubjectLineage.predecessor_subject_id == subject_id
        )
    )


def count(session: Session, model: Any) -> int:  # noqa: ANN401 - any ORM model
    return session.scalar(select(func.count()).select_from(model)) or 0


def twins(session: Session) -> tuple[OverturePoi, OverturePoi]:
    here = poi(name="Pinthouse Pizza", lat=HERE[0], lon=HERE[1])
    twin = poi(name="Pinthouse Pizza", lat=TWIN[0], lon=TWIN[1])
    report = discover(session, [here, twin], 0)
    assert report.minted == 2  # control: discovery cannot see the twin
    return here, twin


def test_merge_remaps_retires_and_merges_unused_parents(session: Session) -> None:
    here, twin = twins(session)
    survivor, loser = venue(session, here.gers_id), venue(session, twin.gers_id)

    report = apply(session, corrections_file([merge(here.gers_id, twin.gers_id)]))

    assert (report.merged, report.remapped, report.parents_merged) == (1, 1, 2)
    assert report.satisfied == report.retired == 0 and not report.skipped
    assert venue(session, twin.gers_id).subject_id == survivor.subject_id
    for old, new in (
        (loser.subject_id, survivor.subject_id),
        (loser.organization_subject_id, survivor.organization_subject_id),
        (loser.place_subject_id, survivor.place_subject_id),
    ):
        assert not current(session, old) and successor(session, old) == new
        assert current(session, new)
    # The survivor keeps its own point; one human Adjudication backs every write.
    place = session.get(Place, survivor.place_subject_id, populate_existing=True)
    assert place is not None and float(place.latitude or 0) == HERE[0]
    adjudication = session.scalars(select(Adjudication)).one()
    assert adjudication.actor == "owner" and "entry M1" in adjudication.rationale
    assert URL in adjudication.rationale
    events = session.scalars(
        select(ResolutionEvent).where(ResolutionEvent.adjudication_id == adjudication.id)
    ).all()
    assert {(e.operation, e.actor_class) for e in events} == {("remap", "human")}
    changes = session.scalars(select(SubjectChange)).all()
    assert [c.operation for c in changes] == ["merge"] * 3
    assert all(c.adjudication_id == adjudication.id for c in changes)
    assert count(session, SubjectChangeEvidence) == 6  # both Overture Versions, per change


def test_rerun_is_a_no_op(session: Session) -> None:
    here, twin = twins(session)
    corrections = corrections_file([merge(here.gers_id, twin.gers_id)])
    apply(session, corrections)
    before = [count(session, m) for m in (ResolutionEvent, SubjectChange, Adjudication)]
    again = apply(session, corrections, step=1)
    assert (again.merged, again.satisfied, again.remapped, again.parents_merged) == (0, 1, 0, 0)
    assert [count(session, m) for m in (ResolutionEvent, SubjectChange, Adjudication)] == before


def test_rebuild_reapplies(session: Session) -> None:
    here, twin = twins(session)
    corrections = corrections_file([merge(here.gers_id, twin.gers_id)])
    apply(session, corrections)
    first = venue(session, here.gers_id).subject_id

    # Projection rebuild: the events replay to the same state.
    rebuild_identity_projections(session)
    assert venue(session, twin.gers_id).subject_id == first
    assert apply(session, corrections, step=1).satisfied == 1

    # Database rebuild: a fresh discovery mints new Subjects; the GERS-keyed file
    # merges them again.
    session.rollback()
    discover(session, [here, twin], 0)
    assert venue(session, here.gers_id).subject_id != venue(session, twin.gers_id).subject_id
    assert apply(session, corrections).merged == 1
    rebuilt = venue(session, here.gers_id).subject_id
    assert venue(session, twin.gers_id).subject_id == rebuilt != first


def test_lifecycle_leaves_a_merged_venue_alone(session: Session) -> None:
    here, twin = twins(session)
    apply(session, corrections_file([merge(here.gers_id, twin.gers_id)]))
    survivor = venue(session, here.gers_id)

    # The next release still carries the twin at its far point, renamed.
    nxt = [
        poi(key=here.gers_id, name="Pinthouse Pizza", lat=HERE[0], lon=HERE[1]),
        poi(key=twin.gers_id, name="Pinthouse Pizza Round Rock", lat=TWIN[0], lon=TWIN[1]),
    ]
    report = discover(session, nxt, 1)
    lifecycle = run_lifecycle(session, release=release(1), decided_at=NOW + timedelta(days=31))
    assert (report.minted, report.needs_review) == (0, 0)
    for counts in (report.lifecycle, lifecycle):
        assert counts.relocated == counts.rebranded == counts.rehomed == counts.retired == 0
    after = venue(session, twin.gers_id)
    assert after.subject_id == survivor.subject_id == venue(session, here.gers_id).subject_id
    assert after.place_subject_id == survivor.place_subject_id
    assert after.operating_status != "closed" and current(session, after.subject_id)


def test_unresolved_member_is_assigned(session: Session) -> None:
    # Two same-name venues 90 m apart, then a third record between them: two
    # dedupe candidates, so discovery leaves it unresolved.
    west = poi(name="Taco Stand", lat=30.3, lon=-97.7)
    east = poi(name="Taco Stand", lat=30.30081, lon=-97.7)
    middle = poi(name="Taco Stand", lat=30.300405, lon=-97.7)
    discover(session, [west, east], 0)
    assert discover(session, [middle], 0, step=1).ambiguous == 1
    assert resolution(session, middle.gers_id)[0] == "unresolved"

    report = apply(session, corrections_file([merge(west.gers_id, east.gers_id, middle.gers_id)]))
    assert (report.merged, report.assigned, report.remapped) == (1, 1, 1)
    target = venue(session, west.gers_id).subject_id
    assert venue(session, middle.gers_id).subject_id == target
    assert venue(session, east.gers_id).subject_id == target


def test_parent_still_used_by_another_venue_is_kept(session: Session) -> None:
    here, twin = twins(session)
    closed = venue(session, twin.gers_id)
    # The twin relocates in the next release: its old venue closes but stays
    # current and keeps the Organization the new venue shares.
    moved = poi(key=twin.gers_id, name="Pinthouse Pizza", lat=30.31, lon=-97.7)
    assert discover(session, [here, moved], 1).lifecycle.relocated == 1
    relocated = venue(session, twin.gers_id)
    assert relocated.organization_subject_id == closed.organization_subject_id

    report = apply(session, corrections_file([merge(here.gers_id, twin.gers_id)]))
    assert (report.merged, report.parents_merged) == (1, 1)  # the new Place only
    assert report.parents_kept == [
        f"M1: organization {closed.organization_subject_id} is still used by venue "
        f"{closed.subject_id}"
    ]
    assert current(session, closed.organization_subject_id)
    assert not current(session, relocated.place_subject_id)


def test_retirement_unassigns_and_is_never_reminted(session: Session) -> None:
    cafeteria = poi(name="Cool Cafe")
    discover(session, [cafeteria], 0)
    retired = venue(session, cafeteria.gers_id)
    corrections = corrections_file(retirements=[retirement(cafeteria.gers_id)])

    report = apply(session, corrections)
    assert (report.retired, report.unassigned) == (1, 1)
    assert resolution(session, cafeteria.gers_id) == ("needs_review", None)
    assert not current(session, retired.subject_id)
    assert successor(session, retired.subject_id) is None
    # Place and Organization stay: the address and the operator still exist.
    assert current(session, retired.place_subject_id)
    assert current(session, retired.organization_subject_id)
    change = session.scalars(select(SubjectChange)).one()
    assert (change.operation, change.method) == ("retire", "identity-correction-retire")

    assert apply(session, corrections, step=1).satisfied == 1
    again = discover(session, [poi(key=cafeteria.gers_id, name="Cool Cafe")], 1)
    assert (again.minted, again.needs_review) == (0, 1)


def test_missing_records_are_reported_not_applied(session: Session) -> None:
    here, _ = twins(session)
    report = apply(
        session,
        corrections_file(
            [
                merge("not-in-this-release", "also-missing"),
                merge(here.gers_id, "gone", entry_id="M2"),
            ],
            [retirement("absent")],
        ),
    )
    assert report.unmatched == ["not-in-this-release", "gone", "absent"]
    assert report.skipped == [
        "M1: survivor not-in-this-release has no Overture record",
        "R1: absent has no Overture record",
    ]
    assert (report.merged, report.retired, report.satisfied) == (0, 0, 1)
    assert count(session, Adjudication) == 0


def test_records_off_a_current_venue_are_skipped(session: Session) -> None:
    rows = {name: poi(name=name, lat=30.3 + i / 100) for i, name in enumerate("abcd")}
    blank = poi(name="")  # rejected in Bronze, never admitted to Identity
    discover(session, [*rows.values(), blank], 0)
    adjudication = create_adjudication(
        session, actor="fixture", rationale="retired elsewhere", decided_at=NOW
    )
    retired: dict[str, int] = {}
    for name in "bcd":
        retired[name] = venue(session, rows[name].gers_id).subject_id
        record_subject_change(
            session,
            operation="retire",
            input_subject_ids=[retired[name]],
            output_subject_ids=[],
            decision=DecisionMetadata(Decimal("1"), "fixture", "1", "human", NOW, NOW),
            adjudication_id=adjudication.id,
        )
    b, c, d = (rows[name].gers_id for name in "bcd")

    report = apply(
        session,
        corrections_file(
            [merge(b, "unused"), merge(rows["a"].gers_id, c, blank.gers_id, entry_id="M2")],
            [retirement(d)],
        ),
    )
    assert report.skipped == [
        f"M1: survivor {b} is on no current venue",
        f"M2: {c} is resolved on retired Subject {retired['c']}",
        f"M2: {blank.gers_id} is not in Identity",
        f"R1: {d} is resolved on retired Subject {retired['d']}",
    ]
    assert (report.merged, report.retired, report.satisfied) == (0, 0, 0)


def test_apply_requires_repo_provenance(session: Session) -> None:
    bare = CorrectionFile(*parse_corrections({"merges": [merge("s", "a")]}), source_url=None)
    with pytest.raises(ValueError, match="provenance"):
        apply(session, bare)


def test_cli_dry_run_apply_and_show_gers(
    historical_database_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    migrate("upgrade", "head")
    factory = sessionmaker(historical_database_engine)
    with factory.begin() as session:
        here, twin = twins(session)
        loser = venue(session, twin.gers_id).subject_id
    corrections = corrections_file([merge(here.gers_id, twin.gers_id)])
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr(cli, "load_corrections", lambda _path: corrections)

    monkeypatch.setattr(sys, "argv", ["corrections", "--actor", "owner", "--dry-run"])
    cli.main()
    assert "dry run" in capsys.readouterr().out
    with factory() as session:
        assert current(session, loser)

    monkeypatch.setattr(sys, "argv", ["corrections", "--actor", "owner"])
    cli.main()
    assert "'merged': 1" in capsys.readouterr().out
    with factory() as session:
        assert not current(session, loser)

    monkeypatch.setattr(sys, "argv", ["corrections", "--show-gers", str(loser)])
    cli.main()
    shown = capsys.readouterr().out
    assert f"'subject_id': {loser}" in shown and "'current': False" in shown

    monkeypatch.setattr(sys, "argv", ["corrections"])
    with pytest.raises(SystemExit):
        cli.main()
