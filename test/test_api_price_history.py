"""``GET /v1/items/{item_id}/price-history`` and the Menu history read behind it.

ADR-0018 §B: the trail is read from committed Menu through the selector's
history mode, one point per change at each family page's ``accepted_at``, only
the scope's own claims. The id tests need no database; the trail tests commit
Menu aggregates to the disposable ``*_test`` database, as the selector tests do.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from apps.api.db import get_session
from apps.api.item_ids import InvalidItemIdError, ItemId, decode_item_id, encode_item_id
from apps.api.main import app
from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.contracts import (
    MenuAggregate,
    PageInput,
)
from packages.helios_core.domains.menu.history import price_history
from packages.helios_core.domains.menu.models import MenuPage
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    TargetRef,
)
from packages.helios_core.gold import refresh_current_menu
from packages.helios_core.identity import (
    admit_source_record,
    assign_source_record,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
    remap_source_record,
)
from packages.helios_core.identity.contracts import ResolvedScopeRequest
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    PersistedBronzeObservation,
    persist_source_record_observation,
)
from test.menu_support import aggregate, successor
from test.provider_support import ScopeFixture, decision, migrate

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.contracts import Operation

OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
SINCE = datetime(2020, 1, 1, tzinfo=UTC)
BURGER = (("section", "s-food"), ("item", "i-burger"))
LUNCH = ContextRef(channel="dine_in", service_period="lunch")


# --------------------------------------------------------------------------- #
# item_id (no database).
# --------------------------------------------------------------------------- #

_ITEM = ItemId(
    subject_kind="establishment",
    subject_id=12,
    source_record_id=34,
    root_key="main",
    target_path=(("base", "7"), ("section", "v9:0:tacos"), ("item", "v9:3:al pastor ñ")),
)


def _token(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_item_id_round_trips_and_is_url_safe() -> None:
    token = encode_item_id(_ITEM)
    assert decode_item_id(token) == _ITEM
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert _ITEM.target_kind == "item"


@pytest.mark.parametrize(
    "token",
    [
        "not base64 !!",
        _token({"a": 1}),
        _token(["establishment", 1, 2, "main"]),
        _token(["place", 1, 2, "main", [["item", "x"]]]),
        _token(["establishment", -1, 2, "main", [["item", "x"]]]),
        _token(["establishment", 2**63, 2, "main", [["item", "x"]]]),
        _token(["establishment", True, 2, "main", [["item", "x"]]]),
        _token(["establishment", 1, 2, "main", []]),
        _token(["establishment", 1, 2, "main", [["dish", "x"]]]),
        _token(["establishment", 1, 2, "main", [["item", "x"], ["base", "7"]]]),
        _token(["establishment", 1, 2, "main", [["base", "7"]]]),
        _token(["establishment", 1, 2, "main", [["item", 3]]]),
        _token(["establishment", 1, 2, "ma\x00in", [["item", "x"]]]),
        # A "\ud800" JSON escape decodes to a lone surrogate, which has no UTF-8 form.
        _token(["establishment", 1, 2, "main", [["item", "\ud800"]]]),
        _token(["establishment", 1, 2, "\udfff", [["item", "x"]]]),
        # Padded and spaced encodings are aliases of a canonical id.
        _token(["establishment", 1, 2, "main", [["item", "x"]]]) + "==",
        base64.urlsafe_b64encode(b'["establishment", 1, 2, "main", [["item", "x"]]]').decode(),
    ],
)
def test_malformed_item_id_is_rejected(token: str) -> None:
    with pytest.raises(InvalidItemIdError):
        decode_item_id(token)


# --------------------------------------------------------------------------- #
# Committed Menu world.
# --------------------------------------------------------------------------- #


@dataclass
class World:
    factory: sessionmaker[Session]
    token: str
    scope: ScopeFixture
    other_establishment: int
    seq: int = 1

    @property
    def venue(self) -> int:
        return self.scope.establishment.subject_id

    @property
    def record(self) -> int:
        return self.scope.local_input.source_record_id


def _observation(tag: str, seq: int) -> BronzeObservation:
    return BronzeObservation(
        source_namespace=f"price-history-{tag}",
        source_kind="fixture",
        external_key=tag,
        observed_at=OBSERVED + timedelta(hours=seq - 1),
        content_hash=f"sha256:{tag}:{seq}",
        source_payload={"tag": tag, "seq": seq},
        evidence_locator="$.tag",
        source_url=f"https://{tag}.example.test/menu",
        capture_content_hash=f"sha256:cap:{tag}:{seq}",
        bundle_path=f"fixture/{tag}/{seq}",
    )


def _establishment(session: Session, organization: int, token: str) -> int:
    place = create_place(session, address=f"{token} Street")
    mark_subject_eligible(session, place.id)
    establishment = create_establishment(
        session,
        organization_subject_id=organization,
        place_subject_id=place.id,
        valid_from=SINCE,
        operating_status="open",
    )
    mark_subject_eligible(session, establishment.id)
    return establishment.id


@pytest.fixture
def world(disposable_database_engine: Engine) -> World:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    token = uuid4().hex
    with factory.begin() as session:
        shared = persist_source_record_observation(session, _observation(f"{token}-s", 1))
        local = persist_source_record_observation(session, _observation(f"{token}-l", 1))
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
        venue = _establishment(session, org.id, f"{token}-a")
        other = _establishment(session, org.id, f"{token}-b")
        admit_source_record(
            session,
            source_record_id=local.source_record_id,
            decision=decision(),
            evidence_ids=(local.evidence_id,),
        )
        local_event = assign_source_record(
            session,
            source_record_id=local.source_record_id,
            to_subject_id=venue,
            decision=decision(),
            evidence_ids=(local.evidence_id,),
        )
    scope = ScopeFixture(
        organization=ResolvedScopeRequest(org.id, shared.source_record_id, org_event.id),
        establishment=ResolvedScopeRequest(venue, local.source_record_id, local_event.id),
        place_id=0,
        shared_input=shared,
        local_input=local,
    )
    return World(factory, token, scope, other)


def _commit(world: World, value: MenuAggregate) -> int:
    with world.factory.begin() as session:
        return persist_menu(session, value).page_id


def _new_version(world: World) -> PersistedBronzeObservation:
    world.seq += 1
    with world.factory.begin() as session:
        return persist_source_record_observation(
            session, _observation(f"{world.token}-l", world.seq)
        )


def _priced(value: MenuAggregate, amount: int, native_key: str = "i-burger") -> MenuAggregate:
    return replace(
        value,
        items=(replace(value.items[0], source_native_key=native_key),),
        prices=(replace(value.prices[0], amount_minor=amount),),
    )


def _next_page(
    value: MenuAggregate,
    version: PersistedBronzeObservation,
    predecessor: int,
    operation: Operation,
    stream_revision: int,
) -> MenuAggregate:
    """The next page of the stream, read from another Bronze Version."""
    return replace(
        value,
        page=replace(
            value.page,
            source_record_version_id=version.source_record_version_id,
            operation=operation,
            supersedes_page_id=predecessor,
            stream_revision=stream_revision,
            evidence_ids=(version.evidence_id,),
        ),
        sections=tuple(replace(s, evidence_ids=(version.evidence_id,)) for s in value.sections),
        items=tuple(replace(i, evidence_ids=(version.evidence_id,)) for i in value.items),
        applicability=tuple(
            replace(a, evidence_ids=(version.evidence_id,)) for a in value.applicability
        ),
        prices=tuple(replace(p, evidence_ids=(version.evidence_id,)) for p in value.prices),
    )


def _withdrawal(
    value: MenuAggregate, version: PersistedBronzeObservation, predecessor: int
) -> MenuAggregate:
    page = value.page
    return MenuAggregate(
        page=PageInput(
            subject_id=page.subject_id,
            subject_kind=page.subject_kind,
            source_record_version_id=version.source_record_version_id,
            resolution_event_id=page.resolution_event_id,
            root_key=page.root_key,
            source_kind=page.source_kind,
            method=page.method,
            method_version=page.method_version,
            stream_revision=page.stream_revision + 1,
            interpretation_revision=1,
            confidence=page.confidence,
            operation="withdrawal",
            evidence_ids=(version.evidence_id,),
            supersedes_page_id=predecessor,
        )
    )


def _accepted_at(world: World, page_id: int) -> datetime:
    with world.factory() as session:
        return session.execute(
            select(MenuPage.accepted_at).where(MenuPage.id == page_id)
        ).scalar_one()


def _history(world: World, subject: int, path: tuple[tuple[str, str], ...] = BURGER) -> Any:
    with world.factory() as session:
        return price_history(
            session,
            subject_id=subject,
            subject_kind="establishment",
            source_record_id=world.record,
            root_key="main",
            target=TargetRef(kind="item", native_path=path),
        )


def _points(world: World, subject: int, path: tuple[tuple[str, str], ...] = BURGER) -> list[Any]:
    (trail,) = _history(world, subject, path)
    assert (trail.context, trail.currency_code) == (LUNCH, "USD")
    return [(p.state, p.amount_minor) for p in trail.points]


def test_corrections_add_points_and_known_from_is_acceptance(world: World) -> None:
    first = _priced(aggregate(world.scope), 1050)
    p1 = _commit(world, first)
    corrected = _priced(successor(first, p1), 1100)
    p2 = _commit(world, corrected)
    # The same amount from a new page is still a change of answer (ADR-0018 §B6).
    p3 = _commit(world, successor(corrected, p2))
    # A lower-ranked stream's page changes nothing: the DOM page still answers.
    llm = replace(first, page=replace(first.page, source_kind="llm"))
    p4 = _commit(world, _priced(llm, 999))

    (trail,) = _history(world, world.venue)
    assert [(p.state, p.amount_minor, p.source_kind) for p in trail.points] == [
        ("priced", 1050, "dom"),
        ("priced", 1100, "dom"),
        ("priced", 1100, "dom"),
    ]
    assert [p.known_from for p in trail.points] == [
        _accepted_at(world, p1),
        _accepted_at(world, p2),
        _accepted_at(world, p3),
    ]
    assert _accepted_at(world, p4) > _accepted_at(world, p3)
    assert trail.points[0].observed_at == OBSERVED
    assert trail.points[0].confidence == 1


def test_newer_version_with_new_keys_ends_the_trail_absent(world: World) -> None:
    first = _priced(aggregate(world.scope), 1050, "v1:burger")
    p1 = _commit(world, first)
    _commit(
        world,
        _priced(_next_page(first, _new_version(world), p1, "observation", 2), 1200, "v2:burger"),
    )

    old = (("section", "s-food"), ("item", "v1:burger"))
    new = (("section", "s-food"), ("item", "v2:burger"))
    assert _points(world, world.venue, old) == [("priced", 1050), ("absent", None)]
    # The new Version's node is its own target with its own one-point trail.
    assert _points(world, world.venue, new) == [("priced", 1200)]


def test_withdrawal_and_restoration_are_points(world: World) -> None:
    first = _priced(aggregate(world.scope), 1050)
    p1 = _commit(world, first)
    p2 = _commit(world, _withdrawal(first, _new_version(world), p1))
    restored = _next_page(first, _new_version(world), p2, "restoration", 3)
    _commit(world, _priced(restored, 1175))

    assert _points(world, world.venue) == [
        ("priced", 1050),
        ("withdrawn", None),
        ("priced", 1175),
    ]


def test_only_the_scopes_own_claims_after_a_remap(world: World) -> None:
    first = _priced(aggregate(world.scope), 1050)
    p1 = _commit(world, first)
    with world.factory.begin() as session:
        moved = remap_source_record(
            session,
            source_record_id=world.record,
            from_subject_id=world.venue,
            to_subject_id=world.other_establishment,
            decision=decision(),
            evidence_ids=(world.scope.local_input.evidence_id,),
        )
    # The successor re-reads the same Version under its own scope.
    successor_page = successor(first, p1, subject_id=world.other_establishment)
    successor_page = replace(
        successor_page, page=replace(successor_page.page, resolution_event_id=moved.id)
    )
    _commit(world, _priced(successor_page, 1300))

    # The predecessor's trail stops at its own claim; the successor's starts at its own.
    assert _points(world, world.venue) == [("priced", 1050)]
    assert _points(world, world.other_establishment) == [("priced", 1300)]


def test_unclaimed_target_or_subject_has_no_history(world: World) -> None:
    _commit(world, _priced(aggregate(world.scope), 1050))
    assert _history(world, world.venue, (("section", "s-food"), ("item", "nope"))) is None
    assert _history(world, world.other_establishment) is None


def test_history_query_count_grows_linearly_with_pages(world: World) -> None:
    value = _priced(aggregate(world.scope), 1000)
    previous = _commit(world, value)
    counts: list[int] = []
    for amount in (1001, 1002, 1003, 1004):
        value = _priced(successor(value, previous), amount)
        previous = _commit(world, value)
        statements = 0

        def _count(*_: Any) -> None:
            nonlocal statements
            statements += 1

        with world.factory() as session:
            connection = session.connection()
            event.listen(connection, "before_cursor_execute", _count)
            trails = price_history(
                session,
                subject_id=world.venue,
                subject_kind="establishment",
                source_record_id=world.record,
                root_key="main",
                target=TargetRef(kind="item", native_path=BURGER),
            )
            event.remove(connection, "before_cursor_execute", _count)
        assert trails is not None
        (trail,) = trails
        assert len(trail.points) == amount - 999
        counts.append(statements)
    steps = {later - earlier for earlier, later in zip(counts, counts[1:], strict=False)}
    # One more page adds the same bounded number of statements each time.
    assert len(steps) == 1
    assert steps.pop() <= 20


# --------------------------------------------------------------------------- #
# Endpoint.
# --------------------------------------------------------------------------- #


@pytest.fixture
def committed_client(world: World) -> Iterator[TestClient]:
    def _committed_session() -> Iterator[Session]:
        with world.factory() as session:
            yield session

    app.dependency_overrides[get_session] = _committed_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_menu_node_id_links_to_its_history(world: World, committed_client: TestClient) -> None:
    first = _priced(aggregate(world.scope), 1050)
    p1 = _commit(world, first)
    _commit(world, _priced(successor(first, p1), 1100))
    request = SelectionRequest(
        subject_id=world.venue,
        subject_kind="establishment",
        source_record_id=world.record,
        root_key="main",
        target=TargetRef(kind="item", native_path=BURGER),
        context=LUNCH,
        currency_code="USD",
        effective_instant=datetime.now(UTC),
    )
    with world.factory.begin() as session:
        assert refresh_current_menu(session, [request]) == 1

    menu = committed_client.get(f"/v1/venues/{world.venue}/menu").json()
    (section,) = menu["menus"][0]["sections"]
    assert section["id"] is None  # the section carries no price of its own
    (item,) = section["items"]
    assert decode_item_id(item["id"]) == ItemId(
        "establishment", world.venue, world.record, "main", BURGER
    )

    before = datetime.now(UTC)
    response = committed_client.get(f"/v1/items/{item['id']}/price-history")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"item_id", "as_of", "trails"}
    assert body["item_id"] == item["id"]
    assert datetime.fromisoformat(body["as_of"]) >= before.replace(microsecond=0)
    (trail,) = body["trails"]
    assert {k: v for k, v in trail.items() if k != "points"} == {
        "channel": "dine_in",
        "service_period": "lunch",
        "valid_from": None,
        "valid_to": None,
        "currency_code": "USD",
    }
    assert [(p["state"], p["amount_minor"]) for p in trail["points"]] == [
        ("priced", 1050),
        ("priced", 1100),
    ]
    point = trail["points"][0]
    assert set(point) == {
        "known_from",
        "state",
        "amount_minor",
        "observed_at",
        "source_kind",
        "confidence",
    }
    assert point["known_from"].endswith("Z")
    assert (point["observed_at"], point["source_kind"], point["confidence"]) == (
        "2026-09-01T12:00:00Z",
        "dom",
        1.0,
    )


def test_unknown_item_is_404_and_malformed_is_422(
    world: World, committed_client: TestClient
) -> None:
    _commit(world, _priced(aggregate(world.scope), 1050))
    missing = encode_item_id(
        ItemId("establishment", world.venue, world.record, "main", (("item", "nope"),))
    )
    response = committed_client.get(f"/v1/items/{missing}/price-history")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

    surrogate = _token(["establishment", world.venue, world.record, "main", [["item", "\ud800"]]])
    for bad in ("not-an-id", "x" * 5000, surrogate):
        response = committed_client.get(f"/v1/items/{bad}/price-history")
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "validation_error"
        assert set(body) == {"detail", "code", "trace_id"}
