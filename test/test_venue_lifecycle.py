"""ADR-0012 acceptance on migrated disposable PostgreSQL; no live acquisition."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.routes.venues import _current_venue_select
from apps.discovery.lifecycle import LifecycleReport, record_completion, run_lifecycle
from apps.discovery.models import DiscoveryLifecycleState, DiscoveryReleaseCompletion
from apps.discovery.overture import MetroBbox, OvertureConfig, _to_poi
from apps.discovery.pipeline import run_discovery
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    create_establishment,
    create_organization,
    create_place,
    record_subject_change,
    remap_source_record,
    unassign_source_record,
)
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    Organization,
    Place,
    ResolutionEvent,
    Subject,
    SubjectCurrentness,
    SubjectLineage,
)
from packages.helios_core.provenance.models import (
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)
from test.provider_support import migrate

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.engine import Engine

    from apps.discovery.overture import OverturePoi
    from apps.discovery.pipeline import DiscoveryReport


@pytest.fixture
def session(historical_database_engine: Engine) -> Iterator[Session]:
    # Lifecycle is a global sweep; isolate it from other tests' committed fixtures.
    migrate("upgrade", "head")
    with Session(historical_database_engine) as session:
        yield session


TIMES = [datetime(2026, m, 1, tzinfo=UTC) for m in range(1, 8)]
NOW = datetime.now(UTC)


def release(n: int) -> str:
    return f"s3://overturemaps-us-west-2/release/{TIMES[n]:%Y-%m-%d}.0/theme=places/type=place/*"


def poi(
    *,
    key: str | None = None,
    name: str = "Kitchen",
    lat: float = 30.3,
    lon: float = -97.7,
    address: str = "1 Main St",
) -> OverturePoi:
    return _to_poi(
        {
            "id": key or uuid4().hex,
            "name": name,
            "primary_category": "restaurant",
            "alternate_categories": [],
            "websites": ["https://kitchen.example.com/"],
            "addresses": [{"freeform": address}],
            "latitude": lat,
            "longitude": lon,
            "confidence": 0.9,
        }
    )


def ingest(session: Session, rows: list[OverturePoi], n: int) -> DiscoveryReport:
    return run_discovery(
        session, rows, decided_at=NOW + timedelta(days=n), observed_at=TIMES[n], release=release(n)
    )


def mapped(session: Session, key: str) -> Establishment:
    est = session.scalar(
        select(Establishment)
        .join(CurrentResolution, CurrentResolution.subject_id == Establishment.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source)
        .where(Source.namespace == "overture", SourceRecord.external_key == key)
    )
    assert est is not None
    return est


def complete(
    session: Session,
    n: int,
    count: int = 100,
    *,
    predecessor: int | None = None,
    bbox: MetroBbox | None = None,
) -> None:
    record_completion(
        session,
        config=OvertureConfig(release=release(n), bbox=bbox or MetroBbox.austin()),
        release_at=TIMES[n],
        poi_count=count,
        expected_predecessor=release(predecessor) if predecessor is not None else None,
    )


def sweep(session: Session, n: int) -> LifecycleReport:
    return run_lifecycle(session, release=release(n), decided_at=NOW + timedelta(days=n))


def test_feature_update_is_monotonic_and_replay_idempotent(session: Session) -> None:
    first = poi(name="Café Kitchen")
    ingest(session, [first], 0)
    original = mapped(session, first.gers_id)
    changed = poi(key=first.gers_id, name="CAFE KITCHEN!", lat=30.3001, address="1 Main Street")
    report = ingest(session, [changed], 1)
    assert report.lifecycle.updated == 1
    assert report.lifecycle.version_ids
    assert mapped(session, first.gers_id).subject_id == original.subject_id
    place = session.get(Place, original.place_subject_id)
    assert place and place.address == "1 Main Street" and place.latitude == Decimal("30.300100")
    events = session.scalar(select(func.count()).select_from(ResolutionEvent))
    for n, row in ((1, changed), (0, first)):
        retry = ingest(session, [row], n)
        assert (
            retry.lifecycle.updated == retry.lifecycle.rebranded == retry.lifecycle.relocated == 0
        )
    assert session.scalar(select(func.count()).select_from(ResolutionEvent)) == events
    assert place.latitude == Decimal("30.300100")
    org = session.get(Organization, original.organization_subject_id)
    assert org and org.canonical_name == "CAFE KITCHEN!"


@pytest.mark.parametrize(("rebrand", "relocate"), [(True, False), (False, True), (True, True)])
def test_successor_transition_and_replay(session: Session, rebrand: bool, relocate: bool) -> None:
    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    changed = poi(
        key=first.gers_id,
        name="New Business" if rebrand else first.name,
        lat=30.31 if relocate else 30.3,
        address="200 New St" if relocate else first.address or "",
    )
    report = ingest(session, [changed], 1)
    new = mapped(session, first.gers_id)
    assert new.subject_id != old.subject_id
    assert (new.organization_subject_id != old.organization_subject_id) == rebrand
    assert (new.place_subject_id != old.place_subject_id) == relocate
    assert old.operating_status == "closed" and old.valid_to == TIMES[1]
    assert new.operating_status == "unknown"
    assert session.get(SubjectCurrentness, old.place_subject_id).is_current  # type: ignore[union-attr]
    assert (report.lifecycle.rebranded, report.lifecycle.relocated) == (int(rebrand), int(relocate))
    assert ingest(session, [changed], 1).lifecycle.rebranded == 0
    ingest(session, [first], 0)
    assert mapped(session, first.gers_id).subject_id == new.subject_id
    # The closed predecessor must not freeze the shared surviving parent.
    next_poi = poi(
        key=first.gers_id,
        name=changed.name,
        lat=changed.latitude or 30.3,
        address="New display address",
    )
    assert ingest(session, [next_poi], 2).lifecycle.updated == 1


def test_same_instant_conflict_is_reported_without_choosing_by_id(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    original = mapped(session, first.gers_id)
    conflict = poi(key=first.gers_id, name="Contradiction", lat=30.4)
    report = ingest(session, [conflict], 0)
    assert report.lifecycle.lifecycle_skipped == 1
    assert "conflicting" in report.lifecycle.reasons[0]
    assert mapped(session, first.gers_id).subject_id == original.subject_id
    assert (session.scalar(select(func.count()).select_from(SourceRecordVersion)) or 0) >= 2


@pytest.mark.parametrize("shared", ["record", "organization", "place"])
def test_shared_identity_is_left_for_review(session: Session, shared: str) -> None:
    first = poi()
    ingest(session, [first], 0)
    original = mapped(session, first.gers_id)
    if shared == "record":
        ingest(session, [poi()], 0)
    else:
        org = (
            original.organization_subject_id
            if shared == "organization"
            else create_organization(session, canonical_name="Tenant", name_fingerprint="tenant").id
        )
        place = (
            original.place_subject_id
            if shared == "place"
            else create_place(session, address="Elsewhere").id
        )
        create_establishment(
            session, organization_subject_id=org, place_subject_id=place, valid_from=TIMES[0]
        )
    report = ingest(session, [poi(key=first.gers_id, name="New Owner", lat=30.4)], 1)
    assert report.lifecycle.lifecycle_skipped == 1
    assert mapped(session, first.gers_id).subject_id == original.subject_id
    assert original.operating_status == "unknown"


def test_two_completed_missing_releases_close_and_new_presence_reopens(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    est = mapped(session, first.gers_id)
    complete(session, 0)
    complete(session, 1, predecessor=0)
    assert sweep(session, 1).closed == 0
    complete(session, 2, predecessor=1)
    report = sweep(session, 2)
    assert report.closed == 1
    ((closed_id, last_seen),) = report.closed_venues
    # Compare instants: the offset in the string follows the session's timezone.
    assert closed_id == est.subject_id and datetime.fromisoformat(last_seen) == TIMES[0]
    assert est.operating_status == "closed" and est.valid_to == TIMES[1]
    assert sweep(session, 2).closed == 0
    assert ingest(session, [first], 0).lifecycle.reopened == 0
    assert ingest(session, [first], 3).lifecycle.reopened == 1
    reopened = mapped(session, first.gers_id)
    assert reopened.subject_id == est.subject_id
    assert reopened.operating_status == "unknown" and reopened.valid_to is None
    assert ingest(session, [first], 3).lifecycle.reopened == 0
    assert sweep(session, 2).closed == 0  # old horizon cannot close later presence


@pytest.mark.parametrize(
    "veto",
    [
        "partial",
        "custom95",
        "count",
        "conflict",
        "skip",
        "no_predecessor",
        "old",
        "no_baseline",
        "policy",
    ],
)
def test_absence_requires_durable_matching_consecutive_coverage(
    session: Session, veto: str
) -> None:
    first = poi()
    ingest(session, [first], 0)
    if veto != "no_baseline":
        complete(session, 0)
    complete(session, 1, predecessor=0)
    if veto == "custom95":
        bbox = replace(MetroBbox.austin(), lat_max=MetroBbox.austin().lat_max - 0.01)
        complete(session, 2, 95, predecessor=1, bbox=bbox)
    elif veto == "policy":
        record_completion(
            session,
            config=OvertureConfig(release=release(2), food_categories=("cafe",)),
            release_at=TIMES[2],
            poi_count=95,
            expected_predecessor=release(1),
        )
    elif veto != "partial":
        complete(
            session,
            2,
            89 if veto == "count" else 95,
            predecessor=0 if veto == "skip" else None if veto == "no_predecessor" else 1,
        )
    if veto == "conflict":
        complete(session, 2, 96, predecessor=1)
    if veto == "old":
        complete(session, 3, predecessor=2)
    report = sweep(session, 2)
    assert report.closed == 0 and report.reasons
    assert mapped(session, first.gers_id).operating_status == "unknown"


def test_completion_retry_and_count_conflict_are_durable(session: Session) -> None:
    complete(session, 0)
    complete(session, 0)
    assert session.scalar(select(func.count()).select_from(DiscoveryReleaseCompletion)) == 1
    complete(session, 0, 101)
    assert session.scalar(select(func.count()).select_from(DiscoveryReleaseCompletion)) == 2


def test_manual_closure_never_reopens_and_non_overture_never_closes(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    est = mapped(session, first.gers_id)
    est.operating_status, est.valid_to = "closed", TIMES[1]
    session.flush()
    assert ingest(session, [first], 2).lifecycle.reopened == 0
    assert est.operating_status == "closed"
    manual = create_establishment(
        session,
        organization_subject_id=est.organization_subject_id,
        place_subject_id=est.place_subject_id,
        valid_from=TIMES[0],
    )
    for n in range(3):
        complete(session, n, predecessor=n - 1 if n else None)
    sweep(session, 2)
    assert session.get(Establishment, manual.id).operating_status == "unknown"  # type: ignore[union-attr]


def test_any_current_source_record_proves_presence_including_rejected(session: Session) -> None:
    first, second = poi(), poi()
    ingest(session, [first, second], 0)
    assert mapped(session, first.gers_id).subject_id == mapped(session, second.gers_id).subject_id
    complete(session, 0)
    for n in (1, 2):
        ingest(session, [poi(key=second.gers_id, name="")], n)
        complete(session, n, predecessor=n - 1)
    assert sweep(session, 2).closed == 0


def parent_change(session: Session, est: Establishment, kind: str, operation: str) -> list[int]:
    parent = est.organization_subject_id if kind == "organization" else est.place_subject_id
    make: Callable[[], Subject] = (
        (
            lambda: create_organization(
                session, canonical_name="Surviving Business", name_fingerprint="surviving business"
            )
        )
        if kind == "organization"
        else (lambda: create_place(session, address="Surviving Place"))
    )
    outputs = (
        [make().id for _ in range(2 if operation == "split" else 1)]
        if operation != "retire"
        else []
    )
    inputs = [parent, *outputs] if operation == "merge" else [parent]
    evidence = session.scalar(select(Evidence.id).limit(1))
    assert evidence
    record_subject_change(
        session,
        operation=operation,
        input_subject_ids=inputs,
        output_subject_ids=outputs,
        decision=DecisionMetadata(Decimal(1), "fixture-parent-change", "1", "human", NOW, NOW),
        evidence_ids=[evidence],
    )
    return outputs


@pytest.mark.parametrize("kind", ["organization", "place"])
@pytest.mark.parametrize("operation", ["merge", "retire", "split"])
def test_parent_lifecycle_api_and_evented_rehome(
    session: Session, kind: str, operation: str
) -> None:
    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    outputs = parent_change(session, old, kind, operation)
    assert (
        session.execute(
            _current_venue_select().where(Establishment.subject_id == old.subject_id)
        ).first()
        is None
    )
    report = sweep(session, 1)
    assert not session.get(SubjectCurrentness, old.subject_id, populate_existing=True).is_current  # type: ignore[union-attr]
    if operation == "merge":
        new = mapped(session, first.gers_id)
        assert report.rehomed == 1
        assert (
            session.scalar(
                select(SubjectLineage.successor_subject_id).where(
                    SubjectLineage.predecessor_subject_id == old.subject_id
                )
            )
            == new.subject_id
        )
        assert (
            new.organization_subject_id if kind == "organization" else new.place_subject_id
        ) == outputs[0]
        assert session.execute(
            _current_venue_select().where(Establishment.subject_id == new.subject_id)
        ).first()
        assert sweep(session, 1).rehomed == 0
    else:
        assert report.retired == 1
        ingest(session, [first], 2)
        record_state = session.scalar(
            select(CurrentResolution.state)
            .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
            .where(SourceRecord.external_key == first.gers_id)
        )
        assert record_state == "needs_review"


def test_api_hides_closed_and_expired_venues(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    est = mapped(session, first.gers_id)
    query = _current_venue_select().where(Establishment.subject_id == est.subject_id)
    est.valid_to = TIMES[1]
    session.flush()
    assert session.execute(query).first() is None
    est.valid_to, est.operating_status = None, "closed"
    session.flush()
    assert session.execute(query).first() is None


def test_place_promotion_and_establishment_demotion(session: Session) -> None:
    from apps.discovery.url_pipeline import resolve_urls
    from test.test_url_pipeline import _FakeResolver

    first = poi()
    ingest(session, [first], 0)
    est = mapped(session, first.gers_id)
    sweep(session, 0)
    assert session.get(Subject, est.place_subject_id).readiness == "eligible"  # type: ignore[union-attr]
    resolve_urls(
        session, resolver=_FakeResolver(None), registry={}, decided_at=NOW, observed_at=NOW
    )
    assert session.get(Subject, est.subject_id).readiness == "eligible"  # type: ignore[union-attr]
    record = session.scalar(
        select(CurrentResolution).where(CurrentResolution.subject_id == est.organization_subject_id)
    )
    assert record
    evidence = session.scalar(select(Evidence.id).limit(1))
    assert evidence
    unassign_source_record(
        session,
        source_record_id=record.source_record_id,
        from_subject_id=est.organization_subject_id,
        decision=DecisionMetadata(Decimal(1), "fixture-unassign", "1", "human", NOW, NOW),
        evidence_ids=[evidence],
    )
    report = sweep(session, 0)
    assert report.demoted >= 1
    assert session.get(Subject, est.subject_id).readiness == "provisional"  # type: ignore[union-attr]
    assert session.scalar(select(func.count()).select_from(DiscoveryLifecycleState)) == 0


def test_http_venue_routes_hide_parent_merge_until_rehome(session: Session) -> None:
    from fastapi.testclient import TestClient

    from apps.api.db import get_session
    from apps.api.main import app

    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(app) as client:
            assert client.get(f"/v1/venues/{old.subject_id}").status_code == 200
            parent_change(session, old, "organization", "merge")
            assert client.get(f"/v1/venues/{old.subject_id}").status_code == 404
            sweep(session, 1)
            new = mapped(session, first.gers_id)
            response = client.get(f"/v1/venues/{new.subject_id}")
            assert response.status_code == 200
            assert response.json()["name"] == "Surviving Business"
            assert client.get(f"/v1/venues/{old.subject_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_address_change_without_comparable_coordinates_is_ambiguous(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    changed = poi(key=first.gers_id, address="Unknown new location")
    changed = replace(
        changed, latitude=None, longitude=None, raw=dict(changed.raw, latitude=None, longitude=None)
    )
    report = ingest(session, [changed], 1)
    assert report.lifecycle.lifecycle_skipped == 1
    est = mapped(session, first.gers_id)
    place = session.get(Place, est.place_subject_id)
    assert place and place.address == first.address


def test_new_readiness_command_handles_retirement_and_missing_subject(session: Session) -> None:
    from packages.helios_core.identity.commands import refresh_subject_readiness

    first = poi()
    ingest(session, [first], 0)
    est = mapped(session, first.gers_id)
    sweep(session, 0)
    assert refresh_subject_readiness(session, est.place_subject_id).readiness == "eligible"
    parent_change(session, est, "place", "retire")
    assert refresh_subject_readiness(session, est.place_subject_id).readiness == "provisional"
    with pytest.raises(ValueError, match="Unknown Subject"):
        refresh_subject_readiness(session, 999_999_999)


def test_failed_successor_remap_rolls_back_all_venue_changes(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import apps.discovery.lifecycle as lifecycle

    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    count = session.scalar(select(func.count()).select_from(Subject))
    real_remap = remap_source_record

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected remap refusal")

    monkeypatch.setattr(lifecycle, "remap_source_record", refuse)
    changed = poi(key=first.gers_id, name="New Owner", lat=30.4)
    with pytest.raises(RuntimeError, match="injected"):
        ingest(session, [changed], 1)
    assert session.scalar(select(func.count()).select_from(Subject)) == count
    assert mapped(session, first.gers_id).subject_id == old.subject_id
    session.refresh(old)
    assert old.operating_status == "unknown" and old.valid_to is None
    assert session.scalar(select(func.count()).select_from(DiscoveryLifecycleState)) == 0
    monkeypatch.setattr(lifecycle, "remap_source_record", real_remap)
    retry = ingest(session, [changed], 1)
    assert retry.lifecycle.rebranded == retry.lifecycle.relocated == 1
