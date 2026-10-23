"""``GET /v1/venues/{venue_id}/menu``: shape, staleness, scope rules, 404s, index use.

The endpoint reads ``gold.current_menu`` only (ADR-0008 §9). Most tests seed
Identity and Bronze in the rolled-back API test session and write
``current_menu`` rows directly (a rebuildable Gold table, as the price-index tests
do); one test goes end to end from a persisted Menu through the bounded Gold
refresh on committed rows in the disposable ``*_test`` database.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, text
from sqlalchemy.orm import sessionmaker

from apps.api.db import get_session
from apps.api.item_ids import decode_item_id
from apps.api.main import app
from apps.api.routes.venues import _shape_menu
from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.selection import ContextRef, SelectionRequest, TargetRef
from packages.helios_core.gold import menu_read, refresh_current_menu
from packages.helios_core.gold.menu_read import CurrentMenuRow, menu_source_urls
from packages.helios_core.gold.models import CurrentMenu
from packages.helios_core.identity import (
    admit_source_record,
    assign_source_record,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
)
from packages.helios_core.identity.contracts import ResolvedScopeRequest
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    CaptureReference,
    PersistedBronzeObservation,
    persist_source_record_observation,
    source_endpoint_for_evidence,
)
from test.menu_support import aggregate
from test.provider_support import ScopeFixture, decision, migrate

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

E = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
LATER = E + timedelta(hours=6)
OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
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


def _record(session: Session) -> PersistedBronzeObservation:
    token = uuid4().hex
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=f"venue-menu-{token}",
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


def _organization(session: Session) -> int:
    token = uuid4().hex
    return create_organization(session, canonical_name=f"Org {token}", name_fingerprint=token).id


def _venue(
    session: Session, *, organization_id: int | None = None, status: str = "open"
) -> tuple[int, int]:
    """A current Establishment; returns ``(organization id, establishment id)``."""
    if organization_id is None:
        organization_id = _organization(session)
    place = create_place(session, address=f"{uuid4().hex} Street")
    establishment = create_establishment(
        session,
        organization_subject_id=organization_id,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status=status,
    )
    return organization_id, establishment.id


def _path(*nodes: tuple[str, str]) -> str:
    return json.dumps([list(node) for node in nodes], separators=(",", ":"))


def _row(
    subject: tuple[int, str],
    record: PersistedBronzeObservation,
    target_kind: str,
    path: str,
    *,
    amount: int | None = None,
    state: str = "priced",
    name: str | None = None,
    section_name: str | None = None,
    item_name: str | None = None,
    channel: str = "unspecified",
    effective_instant: datetime = E,
    observed_at: datetime | None = OBSERVED,
    source_kind: str | None = "llm",
    confidence: Decimal | None = Decimal("0.9000"),
    evidence_ids: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "subject_id": subject[0],
        "subject_kind": subject[1],
        "source_record_id": record.source_record_id,
        "root_key": "page",
        "target_kind": target_kind,
        "target_path": path,
        "channel": channel,
        "currency_code": "USD",
        "effective_instant": effective_instant,
        "price_state": state,
        "amount_minor": amount,
        "price_source_kind": source_kind,
        "price_observed_at": observed_at,
        "price_confidence": confidence,
        "price_evidence_ids": [record.evidence_id] if evidence_ids is None else evidence_ids,
        "content_name": name,
        "content_evidence_ids": [],
        "section_name": section_name,
        "item_name": item_name,
        "organization_claim_count": 0,
        "refreshed_at": effective_instant,
    }


def _insert(session: Session, rows: list[dict[str, Any]]) -> None:
    session.execute(insert(CurrentMenu), rows)
    session.flush()


TACOS = ("section", "12:tacos")
PASTOR = ("item", "14:al pastor")
LARGE = ("variant", "large")


def _seed_tacos(session: Session, subject: tuple[int, str]) -> None:
    """A section with a named item, a size-only item and an add-on.

    No row is the section's own, and the size-only item has no row of its own:
    their names arrive only as ``section_name`` / ``item_name`` on other rows.
    """
    record = _record(session)
    _insert(
        session,
        [
            _row(
                subject,
                record,
                "item",
                _path(TACOS, ("item", "13:bean")),
                amount=350,
                name="Bean",
                item_name="Bean",
                section_name="Tacos",
            ),
            _row(
                subject,
                record,
                "variant",
                _path(TACOS, PASTOR, LARGE),
                amount=1200,
                name="Large",
                item_name="Al Pastor",
                section_name="Tacos",
            ),
            _row(
                subject,
                record,
                "modifier",
                _path(TACOS, ("item", "13:bean"), ("modifier", "cheese")),
                amount=100,
                name="Cheese",
                item_name="Bean",
                section_name="Tacos",
            ),
            _row(
                subject,
                record,
                "item",
                _path(TACOS, ("item", "15:market fish")),
                state="unknown",
                section_name="Tacos",
            ),
            # Derived no-value state: never served.
            _row(subject, record, "item", _path(TACOS, ("item", "16:gone")), state="absent"),
        ],
    )


# --------------------------------------------------------------------------- #
# Shape (no database).
# --------------------------------------------------------------------------- #


def _plain(
    target_kind: str,
    *path: tuple[str, str],
    name: str | None = None,
    section_name: str | None = None,
    item_name: str | None = None,
    channel: str = "unspecified",
    observed_at: datetime | None = OBSERVED,
) -> CurrentMenuRow:
    return CurrentMenuRow(
        subject_id=1,
        subject_kind="establishment",
        source_record_id=1,
        root_key="page",
        target_kind=target_kind,
        target_path=path,
        channel=channel,
        service_period=None,
        valid_from=None,
        valid_to=None,
        currency_code="USD",
        effective_instant=E,
        price_state="priced",
        amount_minor=100,
        price_source_kind="jsonld",
        price_observed_at=observed_at,
        price_confidence=None,
        price_page_id=None,
        price_evidence_ids=(),
        content_name=name,
        content_description=None,
        section_name=section_name,
        item_name=item_name,
    )


def test_shape_nests_by_native_path() -> None:
    rows = [
        _plain("section", TACOS, name="Tacos"),
        _plain("item", TACOS, PASTOR, name="Al Pastor"),
        _plain("item", TACOS, PASTOR, name="Al Pastor", channel="takeaway"),
        _plain("variant", TACOS, PASTOR, LARGE, name="Large"),
        _plain("modifier", TACOS, PASTOR, ("modifier", "salsa"), name="Salsa"),
        _plain("modifier", TACOS, ("modifier", "chips"), name="Chips"),
        # Same item key under another section stays a separate item.
        _plain("item", ("section", "20:drinks"), PASTOR, name="Pastor Soda"),
    ]
    sections = _shape_menu(rows, LATER)
    assert [(s.key, s.name) for s in sections] == [("12:tacos", "Tacos"), ("20:drinks", None)]
    tacos = sections[0]
    assert len(tacos.prices) == 1
    assert [m.key for m in tacos.modifiers] == ["chips"]
    (pastor,) = tacos.items
    assert (pastor.key, pastor.name) == ("14:al pastor", "Al Pastor")
    assert [p.channel for p in pastor.prices] == ["unspecified", "takeaway"]
    assert [(v.key, v.name) for v in pastor.variants] == [("large", "Large")]
    assert [(m.key, m.name) for m in pastor.modifiers] == [("salsa", "Salsa")]
    assert sections[1].items[0].name == "Pastor Soda"


def test_shape_names_nodes_without_rows_of_their_own() -> None:
    # ADR-0006 Amendment 1: every row carries its path's section and item names.
    rows = [
        _plain(
            "variant",
            TACOS,
            PASTOR,
            LARGE,
            name="Large",
            section_name="Tacos",
            item_name="Al Pastor",
        ),
        _plain("modifier", TACOS, ("modifier", "chips"), name="Chips", section_name="Tacos"),
        # Rows refreshed before the columns existed: the own row still names its node.
        _plain("item", ("section", "20:drinks"), ("item", "21:soda"), name="Soda"),
    ]
    tacos, drinks = _shape_menu(rows, LATER)
    assert (tacos.name, tacos.id, tacos.prices) == ("Tacos", None, [])
    (pastor,) = tacos.items
    assert (pastor.name, pastor.id, pastor.prices) == ("Al Pastor", None, [])
    assert [v.name for v in pastor.variants] == ["Large"]
    assert [m.name for m in tacos.modifiers] == ["Chips"]
    assert (drinks.name, drinks.items[0].name) == (None, "Soda")


def test_shape_keeps_base_prefixed_and_nested_sections_apart() -> None:
    base = ("base", "77")
    rows = [
        _plain("item", base, TACOS, PASTOR, name="Inherited"),
        _plain("item", TACOS, PASTOR, name="Local"),
        _plain("item", TACOS, ("section", "sub"), ("item", "x"), name="Nested"),
    ]
    sections = _shape_menu(rows, LATER)
    assert [(s.key, s.items[0].name) for s in sections] == [
        ("12:tacos", "Inherited"),
        ("12:tacos", "Local"),
        ("sub", "Nested"),
    ]


def test_shape_age_is_request_time_never_negative() -> None:
    rows = [
        _plain("item", TACOS, ("item", "a"), observed_at=OBSERVED),
        _plain("item", TACOS, ("item", "b"), observed_at=LATER + timedelta(days=1)),
        _plain("item", TACOS, ("item", "c"), observed_at=None),
    ]
    items = _shape_menu(rows, LATER)[0].items
    ages = [item.prices[0].age_seconds for item in items]
    assert ages == [int((LATER - OBSERVED).total_seconds()), 0, None]


# --------------------------------------------------------------------------- #
# Endpoint (database).
# --------------------------------------------------------------------------- #


def test_menu_shape_staleness_and_source(client: TestClient, session: Session) -> None:
    _, venue = _venue(session)
    _seed_tacos(session, (venue, "establishment"))

    before = datetime.now(UTC)
    response = client.get(f"/v1/venues/{venue}/menu")
    after = datetime.now(UTC)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"venue_id", "as_of", "menus"}
    assert body["venue_id"] == venue
    assert body["as_of"] == "2026-09-30T12:00:00Z"
    (menu,) = body["menus"]
    assert set(menu) == {"scope", "source_url", "sections"}
    assert menu["scope"] == "establishment"
    assert menu["source_url"].endswith(".example.test/menu")
    (section,) = menu["sections"]
    # Named from the rows under it: the section has no row of its own.
    assert (section["key"], section["name"]) == ("12:tacos", "Tacos")
    assert [item["key"] for item in section["items"]] == [
        "13:bean",
        "14:al pastor",
        "15:market fish",
    ]
    bean, pastor, fish = section["items"]

    assert (bean["name"], bean["description"]) == ("Bean", None)
    (price,) = bean["prices"]
    assert set(price) == {
        "state",
        "amount_minor",
        "currency_code",
        "channel",
        "service_period",
        "valid_from",
        "valid_to",
        "observed_at",
        "age_seconds",
        "source_kind",
        "confidence",
    }
    assert (price["state"], price["amount_minor"], price["currency_code"]) == ("priced", 350, "USD")
    assert price["observed_at"] == "2026-09-01T12:00:00Z"
    assert (price["source_kind"], price["confidence"]) == ("llm", 0.9)
    lowest = int((before - OBSERVED).total_seconds())
    assert lowest <= price["age_seconds"] <= int((after - OBSERVED).total_seconds()) + 1
    assert [(m["key"], m["name"]) for m in bean["modifiers"]] == [("cheese", "Cheese")]

    # Every priced node links to its history; an unpriced node has no id.
    assert section["id"] is None
    bean_id = decode_item_id(bean["id"])
    assert (bean_id.subject_kind, bean_id.subject_id, bean_id.root_key) == (
        "establishment",
        venue,
        "page",
    )
    assert bean_id.target_path == (TACOS, ("item", "13:bean"))
    assert decode_item_id(bean["modifiers"][0]["id"]).target_kind == "modifier"
    assert decode_item_id(pastor["variants"][0]["id"]).target_path == (TACOS, PASTOR, LARGE)

    # Only the variant is priced: the item is named from the variant's row.
    assert (pastor["name"], pastor["prices"], pastor["id"]) == ("Al Pastor", [], None)
    assert [(v["key"], v["name"], v["prices"][0]["amount_minor"]) for v in pastor["variants"]] == [
        ("large", "Large", 1200)
    ]
    assert fish["prices"][0]["state"] == "unknown"
    assert fish["prices"][0]["amount_minor"] is None


def test_as_of_is_the_oldest_refresh_instant(client: TestClient, session: Session) -> None:
    _, venue = _venue(session)
    record = _record(session)
    subject = (venue, "establishment")
    _insert(
        session,
        [
            _row(subject, record, "item", _path(TACOS, ("item", "a")), amount=1),
            _row(
                subject,
                record,
                "item",
                _path(TACOS, ("item", "b")),
                amount=2,
                effective_instant=E - timedelta(days=2),
            ),
        ],
    )
    body = client.get(f"/v1/venues/{venue}/menu").json()
    assert body["as_of"] == "2026-09-28T12:00:00Z"


def test_sole_venue_organization_menu_is_labelled_and_follows_local(
    client: TestClient, session: Session
) -> None:
    organization, venue = _venue(session)
    _seed_tacos(session, (organization, "organization"))
    _seed_tacos(session, (venue, "establishment"))
    # Another Organization's rows never leak in.
    other, _ = _venue(session)
    _seed_tacos(session, (other, "organization"))

    body = client.get(f"/v1/venues/{venue}/menu").json()
    assert [menu["scope"] for menu in body["menus"]] == ["establishment", "organization"]
    # Each family carries its own page: the Organization's record is not the venue's.
    local_url, organization_url = (menu["source_url"] for menu in body["menus"])
    assert local_url is not None and organization_url is not None
    assert local_url != organization_url


def test_chain_organization_menu_is_not_fanned_out(client: TestClient, session: Session) -> None:
    organization, first = _venue(session)
    _, second = _venue(session, organization_id=organization)
    _seed_tacos(session, (organization, "organization"))

    for venue in (first, second):
        body = client.get(f"/v1/venues/{venue}/menu").json()
        assert body == {"venue_id": venue, "as_of": None, "menus": []}


def test_closed_sibling_does_not_block_the_organization_menu(
    client: TestClient, session: Session
) -> None:
    organization, venue = _venue(session)
    _venue(session, organization_id=organization, status="closed")
    _seed_tacos(session, (organization, "organization"))

    body = client.get(f"/v1/venues/{venue}/menu").json()
    assert [menu["scope"] for menu in body["menus"]] == ["organization"]


def test_current_venue_without_menu_is_200_empty(client: TestClient, session: Session) -> None:
    _, venue = _venue(session)
    response = client.get(f"/v1/venues/{venue}/menu")
    assert response.status_code == 200
    assert response.json() == {"venue_id": venue, "as_of": None, "menus": []}


def test_missing_or_closed_venue_is_404(client: TestClient, session: Session) -> None:
    _, closed = _venue(session, status="closed")
    _seed_tacos(session, (closed, "establishment"))
    for venue in (closed, 999_999_999_999):
        response = client.get(f"/v1/venues/{venue}/menu")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "not_found"
        assert set(body) == {"detail", "code", "trace_id"}


def test_out_of_range_venue_id_is_422(client: TestClient) -> None:
    response = client.get(f"/v1/venues/{2**63}/menu")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def _seq_scans(plan: dict[str, Any]) -> list[str]:
    found = [plan["Relation Name"]] if plan.get("Node Type") == "Seq Scan" else []
    for child in plan.get("Plans", []):
        found.extend(_seq_scans(child))
    return found


def test_menu_query_never_seq_scans_current_menu(client: TestClient, session: Session) -> None:
    # ROADMAP Phase 7: the read path is index-backed. With sequential scans
    # priced out, the planner still seq-scans a table no index can serve.
    organization, venue = _venue(session)
    _seed_tacos(session, (organization, "organization"))
    _seed_tacos(session, (venue, "establishment"))

    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "gold.current_menu" in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        assert client.get(f"/v1/venues/{venue}/menu").status_code == 200
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
    assert "current_menu" not in _seq_scans(plan["Plan"])


# --------------------------------------------------------------------------- #
# source_url (ADR-0008 Amendment 4).
# --------------------------------------------------------------------------- #


def _reobserve(
    session: Session,
    record: PersistedBronzeObservation,
    url: str,
    observed_at: datetime,
    fetched_at: datetime | None = None,
) -> int:
    """A later page of ``record``'s stream, fetched from ``url``; returns its Evidence id."""
    namespace, external_key = session.execute(
        text(
            "SELECT s.namespace, r.external_key FROM bronze.source_record r "
            "JOIN bronze.source s ON s.id = r.source_id WHERE r.id = :id"
        ),
        {"id": record.source_record_id},
    ).one()
    token = uuid4().hex
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=namespace,
            source_kind="fixture",
            external_key=external_key,
            observed_at=observed_at,
            content_hash=f"sha256:{token}",
            source_payload={"id": token},
            evidence_locator="$.id",
            source_url=url,
            fetched_at=fetched_at,
            capture_content_hash=f"sha256:cap:{token}",
            bundle_path=f"fixture/{token}",
        ),
    ).evidence_id


def _menu_source_url(client: TestClient, venue: int) -> str | None:
    (menu,) = client.get(f"/v1/venues/{venue}/menu").json()["menus"]
    return cast("str | None", menu["source_url"])


def test_source_url_is_the_most_recent_page_of_a_multi_page_family(
    client: TestClient, session: Session
) -> None:
    _, venue = _venue(session)
    subject = (venue, "establishment")
    record = _record(session)
    newest_at, middle_at = OBSERVED + timedelta(days=3), OBSERVED + timedelta(days=1)
    newest = _reobserve(session, record, "https://new.example.test/menu", newest_at)
    middle = _reobserve(session, record, "https://middle.example.test/menu", middle_at)
    _insert(
        session,
        [
            _row(subject, record, "item", _path(TACOS, ("item", "a")), amount=1),
            _row(
                subject,
                record,
                "item",
                _path(TACOS, ("item", "b")),
                amount=2,
                observed_at=newest_at,
                evidence_ids=[newest],
            ),
            _row(
                subject,
                record,
                "item",
                _path(TACOS, ("item", "c")),
                amount=3,
                observed_at=middle_at,
                evidence_ids=[middle],
            ),
        ],
    )
    assert _menu_source_url(client, venue) == "https://new.example.test/menu"


def test_source_url_ties_break_on_fetch_time_then_evidence_id(
    client: TestClient, session: Session
) -> None:
    _, by_fetch = _venue(session)
    _, by_id = _venue(session)
    record = _record(session)
    # Every price has one instant. The latest fetch has the smallest Evidence id.
    late = _reobserve(session, record, "https://late.example.test/menu", LATER, fetched_at=LATER)
    first = _reobserve(session, record, "https://first.example.test/menu", LATER, fetched_at=E)
    second = _reobserve(session, record, "https://second.example.test/menu", LATER, fetched_at=E)
    assert late < first < second
    _insert(
        session,
        [
            _row(
                (venue, "establishment"),
                record,
                "item",
                _path(TACOS, ("item", key)),
                amount=1,
                observed_at=LATER,
                evidence_ids=ids,
            )
            for venue, families in (
                (by_fetch, [[first], [late, second]]),
                (by_id, [[second], [first]]),
            )
            for key, ids in zip("ab", families, strict=True)
        ],
    )
    assert _menu_source_url(client, by_fetch) == "https://late.example.test/menu"
    assert _menu_source_url(client, by_id) == "https://second.example.test/menu"


def test_source_url_skips_unresolved_evidence_and_is_null_when_none_resolves(
    client: TestClient, session: Session
) -> None:
    _, venue = _venue(session)
    _, bare = _venue(session)
    record = _record(session)
    unknown = 2**62  # an Evidence id no row has: it reaches no Capture
    local, other = (venue, "establishment"), (bare, "establishment")
    _insert(
        session,
        [
            # The newest price cites only unresolvable Evidence: the next one wins.
            _row(
                local,
                record,
                "item",
                _path(TACOS, ("item", "a")),
                amount=1,
                observed_at=LATER,
                evidence_ids=[unknown],
            ),
            _row(local, record, "item", _path(TACOS, ("item", "b")), amount=2),
            # No price Evidence at all, or none that resolves: null.
            _row(other, record, "item", _path(TACOS, ("item", "a")), amount=1, evidence_ids=[]),
            _row(
                other, record, "item", _path(TACOS, ("item", "b")), amount=2, evidence_ids=[unknown]
            ),
        ],
    )
    url = source_endpoint_for_evidence(session, record.evidence_id).source_url
    assert _menu_source_url(client, venue) == url
    assert _menu_source_url(client, bare) is None


def test_source_url_resolves_in_one_query_however_many_prices(
    client: TestClient, session: Session
) -> None:
    organization, venue = _venue(session)
    statements: list[str] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    def _statements() -> list[str]:
        statements.clear()
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", _capture)
        try:
            assert client.get(f"/v1/venues/{venue}/menu").status_code == 200
        finally:
            event.remove(connection, "before_cursor_execute", _capture)
        return list(statements)

    local, shared = _record(session), _record(session)
    _insert(
        session,
        [_row((venue, "establishment"), local, "item", _path(TACOS, ("item", "a")), amount=1)],
    )
    few = _statements()
    rows = []
    for subject, record in (
        ((venue, "establishment"), local),
        ((organization, "organization"), shared),
    ):
        for index in range(40):
            evidence = _reobserve(
                session,
                record,
                f"https://p{index}.example.test/menu",
                OBSERVED + timedelta(minutes=index),
            )
            rows.append(
                _row(
                    subject,
                    record,
                    "item",
                    _path(TACOS, ("item", f"n{index}")),
                    amount=index + 1,
                    evidence_ids=[evidence],
                )
            )
    _insert(session, rows)
    many = _statements()

    # The venue, its Organization's peers, the Gold rows, then one provenance read.
    assert len(few) == len(many) == 4
    assert [statement for statement in many if "bronze.evidence" in statement] == [many[-1]]


class _FakeEndpoints:
    """Stands in for ``source_endpoints_for_evidence``; records the ids each call asks for."""

    def __init__(self, urls: dict[int, str]) -> None:
        self.urls = urls
        self.calls: list[list[int]] = []

    def __call__(self, _session: object, evidence_ids: Any) -> dict[int, CaptureReference]:
        ids = sorted(set(evidence_ids))
        self.calls.append(ids)
        return {
            eid: CaptureReference(eid, self.urls[eid], "https", E, None, "succeeded", None)
            for eid in ids
            if eid in self.urls
        }


def _page_rows(page: int, ids: range, observed_at: datetime) -> list[CurrentMenuRow]:
    return [
        replace(
            _plain("item", TACOS, ("item", f"{page}-{eid}")),
            price_page_id=page,
            price_evidence_ids=(eid,),
            price_observed_at=observed_at,
        )
        for eid in ids
    ]


def test_source_url_resolves_one_leader_per_page(monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = range(1, 51), range(100, 103)
    urls = dict.fromkeys(old, "https://old.example.test/")
    urls |= dict.fromkeys(new, "https://new.example.test/")
    fake = _FakeEndpoints(urls)
    monkeypatch.setattr(menu_read, "source_endpoints_for_evidence", fake)
    rows = _page_rows(10, old, OBSERVED) + _page_rows(11, new, OBSERVED + timedelta(days=1))

    assert menu_source_urls(cast("Session", None), rows) == {
        ("establishment", 1, 1, "page"): "https://new.example.test/"
    }
    assert fake.calls == [[50, 102]]  # each page's latest-observed, greatest Evidence id


def test_source_url_resolves_a_page_whose_leader_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = dict.fromkeys(range(1, 50), "https://page.example.test/")  # 50 reaches no Capture
    fake = _FakeEndpoints(urls)
    monkeypatch.setattr(menu_read, "source_endpoints_for_evidence", fake)

    rows = _page_rows(10, range(1, 51), OBSERVED)
    assert menu_source_urls(cast("Session", None), rows) == {
        ("establishment", 1, 1, "page"): "https://page.example.test/"
    }
    assert fake.calls == [[50], list(range(1, 51))]


def test_source_url_query_never_seq_scans_provenance(client: TestClient, session: Session) -> None:
    organization, venue = _venue(session)
    _seed_tacos(session, (organization, "organization"))
    _seed_tacos(session, (venue, "establishment"))
    statements: list[tuple[str, Any]] = []

    def _capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "bronze.evidence" in statement:
            statements.append((statement, parameters))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _capture)
    try:
        assert client.get(f"/v1/venues/{venue}/menu").status_code == 200
    finally:
        event.remove(connection, "before_cursor_execute", _capture)

    ((statement, parameters),) = statements
    connection.execute(text("SET LOCAL enable_seqscan = off"))
    try:
        (plan,) = connection.exec_driver_sql(
            f"EXPLAIN (FORMAT JSON) {statement}", parameters
        ).scalar_one()
    finally:
        connection.execute(text("SET LOCAL enable_seqscan = on"))
    provenance = {"evidence", "source_record_version", "capture", "source_endpoint"}
    assert not set(_seq_scans(plan["Plan"])) & provenance


# --------------------------------------------------------------------------- #
# End to end: Menu -> Gold refresh -> API (committed, disposable database).
# --------------------------------------------------------------------------- #


def _observation(token: str) -> BronzeObservation:
    return BronzeObservation(
        source_namespace=f"venue-menu-e2e-{token}",
        source_kind="fixture",
        external_key=token,
        observed_at=OBSERVED,
        content_hash=f"sha256:{token}",
        source_payload={"id": token},
        evidence_locator="$.id",
        source_url=f"https://{token}.example.test/menu",
        capture_content_hash=f"sha256:cap:{token}",
        bundle_path=f"fixture/{token}",
    )


def test_end_to_end_from_menu_through_refresh(disposable_database_engine: Engine) -> None:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    token = uuid4().hex
    with factory.begin() as session:
        shared = persist_source_record_observation(session, _observation(f"{token}-s"))
        local = persist_source_record_observation(session, _observation(f"{token}-l"))
        place = create_place(session, address=f"{token} Street")
        mark_subject_eligible(session, place.id)
        org = create_organization(session, canonical_name=f"Org {token}", name_fingerprint=token)
        admit_source_record(
            session,
            source_record_id=shared.source_record_id,
            decision=decision(),
            evidence_ids=(shared.evidence_id,),
        )
        org_event = assign_source_record(
            session,
            source_record_id=shared.source_record_id,
            to_subject_id=org.id,
            decision=decision(),
            evidence_ids=(shared.evidence_id,),
        )
        establishment = create_establishment(
            session,
            organization_subject_id=org.id,
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
        event_ = assign_source_record(
            session,
            source_record_id=local.source_record_id,
            to_subject_id=establishment.id,
            decision=decision(),
            evidence_ids=(local.evidence_id,),
        )
        scope = ScopeFixture(
            organization=ResolvedScopeRequest(org.id, shared.source_record_id, org_event.id),
            establishment=ResolvedScopeRequest(establishment.id, local.source_record_id, event_.id),
            place_id=place.id,
            shared_input=shared,
            local_input=local,
        )
        venue = establishment.id
    with factory.begin() as session:
        persist_menu(session, aggregate(scope))
    request = SelectionRequest(
        subject_id=venue,
        subject_kind="establishment",
        source_record_id=local.source_record_id,
        root_key="main",
        target=TargetRef(kind="item", native_path=(("section", "s-food"), ("item", "i-burger"))),
        context=ContextRef(channel="dine_in", service_period="lunch"),
        currency_code="USD",
        effective_instant=E,
    )
    with factory.begin() as session:
        assert refresh_current_menu(session, [request]) == 1

    def _committed_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _committed_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get(f"/v1/venues/{venue}/menu")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-09-30T12:00:00Z"
    (menu,) = body["menus"]
    assert menu["scope"] == "establishment"
    (section,) = menu["sections"]
    (item,) = section["items"]
    assert (section["key"], section["name"]) == ("s-food", "Food")
    assert (section["id"], section["prices"]) == (None, [])
    assert (item["key"], item["name"]) == ("i-burger", "Burger")
    assert item["description"] == "Grilled beef"
    (price,) = item["prices"]
    assert (price["amount_minor"], price["channel"], price["service_period"]) == (
        1050,
        "dine_in",
        "lunch",
    )
    assert (price["source_kind"], price["confidence"]) == ("dom", 1.0)
    assert price["observed_at"] == "2026-09-01T12:00:00Z"
    assert menu["source_url"] == f"https://{token}-l.example.test/menu"
