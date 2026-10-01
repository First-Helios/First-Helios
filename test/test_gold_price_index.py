"""Gold price index (ADR-0007 Amendment 1): placement, venue weighting, honesty, rebuild.

The index aggregates ``gold.current_menu`` only, so most tests seed Identity and
Bronze, write ``current_menu`` rows directly (a rebuildable Gold table) and run
:func:`refresh_price_index`; one test goes end to end from a persisted Menu
through the CLI. The disposable database is shared with other suites, so every
test places its venues in grid cells of its own and reads only those rows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from apps.gold.refresh import main
from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.gold.models import CurrentMenu, PriceIndex
from packages.helios_core.gold.price_index import (
    AREA_KIND,
    MIN_VENUES,
    grid_cell,
    refresh_price_index,
)
from packages.helios_core.identity import (
    admit_source_record,
    assign_source_record,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
)
from packages.helios_core.identity.contracts import ResolvedScopeRequest, current_venue_locations
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    PersistedBronzeObservation,
    persist_source_record_observation,
)
from test.menu_support import aggregate
from test.provider_support import ScopeFixture, decision, migrate

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

E = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
SINCE = datetime(2020, 1, 1, tzinfo=UTC)
_BUSINESS_EXCLUDE = {"id", "refreshed_at"}

Point = tuple[Decimal, Decimal]


def test_grid_cell_floors_to_the_south_west_corner() -> None:
    assert grid_cell(Decimal("30.267153"), Decimal("-97.743057"))[0] == "30.26,-97.75"
    assert grid_cell(Decimal("30.260000"), Decimal("-97.750000"))[0] == "30.26,-97.75"
    assert grid_cell(Decimal("22"), Decimal("-97"))[0] == "22.00,-97.00"
    assert grid_cell(Decimal("22"), Decimal("-97")) == grid_cell(
        Decimal("22.000000"), Decimal("-97.000000")
    )
    key, cell_lat, cell_lon = grid_cell(Decimal("-0.000001"), Decimal("0.009999"))
    assert (key, cell_lat, cell_lon) == ("-0.01,0.00", Decimal("-0.01"), Decimal("0.00"))


def test_cli_rejects_an_instant_without_offset() -> None:
    with pytest.raises(SystemExit):
        main(["--as-of", "2026-09-30T12:00:00"])


@pytest.fixture
def factory(disposable_database_engine: Engine) -> sessionmaker[Session]:
    migrate("upgrade", "head")
    return sessionmaker(disposable_database_engine, expire_on_commit=False)


def _cells(count: int) -> list[Point]:
    """``count`` adjacent cells no other test uses; returns a point inside each."""
    n = uuid4().int
    lat = Decimal(10) + Decimal(n % 4000) / 100
    lon = Decimal(-170) + Decimal((n // 4000) % 10000) / 100
    return [(lat, lon + Decimal(i) / 100 + Decimal("0.004321")) for i in range(count)]


def _key(point: Point) -> str:
    return grid_cell(*point)[0]


def _record(session: Session, url: str | None = None) -> PersistedBronzeObservation:
    """A Bronze record whose Evidence was read from ``url`` (default: a URL of its own)."""
    token = uuid4().hex
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=f"price-index-{token}",
            source_kind="fixture",
            external_key=token,
            observed_at=OBSERVED,
            content_hash=f"sha256:{token}",
            source_payload={"id": token},
            evidence_locator="$.id",
            source_url=url or f"https://{token}.example.test/menu",
            capture_content_hash=f"sha256:cap:{token}",
            bundle_path=f"fixture/{token}",
        ),
    )


def _organization(session: Session) -> int:
    token = uuid4().hex
    return create_organization(session, canonical_name=f"Org {token}", name_fingerprint=token).id


def _venue(
    session: Session,
    point: Point | None,
    *,
    organization_id: int | None = None,
    status: str = "open",
) -> tuple[int, int]:
    """An Establishment at ``point``; returns ``(organization id, establishment id)``."""
    place = create_place(
        session,
        address=f"{uuid4().hex} Street",
        latitude=point[0] if point else None,
        longitude=point[1] if point else None,
    )
    if organization_id is None:
        organization_id = _organization(session)
    establishment = create_establishment(
        session,
        organization_subject_id=organization_id,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status=status,
    )
    return organization_id, establishment.id


def _menu(
    session: Session,
    subject: tuple[int, str],
    record: PersistedBronzeObservation,
    amounts: list[int | None],
    *,
    target_kind: str = "item",
) -> None:
    """``current_menu`` rows for one family: a number is priced, ``None`` unknown."""
    rows: list[dict[str, Any]] = []
    for position, amount in enumerate(amounts):
        priced = amount is not None
        rows.append(
            {
                "subject_id": subject[0],
                "subject_kind": subject[1],
                "source_record_id": record.source_record_id,
                "root_key": "page",
                "target_kind": target_kind,
                "target_path": json.dumps([[target_kind, f"{target_kind}-{position}"]]),
                "channel": "unspecified",
                "currency_code": "USD",
                "effective_instant": E,
                "price_state": "priced" if priced else "unknown",
                "amount_minor": amount,
                "price_observed_at": OBSERVED + timedelta(days=position) if priced else None,
                "price_evidence_ids": [record.evidence_id] if priced else [],
                "content_evidence_ids": [],
                "organization_claim_count": 0,
                "refreshed_at": E,
            }
        )
    session.execute(insert(CurrentMenu), rows)


def _index(session: Session, points: list[Point]) -> dict[str, PriceIndex]:
    rows = session.scalars(
        select(PriceIndex).where(PriceIndex.area_key.in_([_key(p) for p in points]))
    ).all()
    return {row.area_key: row for row in rows}


def _shop(session: Session, point: Point, amounts: list[int | None]) -> int:
    """One Establishment-scoped family at ``point``; returns the Establishment id."""
    _, establishment = _venue(session, point)
    _menu(session, (establishment, "establishment"), _record(session), amounts)
    return establishment


def test_percentiles_weigh_each_venue_once(factory: sessionmaker[Session]) -> None:
    (cell,) = _cells(1)
    with factory.begin() as session:
        _shop(session, cell, [100, 200, 300])  # venue median 200
        _shop(session, cell, [400])
        _shop(session, cell, [500, 600])  # percentile_disc: the lower middle, 500
        _shop(session, cell, [1000] * 50)  # a big menu still weighs one venue
        last = _shop(session, cell, [700, None])
        record = _record(session)
        _menu(session, (last, "establishment"), record, [5], target_kind="modifier")
    with factory.begin() as session:
        report = refresh_price_index(session, effective_instant=E)
    with factory() as session:
        row = _index(session, [cell])[_key(cell)]
    assert report.rows >= 1
    assert (row.area_kind, row.category_kind, row.category_key) == (AREA_KIND, "all", "all")
    assert (row.cell_lat, row.cell_lon) == grid_cell(*cell)[1:]
    assert (row.venue_count, row.organization_venue_count) == (5, 0)
    assert (row.priced_count, row.unpriced_count) == (57, 1)  # the modifier is not indexed
    # Venue medians 200, 400, 500, 700, 1000.
    assert (row.min_minor, row.p25_minor, row.median_minor, row.p75_minor, row.max_minor) == (
        200,
        400,
        500,
        700,
        1000,
    )
    assert (row.min_venues, row.low_sample) == (MIN_VENUES, False)
    assert row.oldest_observed_at == OBSERVED
    assert row.newest_observed_at == OBSERVED + timedelta(days=49)
    assert row.effective_instant == E


def test_small_and_unpriced_groups_are_kept_and_flagged(factory: sessionmaker[Session]) -> None:
    small, unpriced = _cells(2)
    with factory.begin() as session:
        _shop(session, small, [1250])
        _shop(session, unpriced, [None, None])
    with factory.begin() as session:
        refresh_price_index(session, effective_instant=E)
    with factory() as session:
        rows = _index(session, [small, unpriced])
    one = rows[_key(small)]
    assert (one.venue_count, one.median_minor, one.low_sample) == (1, 1250, True)
    empty = rows[_key(unpriced)]
    assert (empty.venue_count, empty.priced_count, empty.unpriced_count) == (0, 0, 2)
    assert empty.low_sample is True
    assert (empty.median_minor, empty.oldest_observed_at) == (None, None)


def test_organization_prices_are_placed_only_for_one_unshared_venue(
    factory: sessionmaker[Session],
) -> None:
    single, both, chain_a, chain_b, multi_a, multi_b, closed = _cells(7)
    shared_url = f"https://{uuid4().hex}.example.test/menu"
    with factory.begin() as session:
        # A single-location Organization's own-site menu is placed at its venue.
        org, _ = _venue(session, single)
        _menu(session, (org, "organization"), _record(session), [900])
        # Its venue's own platform page and own-site page: one venue, two families.
        org, establishment = _venue(session, both)
        _menu(session, (establishment, "establishment"), _record(session), [800])
        _menu(session, (org, "organization"), _record(session), [1000])
        # Two venues' Organizations read the same menu URL: a chain menu, left out.
        for point in (chain_a, chain_b):
            org, _ = _venue(session, point)
            _menu(session, (org, "organization"), _record(session, shared_url), [1100])
        # An Organization with two current venues: never fanned out.
        org, _ = _venue(session, multi_a)
        _venue(session, multi_b, organization_id=org)
        _menu(session, (org, "organization"), _record(session), [1200])
        # A closed venue is not current.
        org, _ = _venue(session, closed, status="closed")
        _menu(session, (org, "organization"), _record(session), [1300])
    with factory.begin() as session:
        report = refresh_price_index(session, effective_instant=E)
    with factory() as session:
        rows = _index(session, [single, both, chain_a, chain_b, multi_a, multi_b, closed])
    assert set(rows) == {_key(single), _key(both)}
    placed = rows[_key(single)]
    assert (placed.venue_count, placed.organization_venue_count, placed.median_minor) == (1, 1, 900)
    merged = rows[_key(both)]
    assert (merged.venue_count, merged.organization_venue_count, merged.priced_count) == (1, 1, 2)
    assert merged.median_minor == 800  # the venue's two prices, lower middle
    assert report.shared_menu_url >= 2
    assert report.no_single_venue >= 2


def test_venue_locations_contract(factory: sessionmaker[Session]) -> None:
    point, other = _cells(2)
    with factory.begin() as session:
        org, establishment = _venue(session, point)
        multi, _ = _venue(session, point)
        _venue(session, other, organization_id=multi)
        no_point, unlocated = _venue(session, None)
        closed_org, closed = _venue(session, point, status="closed")
        found = current_venue_locations(
            session, [org, establishment, multi, no_point, unlocated, closed_org, closed], at=E
        )
        before = current_venue_locations(session, [establishment], at=SINCE - timedelta(days=1))
    assert set(found) == {org, establishment}
    assert found[org].establishment_subject_id == establishment
    assert (found[org].latitude, found[org].longitude) == (
        point[0],
        point[1].quantize(Decimal("0.000001")),
    )
    assert before == {}
    with factory() as session:
        assert current_venue_locations(session, [], at=E) == {}


def test_rebuild_is_deterministic_and_reads_only_gold(factory: sessionmaker[Session]) -> None:
    cells = _cells(2)
    with factory.begin() as session:
        for point in cells:
            _shop(session, point, [300, 450])
    with factory.begin() as session:
        refresh_price_index(session, effective_instant=E, refreshed_at=E)
        menu_before = session.scalars(select(CurrentMenu).order_by(CurrentMenu.id)).all()
        first = _business(session, cells)
    with factory.begin() as session:
        refresh_price_index(session, effective_instant=E)
        menu_after = session.scalars(select(CurrentMenu).order_by(CurrentMenu.id)).all()
        second = _business(session, cells)
    assert first == second
    assert len(first) == 2
    assert [m.id for m in menu_before] == [m.id for m in menu_after]


def _business(session: Session, points: list[Point]) -> list[dict[str, object]]:
    rows = sorted(_index(session, points).values(), key=lambda row: row.area_key)
    return [
        {
            column.key: getattr(row, column.key)
            for column in PriceIndex.__table__.columns
            if column.key not in _BUSINESS_EXCLUDE
        }
        for row in rows
    ]


def test_low_sample_must_match_the_stored_policy(factory: sessionmaker[Session]) -> None:
    (cell,) = _cells(1)
    key, cell_lat, cell_lon = grid_cell(*cell)
    with factory() as session, pytest.raises(IntegrityError, match="ck_gold_price_index_low"):
        session.execute(
            insert(PriceIndex).values(
                area_kind=AREA_KIND,
                area_key=key,
                cell_lat=cell_lat,
                cell_lon=cell_lon,
                category_kind="all",
                category_key="all",
                currency_code="USD",
                effective_instant=E,
                venue_count=1,
                organization_venue_count=0,
                priced_count=1,
                unpriced_count=0,
                min_venues=MIN_VENUES,
                low_sample=False,
                p25_minor=100,
                median_minor=100,
                p75_minor=100,
                min_minor=100,
                max_minor=100,
                oldest_observed_at=OBSERVED,
                newest_observed_at=OBSERVED,
                refreshed_at=E,
            )
        )


def _seed_located_scope(session: Session, point: Point) -> ScopeFixture:
    """The full-catalog suite's eligible open scope, with a located Place."""
    shared = _record(session)
    local = _record(session)
    place = create_place(session, address="located", latitude=point[0], longitude=point[1])
    mark_subject_eligible(session, place.id)
    org_id = _organization(session)
    admit_source_record(
        session,
        source_record_id=shared.source_record_id,
        decision=decision(),
        evidence_ids=(shared.evidence_id,),
    )
    org_event = assign_source_record(
        session,
        source_record_id=shared.source_record_id,
        to_subject_id=org_id,
        decision=decision(),
        evidence_ids=(shared.evidence_id,),
    )
    establishment = create_establishment(
        session,
        organization_subject_id=org_id,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status="open",
    )
    mark_subject_eligible(session, establishment.id)
    admit_source_record(
        session,
        source_record_id=local.source_record_id,
        decision=decision(),
        evidence_ids=(local.evidence_id,),
    )
    event = assign_source_record(
        session,
        source_record_id=local.source_record_id,
        to_subject_id=establishment.id,
        decision=decision(),
        evidence_ids=(local.evidence_id,),
    )
    return ScopeFixture(
        organization=ResolvedScopeRequest(org_id, shared.source_record_id, org_event.id),
        establishment=ResolvedScopeRequest(establishment.id, local.source_record_id, event.id),
        place_id=place.id,
        shared_input=shared,
        local_input=local,
    )


def test_cli_rebuilds_current_menu_then_the_index(
    factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    (cell,) = _cells(1)
    with factory.begin() as session:
        scope = _seed_located_scope(session, cell)
    with factory.begin() as session:
        persist_menu(session, aggregate(scope))
    main(["--as-of", E.isoformat()])
    summary = json.loads(capsys.readouterr().out.removeprefix("gold refresh complete: "))
    assert summary["current_menu_rows"] >= 1
    assert summary["price_index"]["placed"] >= 1
    with factory() as session:
        row = _index(session, [cell])[_key(cell)]
        menu_row = session.scalars(
            select(CurrentMenu).where(
                CurrentMenu.subject_id == scope.establishment.subject_id,
            )
        ).one()
    assert (row.venue_count, row.median_minor, row.low_sample) == (1, 1050, True)
    assert row.effective_instant == menu_row.effective_instant == E
    assert row.refreshed_at == menu_row.refreshed_at
