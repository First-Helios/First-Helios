"""``GET /v1/venues/{venue_id}/menu``: shape, staleness, scope rules, 404s, index use.

The endpoint reads ``gold.current_menu`` only (ADR-0008 §9). Most tests seed
Identity and Bronze in the rolled-back API test session and write
``current_menu`` rows directly (a rebuildable Gold table, as the price-index tests
do); one test goes end to end from a persisted Menu through the bounded Gold
refresh on committed rows in the disposable ``*_test`` database.
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
from apps.api.routes.venues import _shape_menu
from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.selection import ContextRef, SelectionRequest, TargetRef
from packages.helios_core.gold import refresh_current_menu
from packages.helios_core.gold.menu_read import CurrentMenuRow
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
    PersistedBronzeObservation,
    persist_source_record_observation,
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
    channel: str = "unspecified",
    effective_instant: datetime = E,
    observed_at: datetime | None = OBSERVED,
    source_kind: str | None = "llm",
    confidence: Decimal | None = Decimal("0.9000"),
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
        "price_evidence_ids": [record.evidence_id],
        "content_name": name,
        "content_evidence_ids": [],
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
    """A section with a named item, a size-only item and an add-on."""
    record = _record(session)
    _insert(
        session,
        [
            _row(
                subject, record, "item", _path(TACOS, ("item", "13:bean")), amount=350, name="Bean"
            ),
            _row(
                subject, record, "variant", _path(TACOS, PASTOR, LARGE), amount=1200, name="Large"
            ),
            _row(
                subject,
                record,
                "modifier",
                _path(TACOS, ("item", "13:bean"), ("modifier", "cheese")),
                amount=100,
                name="Cheese",
            ),
            _row(
                subject, record, "item", _path(TACOS, ("item", "15:market fish")), state="unknown"
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
    channel: str = "unspecified",
    observed_at: datetime | None = OBSERVED,
) -> CurrentMenuRow:
    return CurrentMenuRow(
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
        content_name=name,
        content_description=None,
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
    assert menu["scope"] == "establishment"
    (section,) = menu["sections"]
    assert (section["key"], section["name"]) == ("12:tacos", None)
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

    # Only the variant is priced: Gold holds no name for the item itself.
    assert (pastor["name"], pastor["prices"]) == (None, [])
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
    assert (section["key"], item["key"], item["name"]) == ("s-food", "i-burger", "Burger")
    assert item["description"] == "Grilled beef"
    (price,) = item["prices"]
    assert (price["amount_minor"], price["channel"], price["service_period"]) == (
        1050,
        "dine_in",
        "lunch",
    )
    assert (price["source_kind"], price["confidence"]) == ("dom", 1.0)
    assert price["observed_at"] == "2026-09-01T12:00:00Z"
