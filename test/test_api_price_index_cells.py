"""``GET /v1/price-index/cells`` and ``area_kind`` on ``GET /v1/price-index`` (ADR-0007 Amendment 3).

Index rows are written directly in the rolled-back API test session (a
rebuildable Gold table). The cell list reads every row of a kind, so each list
test first empties ``gold.price_index`` inside that session; the rollback
restores whatever other suites committed.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, insert, text

from apps.api.db import get_session
from apps.api.main import app
from apps.api.pagination import CELL_KEY_LENGTHS, decode_cell_cursor, encode_cell_cursor
from packages.helios_core.gold.models import PriceIndex
from packages.helios_core.gold.price_index import (
    ALL_AREA,
    AREA_KIND,
    GRID_STEPS,
    MIN_VENUES,
    grid_cell,
)
from packages.helios_core.gold.price_index_read import price_index_cell

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

E = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
P05 = "latlon_grid_0p05"


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


def _row(area_kind: str, point: tuple[Decimal, Decimal] | None, **overrides: Any) -> dict[str, Any]:
    """An index row of ``area_kind`` for ``point``'s cell (``None``: the all row)."""
    if point is None:
        area_key, cell_lat, cell_lon = ALL_AREA, None, None
    else:
        area_key, cell_lat, cell_lon = grid_cell(*point, GRID_STEPS[area_kind])
    row: dict[str, Any] = {
        "area_kind": area_kind,
        "area_key": area_key,
        "cell_lat": cell_lat,
        "cell_lon": cell_lon,
        "category_kind": "all",
        "category_key": "all",
        "currency_code": "USD",
        "effective_instant": E,
        "venue_count": 5,
        "organization_venue_count": 1,
        "priced_count": 12,
        "unpriced_count": 2,
        "min_venues": MIN_VENUES,
        "low_sample": False,
        "p25_minor": 700,
        "median_minor": 1100,
        "p75_minor": 1425,
        "min_minor": 50,
        "max_minor": 46800,
        "oldest_observed_at": OBSERVED,
        "newest_observed_at": OBSERVED + timedelta(days=3),
        "refreshed_at": E,
    }
    row.update(overrides)
    return row


def _only(session: Session, *rows: dict[str, Any]) -> None:
    """Make ``rows`` the whole index, inside the rolled-back test session."""
    session.execute(delete(PriceIndex))
    if rows:
        session.execute(insert(PriceIndex), list(rows))
    session.flush()


def _point(lat: str, lon: str) -> tuple[Decimal, Decimal]:
    return Decimal(lat), Decimal(lon)


AUSTIN = _point("30.2672", "-97.7431")


def _walk(client: TestClient, limit: int, **params: str) -> list[dict[str, Any]]:
    """Every item of the list, following ``next_cursor`` to the end."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = {**params, "limit": str(limit), **({"cursor": cursor} if cursor else {})}
        response = client.get("/v1/price-index/cells", params=page)
        assert response.status_code == 200, response.json()
        body = response.json()
        assert len(body["items"]) <= limit
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items
        assert len(body["items"]) == limit  # only a full page has a next one


# --------------------------------------------------------------------------- #
# Shape per kind.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("area_kind", "point", "size"),
    [(AREA_KIND, AUSTIN, 0.01), (P05, AUSTIN, 0.05), (ALL_AREA, None, None)],
)
def test_cells_shape_for_each_kind(
    client: TestClient,
    session: Session,
    area_kind: str,
    point: tuple[Decimal, Decimal] | None,
    size: float | None,
) -> None:
    _only(session, _row(AREA_KIND, AUSTIN), _row(P05, AUSTIN), _row(ALL_AREA, None))

    before = datetime.now(UTC)
    response = client.get("/v1/price-index/cells", params={"area_kind": area_kind})
    after = datetime.now(UTC)

    assert response.status_code == 200
    body = response.json()
    (item,) = body.pop("items")
    assert body == {
        "area_kind": area_kind,
        "cell_size_degrees": size,
        "as_of": "2026-10-22T12:00:00Z",
        "next_cursor": None,
    }
    key, cell_lat, cell_lon = (
        (ALL_AREA, None, None) if point is None else grid_cell(*point, GRID_STEPS[area_kind])
    )
    age = item.pop("age_seconds")
    assert (
        int((before - OBSERVED).total_seconds()) <= age <= int((after - OBSERVED).total_seconds())
    )
    assert item == {
        "area_key": key,
        "cell_lat": None if cell_lat is None else float(cell_lat),
        "cell_lon": None if cell_lon is None else float(cell_lon),
        "category_kind": "all",
        "category_key": "all",
        "currency_code": "USD",
        "venue_count": 5,
        "organization_venue_count": 1,
        "priced_count": 12,
        "unpriced_count": 2,
        "min_venues": MIN_VENUES,
        "low_sample": False,
        "p25_minor": 700,
        "median_minor": 1100,
        "p75_minor": 1425,
        "min_minor": 50,
        "max_minor": 46800,
        "oldest_observed_at": "2026-10-01T12:00:00Z",
        "newest_observed_at": "2026-10-04T12:00:00Z",
    }


def test_area_kind_defaults_to_the_0p01_grid(client: TestClient, session: Session) -> None:
    _only(session, _row(AREA_KIND, AUSTIN), _row(P05, AUSTIN), _row(ALL_AREA, None))
    body = client.get("/v1/price-index/cells").json()
    assert (body["area_kind"], body["cell_size_degrees"]) == (AREA_KIND, 0.01)
    assert [item["area_key"] for item in body["items"]] == ["30.26,-97.75"]


def test_empty_kind_is_200_empty(client: TestClient, session: Session) -> None:
    _only(session, _row(AREA_KIND, AUSTIN))
    response = client.get("/v1/price-index/cells", params={"area_kind": P05})
    assert response.status_code == 200
    assert response.json() == {
        "area_kind": P05,
        "cell_size_degrees": 0.05,
        "as_of": None,
        "items": [],
        "next_cursor": None,
    }


# --------------------------------------------------------------------------- #
# Paging.
# --------------------------------------------------------------------------- #

# Keys whose text order differs from map order, and from byte order under a
# linguistic collation ("-" sorts apart from digits).
_POINTS = [
    _point(lat, lon)
    for lat, lon in (
        ("30.2672", "-97.7431"),
        ("30.2672", "-97.7031"),
        ("-1.0001", "10.5"),
        ("9.99", "-0.001"),
        ("10.01", "0.0"),
        ("30.0001", "-97.7431"),
        ("-45.5", "-170.25"),
    )
]


# One point per 0.05° cell: the first two points share theirs.
_P05_POINTS = list({grid_cell(*p, GRID_STEPS[P05])[0]: p for p in _POINTS}.values())


@pytest.mark.parametrize("limit", [1, 2, 200])
def test_walk_visits_every_row_once_in_key_order(
    client: TestClient, session: Session, limit: int
) -> None:
    _only(
        session,
        *(_row(AREA_KIND, point, priced_count=100 + n) for n, point in enumerate(_POINTS)),
        _row(P05, _POINTS[0]),
        _row(ALL_AREA, None),
    )
    expected = session.scalars(
        text(
            "SELECT area_key FROM gold.price_index WHERE area_kind = :k "
            "ORDER BY area_key, category_kind, category_key, currency_code"
        ),
        {"k": AREA_KIND},
    ).all()
    assert len(expected) == len(_POINTS)

    items = _walk(client, limit)
    assert [item["area_key"] for item in items] == expected
    assert sorted(item["priced_count"] for item in items) == list(range(100, 100 + len(_POINTS)))
    # Another kind's rows never appear, and its walk is separate.
    assert [item["area_key"] for item in _walk(client, limit, area_kind=P05)] == ["30.25,-97.75"]
    assert [item["area_key"] for item in _walk(client, limit, area_kind=ALL_AREA)] == [ALL_AREA]


def test_cursor_is_a_business_key_that_survives_a_refresh(
    client: TestClient, session: Session
) -> None:
    rows = [_row(AREA_KIND, point) for point in _POINTS[:3]]
    _only(session, *rows)
    first = client.get("/v1/price-index/cells", params={"limit": "1"}).json()
    cursor = first["next_cursor"]
    assert decode_cell_cursor(cursor) == (first["items"][0]["area_key"], "all", "all", "USD")

    # A rebuild replaces every row (new ids, new instant); the key still places the page.
    later = E + timedelta(days=1)
    _only(session, *({**row, "effective_instant": later} for row in rows))
    rest = client.get("/v1/price-index/cells", params={"limit": "200", "cursor": cursor}).json()
    assert first["items"][0]["area_key"] not in [item["area_key"] for item in rest["items"]]
    assert len(rest["items"]) == 2
    assert rest["as_of"] == "2026-10-23T12:00:00Z"


def test_filters_keep_the_matching_rows(client: TestClient, session: Session) -> None:
    # The index can hold only category all and USD today (ck_gold_price_index_category_kind,
    # an immutable menu.currency), so every row matches; the filters apply to the kind's
    # rows only, and the filtered query's plan is pinned below.
    _only(session, *(_row(AREA_KIND, point) for point in _POINTS[:3]), _row(P05, AUSTIN))
    for filters in ({}, {"currency": "USD"}, {"currency": "USD", "category_kind": "all"}):
        items = _walk(client, 1, **filters)
        assert len(items) == 3, filters
        assert {(item["category_kind"], item["currency_code"]) for item in items} == {
            ("all", "USD")
        }


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #


def _token(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


_VALID = encode_cell_cursor(("30.26,-97.75", "all", "all", "USD"))


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "",
        _VALID + "=",  # padded: not the canonical encoding
        _VALID + "A",
        _token(b"not json"),
        _token(b'{"area_key": "30.26,-97.75"}'),
        _token(b'["30.26,-97.75","all","all"]'),
        _token(b'["30.26,-97.75","all","all","USD","x"]'),
        _token(b'["30.26,-97.75","all","all",1]'),
        _token(b'["30.26,-97.75", "all", "all", "USD"]'),  # not compact
        _token(b'["30.26,-97.75","\\u0061ll","all","USD"]'),  # an escaped alias of "all"
        _token(b'["\\ud800","all","all","USD"]'),  # a lone surrogate
        _token(b'["30.26,-97.75\\u0000","all","all","USD"]'),  # NUL
        encode_cell_cursor(("x" * (CELL_KEY_LENGTHS[0] + 1), "all", "all", "USD")),
        encode_cell_cursor(("30.26,-97.75", "all", "all", "USDX")),
        _token(b"\xff\xfe"),  # not UTF-8
    ],
)
def test_malformed_cursor_is_400(client: TestClient, cursor: str) -> None:
    response = client.get("/v1/price-index/cells", params={"cursor": cursor})
    assert response.status_code == 400, cursor
    body = response.json()
    assert body["code"] == "invalid_cursor"
    assert set(body) == {"detail", "code", "trace_id"}


def test_cursor_round_trips_at_the_column_bounds() -> None:
    key = ("é" * CELL_KEY_LENGTHS[0], "k" * 32, "ü" * 128, "USD")
    assert decode_cell_cursor(encode_cell_cursor(key)) == key
    assert (
        tuple(
            PriceIndex.__table__.c[name].type.length  # type: ignore[attr-defined]
            for name in ("area_key", "category_kind", "category_key", "currency_code")
        )
        == CELL_KEY_LENGTHS
    )


@pytest.mark.parametrize(
    "params",
    [
        {"area_kind": "latlon_grid_0p10"},
        {"area_kind": "ALL"},
        {"limit": "0"},
        {"limit": "201"},
        {"category_kind": "course"},
        {"currency": "EUR"},
    ],
)
def test_unknown_kind_filter_or_limit_is_422(client: TestClient, params: dict[str, str]) -> None:
    response = client.get("/v1/price-index/cells", params=params)
    assert response.status_code == 422, params
    assert response.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# area_kind on GET /v1/price-index.
# --------------------------------------------------------------------------- #


def test_price_index_cell_floors_at_the_kind_step(session: Session) -> None:
    _only(session, _row(AREA_KIND, AUSTIN, priced_count=6), _row(P05, AUSTIN, priced_count=9))
    fine = price_index_cell(session, *AUSTIN)
    coarse = price_index_cell(session, *AUSTIN, area_kind=P05)
    assert (fine.area_kind, fine.area_key, [r.priced_count for r in fine.rows]) == (
        AREA_KIND,
        "30.26,-97.75",
        [6],
    )
    assert (coarse.area_kind, coarse.area_key, [r.priced_count for r in coarse.rows]) == (
        P05,
        "30.25,-97.75",
        [9],
    )
    assert (coarse.cell_lat, coarse.cell_lon) == (Decimal("30.25"), Decimal("-97.75"))


def test_point_endpoint_floors_at_0p05(client: TestClient, session: Session) -> None:
    _only(session, _row(AREA_KIND, AUSTIN, priced_count=6), _row(P05, AUSTIN, priced_count=9))
    # 30.2999, -97.7001 is in the same 0.05° cell but another 0.01° cell.
    params = {"lat": "30.2999", "lon": "-97.7001", "area_kind": P05}
    body = client.get("/v1/price-index", params=params).json()
    assert {k: body[k] for k in ("area_kind", "area_key", "cell_lat", "cell_lon")} == {
        "area_kind": P05,
        "area_key": "30.25,-97.75",
        "cell_lat": 30.25,
        "cell_lon": -97.75,
    }
    assert body["cell_size_degrees"] == 0.05
    assert [item["priced_count"] for item in body["items"]] == [9]
    default = client.get("/v1/price-index", params={"lat": "30.2999", "lon": "-97.7001"}).json()
    assert (default["area_kind"], default["area_key"], default["items"]) == (
        AREA_KIND,
        "30.29,-97.71",
        [],
    )


def test_point_endpoint_rejects_all(client: TestClient) -> None:
    response = client.get(
        "/v1/price-index", params={"lat": "30.26", "lon": "-97.75", "area_kind": "all"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# Read-path performance.
# --------------------------------------------------------------------------- #


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


@pytest.mark.parametrize("area_kind", [AREA_KIND, P05, ALL_AREA])
@pytest.mark.parametrize("filtered", [False, True], ids=["unfiltered", "filtered"])
@pytest.mark.parametrize("paged", [False, True], ids=["first", "cursor"])
def test_cells_query_uses_the_unique_index(
    client: TestClient, session: Session, area_kind: str, filtered: bool, paged: bool
) -> None:
    _only(
        session,
        *(_row(AREA_KIND, point) for point in _POINTS),
        *(_row(P05, point) for point in _P05_POINTS),
        _row(ALL_AREA, None),
    )
    params = {"area_kind": area_kind}
    if filtered:
        params |= {"category_kind": "all", "currency": "USD"}
    if paged:
        params["cursor"] = encode_cell_cursor(("0", "all", "all", "USD"))

    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "gold.price_index" in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        assert client.get("/v1/price-index/cells", params=params).status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", _capture)

    (statement, parameters) = statements[-1]
    connection.execute(text("SET LOCAL enable_seqscan = off"))
    try:
        (plan,) = connection.exec_driver_sql(
            f"EXPLAIN (FORMAT JSON) {statement}", parameters
        ).scalar_one()
    finally:
        connection.execute(text("SET LOCAL enable_seqscan = on"))
    nodes = _plan_nodes(plan["Plan"])
    assert not [n for n in nodes if n.get("Node Type") == "Seq Scan"]
    assert "uq_gold_price_index" in [n.get("Index Name") for n in nodes]
    if paged:
        # The keyset bound is a range condition on the index, not a filter after it.
        (scan,) = [n for n in nodes if n.get("Index Name") == "uq_gold_price_index"]
        assert "area_key" in scan.get("Index Cond", "")
