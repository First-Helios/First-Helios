"""``GET /v1/price-index/area`` and ``/area/items`` (ADR-0020 §3-4), over stored placements.

Most tests seed Identity, Bronze and ``gold.current_menu`` rows in the
rolled-back API test session and run :func:`refresh_price_index` there, so the
placements are written exactly as on a real refresh. Each draws its venues in a
0.1° square of its own in the southern hemisphere, east of Greenwich, where no
committed suite places a venue. The exactness tests (every cell drawn as a
rectangle equals its Gold row; a rectangle around every placement equals the
``all`` row) run in a database of their own, where the ``all`` row holds only
their venues.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from apps.api.db import get_session
from apps.api.item_ids import decode_item_id
from apps.api.main import app
from apps.api.pagination import decode_area_item_cursor, encode_area_item_cursor
from packages.helios_core.gold.models import CurrentMenu, PriceIndex, PriceIndexPlacement
from packages.helios_core.gold.price_index import (
    ALL_AREA,
    GRID_STEPS,
    MIN_VENUES,
    refresh_price_index,
)
from packages.helios_core.gold.price_index_read import like_pattern
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
from test.provider_support import migrate

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

E = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SINCE = datetime(2020, 1, 1, tzinfo=UTC)
D = Decimal
Point = tuple[Decimal, Decimal]


def _client(session: Session) -> Iterator[TestClient]:
    def _use_test_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _use_test_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    yield from _client(session)


# --------------------------------------------------------------------------- #
# Seeding.
# --------------------------------------------------------------------------- #


def _region() -> Point:
    """The south-west corner of a 0.1° square no other test uses (on the 0.05° grid)."""
    n = uuid4().int
    return D(-60) + D(n % 800) / 20, D(20) + D((n // 800) % 3000) / 20


def _at(corner: Point, north: str, east: str) -> Point:
    return corner[0] + D(north), corner[1] + D(east)


def _rect(south: Decimal, west: Decimal, north: Decimal, east: Decimal) -> str:
    return f"{south},{west};{north},{west};{north},{east};{south},{east}"


def _record(session: Session, url: str | None = None) -> PersistedBronzeObservation:
    token = uuid4().hex
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=f"area-{token}",
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


def _organization(session: Session, name: str | None = None) -> int:
    token = uuid4().hex
    return create_organization(
        session, canonical_name=name or f"Org {token}", name_fingerprint=token
    ).id


def _venue(
    session: Session, point: Point, *, organization: int | None = None, name: str | None = None
) -> tuple[int, int]:
    """An open Establishment at ``point``; returns ``(organization id, establishment id)``."""
    place = create_place(
        session, address=f"{uuid4().hex} Street", latitude=point[0], longitude=point[1]
    )
    organization = organization if organization is not None else _organization(session, name)
    establishment = create_establishment(
        session,
        organization_subject_id=organization,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status="open",
    )
    return organization, establishment.id


def _path(*nodes: tuple[str, str]) -> str:
    return json.dumps([list(node) for node in nodes], separators=(",", ":"))


def _menu(
    session: Session,
    subject: tuple[int, str],
    record: PersistedBronzeObservation,
    amounts: list[int | None],
    *,
    section: str = "Mains",
    names: list[str] | None = None,
) -> None:
    """One item row per amount (``None``: unknown) under one section of one family."""
    rows: list[dict[str, Any]] = []
    for position, amount in enumerate(amounts):
        name = names[position] if names else f"Item {position}"
        rows.append(
            _row(
                subject,
                record,
                _path(("section", "s"), ("item", f"i{position}")),
                amount,
                section_name=section,
                item_name=name,
                content_name=name,
                observed=OBSERVED + timedelta(days=position),
            )
        )
    session.execute(insert(CurrentMenu), rows)


def _row(
    subject: tuple[int, str],
    record: PersistedBronzeObservation,
    path: str,
    amount: int | None,
    *,
    section_name: str | None = None,
    item_name: str | None = None,
    content_name: str | None = None,
    observed: datetime = OBSERVED,
    target_kind: str | None = None,
    service_period: str | None = None,
) -> dict[str, Any]:
    priced = amount is not None
    return {
        "subject_id": subject[0],
        "subject_kind": subject[1],
        "source_record_id": record.source_record_id,
        "root_key": "page",
        "target_kind": target_kind or json.loads(path)[-1][0],
        "target_path": path,
        "channel": "unspecified",
        "service_period": service_period,
        "currency_code": "USD",
        "effective_instant": E,
        "price_state": "priced" if priced else "unknown",
        "amount_minor": amount,
        "price_source_kind": "jsonld" if priced else None,
        "price_observed_at": observed if priced else None,
        "price_evidence_ids": [record.evidence_id] if priced else [],
        "content_evidence_ids": [],
        "content_name": content_name,
        "section_name": section_name,
        "item_name": item_name,
        "organization_claim_count": 0,
        "refreshed_at": E,
    }


def _shop(session: Session, point: Point, amounts: list[int | None], **menu: Any) -> int:
    """One Establishment-scoped family at ``point``; returns the Establishment id."""
    _, establishment = _venue(session, point)
    _menu(session, (establishment, "establishment"), _record(session), amounts, **menu)
    return establishment


def _refresh(session: Session, instant: datetime = E) -> None:
    refresh_price_index(session, effective_instant=instant, refreshed_at=instant)
    session.flush()


# --------------------------------------------------------------------------- #
# Summary.
# --------------------------------------------------------------------------- #


def _area(client: TestClient, boundary: str, **params: str) -> dict[str, Any]:
    response = client.get("/v1/price-index/area", params={"boundary": boundary, **params})
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def test_summary_shape_and_venue_weighting(client: TestClient, session: Session) -> None:
    corner = _region()
    point = _at(corner, "0.012", "0.034")
    _shop(session, point, [100, 200, 300])  # venue median 200
    _shop(session, point, [400])
    _shop(session, point, [500, 600])  # percentile_disc: the lower middle, 500
    _shop(session, point, [1000] * 3)  # a bigger menu still weighs one venue
    _shop(session, point, [700, None])
    _shop(session, _at(corner, "0.090", "0.090"), [9999])  # outside the boundary
    _refresh(session)

    s, w = corner
    boundary = _rect(s, w, s + D("0.05"), w + D("0.05"))
    before = datetime.now(UTC)
    body = _area(client, boundary + f";{s},{w}")  # a closing corner is dropped
    after = datetime.now(UTC)

    assert body.pop("boundary") == [
        [float(s), float(w)],
        [float(s + D("0.05")), float(w)],
        [float(s + D("0.05")), float(w + D("0.05"))],
        [float(s), float(w + D("0.05"))],
    ]
    assert body.pop("as_of") == "2026-10-23T12:00:00Z"
    (item,) = body.pop("items")
    assert body == {}
    age = item.pop("age_seconds")
    assert (
        int((before - OBSERVED).total_seconds()) <= age <= int((after - OBSERVED).total_seconds())
    )
    assert item == {
        "category_kind": "all",
        "category_key": "all",
        "currency_code": "USD",
        "venue_count": 5,
        "organization_venue_count": 0,
        "priced_count": 10,
        "unpriced_count": 1,
        "min_venues": MIN_VENUES,
        "low_sample": False,
        "p25_minor": 400,
        "median_minor": 500,
        "p75_minor": 700,
        "min_minor": 200,
        "max_minor": 1000,
        "oldest_observed_at": "2026-10-01T12:00:00Z",
        "newest_observed_at": "2026-10-03T12:00:00Z",
    }
    # The index holds only category all and USD today, so the filters keep the item.
    filtered = _area(client, boundary, category_kind="all", currency="USD")
    assert [i["median_minor"] for i in filtered["items"]] == [500]


def test_low_sample_unpriced_and_empty_boundaries(client: TestClient, session: Session) -> None:
    corner = _region()
    _shop(session, _at(corner, "0.001", "0.001"), [1250])
    _shop(session, _at(corner, "0.001", "0.002"), [800])
    _shop(session, _at(corner, "0.051", "0.001"), [None, None])  # nothing priced
    _refresh(session)
    s, w = corner

    small = _area(client, _rect(s, w, s + D("0.01"), w + D("0.01")))["items"]
    assert [(i["venue_count"], i["low_sample"], i["median_minor"]) for i in small] == [
        (2, True, 800)
    ]
    unpriced = _area(client, _rect(s + D("0.05"), w, s + D("0.06"), w + D("0.01")))["items"]
    assert [
        (i["venue_count"], i["priced_count"], i["unpriced_count"], i["median_minor"])
        for i in unpriced
    ] == [(0, 0, 2, None)]
    assert unpriced[0]["low_sample"] is True
    assert unpriced[0]["oldest_observed_at"] is None
    assert unpriced[0]["age_seconds"] is None

    empty = _area(client, _rect(s + D("0.02"), w + D("0.02"), s + D("0.03"), w + D("0.03")))
    assert (empty["items"], empty["as_of"]) == ([], None)
    assert len(empty["boundary"]) == 4


def test_only_the_index_placements_count(client: TestClient, session: Session) -> None:
    corner = _region()
    point = _at(corner, "0.004", "0.004")
    shared_url = f"https://{uuid4().hex}.example.test/menu"
    single, _ = _venue(session, point)  # an own-site menu, placed via its Organization
    _menu(session, (single, "organization"), _record(session), [900])
    for _ in range(2):  # a chain menu two venues share: left out
        chain, _ = _venue(session, point)
        _menu(session, (chain, "organization"), _record(session, shared_url), [100])
    multi, _ = _venue(session, point)  # an Organization with two venues: left out
    _venue(session, _at(corner, "0.090", "0.090"), organization=multi)
    _menu(session, (multi, "organization"), _record(session), [100])
    _shop(session, point, [1100])
    _refresh(session)

    boundary = _rect(corner[0], corner[1], corner[0] + D("0.01"), corner[1] + D("0.01"))
    (item,) = _area(client, boundary)["items"]
    assert (item["venue_count"], item["organization_venue_count"], item["priced_count"]) == (
        2,
        1,
        2,
    )
    assert (item["min_minor"], item["max_minor"]) == (900, 1100)
    amounts = [row["amount_minor"] for row in _walk(client, boundary, 50)]
    assert amounts == [900, 1100]  # the items are the rows behind the median


# --------------------------------------------------------------------------- #
# Items.
# --------------------------------------------------------------------------- #


def _walk(client: TestClient, boundary: str, limit: int, **params: str) -> list[dict[str, Any]]:
    """Every item, following ``next_cursor`` to the end."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = {"boundary": boundary, **params, "limit": str(limit)}
        if cursor:
            page["cursor"] = cursor
        response = client.get("/v1/price-index/area/items", params=page)
        assert response.status_code == 200, response.json()
        body = response.json()
        assert len(body["items"]) <= limit
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items
        assert len(body["items"]) == limit  # only a full page has a next one


def _seed_items(session: Session, corner: Point) -> tuple[int, int, str]:
    """Two venues with ties, NULL and non-NULL contexts, and a variant; returns their ids."""
    point = _at(corner, "0.004", "0.004")
    _, burgers = _venue(session, point, name="Burger Barn")
    record = _record(session)
    subject = (burgers, "establishment")
    section = ("section", "s")
    session.execute(
        insert(CurrentMenu),
        [
            _row(
                subject,
                record,
                _path(section, ("item", "a")),
                500,
                item_name="Cheeseburger",
                content_name="Cheeseburger",
                section_name="Burgers",
            ),
            # The same item at dinner: a non-NULL service period ties on price.
            _row(
                subject,
                record,
                _path(section, ("item", "a")),
                500,
                item_name="Cheeseburger",
                content_name="Cheeseburger",
                section_name="Burgers",
                service_period="dinner",
            ),
            _row(
                subject,
                record,
                _path(section, ("item", "b")),
                300,
                item_name="Kids Mac & Cheese",
                content_name="Kids Mac & Cheese",
                section_name="Burgers",
            ),
            _row(
                subject,
                record,
                _path(section, ("item", "c"), ("variant", "l")),
                700,
                item_name="Fries",
                content_name="Large",
                section_name="Sides",
            ),
            _row(
                subject,
                record,
                _path(section, ("item", "c")),
                None,
                item_name="Fries",
                content_name="Fries",
                section_name="Sides",
            ),  # not priced: never listed
            _row(
                subject,
                record,
                _path(section, ("modifier", "m")),
                50,
                content_name="Bacon",
                section_name="Sides",
            ),  # a modifier: never listed
        ],
    )
    _, tacos = _venue(session, point, name="Taco Stand")
    record = _record(session)
    session.execute(
        insert(CurrentMenu),
        [
            _row(
                (tacos, "establishment"),
                record,
                _path(section, ("item", f"t{n}")),
                amount,
                item_name=name,
                content_name=name,
                section_name="Tacos",
            )
            for n, (amount, name) in enumerate(
                [(300, "100% Agave_Taco"), (500, "Taco\\Plate"), (250, "BURGER taco")]
            )
        ],
    )
    _refresh(session)
    s, w = corner
    return burgers, tacos, _rect(s, w, s + D("0.01"), w + D("0.01"))


@pytest.mark.parametrize("limit", [1, 2, 200])
def test_items_walk_is_cheapest_first_and_total(
    client: TestClient, session: Session, limit: int
) -> None:
    burgers, tacos, boundary = _seed_items(session, _region())
    items = _walk(client, boundary, limit)

    assert [i["amount_minor"] for i in items] == [250, 300, 300, 500, 500, 500, 700]
    # Ties break on the business key: the venue created first, then NULL context first.
    assert [(i["venue_id"], i["item_name"]) for i in items[1:3]] == [
        (burgers, "Kids Mac & Cheese"),
        (tacos, "100% Agave_Taco"),
    ]
    assert [(i["venue_id"], i["service_period"]) for i in items[3:6]] == [
        (burgers, None),
        (burgers, "dinner"),
        (tacos, None),
    ]
    (summary,) = _area(client, boundary)["items"]
    assert len(items) == summary["priced_count"]  # the rows behind the median, all of them


def test_item_fields(client: TestClient, session: Session) -> None:
    burgers, _, boundary = _seed_items(session, _region())
    by_amount = {i["amount_minor"]: i for i in _walk(client, boundary, 200)}

    large = by_amount[700]
    age = large.pop("age_seconds")
    assert age >= 0
    item_id = large.pop("item_id")
    assert large == {
        "venue_id": burgers,
        "venue_name": "Burger Barn",
        "section_name": "Sides",
        "item_name": "Fries",
        "variant_name": "Large",
        "amount_minor": 700,
        "currency_code": "USD",
        "channel": "unspecified",
        "service_period": None,
        "observed_at": "2026-10-01T12:00:00Z",
        "source_kind": "jsonld",
    }
    # The id names the node, as the menu and price-history endpoints do.
    target = decode_item_id(item_id)
    assert (target.subject_kind, target.subject_id, target.root_key, target.target_path) == (
        "establishment",
        burgers,
        "page",
        (("section", "s"), ("item", "c"), ("variant", "l")),
    )
    # An item's own price has no variant name.
    assert (by_amount[250]["item_name"], by_amount[250]["variant_name"]) == ("BURGER taco", None)


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("burger", ["BURGER taco", "Cheeseburger", "Cheeseburger"]),  # not "Burgers" sections
        ("LARGE", ["Fries"]),  # a variant's own name
        ("fries", ["Fries"]),  # its item's name
        ("100%", ["100% Agave_Taco"]),
        ("0%", ["100% Agave_Taco"]),
        ("e_t", ["100% Agave_Taco"]),
        ("o\\p", ["Taco\\Plate"]),  # an escaped backslash: unescaped, "\p" would match "p"
        ("o_p", []),  # unescaped, "_" would match the backslash in "Taco\Plate"
        ("o%e", []),  # unescaped, "%" would match "o\Plate"
        ("%%", []),  # a literal "%%", not a wildcard
        ("__", []),
        ("zzz", []),
    ],
)
def test_items_q_matches_item_and_variant_names_literally(
    client: TestClient, session: Session, q: str, expected: list[str]
) -> None:
    _, _, boundary = _seed_items(session, _region())
    items = _walk(client, boundary, 2, q=q)
    assert [i["item_name"] for i in items] == expected


def test_like_pattern_escapes_the_wildcards() -> None:
    assert like_pattern("a%b_c\\d") == "%a\\%b\\_c\\\\d%"


def test_items_cursor_is_a_business_key_that_survives_a_refresh(
    client: TestClient, session: Session
) -> None:
    burgers, tacos, boundary = _seed_items(session, _region())
    first = client.get(
        "/v1/price-index/area/items", params={"boundary": boundary, "limit": "3"}
    ).json()
    cursor = first["next_cursor"]
    assert decode_area_item_cursor(cursor)[0] == first["items"][-1]["amount_minor"]

    # A rebuild replaces every Gold row (new ids, new instant); the key still places the page.
    ours = CurrentMenu.subject_id.in_([burgers, tacos])
    rows = session.execute(select(CurrentMenu.__table__).where(ours)).mappings().all()
    session.execute(delete(CurrentMenu).where(ours))
    later = E + timedelta(days=1)
    session.execute(
        insert(CurrentMenu),
        [
            {**{k: v for k, v in row.items() if k != "id"}, "effective_instant": later}
            for row in rows
        ],
    )
    _refresh(session, later)

    rest = client.get(
        "/v1/price-index/area/items", params={"boundary": boundary, "cursor": cursor}
    ).json()
    assert rest["as_of"] == "2026-10-24T12:00:00Z"
    assert rest["next_cursor"] is None
    whole = _walk(client, boundary, 200)
    assert [i["item_id"] for i in first["items"] + rest["items"]] == [i["item_id"] for i in whole]
    assert len(whole) == 7


def test_empty_items_are_200(client: TestClient) -> None:
    corner = _region()
    body = client.get(
        "/v1/price-index/area/items",
        params={
            "boundary": _rect(corner[0], corner[1], corner[0] + D("0.1"), corner[1] + D("0.1"))
        },
    ).json()
    assert body == {"as_of": None, "items": [], "next_cursor": None}


def _token(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


_KEY = (
    500,
    1,
    "establishment",
    2,
    "page",
    '[["item","a"]]',
    "unspecified",
    None,
    None,
    None,
    "USD",
)
_VALID = encode_area_item_cursor(_KEY)


def test_area_item_cursor_round_trips() -> None:
    assert decode_area_item_cursor(_VALID) == _KEY
    timed = (*_KEY[:7], "dinner", E, E + timedelta(microseconds=5), "USD")
    assert decode_area_item_cursor(encode_area_item_cursor(timed)) == timed
    eastern = datetime(2026, 10, 23, 7, 0, tzinfo=UTC).astimezone()
    shifted = (*_KEY[:8], eastern, None, "USD")
    assert decode_area_item_cursor(encode_area_item_cursor(shifted))[8] == E - timedelta(hours=5)


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "",
        _VALID + "=",
        _VALID + "A",
        _token(b"not json"),
        _token(json.dumps(list(_KEY[:10])).encode()),
        _token(b'[500,1,"establishment",2,"page","p","unspecified",null,null,null,"USD"]  '),
        _token(b'[500, 1,"establishment",2,"page","p","unspecified",null,null,null,"USD"]'),
        _token(b'[true,1,"establishment",2,"page","p","unspecified",null,null,null,"USD"]'),
        _token(b'[500,-1,"establishment",2,"page","p","unspecified",null,null,null,"USD"]'),
        _token(b'[500,1,"establishment",2,"page","p","unspecified",null,null,null,"USDX"]'),
        _token(b'[500,1,"establishment",2,"page","p","unspecified",1,null,null,"USD"]'),
        _token(b'[500,1,"establishment",2,"\\u0000","p","unspecified",null,null,null,"USD"]'),
        _token(b'[500,1,"establishment",2,"\\ud800","p","unspecified",null,null,null,"USD"]'),
        _token(
            b'[500,1,"establishment",2,"page","p","unspecified",null,'
            b'"2026-10-23T12:00:00",null,"USD"]'  # no offset
        ),
        _token(
            b'[500,1,"establishment",2,"page","p","unspecified",null,'
            b'"2026-10-23T07:00:00-05:00",null,"USD"]'  # not in UTC
        ),
        _token(b'[500,1,"establishment",2,"page","p","unspecified",null,"yesterday",null,"USD"]'),
        _token(
            json.dumps(
                [9_223_372_036_854_775_808, 1, "establishment", 2, "page", "p", "unspecified"]
                + [None, None, None, "USD"]
            ).encode()
        ),
        _token(b"\xff\xfe"),
    ],
)
def test_malformed_area_item_cursor_is_400(client: TestClient, cursor: str) -> None:
    response = client.get(
        "/v1/price-index/area/items", params={"boundary": "0,0;0,1;1,0", "cursor": cursor}
    )
    assert response.status_code == 400, cursor
    body = response.json()
    assert body["code"] == "invalid_cursor"
    assert set(body) == {"detail", "code", "trace_id"}


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #

_BAD_BOUNDARIES = [
    ("0,0;0,1", "3-50 corners"),
    ("0,0;0,1;1,0;", "lat,lon"),
    ("1e1,0;0,1;1,0", "plain decimal"),
    ("0.1234567,0;0,1;1,0", "plain decimal"),
    ("91,0;0,1;1,0", "latitude"),
    ("0,0;0,3;1,0", "at most 2°"),
    ("0," * 601, "at most 1200 characters"),
]


@pytest.mark.parametrize("path", ["/v1/price-index/area", "/v1/price-index/area/items"])
@pytest.mark.parametrize(("boundary", "rule"), _BAD_BOUNDARIES)
def test_bad_boundary_is_422_naming_the_rule(
    client: TestClient, path: str, boundary: str, rule: str
) -> None:
    response = client.get(path, params={"boundary": boundary})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert rule.replace("\\", "") in body["detail"]
    assert set(body) == {"detail", "code", "trace_id"}


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/price-index/area", {}),
        ("/v1/price-index/area", {"boundary": "0,0;0,1;1,0", "category_kind": "course"}),
        ("/v1/price-index/area", {"boundary": "0,0;0,1;1,0", "currency": "EUR"}),
        ("/v1/price-index/area/items", {}),
        ("/v1/price-index/area/items", {"boundary": "0,0;0,1;1,0", "q": "a"}),
        ("/v1/price-index/area/items", {"boundary": "0,0;0,1;1,0", "q": "a" * 101}),
        ("/v1/price-index/area/items", {"boundary": "0,0;0,1;1,0", "limit": "0"}),
        ("/v1/price-index/area/items", {"boundary": "0,0;0,1;1,0", "limit": "201"}),
        ("/v1/price-index/area/items", {"boundary": "0,0;0,1;1,0", "currency": "EUR"}),
    ],
)
def test_missing_boundary_or_bad_filter_is_422(
    client: TestClient, path: str, params: dict[str, str]
) -> None:
    response = client.get(path, params=params)
    assert response.status_code == 422, params
    assert response.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# Read-path performance.
# --------------------------------------------------------------------------- #


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


def _plans(
    client: TestClient, session: Session, path: str, params: dict[str, str]
) -> list[list[dict[str, Any]]]:
    """The plan nodes of every statement the request runs, sequential scans priced out."""
    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "gold." in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        assert client.get(path, params=params).status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", _capture)
    connection.execute(text("SET LOCAL enable_seqscan = off"))
    try:
        return [
            _plan_nodes(
                connection.exec_driver_sql(
                    f"EXPLAIN (FORMAT JSON) {statement}", parameters
                ).scalar_one()[0]["Plan"]
            )
            for statement, parameters in statements
        ]
    finally:
        connection.execute(text("SET LOCAL enable_seqscan = on"))


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/v1/price-index/area", {}),
        ("/v1/price-index/area", {"currency": "USD"}),
        ("/v1/price-index/area/items", {}),
        ("/v1/price-index/area/items", {"q": "burger", "currency": "USD"}),
        ("/v1/price-index/area/items", {"cursor": _VALID}),
    ],
)
def test_area_reads_never_seq_scan(
    client: TestClient, session: Session, path: str, extra: dict[str, str]
) -> None:
    _, _, boundary = _seed_items(session, _region())
    plans = _plans(client, session, path, {"boundary": boundary, **extra})
    assert len(plans) == 2  # the placements in the bbox, then the menu rows
    for nodes in plans:
        assert not [n for n in nodes if n.get("Node Type") == "Seq Scan"]
    placement, menu = ({n.get("Index Name") for n in nodes} for nodes in plans)
    assert "ix_gold_price_index_placement_point" in placement
    # The menu rows are reached per placed family through one of current_menu's
    # indexes: the planner's pick (uq_gold_current_menu, the scope or the record
    # index) depends on the table's statistics.
    assert {
        name
        for name in menu
        if name and name.startswith(("uq_gold_current_menu", "ix_gold_current_menu"))
    }


# --------------------------------------------------------------------------- #
# Exactness, in a database of its own.
# --------------------------------------------------------------------------- #

# Two 0.05° cells around Austin, several 0.01° cells in each, and a cell edge shared.
_SHOPS: list[tuple[str, str, list[int | None]]] = [
    ("30.2600", "-97.7500", [100, 200, 300]),  # a 0.01° cell's south-west corner
    ("30.2650", "-97.7450", [400]),
    ("30.2699", "-97.7401", [500, 600, None]),
    ("30.2700", "-97.7450", [650]),  # the cell north of the first, same 0.05° cell
    ("30.2850", "-97.7150", [700, 800]),
    ("30.2999", "-97.7001", [900]),  # the 0.05° cell's north-east-most point
    ("30.3000", "-97.7000", [1000]),  # the next 0.05° cell, at its corner
    ("30.3550", "-97.6550", [1100, 1200]),
]


@pytest.fixture
def isolated(historical_database_engine: Engine) -> sessionmaker[Session]:
    migrate("upgrade", "head")
    return sessionmaker(historical_database_engine, expire_on_commit=False)


def test_every_cell_drawn_as_a_rectangle_equals_its_gold_row(
    isolated: sessionmaker[Session],
) -> None:
    shared_url = f"https://{uuid4().hex}.example.test/menu"
    with isolated.begin() as session:
        for lat, lon, amounts in _SHOPS:
            _shop(session, (D(lat), D(lon)), amounts)
        org, _ = _venue(session, (D("30.2655"), D("-97.7445")))  # placed via its Organization
        _menu(session, (org, "organization"), _record(session), [450])
        for lat in ("30.2610", "30.3010"):  # a chain menu: in no row
            chain, _ = _venue(session, (D(lat), D("-97.7010")))
            _menu(session, (chain, "organization"), _record(session, shared_url), [5])
    with isolated.begin() as session:
        report = refresh_price_index(session, effective_instant=E, refreshed_at=E)

    with isolated() as session:
        placements = session.scalars(select(PriceIndexPlacement)).all()
        rows = session.scalars(select(PriceIndex)).all()
        # Written beside the index, at its instant: one row per kept family.
        assert len(placements) == report.placed == len(_SHOPS) + 1
        assert sum(p.via_organization for p in placements) == report.organization_placed == 1
        assert {(p.effective_instant, p.refreshed_at) for p in placements} == {(E, E)}
        assert {(r.effective_instant, r.refreshed_at) for r in rows} == {(E, E)}

        client_iter = _client(session)
        client = next(client_iter)
        try:
            checked = 0
            for row in rows:
                if row.area_kind == ALL_AREA:
                    lats = [p.latitude for p in placements]
                    lons = [p.longitude for p in placements]
                    boundary = _rect(
                        min(lats), min(lons), max(lats) + D("0.000001"), max(lons) + D("0.000001")
                    )
                else:
                    step = GRID_STEPS[row.area_kind]
                    assert row.cell_lat is not None
                    assert row.cell_lon is not None
                    boundary = _rect(
                        row.cell_lat,
                        row.cell_lon,
                        (row.cell_lat + step),
                        (row.cell_lon + step),
                    )
                body = _area(client, boundary)
                (item,) = body["items"]
                for field in (
                    "venue_count",
                    "organization_venue_count",
                    "priced_count",
                    "unpriced_count",
                    "min_venues",
                    "low_sample",
                    "p25_minor",
                    "median_minor",
                    "p75_minor",
                    "min_minor",
                    "max_minor",
                ):
                    assert item[field] == getattr(row, field), (row.area_kind, row.area_key, field)
                for field in ("oldest_observed_at", "newest_observed_at"):
                    value = getattr(row, field)
                    assert item[field] == value.astimezone(UTC).isoformat().replace("+00:00", "Z")
                assert body["as_of"] == "2026-10-23T12:00:00Z"
                checked += 1
        finally:
            next(client_iter, None)
    kinds = {row.area_kind for row in rows}
    assert kinds == {"latlon_grid_0p01", "latlon_grid_0p05", ALL_AREA}
    assert checked == len(rows) >= 9
