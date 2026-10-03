"""``GET /v1/price-index``: shape, area selection, low-sample honesty, 422s, index use.

The endpoint reads ``gold.price_index`` only (ADR-0008 §9; ADR-0007 Amendment 2).
Most tests write index rows directly in the rolled-back API test session (a
rebuildable Gold table); one goes end to end from ``current_menu`` rows through
:func:`refresh_price_index` on committed rows in the disposable ``*_test``
database. Every test uses grid cells of its own, as the price-index tests do.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, text
from sqlalchemy.orm import sessionmaker

from apps.api.db import get_session
from apps.api.main import app
from apps.api.routes.price_index import _group
from packages.helios_core.gold.models import CurrentMenu, PriceIndex
from packages.helios_core.gold.price_index import (
    AREA_KIND,
    MIN_VENUES,
    grid_cell,
    refresh_price_index,
)
from packages.helios_core.gold.price_index_read import PriceIndexRow
from packages.helios_core.identity import (
    create_establishment,
    create_organization,
    create_place,
)
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    persist_source_record_observation,
)
from test.provider_support import migrate

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

E = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
SINCE = datetime(2020, 1, 1, tzinfo=UTC)

Point = tuple[Decimal, Decimal]


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def _use_test_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _use_test_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _point() -> Point:
    """A point inside a cell no other test uses."""
    n = uuid4().int
    lat = Decimal(10) + Decimal(n % 4000) / 100 + Decimal("0.004321")
    lon = Decimal(-170) + Decimal((n // 4000) % 10000) / 100 + Decimal("0.001234")
    return lat, lon


def _params(point: Point, **extra: str) -> dict[str, str]:
    return {"lat": str(point[0]), "lon": str(point[1]), **extra}


def _index_row(point: Point, **overrides: Any) -> dict[str, Any]:
    """A ``gold.price_index`` row for ``point``'s cell: five venues, all priced."""
    area_key, cell_lat, cell_lon = grid_cell(*point)
    row: dict[str, Any] = {
        "area_kind": AREA_KIND,
        "area_key": area_key,
        "cell_lat": cell_lat,
        "cell_lon": cell_lon,
        "category_kind": "all",
        "category_key": "all",
        "currency_code": "USD",
        "effective_instant": E,
        "venue_count": 5,
        "organization_venue_count": 2,
        "priced_count": 40,
        "unpriced_count": 3,
        "min_venues": MIN_VENUES,
        "low_sample": False,
        "p25_minor": 900,
        "median_minor": 1200,
        "p75_minor": 1500,
        "min_minor": 450,
        "max_minor": 2400,
        "oldest_observed_at": OBSERVED,
        "newest_observed_at": OBSERVED + timedelta(days=10),
        "refreshed_at": E,
    }
    row.update(overrides)
    return row


def _insert(session: Session, *rows: dict[str, Any]) -> None:
    session.execute(insert(PriceIndex), list(rows))
    session.flush()


# --------------------------------------------------------------------------- #
# Shape and area selection.
# --------------------------------------------------------------------------- #


def test_cell_shape_statistics_and_freshness(client: TestClient, session: Session) -> None:
    point = _point()
    _insert(session, _index_row(point))
    area_key, cell_lat, cell_lon = grid_cell(*point)

    before = datetime.now(UTC)
    response = client.get("/v1/price-index", params=_params(point))
    after = datetime.now(UTC)

    assert response.status_code == 200
    body = response.json()
    (item,) = body.pop("items")
    assert body == {
        "area_kind": "latlon_grid_0p01",
        "area_key": area_key,
        "cell_lat": float(cell_lat),
        "cell_lon": float(cell_lon),
        "cell_size_degrees": 0.01,
        "as_of": "2026-09-30T12:00:00Z",
    }
    age = item.pop("age_seconds")
    assert (
        int((before - OBSERVED).total_seconds()) <= age <= int((after - OBSERVED).total_seconds())
    )
    assert item == {
        "category_kind": "all",
        "category_key": "all",
        "currency_code": "USD",
        "venue_count": 5,
        "organization_venue_count": 2,
        "priced_count": 40,
        "unpriced_count": 3,
        "min_venues": MIN_VENUES,
        "low_sample": False,
        "p25_minor": 900,
        "median_minor": 1200,
        "p75_minor": 1500,
        "min_minor": 450,
        "max_minor": 2400,
        "oldest_observed_at": "2026-09-01T12:00:00Z",
        "newest_observed_at": "2026-09-11T12:00:00Z",
    }


def test_a_point_selects_the_cell_it_is_in(client: TestClient, session: Session) -> None:
    point = _point()
    _insert(session, _index_row(point, median_minor=1234))
    cell_lat, cell_lon = grid_cell(*point)[1:]
    north_east = (cell_lat + Decimal("0.009999"), cell_lon + Decimal("0.009999"))

    for inside in ((cell_lat, cell_lon), north_east):  # the south-west corner is inside
        body = client.get("/v1/price-index", params=_params(inside)).json()
        assert [item["median_minor"] for item in body["items"]] == [1234]
    # One step north or east is the next cell, which has no row.
    for outside in ((cell_lat + Decimal("0.01"), cell_lon), (cell_lat, cell_lon + Decimal("0.01"))):
        body = client.get("/v1/price-index", params=_params(outside)).json()
        assert body["area_key"] != grid_cell(*point)[0]
        assert body["items"] == []


def test_low_sample_and_unpriced_groups_are_served_and_flagged(
    client: TestClient, session: Session
) -> None:
    small, unpriced = _point(), _point()
    _insert(
        session,
        _index_row(
            small,
            venue_count=2,
            organization_venue_count=0,
            priced_count=7,
            unpriced_count=0,
            low_sample=True,
        ),
        _index_row(
            unpriced,
            venue_count=0,
            organization_venue_count=0,
            priced_count=0,
            unpriced_count=4,
            low_sample=True,
            p25_minor=None,
            median_minor=None,
            p75_minor=None,
            min_minor=None,
            max_minor=None,
            oldest_observed_at=None,
            newest_observed_at=None,
        ),
    )

    (few,) = client.get("/v1/price-index", params=_params(small)).json()["items"]
    assert (few["venue_count"], few["min_venues"], few["low_sample"]) == (2, MIN_VENUES, True)
    assert few["median_minor"] == 1200  # served, but flagged

    body = client.get("/v1/price-index", params=_params(unpriced)).json()
    assert body["as_of"] == "2026-09-30T12:00:00Z"
    (none,) = body["items"]
    assert (none["venue_count"], none["unpriced_count"], none["low_sample"]) == (0, 4, True)
    stats = ("p25_minor", "median_minor", "p75_minor", "min_minor", "max_minor")
    assert [none[key] for key in stats] == [None] * len(stats)
    assert (none["oldest_observed_at"], none["newest_observed_at"], none["age_seconds"]) == (
        None,
        None,
        None,
    )


def test_cell_without_a_row_is_200_empty(client: TestClient) -> None:
    point = _point()
    response = client.get("/v1/price-index", params=_params(point))
    assert response.status_code == 200
    body = response.json()
    assert (body["area_key"], body["as_of"], body["items"]) == (grid_cell(*point)[0], None, [])


def test_filters_narrow_and_unknown_values_are_422(client: TestClient, session: Session) -> None:
    point = _point()
    _insert(session, _index_row(point))

    for filters in ({}, {"category_kind": "all"}, {"currency": "USD"}):
        body = client.get("/v1/price-index", params=_params(point, **filters)).json()
        assert len(body["items"]) == 1, filters
    for filters in ({"category_kind": "course"}, {"currency": "EUR"}, {"currency": "usd"}):
        response = client.get("/v1/price-index", params=_params(point, **filters))
        assert response.status_code == 422, filters
        assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"lat": "30.26"},
        {"lon": "-97.75"},
        {"lat": "90.000001", "lon": "-97.75"},
        {"lat": "-90.5", "lon": "-97.75"},
        {"lat": "30.26", "lon": "180.1"},
        {"lat": "30.26", "lon": "-181"},
        {"lat": "nan", "lon": "-97.75"},
        {"lat": "30.26", "lon": "inf"},
        {"lat": "north", "lon": "-97.75"},
    ],
)
def test_missing_or_out_of_range_coordinates_are_422(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get("/v1/price-index", params=params)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["trace_id"]


def test_world_edges_and_negative_zero_are_accepted(client: TestClient) -> None:
    for lat, lon, key in (
        ("90", "180", "90.00,180.00"),
        ("-90", "-180", "-90.00,-180.00"),
        ("-0.0", "-0.0", "0.00,0.00"),  # Postgres numeric has no -0, so neither does a key
        ("30.26", "-97.75", "30.26,-97.75"),  # an edge is not floored into the cell below
    ):
        response = client.get("/v1/price-index", params={"lat": lat, "lon": lon})
        assert response.status_code == 200, (lat, lon)
        assert response.json()["area_key"] == key


def test_age_is_request_time_never_negative() -> None:
    row = PriceIndexRow(
        category_kind="all",
        category_key="all",
        currency_code="USD",
        effective_instant=E,
        venue_count=1,
        organization_venue_count=0,
        priced_count=1,
        unpriced_count=0,
        min_venues=MIN_VENUES,
        low_sample=True,
        p25_minor=100,
        median_minor=100,
        p75_minor=100,
        min_minor=100,
        max_minor=100,
        oldest_observed_at=OBSERVED,
        newest_observed_at=OBSERVED,
    )
    assert _group(row, OBSERVED + timedelta(hours=1)).age_seconds == 3600
    assert _group(row, OBSERVED - timedelta(hours=1)).age_seconds == 0


# --------------------------------------------------------------------------- #
# Read-path performance.
# --------------------------------------------------------------------------- #


def _seq_scans(plan: dict[str, Any]) -> list[str]:
    found = [plan["Relation Name"]] if plan.get("Node Type") == "Seq Scan" else []
    for child in plan.get("Plans", []):
        found.extend(_seq_scans(child))
    return found


@pytest.mark.parametrize("filters", [{}, {"category_kind": "all", "currency": "USD"}])
def test_price_index_query_never_seq_scans(
    client: TestClient, session: Session, filters: dict[str, str]
) -> None:
    # ROADMAP Phase 7: the read path is index-backed (uq_gold_price_index leads
    # with area_kind, area_key). With sequential scans priced out, the planner
    # still seq-scans a table no index can serve.
    point = _point()
    _insert(session, _index_row(point), _index_row(_point()))

    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "gold.price_index" in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        assert client.get("/v1/price-index", params=_params(point, **filters)).status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", _capture)

    assert len(statements) == 1
    statement, parameters = statements[0]
    connection.execute(text("SET LOCAL enable_seqscan = off"))
    try:
        (plan,) = connection.exec_driver_sql(
            f"EXPLAIN (FORMAT JSON) {statement}", parameters
        ).scalar_one()
    finally:
        connection.execute(text("SET LOCAL enable_seqscan = on"))
    assert "price_index" not in _seq_scans(plan["Plan"])


# --------------------------------------------------------------------------- #
# End to end: current_menu -> refresh_price_index -> API (committed, disposable).
# --------------------------------------------------------------------------- #


def _shop(session: Session, point: Point, amounts: list[int]) -> None:
    """An Establishment at ``point`` with one priced item per amount in ``current_menu``."""
    token = uuid4().hex
    record = persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=f"price-index-api-{token}",
            source_kind="fixture",
            external_key=token,
            observed_at=OBSERVED,
            content_hash=f"sha256:{token}",
            source_payload={"id": token},
            evidence_locator="$.id",
            source_url=f"https://{token}.example.test/menu",
            capture_content_hash=f"sha256:cap:{token}",
            bundle_path=f"fixture/{token}",
        ),
    )
    organization = create_organization(
        session, canonical_name=f"Org {token}", name_fingerprint=token
    )
    place = create_place(session, address=f"{token} Street", latitude=point[0], longitude=point[1])
    establishment = create_establishment(
        session,
        organization_subject_id=organization.id,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status="open",
    )
    session.execute(
        insert(CurrentMenu),
        [
            {
                "subject_id": establishment.id,
                "subject_kind": "establishment",
                "source_record_id": record.source_record_id,
                "root_key": "page",
                "target_kind": "item",
                "target_path": json.dumps([["item", f"item-{position}"]]),
                "channel": "unspecified",
                "currency_code": "USD",
                "effective_instant": E,
                "price_state": "priced",
                "amount_minor": amount,
                "price_observed_at": OBSERVED + timedelta(days=position),
                "price_evidence_ids": [record.evidence_id],
                "content_evidence_ids": [],
                "organization_claim_count": 0,
                "refreshed_at": E,
            }
            for position, amount in enumerate(amounts)
        ],
    )


def test_end_to_end_from_current_menu_through_refresh(
    disposable_database_engine: Engine,
) -> None:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    point = _point()
    other_lat = point[0] + Decimal("0.003")  # same cell, a different Place
    with factory.begin() as session:
        for amounts in ([300, 500], [700], [900, 1100, 1300], [1500], [2000, 2200]):
            _shop(session, (other_lat if len(amounts) == 1 else point[0], point[1]), amounts)
    with factory.begin() as session:
        refresh_price_index(session, effective_instant=E)

    def _committed_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _committed_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/v1/price-index", params=_params(point))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert (body["area_key"], body["as_of"]) == (grid_cell(*point)[0], "2026-09-30T12:00:00Z")
    (item,) = body["items"]
    # Venue medians (percentile_disc, lower middle): 300, 700, 1100, 1500, 2000.
    assert [item[key] for key in ("min_minor", "p25_minor", "median_minor")] == [300, 700, 1100]
    assert [item[key] for key in ("p75_minor", "max_minor")] == [1500, 2000]
    assert (item["venue_count"], item["priced_count"], item["low_sample"]) == (5, 9, False)
    assert (item["oldest_observed_at"], item["newest_observed_at"]) == (
        "2026-09-01T12:00:00Z",
        "2026-09-03T12:00:00Z",
    )
