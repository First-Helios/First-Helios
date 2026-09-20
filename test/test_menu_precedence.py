"""Pure current/accepted-history Menu selection over committed disposable data.

These tests are the read-side complement of the accepted writer tests. They
build committed Menu aggregates with the shared fixtures and assert the
deterministic selection defined by the ADR-0005 example matrix: price-only
inheritance, absent vs. explicit-unknown local prices, sibling independence,
kind/recency/confidence ranking, stream head at ``K`` before ``O``/``E``
filtering, tombstone and restoration, pin survival and unresolved base, remap
and retirement, operating availability, effective-context intersection, and
native/base correspondence.

All data is disposable ``*_test`` PostgreSQL committed by the fixtures; nothing
here writes application data or asserts source truth.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.contracts import (
    ApplicabilityInput,
    ItemInput,
    MenuAggregate,
    PageInput,
    PriceInput,
    SectionInput,
    Target,
    VariantInput,
)
from packages.helios_core.domains.menu.models import MenuPage
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    Selection,
    SelectionRequest,
    TargetRef,
    select_price,
)
from packages.helios_core.identity import (
    admit_source_record,
    assign_source_record,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
    record_subject_change,
    remap_source_record,
)
from packages.helios_core.identity.contracts import ResolvedScopeRequest
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    PersistedBronzeObservation,
    persist_source_record_observation,
)
from test.menu_support import aggregate, inherited
from test.provider_support import ScopeFixture, decision, migrate, pending_change

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.contracts import Operation, PersistedMenu, SourceKind

_PriceState = Literal["priced", "unknown", "unavailable"]

TARGET = TargetRef(kind="item", native_path=(("section", "s-food"), ("item", "i-burger")))
LUNCH = ContextRef(channel="dine_in", service_period="lunch")
E = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 17, hour, minute, tzinfo=UTC)


def _applicability(
    key: str, evidence_ids: tuple[int, ...], valid_from: datetime, valid_to: datetime
) -> ApplicabilityInput:
    return ApplicabilityInput(
        applicability_key=key,
        channel="dine_in",
        evidence_ids=evidence_ids,
        service_period="lunch",
        valid_from=valid_from,
        valid_to=valid_to,
    )


@dataclass(frozen=True)
class Actor:
    subject_id: int
    source_record_id: int
    event_id: int
    v1: PersistedBronzeObservation
    tag: str

    @property
    def req(self) -> ResolvedScopeRequest:
        return ResolvedScopeRequest(self.subject_id, self.source_record_id, self.event_id)


@dataclass(frozen=True)
class World:
    factory: sessionmaker[Session]
    org: Actor
    a: Actor
    b: Actor
    place_a: int
    place_b: int
    token: str


def _observe(session: Session, tag: str, at: datetime, seq: int) -> PersistedBronzeObservation:
    """One immutable Bronze observation; a later ``seq`` appends a new version."""
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=f"menu-sel-{tag}",
            source_kind="fixture",
            external_key=tag,
            observed_at=at,
            content_hash=f"sha256:{tag}:{seq}",
            source_payload={"tag": tag, "seq": seq},
            evidence_locator=f"$.{tag}.{seq}",
            evidence_excerpt_hash=f"sha256:ev:{tag}:{seq}",
            canonical_url=f"https://{tag}.example.test/menu",
            capture_content_hash=f"sha256:cap:{tag}:{seq}",
            bundle_path=f"fixture/{tag}/{seq}",
            fetched_at=at,
        ),
    )


def _eligible_establishment(
    session: Session,
    org_subject_id: int,
    place_subject_id: int,
    obs: PersistedBronzeObservation,
    operating_status: str,
) -> tuple[int, int]:
    establishment = create_establishment(
        session,
        organization_subject_id=org_subject_id,
        place_subject_id=place_subject_id,
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        operating_status=operating_status,
    )
    mark_subject_eligible(session, establishment.id)
    admit_source_record(
        session,
        source_record_id=obs.source_record_id,
        decision=decision(),
        evidence_ids=(obs.evidence_id,),
    )
    event = assign_source_record(
        session,
        source_record_id=obs.source_record_id,
        to_subject_id=establishment.id,
        decision=decision(),
        evidence_ids=(obs.evidence_id,),
    )
    return establishment.id, event.id


@pytest.fixture
def world(disposable_database_engine: Engine) -> Iterator[World]:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    token = uuid4().hex
    with factory.begin() as s:
        org_v1 = _observe(s, f"{token}-org", _t(9, 0), 1)
        a_v1 = _observe(s, f"{token}-a", _t(9, 10), 1)
        b_v1 = _observe(s, f"{token}-b", _t(9, 20), 1)
        place_a = create_place(s, address="100 A Street")
        mark_subject_eligible(s, place_a.id)
        place_b = create_place(s, address="200 B Street")
        mark_subject_eligible(s, place_b.id)
        org = create_organization(s, canonical_name="Chain", name_fingerprint="chain")
        admit_source_record(
            s,
            source_record_id=org_v1.source_record_id,
            decision=decision(),
            evidence_ids=(org_v1.evidence_id,),
        )
        org_event = assign_source_record(
            s,
            source_record_id=org_v1.source_record_id,
            to_subject_id=org.id,
            decision=decision(),
            evidence_ids=(org_v1.evidence_id,),
        )
        a_id, a_event = _eligible_establishment(s, org.id, place_a.id, a_v1, "open")
        b_id, b_event = _eligible_establishment(s, org.id, place_b.id, b_v1, "open")
    yield World(
        factory,
        Actor(org.id, org_v1.source_record_id, org_event.id, org_v1, f"{token}-org"),
        Actor(a_id, a_v1.source_record_id, a_event, a_v1, f"{token}-a"),
        Actor(b_id, b_v1.source_record_id, b_event, b_v1, f"{token}-b"),
        place_a.id,
        place_b.id,
        token,
    )


# --------------------------------------------------------------------------- #
# Committed builders.
# --------------------------------------------------------------------------- #


def _commit(world: World, value: MenuAggregate) -> PersistedMenu:
    with world.factory.begin() as session:
        return persist_menu(session, value)


def _select(world: World, request: SelectionRequest) -> Selection:
    with world.factory() as session:
        return select_price(session, request)


def _accepted_at(world: World, page_id: int) -> datetime:
    with world.factory() as session:
        return session.execute(
            select(MenuPage.accepted_at).where(MenuPage.id == page_id)
        ).scalar_one()


def _append(world: World, actor: Actor, at: datetime, seq: int) -> PersistedBronzeObservation:
    with world.factory.begin() as session:
        return _observe(session, actor.tag, at, seq)


def _org_page(
    world: World,
    obs: PersistedBronzeObservation,
    *,
    amount: int,
    name: str = "Burger",
    description: str = "Grilled beef",
    operation: Operation = "initial",
    supersedes: int | None = None,
    stream_rev: int = 1,
    interp_rev: int = 1,
) -> MenuAggregate:
    scope = ScopeFixture(world.org.req, world.a.req, world.place_a, obs, world.a.v1)
    value = aggregate(scope, shared=True)
    return replace(
        value,
        page=replace(
            value.page,
            source_kind="jsonld",
            operation=operation,
            supersedes_page_id=supersedes,
            stream_revision=stream_rev,
            interpretation_revision=interp_rev,
        ),
        items=(replace(value.items[0], name=name, description=description),),
        prices=(replace(value.prices[0], amount_minor=amount),),
    )


def _local_page(
    world: World,
    actor: Actor,
    place: int,
    obs: PersistedBronzeObservation,
    base: PersistedMenu,
    *,
    amount: int = 1050,
    state: _PriceState = "priced",
    operation: Operation = "initial",
    supersedes: int | None = None,
    stream_rev: int = 1,
    interp_rev: int = 1,
    with_price: bool = True,
) -> MenuAggregate:
    scope = ScopeFixture(world.org.req, actor.req, place, world.org.v1, obs)
    value = inherited(aggregate(scope), base)
    page = replace(
        value.page,
        operation=operation,
        supersedes_page_id=supersedes,
        stream_revision=stream_rev,
        interpretation_revision=interp_rev,
    )
    if not with_price:
        return replace(value, page=page, prices=(), applicability=())
    price = replace(
        value.prices[0],
        amount_minor=amount if state == "priced" else None,
        price_state=state,
    )
    return replace(value, page=page, prices=(price,))


def _direct_page(
    world: World,
    actor: Actor,
    place: int,
    obs: PersistedBronzeObservation,
    *,
    amount: int,
    kind: SourceKind = "dom",
    confidence: str = "1",
) -> MenuAggregate:
    scope = ScopeFixture(world.org.req, actor.req, place, world.org.v1, obs)
    value = aggregate(scope)
    return replace(
        value,
        page=replace(value.page, source_kind=kind),
        prices=(replace(value.prices[0], amount_minor=amount, confidence=Decimal(confidence)),),
    )


def _withdrawal_page(
    world: World,
    actor: Actor,
    obs: PersistedBronzeObservation,
    *,
    supersedes: int,
    stream_rev: int,
    subject_kind: Literal["organization", "establishment"] = "establishment",
    source_kind: SourceKind = "dom",
) -> MenuAggregate:
    return MenuAggregate(
        page=PageInput(
            subject_id=actor.subject_id,
            subject_kind=subject_kind,
            source_record_version_id=obs.source_record_version_id,
            resolution_event_id=actor.event_id,
            root_key="main",
            source_kind=source_kind,
            method="menu-fixture",
            method_version="1",
            stream_revision=stream_rev,
            interpretation_revision=1,
            confidence=Decimal("1"),
            operation="withdrawal",
            evidence_ids=(obs.evidence_id,),
            supersedes_page_id=supersedes,
        )
    )


def _est_request(
    actor: Actor,
    *,
    knowledge_cutoff: datetime | None = None,
    observation_cutoff: datetime | None = None,
    context: ContextRef = LUNCH,
    instant: datetime = E,
) -> SelectionRequest:
    return SelectionRequest(
        subject_id=actor.subject_id,
        subject_kind="establishment",
        source_record_id=actor.source_record_id,
        root_key="main",
        target=TARGET,
        context=context,
        currency_code="USD",
        effective_instant=instant,
        knowledge_cutoff=knowledge_cutoff,
        observation_cutoff=observation_cutoff,
    )


def _org_request(world: World, *, knowledge_cutoff: datetime | None = None) -> SelectionRequest:
    return SelectionRequest(
        subject_id=world.org.subject_id,
        subject_kind="organization",
        source_record_id=world.org.source_record_id,
        root_key="main",
        target=TARGET,
        context=LUNCH,
        currency_code="USD",
        effective_instant=E,
        knowledge_cutoff=knowledge_cutoff,
    )


# --------------------------------------------------------------------------- #
# Matrix rows.
# --------------------------------------------------------------------------- #


def test_price_only_inheritance_and_separate_org_claim(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))

    result = _select(world, _est_request(world.a))

    assert result.local_price.state == "priced"
    assert result.local_price.amount_minor == 1050
    assert result.local_price.scope_subject_id == world.a.subject_id
    assert result.local_price.source_kind == "dom"
    assert result.local_price.observed_at == _t(9, 10)
    assert result.content is not None
    assert result.content.scope == "organization"
    assert result.content.scope_subject_id == world.org.subject_id
    assert result.content.source_kind == "jsonld"
    assert (result.content.name, result.content.description) == ("Burger", "Grilled beef")
    assert result.content.observed_at == _t(9, 0)
    assert [(c.origin, c.amount_minor) for c in result.organization] == [("pinned", 900)]


def test_absent_local_price_is_derived_unknown_without_fallback(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    _commit(
        world,
        _local_page(world, world.b, world.place_b, world.b.v1, o1, with_price=False),
    )

    result = _select(world, _est_request(world.b))

    # No invented Evidence, no sibling (A=1050) or Organization (900) fallback.
    assert result.local_price.state == "absent"
    assert result.local_price.amount_minor is None
    assert result.local_price.evidence_ids == ()
    assert result.content is not None and result.content.scope == "organization"
    assert [(c.origin, c.amount_minor) for c in result.organization] == [("pinned", 900)]


def test_sibling_prices_stay_distinct_local_over_shared(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    _commit(world, _local_page(world, world.b, world.place_b, world.b.v1, o1, amount=1200))

    a_result = _select(world, _est_request(world.a))
    b_result = _select(world, _est_request(world.b))

    assert a_result.local_price.amount_minor == 1050
    assert b_result.local_price.amount_minor == 1200
    assert a_result.local_price.source_kind == "dom"
    assert a_result.content is not None and a_result.content.source_kind == "jsonld"
    assert [(c.origin, c.amount_minor) for c in a_result.organization] == [("pinned", 900)]
    assert [(c.origin, c.amount_minor) for c in b_result.organization] == [("pinned", 900)]


def test_ranking_prefers_interpretation_kind(world: World) -> None:
    # Two local streams on one record: JSON-LD outranks DOM even though DOM is
    # dearer, and it supplies the selected content too.
    _commit(world, _direct_page(world, world.a, world.place_a, world.a.v1, amount=1050, kind="dom"))
    _commit(
        world, _direct_page(world, world.a, world.place_a, world.a.v1, amount=1000, kind="jsonld")
    )

    result = _select(world, _est_request(world.a))

    assert result.local_price.amount_minor == 1000
    assert result.local_price.source_kind == "jsonld"
    assert result.content is not None and result.content.source_kind == "jsonld"


def test_ranking_breaks_ties_by_confidence(world: World) -> None:
    scope = ScopeFixture(world.org.req, world.a.req, world.place_a, world.org.v1, world.a.v1)
    value = aggregate(scope)
    low = replace(
        value.prices[0], observation_key="p-low", amount_minor=1000, confidence=Decimal("0.5")
    )
    high = replace(
        value.prices[0], observation_key="p-high", amount_minor=1200, confidence=Decimal("0.9")
    )
    _commit(world, replace(value, prices=(low, high)))

    result = _select(world, _est_request(world.a))

    assert result.local_price.amount_minor == 1200
    assert result.local_price.confidence == Decimal("0.9000")


def test_ranking_is_independent_of_ingestion_order(world: World) -> None:
    # Commit DOM (later observation) before JSON-LD (earlier observation): the
    # business answer follows kind/observation, never arrival order.
    _commit(world, _direct_page(world, world.a, world.place_a, world.a.v1, amount=1050, kind="dom"))
    later = _append(world, world.a, _t(11, 0), 9)
    _commit(world, _direct_page(world, world.a, world.place_a, later, amount=1000, kind="jsonld"))

    result = _select(world, _est_request(world.a))

    assert result.local_price.source_kind == "jsonld"
    assert result.local_price.amount_minor == 1000


def test_history_stream_head_at_k_and_later_observation(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    a_v2 = _append(world, world.a, _t(10, 0), 2)
    a2 = _commit(
        world,
        _local_page(
            world,
            world.a,
            world.place_a,
            a_v2,
            o1,
            amount=1050,
            operation="observation",
            supersedes=a1.page_id,
            stream_rev=2,
        ),
    )

    at_a1 = _select(world, _est_request(world.a, knowledge_cutoff=_accepted_at(world, a1.page_id)))
    at_a2 = _select(world, _est_request(world.a, knowledge_cutoff=_accepted_at(world, a2.page_id)))

    assert at_a1.local_price.page_id == a1.page_id
    assert at_a1.local_price.observed_at == _t(9, 10)
    assert at_a2.local_price.page_id == a2.page_id
    assert at_a2.local_price.observed_at == _t(10, 0)


def test_correction_changes_accepted_interpretation_by_k(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    a_v2 = _append(world, world.a, _t(10, 0), 2)
    a2 = _commit(
        world,
        _local_page(
            world,
            world.a,
            world.place_a,
            a_v2,
            o1,
            amount=1050,
            operation="observation",
            supersedes=a1.page_id,
            stream_rev=2,
        ),
    )
    a3 = _commit(
        world,
        _local_page(
            world,
            world.a,
            world.place_a,
            a_v2,
            o1,
            amount=1150,
            operation="correction",
            supersedes=a2.page_id,
            stream_rev=3,
            interp_rev=2,
        ),
    )

    before = _select(world, _est_request(world.a, knowledge_cutoff=_accepted_at(world, a2.page_id)))
    after = _select(world, _est_request(world.a, knowledge_cutoff=_accepted_at(world, a3.page_id)))

    assert before.local_price.amount_minor == 1050
    assert after.local_price.amount_minor == 1150
    # The correction reuses vA2's observation time, not its acceptance time.
    assert after.local_price.observed_at == _t(10, 0)


def test_explicit_local_unknown_keeps_its_observation(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a_v4 = _append(world, world.a, _t(10, 20), 4)
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    _commit(
        world,
        _local_page(
            world,
            world.a,
            world.place_a,
            a_v4,
            o1,
            state="unknown",
            operation="observation",
            supersedes=a1.page_id,
            stream_rev=2,
        ),
    )

    result = _select(world, _est_request(world.a))

    # An explicit unknown keeps observation time and Evidence, unlike absence.
    assert result.local_price.state == "unknown"
    assert result.local_price.amount_minor is None
    assert result.local_price.observed_at == _t(10, 20)
    assert result.local_price.evidence_ids != ()
    assert [(c.origin, c.amount_minor) for c in result.organization] == [("pinned", 900)]


def test_withdrawal_blocks_predecessors_even_under_observation_cutoff(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    a_v4 = _append(world, world.a, _t(10, 20), 4)
    a4 = _commit(
        world,
        _local_page(
            world,
            world.a,
            world.place_a,
            a_v4,
            o1,
            state="unknown",
            operation="observation",
            supersedes=a1.page_id,
            stream_rev=2,
        ),
    )
    a_v5 = _append(world, world.a, _t(10, 30), 5)
    a5 = _commit(world, _withdrawal_page(world, world.a, a_v5, supersedes=a4.page_id, stream_rev=3))

    # K after the tombstone, O before it: still withdrawn, no predecessor revived.
    blocked = _select(
        world,
        _est_request(
            world.a,
            knowledge_cutoff=_accepted_at(world, a5.page_id),
            observation_cutoff=_t(10, 20),
        ),
    )
    assert blocked.local_price.state == "withdrawn"
    assert blocked.content is None

    # K before the tombstone still shows the explicit unknown at A4.
    earlier = _select(
        world, _est_request(world.a, knowledge_cutoff=_accepted_at(world, a4.page_id))
    )
    assert earlier.local_price.state == "unknown"


def test_restoration_requires_a_new_supported_page(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    a_v5 = _append(world, world.a, _t(10, 30), 5)
    a5 = _commit(world, _withdrawal_page(world, world.a, a_v5, supersedes=a1.page_id, stream_rev=2))
    a_v6 = _append(world, world.a, _t(10, 40), 6)
    _commit(
        world,
        _local_page(
            world,
            world.a,
            world.place_a,
            a_v6,
            o1,
            amount=1175,
            operation="restoration",
            supersedes=a5.page_id,
            stream_rev=3,
        ),
    )

    result = _select(world, _est_request(world.a))

    assert result.local_price.state == "priced"
    assert result.local_price.amount_minor == 1175
    assert result.local_price.observed_at == _t(10, 40)


def test_org_successor_keeps_pin_and_shows_separate_head(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    o_v2 = _append(world, world.org, _t(11, 0), 2)
    _commit(
        world,
        _org_page(
            world,
            o_v2,
            amount=950,
            description="Angus beef",
            operation="observation",
            supersedes=o1.page_id,
            stream_rev=2,
        ),
    )

    result = _select(world, _est_request(world.a))

    # A stays pinned to O1: its content and shared claim are O1, not O2.
    assert result.local_price.amount_minor == 1050
    assert result.content is not None
    assert result.content.page_id == o1.page_id
    assert result.content.description == "Grilled beef"
    assert sorted((c.origin, c.amount_minor) for c in result.organization) == [
        ("head", 950),
        ("pinned", 900),
    ]


def test_org_withdrawal_makes_pin_unresolved_until_rebased(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    before_withdrawal = _accepted_at(world, a1.page_id)
    o_v3 = _append(world, world.org, _t(11, 10), 3)
    _commit(
        world,
        _withdrawal_page(
            world,
            world.org,
            o_v3,
            supersedes=o1.page_id,
            stream_rev=2,
            subject_kind="organization",
            source_kind="jsonld",
        ),
    )

    # Current: the pin's base is withdrawn, so no resolved local price and no
    # revived predecessor; no sibling/base fallback is invented.
    current = _select(world, _est_request(world.a))
    assert current.local_price.state == "unresolved_base"
    assert current.content is None

    # History before the base withdrawal still resolves the pinned claim.
    historical = _select(world, _est_request(world.a, knowledge_cutoff=before_withdrawal))
    assert historical.local_price.amount_minor == 1050

    # An explicit organization restoration does not silently revive the old pin.
    o_v4 = _append(world, world.org, _t(11, 20), 4)
    _commit(
        world,
        _org_page(
            world,
            o_v4,
            amount=975,
            operation="restoration",
            supersedes=self_withdrawal_revision(world),
            stream_rev=3,
        ),
    )
    still_unresolved = _select(world, _est_request(world.a))
    assert still_unresolved.local_price.state == "unresolved_base"
    restored_org = _select(world, _org_request(world))
    assert restored_org.local_price.amount_minor == 975


def self_withdrawal_revision(world: World) -> int:
    with world.factory() as session:
        return session.execute(
            select(MenuPage.id).where(
                MenuPage.source_record_id == world.org.source_record_id,
                MenuPage.operation == "withdrawal",
            )
        ).scalar_one()


def test_current_remap_is_stale_but_history_is_preserved(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    accepted = _accepted_at(world, a1.page_id)
    with world.factory.begin() as session:
        remap_source_record(
            session,
            source_record_id=world.a.source_record_id,
            from_subject_id=world.a.subject_id,
            to_subject_id=world.b.subject_id,
            decision=decision(),
            evidence_ids=(world.a.v1.evidence_id,),
        )

    current = _select(world, _est_request(world.a))
    assert current.local_price.state == "unresolved_scope"

    historical = _select(world, _est_request(world.a, knowledge_cutoff=accepted))
    assert historical.local_price.amount_minor == 1050
    assert historical.local_price.scope_subject_id == world.a.subject_id


def test_current_retirement_is_ineligible_but_history_is_preserved(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    accepted = _accepted_at(world, a1.page_id)
    with world.factory.begin() as session:
        record_subject_change(
            session,
            operation="retire",
            input_subject_ids=[world.a.subject_id],
            output_subject_ids=[],
            decision=decision(),
            evidence_ids=(world.a.v1.evidence_id,),
        )

    current = _select(world, _est_request(world.a))
    assert current.local_price.state == "unresolved_scope"

    historical = _select(world, _est_request(world.a, knowledge_cutoff=accepted))
    assert historical.local_price.amount_minor == 1050


def test_current_requires_operating_availability(world: World) -> None:
    with world.factory.begin() as session:
        obs = _observe(session, f"{world.token}-closed", _t(9, 0), 1)
        place_c = create_place(session, address="300 C Street")
        mark_subject_eligible(session, place_c.id)
        closed_id, closed_event = _eligible_establishment(
            session, world.org.subject_id, place_c.id, obs, "closed"
        )
    closed = Actor(closed_id, obs.source_record_id, closed_event, obs, f"{world.token}-closed")
    _commit(world, _direct_page(world, closed, place_c.id, obs, amount=1050))

    result = _select(world, _est_request(closed))

    assert result.local_price.state == "not_operating"
    assert result.content is None


def test_effective_context_equality_and_half_open_instant(world: World) -> None:
    ev = (world.a.v1.evidence_id,)
    page = MenuAggregate(
        page=PageInput(
            subject_id=world.a.subject_id,
            subject_kind="establishment",
            source_record_version_id=world.a.v1.source_record_version_id,
            resolution_event_id=world.a.event_id,
            root_key="main",
            source_kind="dom",
            method="menu-fixture",
            method_version="1",
            stream_revision=1,
            interpretation_revision=1,
            confidence=Decimal("1"),
            operation="initial",
            evidence_ids=ev,
        ),
        sections=(
            SectionInput(
                section_key="food",
                name="Food",
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=ev,
                source_native_key="s-food",
                applicability_key="sec",
            ),
        ),
        items=(
            ItemInput(
                item_key="burger",
                section_key="food",
                name="Burger",
                description="Grilled beef",
                position=0,
                dietary_tags=(),
                effect="replace",
                support_kind="direct",
                evidence_ids=ev,
                source_native_key="i-burger",
            ),
        ),
        applicability=(
            _applicability("sec", ev, _t(11, 0), _t(14, 0)),
            _applicability("wide", ev, _t(10, 0), _t(15, 0)),
            _applicability("mid", ev, _t(10, 30), _t(14, 30)),
            _applicability("later", ev, _t(12, 0), _t(14, 0)),
        ),
        prices=(
            PriceInput(
                observation_key="p-wide",
                target=Target(kind="item", key="burger"),
                applicability_key="wide",
                price_kind="absolute",
                price_state="priced",
                amount_minor=1000,
                currency_code="USD",
                confidence=Decimal("1"),
                evidence_ids=ev,
            ),
            PriceInput(
                observation_key="p-mid",
                target=Target(kind="item", key="burger"),
                applicability_key="mid",
                price_kind="absolute",
                price_state="priced",
                amount_minor=1100,
                currency_code="USD",
                confidence=Decimal("1"),
                evidence_ids=ev,
            ),
            PriceInput(
                observation_key="p-later",
                target=Target(kind="item", key="burger"),
                applicability_key="later",
                price_kind="absolute",
                price_state="priced",
                amount_minor=1200,
                currency_code="USD",
                confidence=Decimal("1"),
                evidence_ids=ev,
            ),
        ),
    )
    _commit(world, page)

    # Two different declared windows intersect the section to the same effective
    # [11:00,14:00); they compete, and the [12:00,14:00) contender stays separate.
    lunch_window = ContextRef("dine_in", "lunch", _t(11, 0), _t(14, 0))
    compete = _select(world, _est_request(world.a, context=lunch_window, instant=_t(12, 0)))
    assert compete.local_price.amount_minor in {1000, 1100}

    late_window = ContextRef("dine_in", "lunch", _t(12, 0), _t(14, 0))
    distinct = _select(world, _est_request(world.a, context=late_window, instant=_t(12, 30)))
    assert distinct.local_price.amount_minor == 1200

    # E at the half-open end is excluded; nothing matches, no older price shown.
    at_end = _select(world, _est_request(world.a, context=lunch_window, instant=_t(14, 0)))
    assert at_end.local_price.state == "absent"


def test_variant_price_is_selected_by_its_native_path(world: World) -> None:
    scope = ScopeFixture(world.org.req, world.a.req, world.place_a, world.org.v1, world.a.v1)
    value = aggregate(scope)
    variant = VariantInput(
        variant_key="large",
        item_key="burger",
        label="Large",
        position=0,
        effect="replace",
        support_kind="direct",
        evidence_ids=(world.a.v1.evidence_id,),
        source_native_key="v-large",
    )
    variant_price = PriceInput(
        observation_key="v-price",
        target=Target(kind="variant", key="large", item_key="burger"),
        applicability_key="lunch",
        price_kind="absolute",
        price_state="priced",
        amount_minor=1500,
        currency_code="USD",
        confidence=Decimal("1"),
        evidence_ids=(world.a.v1.evidence_id,),
    )
    _commit(world, replace(value, variants=(variant,), prices=(*value.prices, variant_price)))

    request = replace(
        _est_request(world.a),
        target=TargetRef(
            kind="variant",
            native_path=(("section", "s-food"), ("item", "i-burger"), ("variant", "v-large")),
        ),
    )
    result = _select(world, request)

    assert result.local_price.amount_minor == 1500
    assert result.content is not None and result.content.name == "Large"


def test_pending_lineage_withholds_the_current_value(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))

    # A Subject change is applied by a deferred trigger at commit, so an
    # unapplied pending change is only observable inside its own transaction.
    with world.factory() as session:
        pending_change(session, world.a.subject_id, "establishment")
        current = select_price(session, _est_request(world.a))
        session.rollback()
    assert current.local_price.state == "unresolved_scope"

    # The accepted claim is still readable as history once the change is gone.
    historical = _select(
        world, _est_request(world.a, knowledge_cutoff=_accepted_at(world, a1.page_id))
    )
    assert historical.local_price.amount_minor == 1050


def test_currency_mismatch_yields_no_local_price(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))

    request = replace(_est_request(world.a), currency_code="EUR")
    result = _select(world, request)

    assert result.local_price.state == "absent"


def test_observation_cutoff_filters_head_without_reviving_predecessor(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    a1 = _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))

    # Head A1 was observed at 09:10; O=09:00 filters it and no older claim exists.
    result = _select(
        world,
        _est_request(
            world.a,
            knowledge_cutoff=_accepted_at(world, a1.page_id),
            observation_cutoff=_t(9, 0),
        ),
    )
    assert result.content is None
    assert result.local_price.state == "absent"


def test_native_correspondence_is_required(world: World) -> None:
    o1 = _commit(world, _org_page(world, world.org.v1, amount=900))
    _commit(world, _local_page(world, world.a, world.place_a, world.a.v1, o1, amount=1050))
    # A native-path target that no node carries has no stable correspondence.
    mismatched = replace(
        _est_request(world.a),
        target=TargetRef(kind="item", native_path=(("section", "s-food"), ("item", "i-fries"))),
    )

    result = _select(world, mismatched)

    assert result.content is None
    assert result.local_price.state == "absent"
