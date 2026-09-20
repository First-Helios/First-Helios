"""Gold current-menu refresh: selector fidelity, deterministic rebuild, idempotence.

The refresh reuses the accepted Menu selector, so these tests assert that the
materialized row equals ``select_price``'s result and that a full rebuild (delete
Gold, refresh) reproduces identical business columns without touching Bronze,
Identity or Menu (ADR-0006; Plan 0002 §8 Gold rebuildability). All rows are
committed to disposable ``*_test`` PostgreSQL; nothing writes application data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    TargetRef,
    select_price,
)
from packages.helios_core.gold import refresh_current_menu
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
        source_namespace=f"gold-{token}",
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


def _business(session: Session, request: SelectionRequest) -> list[dict[str, object]]:
    """Business columns for one family only -- the disposable DB is shared, so
    tests must not read another test's committed rows.
    """
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
def world(
    disposable_database_engine: Engine,
) -> Iterator[tuple[sessionmaker[Session], SelectionRequest]]:
    """A committed open Establishment with one priced burger and its request."""
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    token = uuid4().hex
    with factory.begin() as session:
        # Mirror the accepted seed: the Organization carries source-key features
        # before the Establishment is marked eligible; only operating_status is
        # "open" so the current-mode selector returns a live value.
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
            operating_status="open",
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
        scope = ScopeFixture(
            organization=ResolvedScopeRequest(org.id, shared.source_record_id, org_event.id),
            establishment=ResolvedScopeRequest(establishment.id, local.source_record_id, event.id),
            place_id=place.id,
            shared_input=shared,
            local_input=local,
        )
        establishment_id = establishment.id
    # Menu admission consumes already committed Bronze/resolution input, so the
    # page is written in a second, separate transaction.
    with factory.begin() as session:
        persist_menu(session, aggregate(scope))
    request = SelectionRequest(
        subject_id=establishment_id,
        subject_kind="establishment",
        source_record_id=local.source_record_id,
        root_key="main",
        target=TARGET,
        context=LUNCH,
        currency_code="USD",
        effective_instant=E,
    )
    yield factory, request


def test_refresh_materializes_the_selector_result(
    world: tuple[sessionmaker[Session], SelectionRequest],
) -> None:
    factory, request = world
    with factory.begin() as session:
        assert refresh_current_menu(session, [request]) == 1
    with factory() as session:
        selection = select_price(session, request)
        rows = _business(session, request)
    assert len(rows) == 1
    row = rows[0]
    assert selection.local_price.state == "priced"
    assert row["price_state"] == "priced"
    assert row["amount_minor"] == selection.local_price.amount_minor == 1050
    assert row["currency_code"] == "USD"
    assert row["target_kind"] == "item"
    assert row["target_path"] == '[["section","s-food"],["item","i-burger"]]'
    assert row["channel"] == "dine_in"
    assert row["service_period"] == "lunch"
    assert row["subject_id"] == request.subject_id
    assert row["content_scope"] == "local"
    assert row["content_name"] == "Burger"
    assert row["price_evidence_ids"] == list(selection.local_price.evidence_ids)
    assert row["organization_claim_count"] == 0
    assert row["staleness_seconds"] == int((E - OBSERVED).total_seconds())


def test_full_rebuild_reproduces_business_columns(
    world: tuple[sessionmaker[Session], SelectionRequest],
) -> None:
    factory, request = world
    with factory.begin() as session:
        refresh_current_menu(session, [request])
    with factory() as session:
        before = _business(session, request)
    assert before  # at least one materialized row

    # Losing the projection and rebuilding must reproduce identical business
    # columns (refreshed_at excluded), without any source-layer change.
    with factory.begin() as session:
        session.execute(
            delete(CurrentMenu).where(
                CurrentMenu.subject_id == request.subject_id,
                CurrentMenu.source_record_id == request.source_record_id,
            )
        )
    with factory() as session:
        assert _business(session, request) == []
    with factory.begin() as session:
        refresh_current_menu(session, [request])
    with factory() as session:
        assert _business(session, request) == before


def test_refresh_is_idempotent(
    world: tuple[sessionmaker[Session], SelectionRequest],
) -> None:
    factory, request = world
    with factory.begin() as session:
        refresh_current_menu(session, [request])
    with factory() as session:
        first = _business(session, request)
    # Re-running clears the family and re-inserts; business columns are stable
    # and no duplicate row accumulates.
    with factory.begin() as session:
        assert refresh_current_menu(session, [request]) == 1
    with factory() as session:
        again = _business(session, request)
    assert again == first
    assert len(again) == 1
