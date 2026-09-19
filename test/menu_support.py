"""Committed, disposable Menu fixtures; no application data."""

from __future__ import annotations

from dataclasses import asdict, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, text

from packages.helios_core.domains.menu.contracts import (
    ApplicabilityInput,
    ItemInput,
    MenuAggregate,
    PageInput,
    PriceInput,
    SectionInput,
    Target,
)
from packages.helios_core.domains.menu.models import EvidenceLink, MenuPage
from packages.helios_core.provenance.contracts import get_record_version

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from test.provider_support import ScopeFixture

HEAD = "d83f0a21c592"
PARENT = "b72e6a90c431"


def aggregate(fixture: ScopeFixture, *, shared: bool = False, root: str = "main") -> MenuAggregate:
    request = fixture.organization if shared else fixture.establishment
    source = fixture.shared_input if shared else fixture.local_input
    evidence = (source.evidence_id,)
    return MenuAggregate(
        page=PageInput(
            subject_id=request.subject_id,
            subject_kind="organization" if shared else "establishment",
            source_record_version_id=source.source_record_version_id,
            resolution_event_id=request.resolution_event_id,
            root_key=root,
            source_kind="dom",
            method="menu-fixture",
            method_version="1",
            stream_revision=1,
            interpretation_revision=1,
            confidence=Decimal("1"),
            operation="initial",
            evidence_ids=evidence,
        ),
        sections=(
            SectionInput(
                section_key="food",
                name="Food",
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
                source_native_key="s-food",
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
                evidence_ids=evidence,
                source_native_key="i-burger",
            ),
        ),
        applicability=(
            ApplicabilityInput(
                applicability_key="lunch",
                channel="dine_in",
                service_period="lunch",
                evidence_ids=evidence,
            ),
        ),
        prices=(
            PriceInput(
                observation_key="burger-price",
                target=Target(kind="item", key="burger"),
                applicability_key="lunch",
                price_kind="absolute",
                price_state="priced",
                amount_minor=1050,
                currency_code="USD",
                confidence=Decimal("1"),
                evidence_ids=evidence,
            ),
        ),
    )


def raw_page(session: Session, value: MenuAggregate, **overrides: Any) -> int:
    p = value.page
    version = get_record_version(session, p.source_record_version_id)
    data = asdict(p)
    data.pop("evidence_ids")
    data.update(
        source_record_id=version.source_record_id,
        observed_at=version.observed_at,
        state="withdrawn" if p.operation == "withdrawal" else "published",
    )
    data.update(overrides)
    return session.execute(insert(MenuPage).values(**data).returning(MenuPage.id)).scalar_one()


def raw_page_support(session: Session, page: int, evidence: int) -> None:
    session.execute(
        insert(EvidenceLink).values(page_id=page, page_target=True, evidence_id=evidence)
    )


def force(session: Session) -> None:
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def successor(value: MenuAggregate, predecessor: int, **changes: Any) -> MenuAggregate:
    return replace(
        value,
        page=replace(
            value.page,
            operation="correction",
            supersedes_page_id=predecessor,
            stream_revision=value.page.stream_revision + 1,
            interpretation_revision=value.page.interpretation_revision + 1,
            **changes,
        ),
    )


def inherited(local: MenuAggregate, base: Any) -> MenuAggregate:
    section = next(m.id for m in base.members if m.table == "menu_section" and m.key == ("food",))
    item = next(m.id for m in base.members if m.table == "menu_item" and m.key == ("burger",))
    return replace(
        local,
        page=replace(local.page, base_organization_page_id=base.page_id),
        sections=(
            SectionInput(
                section_key="food",
                effect="inherit",
                support_kind="inherited",
                base_section_id=section,
            ),
        ),
        items=(
            ItemInput(
                item_key="burger",
                section_key="food",
                effect="inherit",
                support_kind="inherited",
                base_item_id=item,
            ),
        ),
    )
