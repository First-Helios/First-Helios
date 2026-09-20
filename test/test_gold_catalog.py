"""Full-catalog Gold refresh: enumeration, current eligibility, rebuild, idempotence.

The full-catalog refresh enumerates the current priced catalog from Identity +
Menu (ADR-0006 deferred follow-up) and reuses the accepted selector, so these
tests assert that an eligible operating scope is materialized to equal
``select_price``, that a not-operating scope is excluded (ADR-0004 §5), that a
whole-catalog rebuild reproduces identical business columns without touching the
source layers (Plan 0002 §8 / scenario A11), and that re-running is idempotent.
The shared disposable database also holds other suites' committed families, so
per-scope assertions filter by family and the rebuild compares the family's own
rows before and after; enumeration over the whole catalog is exercised too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
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
from packages.helios_core.gold.catalog import refresh_full_catalog
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
    persist_source_record_observation,
)
from test.menu_support import aggregate
from test.provider_support import ScopeFixture, decision, migrate

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
def catalog(
    disposable_database_engine: Engine,
) -> Iterator[tuple[sessionmaker[Session], SelectionRequest, SelectionRequest]]:
    """A committed open Establishment and a committed closed one, each with a
    priced burger, plus their requests (open is current, closed is excluded).
    """
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
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
