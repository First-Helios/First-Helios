"""``GET /v1/venues`` filters: ``has_menu``, ``organization``, ``area`` (ADR-0018 §A).

Identity and Gold rows are seeded in the rolled-back API test session, as in the
menu tests. Rows other tests committed may share the database, so each test
reads only the venues it created (an ``organization`` filter, or ids at or
after its own first id).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, text

from apps.api.db import get_session
from apps.api.main import app
from apps.api.pagination import encode_cursor
from packages.helios_core.gold.models import CurrentMenu
from packages.helios_core.identity import (
    create_establishment,
    create_organization,
    create_place,
)
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    PersistedBronzeObservation,
    persist_source_record_observation,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

E = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
SINCE = datetime(2020, 1, 1, tzinfo=UTC)


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


def _organization(session: Session) -> int:
    token = uuid4().hex
    return create_organization(session, canonical_name=f"Org {token}", name_fingerprint=token).id


def _venue(
    session: Session,
    organization: int,
    *,
    point: tuple[str, str] | None = ("30.2650", "-97.7450"),
    status: str = "open",
) -> int:
    place = create_place(
        session,
        address=f"{uuid4().hex} Street",
        latitude=Decimal(point[0]) if point else None,
        longitude=Decimal(point[1]) if point else None,
    )
    return create_establishment(
        session,
        organization_subject_id=organization,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status=status,
    ).id


def _record(session: Session) -> PersistedBronzeObservation:
    token = uuid4().hex
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=f"venue-filter-{token}",
            source_kind="fixture",
            external_key=token,
            observed_at=E,
            content_hash=f"sha256:{token}",
            source_payload={"id": token},
            evidence_locator="$.id",
            source_url=f"https://{token}.example.test/menu",
            capture_content_hash=f"sha256:cap:{token}",
            bundle_path=f"fixture/{token}",
        ),
    )


def _menu(session: Session, subject_id: int, kind: str, *states: str) -> None:
    """One Gold row per state for the scope ``(subject_id, kind)``."""
    record = _record(session)
    rows: list[dict[str, Any]] = [
        {
            "subject_id": subject_id,
            "subject_kind": kind,
            "source_record_id": record.source_record_id,
            "root_key": "page",
            "target_kind": "item",
            "target_path": json.dumps([["section", "s"], ["item", f"i{n}"]]),
            "channel": "unspecified",
            "currency_code": "USD",
            "effective_instant": E,
            "price_state": state,
            "amount_minor": 100 if state == "priced" else None,
            "price_evidence_ids": [record.evidence_id],
            "content_evidence_ids": [],
            "organization_claim_count": 0,
            "refreshed_at": E,
        }
        for n, state in enumerate(states)
    ]
    session.execute(insert(CurrentMenu), rows)
    session.flush()


def _ids(client: TestClient, since: int, **params: Any) -> list[int]:
    """Every listed venue id at or after ``since``, walking all pages."""
    found: list[int] = []
    cursor: str | None = encode_cursor(since - 1)
    while cursor is not None:
        response = client.get("/v1/venues", params={**params, "cursor": cursor, "limit": 200})
        assert response.status_code == 200, response.json()
        body = response.json()
        found.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
    return found


def test_has_menu_matches_what_the_menu_endpoint_serves(
    client: TestClient, session: Session
) -> None:
    own = _venue(session, _organization(session))
    _menu(session, own, "establishment", "priced")
    unknown_only = _venue(session, _organization(session))
    _menu(session, unknown_only, "establishment", "unknown")
    derived_only = _venue(session, _organization(session))
    _menu(session, derived_only, "establishment", "absent", "withdrawn", "unresolved_base")
    none = _venue(session, _organization(session))
    sole_org = _organization(session)
    sole = _venue(session, sole_org)
    _venue(session, sole_org, status="closed")  # a closed sibling is not a current venue
    _menu(session, sole_org, "organization", "priced")
    chain = _organization(session)
    chain_a, chain_b = _venue(session, chain), _venue(session, chain)
    _menu(session, chain, "organization", "priced")
    seeded = [own, unknown_only, derived_only, none, sole, chain_a, chain_b]

    with_menu = [own, unknown_only, sole]
    for venue in seeded:
        menus = client.get(f"/v1/venues/{venue}/menu").json()["menus"]
        assert bool(menus) == (venue in with_menu), venue

    since = min(seeded)
    assert [v for v in _ids(client, since, has_menu=True) if v in seeded] == with_menu
    without = [v for v in _ids(client, since, has_menu=False) if v in seeded]
    assert without == [derived_only, none, chain_a, chain_b]


def test_organization_filter_and_organization_id(client: TestClient, session: Session) -> None:
    organization, other = _organization(session), _organization(session)
    first, second = _venue(session, organization), _venue(session, organization)
    _venue(session, other)

    body = client.get("/v1/venues", params={"organization": organization}).json()
    assert [item["id"] for item in body["items"]] == [first, second]
    assert {item["organization_id"] for item in body["items"]} == {organization}
    assert client.get(f"/v1/venues/{first}").json()["organization_id"] == organization

    missing = client.get("/v1/venues", params={"organization": 999_999_999_999})
    assert missing.json() == {"items": [], "next_cursor": None}
    out_of_range = client.get("/v1/venues", params={"organization": 2**63})
    assert out_of_range.status_code == 422


def test_area_is_the_price_index_cell_half_open(client: TestClient, session: Session) -> None:
    organization = _organization(session)
    inside = [
        _venue(session, organization, point=("30.2600", "-97.7500")),  # the south-west corner
        _venue(session, organization, point=("30.269999", "-97.740001")),
    ]
    _venue(session, organization, point=("30.2700", "-97.7450"))  # the next cell north
    _venue(session, organization, point=("30.2650", "-97.7400"))  # the next cell east
    _venue(session, organization, point=("30.2599", "-97.7450"))  # the cell south
    _venue(session, organization, point=None)  # no point never matches

    params = {"organization": organization, "area": "30.26,-97.75"}
    assert [item["id"] for item in client.get("/v1/venues", params=params).json()["items"]] == (
        inside
    )


def test_filters_and_together_and_paginate(client: TestClient, session: Session) -> None:
    organization = _organization(session)
    matching = [_venue(session, organization) for _ in range(3)]
    for venue in matching:
        _menu(session, venue, "establishment", "priced")
    _venue(session, organization)  # no menu
    off_cell = _venue(session, organization, point=("30.2850", "-97.7450"))
    _menu(session, off_cell, "establishment", "priced")
    other = _venue(session, _organization(session))
    _menu(session, other, "establishment", "priced")

    params = {"has_menu": "true", "organization": organization, "area": "30.26,-97.75"}
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = {**params, "limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get("/v1/venues", params=page).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == matching


@pytest.mark.parametrize(
    "area",
    [
        "30.260,-97.75",  # not canonical: the key has exactly two decimals
        "30.265,-97.75",  # inside a cell, but not its key
        "30.26",
        "30.26,-97.75,1",
        "abc,def",
        "NaN,-97.75",
        "Infinity,-97.75",
        "91.00,0.00",
        "0.00,181.00",
        "-0.00,0.00",
        "1E+1,0.00",
        " 30.26,-97.75",
        "",
    ],
)
def test_non_canonical_area_is_422(client: TestClient, area: str) -> None:
    response = client.get("/v1/venues", params={"area": area})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body) == {"detail", "code", "trace_id"}


def test_canonical_area_matching_nothing_is_200_empty(client: TestClient) -> None:
    response = client.get("/v1/venues", params={"area": "-89.99,179.99"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


# --------------------------------------------------------------------------- #
# area_kind (ADR-0007 Amendment 3): which price-index grid area is a key of.
# --------------------------------------------------------------------------- #


def test_area_is_the_0p05_cell_half_open(client: TestClient, session: Session) -> None:
    organization = _organization(session)
    inside = [
        _venue(session, organization, point=("30.2500", "-97.7500")),  # the south-west corner
        _venue(session, organization, point=("30.2650", "-97.7350")),  # another 0.01° cell
        _venue(session, organization, point=("30.299999", "-97.700001")),
    ]
    _venue(session, organization, point=("30.3000", "-97.7250"))  # the next cell north
    _venue(session, organization, point=("30.2750", "-97.7000"))  # the next cell east
    _venue(session, organization, point=("30.2499", "-97.7250"))  # the cell south
    _venue(session, organization, point=None)

    params = {"organization": organization, "area": "30.25,-97.75"}
    coarse = client.get("/v1/venues", params={**params, "area_kind": "latlon_grid_0p05"})
    assert [item["id"] for item in coarse.json()["items"]] == inside
    # The same key under the default 0.01° kind is the one 0.01° cell at that corner.
    fine = client.get("/v1/venues", params=params).json()["items"]
    explicit = client.get("/v1/venues", params={**params, "area_kind": "latlon_grid_0p01"})
    assert [item["id"] for item in fine] == [inside[0]]
    assert explicit.json()["items"] == fine


def test_area_kind_all_lists_every_venue_with_a_point(client: TestClient, session: Session) -> None:
    organization = _organization(session)
    located = [
        _venue(session, organization, point=("30.2650", "-97.7450")),
        _venue(session, organization, point=("-45.0000", "170.0000")),
    ]
    _venue(session, organization, point=None)  # no point: not placed, not listed

    params = {"organization": organization, "area_kind": "all", "area": "all"}
    assert [item["id"] for item in client.get("/v1/venues", params=params).json()["items"]] == (
        located
    )


@pytest.mark.parametrize(
    "params",
    [
        {"area_kind": "latlon_grid_0p05", "area": "30.26,-97.75"},  # a 0.01°-only key
        {"area_kind": "latlon_grid_0p05", "area": "30.250,-97.75"},
        {"area_kind": "latlon_grid_0p05", "area": "all"},
        {"area_kind": "all", "area": "30.25,-97.75"},
        {"area_kind": "all", "area": "ALL"},
        {"area": "all"},  # all is not a 0.01° key
        {"area_kind": "all"},  # a kind alone names no area
        {"area_kind": "latlon_grid_0p05"},
        {"area_kind": "latlon_grid_0p10", "area": "30.25,-97.75"},
    ],
)
def test_area_kind_and_area_must_name_an_area(client: TestClient, params: dict[str, str]) -> None:
    response = client.get("/v1/venues", params=params)
    assert response.status_code == 422, params
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body) == {"detail", "code", "trace_id"}


# --------------------------------------------------------------------------- #
# Index use (ROADMAP Phase 7: every filter combination is index-backed).
# --------------------------------------------------------------------------- #


def _seq_scans(plan: dict[str, Any]) -> list[str]:
    found = [plan["Relation Name"]] if plan.get("Node Type") == "Seq Scan" else []
    for child in plan.get("Plans", []):
        found.extend(_seq_scans(child))
    return found


def _indexes(plan: dict[str, Any]) -> list[str]:
    found = [plan["Index Name"]] if "Index Name" in plan else []
    for child in plan.get("Plans", []):
        found.extend(_indexes(child))
    return found


_COMBINATIONS = [
    {"has_menu": "true"},
    {"has_menu": "false"},
    {"organization": "1"},
    {"area": "30.26,-97.75"},
    {"has_menu": "true", "organization": "1"},
    {"has_menu": "false", "area": "30.26,-97.75"},
    {"organization": "1", "area": "30.26,-97.75"},
    {"has_menu": "true", "organization": "1", "area": "30.26,-97.75"},
    {"area_kind": "latlon_grid_0p05", "area": "30.25,-97.75"},
    {"has_menu": "true", "area_kind": "latlon_grid_0p05", "area": "30.25,-97.75"},
    {"organization": "1", "area_kind": "latlon_grid_0p05", "area": "30.25,-97.75"},
    {"area_kind": "all", "area": "all"},
    {"has_menu": "false", "area_kind": "all", "area": "all"},
]


@pytest.mark.parametrize(
    "params", _COMBINATIONS, ids=lambda p: "&".join(f"{k}={v}" for k, v in sorted(p.items()))
)
def test_filtered_list_never_seq_scans(
    client: TestClient, session: Session, params: dict[str, str]
) -> None:
    # With sequential scans priced out, the planner still seq-scans a table no
    # index can serve.
    organization = _organization(session)
    venue = _venue(session, organization)
    _menu(session, venue, "establishment", "priced")
    _menu(session, organization, "organization", "priced")

    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "identity.establishment" in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        assert client.get("/v1/venues", params=params).status_code == 200
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
    scans = _seq_scans(plan["Plan"])
    assert "current_menu" not in scans
    assert "place" not in scans
    if "area" in params and "organization" not in params and params["area"] != "all":
        # With no other selective predicate, the cell range drives the Place read.
        # "Has a point" (area_kind=all) is not selective, so no index is pinned for it.
        assert "ix_place_latitude_longitude" in _indexes(plan["Plan"])


# --------------------------------------------------------------------------- #
# boundary (ADR-0020 owner decision 7): a drawn area, bbox then exact ray casting.
# --------------------------------------------------------------------------- #


def _corner() -> tuple[Decimal, Decimal]:
    """The south-west corner of a 0.1° square no other test uses (southern hemisphere)."""
    n = uuid4().int
    return Decimal(-60) + Decimal(n % 800) / 20, Decimal(20) + Decimal((n // 800) % 3000) / 20


def _near(corner: tuple[Decimal, Decimal], north: str, east: str) -> tuple[str, str]:
    return str(corner[0] + Decimal(north)), str(corner[1] + Decimal(east))


def _l_shape(corner: tuple[Decimal, Decimal]) -> str:
    """An L: the square's west and south strips, 0.02° wide; its north-east is out."""
    s, w = corner
    return ";".join(
        f"{s + Decimal(lat)},{w + Decimal(lon)}"
        for lat, lon in [
            ("0", "0"),
            ("0.1", "0"),
            ("0.1", "0.02"),
            ("0.02", "0.02"),
            ("0.02", "0.1"),
            ("0", "0.1"),
        ]
    )


# Points of the L test: inside (the strips, the south-west corner, the inner
# corner's west and south edges) and outside (the notch, the north and east edges).
_L_INSIDE = [("0", "0"), ("0.05", "0.01"), ("0.01", "0.05"), ("0.019999", "0.0999"), ("0.05", "0")]
_L_OUTSIDE = [
    ("0.05", "0.05"),
    ("0.1", "0.01"),
    ("0.01", "0.1"),
    ("0.02", "0.05"),
    ("0.05", "0.02"),
]


def test_boundary_lists_every_venue_inside(client: TestClient, session: Session) -> None:
    corner, organization = _corner(), _organization(session)
    inside = [_venue(session, organization, point=_near(corner, *p)) for p in _L_INSIDE]
    for point in _L_OUTSIDE:
        _venue(session, organization, point=_near(corner, *point))
    _venue(session, organization, point=None)

    params = {"organization": organization, "boundary": _l_shape(corner)}
    assert [item["id"] for item in client.get("/v1/venues", params=params).json()["items"]] == (
        inside
    )
    # ANDed with has_menu, like every filter.
    _menu(session, inside[1], "establishment", "priced")
    with_menu = client.get("/v1/venues", params={**params, "has_menu": "true"}).json()["items"]
    assert [item["id"] for item in with_menu] == [inside[1]]


@pytest.mark.parametrize("batch", [1, 2, 1000])
@pytest.mark.parametrize("limit", [1, 2, 200])
def test_boundary_pages_fill_past_candidates_outside(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    batch: int,
    limit: int,
) -> None:
    monkeypatch.setattr("apps.api.routes.venues._BOUNDARY_BATCH", batch)
    corner, organization = _corner(), _organization(session)
    inside: list[int] = []
    # Bbox candidates in id order: three outside, then an inside one, and so on.
    for n in range(4):
        for point in _L_OUTSIDE[:3]:
            _venue(session, organization, point=_near(corner, *point))
        inside.append(_venue(session, organization, point=_near(corner, *_L_INSIDE[n])))

    params = {"organization": organization, "boundary": _l_shape(corner)}
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = {**params, "limit": limit, **({"cursor": cursor} if cursor else {})}
        body = client.get("/v1/venues", params=page).json()
        assert len(body["items"]) == min(limit, len(inside) - len(seen))  # pages fill
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == inside


@pytest.mark.parametrize(
    "params",
    [
        {"boundary": "0,0;0,1;1,0", "area": "0.00,0.00"},
        {"boundary": "0,0;0,1;1,0", "area_kind": "latlon_grid_0p05"},
        {"boundary": "0,0;0,1;1,0", "area_kind": "all", "area": "all"},
        {"boundary": "0,0;0,1"},
        {"boundary": "0,0;0,3;1,0"},
        {"boundary": ""},
    ],
)
def test_bad_or_combined_boundary_is_422(client: TestClient, params: dict[str, str]) -> None:
    response = client.get("/v1/venues", params=params)
    assert response.status_code == 422, params
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body) == {"detail", "code", "trace_id"}
    if "area" in params or "area_kind" in params:
        assert body["detail"] == "boundary cannot be combined with area or area_kind"


def test_boundary_matching_nothing_is_200_empty(client: TestClient) -> None:
    corner = _corner()
    params = {"boundary": _l_shape(corner), "organization": 999_999_999_999}
    assert client.get("/v1/venues", params=params).json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "extra",
    [{}, {"has_menu": "true"}, {"has_menu": "false"}, {"organization": "1"}],
    ids=["boundary", "has_menu=true", "has_menu=false", "organization"],
)
def test_boundary_list_never_seq_scans(
    client: TestClient, session: Session, extra: dict[str, str]
) -> None:
    corner, organization = _corner(), _organization(session)
    venue = _venue(session, organization, point=_near(corner, "0.01", "0.01"))
    _menu(session, venue, "establishment", "priced")

    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "identity.establishment" in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        params = {"boundary": _l_shape(corner), **extra}
        assert client.get("/v1/venues", params=params).status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", _capture)

    candidates, page = statements  # the bbox candidates, then the page's venues by id
    connection.execute(text("SET LOCAL enable_seqscan = off"))
    try:
        plans = [
            connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {sql}", parameters).scalar_one()[0]
            for sql, parameters in (candidates, page)
        ]
    finally:
        connection.execute(text("SET LOCAL enable_seqscan = on"))
    for plan in plans:
        scans = _seq_scans(plan["Plan"])
        assert "current_menu" not in scans
        assert "place" not in scans
    if "organization" not in extra:
        assert "ix_place_latitude_longitude" in _indexes(plans[0]["Plan"])
