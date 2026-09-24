"""Full-catalog Gold refresh: enumeration, current eligibility, rebuild, idempotence.

The full-catalog refresh enumerates the current priced catalog from Identity +
Menu (ADR-0006 deferred follow-up) and reuses the accepted selector, so these
tests assert that an eligible operating scope is materialized to equal
``select_price``, that a not-operating scope is excluded (ADR-0004 §5), that a
whole-catalog rebuild reproduces identical business columns without touching the
source layers (Plan 0002 §8 / scenario A11), and that re-running is idempotent.
Identity corrections (retire, remap, pending lineage) must neither break the
rebuild nor leak a predecessor's facts into the current catalog, reads take no
write locks, and the bounded refresh replaces whole scopes.
The shared disposable database also holds other suites' committed families
(including remapped and retired ones), so assertions read only this test's own
seeded rows; enumeration over the whole catalog is exercised too.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import sessionmaker

from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.enumeration import enumerate_current_requests
from packages.helios_core.domains.menu.models import MenuPage, PriceObservation
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    TargetRef,
    select_price,
)
from packages.helios_core.gold import refresh_current_menu
from packages.helios_core.gold.catalog import refresh_full_catalog
from packages.helios_core.gold.models import CurrentMenu
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
    persist_source_record_observation,
)
from test.menu_support import aggregate, inherited
from test.provider_support import (
    ScopeFixture,
    decision,
    held_write_locks,
    migrate,
    pending_change,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

TARGET = TargetRef(kind="item", native_path=(("section", "s-food"), ("item", "i-burger")))
LUNCH = ContextRef(channel="dine_in", service_period="lunch")
E = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

_BUSINESS_EXCLUDE = {"id", "refreshed_at"}


def _observation(token: str) -> BronzeObservation:
    return BronzeObservation(
        source_namespace=f"catalog-{token}",
        source_kind="fixture",
        external_key=token,
        observed_at=OBSERVED,
        content_hash=f"sha256:{token}",
        source_payload={"id": token},
        evidence_locator="$.id",
        evidence_excerpt_hash=f"sha256:ev:{token}",
        canonical_url=f"https://{token}.example.test/menu",
        capture_content_hash=f"sha256:cap:{token}",
        bundle_path=f"fixture/{token}",
    )


def _seed_scope(session: Session, token: str, operating_status: str) -> ScopeFixture:
    """Mirror the accepted seed: an eligible Establishment under an Organization
    whose ``operating_status`` is the caller's, committed for a later refresh.
    """
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
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        operating_status=operating_status,
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
        organization=ResolvedScopeRequest(org.id, shared.source_record_id, org_event.id),
        establishment=ResolvedScopeRequest(establishment.id, local.source_record_id, event.id),
        place_id=place.id,
        shared_input=shared,
        local_input=local,
    )


def _request(scope: ScopeFixture) -> SelectionRequest:
    return SelectionRequest(
        subject_id=scope.establishment.subject_id,
        subject_kind="establishment",
        source_record_id=scope.local_input.source_record_id,
        root_key="main",
        target=TARGET,
        context=LUNCH,
        currency_code="USD",
        effective_instant=E,
    )


def _business(session: Session, request: SelectionRequest) -> list[dict[str, object]]:
    """Business columns for one family only -- the disposable DB is shared."""
    rows = session.scalars(
        select(CurrentMenu)
        .where(
            CurrentMenu.subject_id == request.subject_id,
            CurrentMenu.source_record_id == request.source_record_id,
        )
        .order_by(CurrentMenu.subject_id, CurrentMenu.target_path)
    ).all()
    return [
        {
            column.key: getattr(row, column.key)
            for column in CurrentMenu.__table__.columns
            if column.key not in _BUSINESS_EXCLUDE
        }
        for row in rows
    ]


@pytest.fixture
def factory(disposable_database_engine: Engine) -> sessionmaker[Session]:
    migrate("upgrade", "head")
    return sessionmaker(disposable_database_engine, expire_on_commit=False)


def _committed_scope(
    factory: sessionmaker[Session], token: str, *, shared: bool = False
) -> ScopeFixture:
    """An open eligible scope with a committed priced burger page (and, with
    ``shared``, a priced Organization page too), ready for a refresh.
    """
    with factory.begin() as session:
        scope = _seed_scope(session, token, "open")
    with factory.begin() as session:
        persist_menu(session, aggregate(scope))
        if shared:
            persist_menu(session, aggregate(scope, shared=True))
    return scope


def _family_rows(session: Session, scope: ScopeFixture) -> list[CurrentMenu]:
    """Every Gold row of the scope's local family, whichever subject it names."""
    return list(
        session.scalars(
            select(CurrentMenu).where(
                CurrentMenu.source_record_id == scope.local_input.source_record_id
            )
        )
    )


def _remap(session: Session, scope: ScopeFixture, from_id: int, to_id: int) -> int:
    return remap_source_record(
        session,
        source_record_id=scope.local_input.source_record_id,
        from_subject_id=from_id,
        to_subject_id=to_id,
        decision=decision(),
        evidence_ids=(scope.local_input.evidence_id,),
    ).id


def _retire(session: Session, scope: ScopeFixture) -> None:
    record_subject_change(
        session,
        operation="retire",
        input_subject_ids=[scope.establishment.subject_id],
        output_subject_ids=[],
        decision=decision(),
        evidence_ids=(scope.local_input.evidence_id,),
    )


@pytest.fixture
def catalog(
    factory: sessionmaker[Session],
) -> Iterator[tuple[sessionmaker[Session], SelectionRequest, SelectionRequest]]:
    """A committed open Establishment and a committed closed one, each with a
    priced burger, plus their requests (open is current, closed is excluded).
    """
    token = uuid4().hex
    with factory.begin() as session:
        open_scope = _seed_scope(session, f"{token}-open", "open")
        closed_scope = _seed_scope(session, f"{token}-closed", "closed")
    with factory.begin() as session:
        persist_menu(session, aggregate(open_scope))
        persist_menu(session, aggregate(closed_scope))
    yield factory, _request(open_scope), _request(closed_scope)


def test_full_catalog_materializes_open_scope_and_excludes_closed(
    catalog: tuple[sessionmaker[Session], SelectionRequest, SelectionRequest],
) -> None:
    factory, open_request, closed_request = catalog
    with factory.begin() as session:
        written = refresh_full_catalog(session, effective_instant=E)
    assert written >= 1  # at least the open scope; the shared DB may hold more
    with factory() as session:
        open_rows = _business(session, open_request)
        closed_rows = _business(session, closed_request)
        selection = select_price(session, open_request)
    # The current, operating scope is materialized exactly as the selector says.
    assert len(open_rows) == 1
    row = open_rows[0]
    assert selection.local_price.state == "priced"
    assert row["price_state"] == "priced"
    assert row["amount_minor"] == selection.local_price.amount_minor == 1050
    assert row["currency_code"] == "USD"
    assert row["target_kind"] == "item"
    assert row["target_path"] == '[["section","s-food"],["item","i-burger"]]'
    assert row["channel"] == "dine_in"
    assert row["service_period"] == "lunch"
    assert row["content_name"] == "Burger"
    assert row["staleness_seconds"] == int((E - OBSERVED).total_seconds())
    # The not-operating scope is excluded from the current catalog (ADR-0004 §5).
    assert closed_rows == []


def test_full_catalog_enumeration_is_deterministic_and_scoped(
    catalog: tuple[sessionmaker[Session], SelectionRequest, SelectionRequest],
) -> None:
    factory, open_request, closed_request = catalog
    with factory() as session:
        first = enumerate_current_requests(session, effective_instant=E)
        second = enumerate_current_requests(session, effective_instant=E)
    assert first == second  # deterministic function of committed sources
    grains = {
        (r.subject_id, r.source_record_id, r.target, r.context, r.currency_code) for r in first
    }
    assert (
        open_request.subject_id,
        open_request.source_record_id,
        open_request.target,
        open_request.context,
        open_request.currency_code,
    ) in grains
    # The closed scope contributes no request at all.
    assert not any(r.subject_id == closed_request.subject_id for r in first)


def test_full_catalog_rebuild_reproduces_business_columns(
    catalog: tuple[sessionmaker[Session], SelectionRequest, SelectionRequest],
) -> None:
    factory, open_request, _ = catalog
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        before = _business(session, open_request)
        source_counts_before = _source_counts(session, open_request)
    assert before

    # Losing the whole projection and rebuilding must reproduce identical
    # business columns without any source-layer change (A11 / Plan §8).
    with factory.begin() as session:
        session.execute(delete(CurrentMenu))
    with factory() as session:
        assert _business(session, open_request) == []
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        assert _business(session, open_request) == before
        assert _source_counts(session, open_request) == source_counts_before


def test_full_catalog_refresh_is_idempotent(
    catalog: tuple[sessionmaker[Session], SelectionRequest, SelectionRequest],
) -> None:
    factory, open_request, _ = catalog
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        first = _business(session, open_request)
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        again = _business(session, open_request)
    assert again == first
    assert len(again) == 1  # no duplicate grain accumulates


def _source_counts(session: Session, request: SelectionRequest) -> tuple[int, int]:
    """Menu-page and price-observation counts for one family; must not change."""
    pages = session.scalar(
        select(func.count())
        .select_from(MenuPage)
        .where(MenuPage.source_record_id == request.source_record_id)
    )
    prices = session.scalar(
        select(func.count())
        .select_from(PriceObservation)
        .join(MenuPage, MenuPage.id == PriceObservation.page_id)
        .where(MenuPage.source_record_id == request.source_record_id)
    )
    return (pages or 0, prices or 0)


@pytest.mark.parametrize("correction", ["retire", "remap", "pending"])
def test_full_catalog_survives_identity_corrections(
    factory: sessionmaker[Session], correction: Literal["retire", "remap", "pending"]
) -> None:
    token = uuid4().hex
    scope = _committed_scope(factory, f"{token}-a")
    successor = _committed_scope(factory, f"{token}-b")
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        assert len(_family_rows(session, scope)) == 1

    if correction == "retire":
        with factory.begin() as session:
            _retire(session, scope)
    elif correction == "remap":
        with factory.begin() as session:
            _remap(
                session, scope, scope.establishment.subject_id, successor.establishment.subject_id
            )
    with factory() as session:
        if correction == "pending":
            # Unapplied lineage is only visible inside its own transaction.
            pending_change(session, scope.establishment.subject_id, "establishment")
        # The rebuild must not abort on the non-live scope (R01), and the
        # corrected family leaves the current catalog under every subject:
        # neither the predecessor nor the successor keeps or inherits its price.
        refresh_full_catalog(session, effective_instant=E)
        family = _family_rows(session, scope)
        successor_rows = _business(session, _request(successor))
        if correction == "pending":
            session.rollback()
        else:
            session.commit()
    assert family == []
    assert len(successor_rows) == 1
    assert successor_rows[0]["price_state"] == "priced"


def test_successor_never_selects_a_remapped_predecessors_price(
    factory: sessionmaker[Session],
) -> None:
    token = uuid4().hex
    scope = _committed_scope(factory, f"{token}-a")
    successor = _committed_scope(factory, f"{token}-b")
    with factory.begin() as session:
        _remap(session, scope, scope.establishment.subject_id, successor.establishment.subject_id)
    predecessor_request = _request(scope)
    successor_request = replace(predecessor_request, subject_id=successor.establishment.subject_id)

    with factory() as session:
        selection = select_price(session, successor_request)
    # The successor owns no page in this family yet, so it has no local value;
    # it must never see the remapped predecessor's price or content (ADR-0004 §5).
    assert selection.local_price.state == "absent"
    assert selection.local_price.scope_subject_id == successor.establishment.subject_id
    assert selection.content is None

    # The bounded refresh records both answers without aborting (R01).
    with factory.begin() as session:
        assert refresh_current_menu(session, [predecessor_request, successor_request]) == 2
    with factory() as session:
        (stale,) = _business(session, predecessor_request)
        (fresh,) = _business(session, successor_request)
    assert stale["price_state"] == "unresolved_scope"
    assert stale["amount_minor"] is None
    assert fresh["price_state"] == "absent"
    assert fresh["amount_minor"] is None
    assert fresh["price_scope_subject_id"] == successor.establishment.subject_id


def test_gate_checks_every_head_the_subject_owns(factory: sessionmaker[Session]) -> None:
    token = uuid4().hex
    scope = _committed_scope(factory, f"{token}-a")  # dom head under the first event
    successor = _committed_scope(factory, f"{token}-b")
    subject_id = scope.establishment.subject_id
    with factory.begin() as session:
        _remap(session, scope, subject_id, successor.establishment.subject_id)
    with factory.begin() as session:
        back = _remap(session, scope, successor.establishment.subject_id, subject_id)
    rescoped = replace(
        scope,
        establishment=ResolvedScopeRequest(subject_id, scope.local_input.source_record_id, back),
    )
    value = aggregate(rescoped)
    with factory.begin() as session:
        persist_menu(session, replace(value, page=replace(value.page, source_kind="jsonld")))

    # Two heads of one subject under different events: the jsonld head's
    # mapping is live, the dom head's is stale. Selector and enumeration both
    # check every head, so the answer never depends on row or query-plan order.
    with factory() as session:
        selection = select_price(session, _request(scope))
        requests = enumerate_current_requests(session, effective_instant=E)
    assert selection.local_price.state == "unresolved_scope"
    assert not any(r.source_record_id == scope.local_input.source_record_id for r in requests)


def test_bounded_refresh_replaces_every_row_of_each_requested_scope(
    factory: sessionmaker[Session],
) -> None:
    token = uuid4().hex
    scope = _committed_scope(factory, f"{token}-a")
    other = _committed_scope(factory, f"{token}-b")
    request, other_request = _request(scope), _request(other)
    with factory.begin() as session:
        assert refresh_current_menu(session, [request, other_request]) == 2
    with factory.begin() as session:
        _retire(session, scope)

    # The retired scope yields no request any more; naming it still clears its
    # stale rows, so bounded(S) matches the full catalog for S (R20).
    with factory.begin() as session:
        requests = [
            r
            for r in enumerate_current_requests(session, effective_instant=E)
            if r.subject_id == scope.establishment.subject_id
        ]
        assert requests == []
        written = refresh_current_menu(
            session, requests, subject_ids=[scope.establishment.subject_id]
        )
    assert written == 0
    with factory() as session:
        assert _business(session, request) == []
        assert len(_business(session, other_request)) == 1  # unrequested scope untouched


@pytest.mark.parametrize("cutoff", ["knowledge_cutoff", "observation_cutoff"])
def test_bounded_refresh_rejects_cutoff_requests(
    catalog: tuple[sessionmaker[Session], SelectionRequest, SelectionRequest], cutoff: str
) -> None:
    factory, open_request, _ = catalog
    rejected = (
        replace(open_request, knowledge_cutoff=E)
        if cutoff == "knowledge_cutoff"
        else replace(open_request, observation_cutoff=E)
    )
    with factory.begin() as session:
        refresh_current_menu(session, [open_request])
    with factory.begin() as session, pytest.raises(ValueError, match="current answers only"):
        refresh_current_menu(session, [open_request, rejected])
    with factory() as session:
        assert len(_business(session, open_request)) == 1  # rejected before any delete


def test_full_catalog_materializes_organization_scoped_rows(
    factory: sessionmaker[Session],
) -> None:
    scope = _committed_scope(factory, uuid4().hex, shared=True)
    org_request = SelectionRequest(
        subject_id=scope.organization.subject_id,
        subject_kind="organization",
        source_record_id=scope.shared_input.source_record_id,
        root_key="main",
        target=TARGET,
        context=LUNCH,
        currency_code="USD",
        effective_instant=E,
    )
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        rows = _business(session, org_request)
        selection = select_price(session, org_request)
    assert len(rows) == 1
    row = rows[0]
    assert row["subject_kind"] == "organization"
    assert row["price_state"] == "priced"
    assert row["amount_minor"] == selection.local_price.amount_minor == 1050
    assert row["price_scope_subject_id"] == scope.organization.subject_id
    assert row["content_scope"] == "local"


def test_full_catalog_keys_inherited_prices_by_their_pinned_base(
    factory: sessionmaker[Session],
) -> None:
    # R22: a local price riding a pinned base is enumerated under the base-scoped
    # target, and the selector resolves that same target (no silent ``absent``).
    with factory.begin() as session:
        scope = _seed_scope(session, uuid4().hex, "open")
    with factory.begin() as session:
        base = persist_menu(session, aggregate(scope, shared=True))
    with factory.begin() as session:  # a pin must name a committed base
        persist_menu(session, inherited(aggregate(scope), base))
    with factory.begin() as session:
        refresh_full_catalog(session, effective_instant=E)
    with factory() as session:
        rows = _business(session, _request(scope))
    assert len(rows) == 1
    row = rows[0]
    assert row["target_path"] == (
        f'[["base","{base.page_id}"],["section","s-food"],["item","i-burger"]]'
    )
    assert (row["price_state"], row["amount_minor"]) == ("priced", 1050)
    assert (row["content_scope"], row["content_page_id"]) == ("organization", base.page_id)


def test_selection_and_enumeration_take_no_write_locks(
    catalog: tuple[sessionmaker[Session], SelectionRequest, SelectionRequest],
) -> None:
    factory, open_request, closed_request = catalog
    with factory() as session:
        # Reads must work in a READ ONLY transaction and must not hold the
        # Identity writer's row or advisory locks (R21).
        session.execute(text("SET TRANSACTION READ ONLY"))
        requests = enumerate_current_requests(session, effective_instant=E)
        assert select_price(session, open_request).local_price.state == "priced"
        assert select_price(session, closed_request).local_price.state == "not_operating"
        assert held_write_locks(session) == []
    assert any(r.subject_id == open_request.subject_id for r in requests)
