"""Raw SQL and Python integrity, forced deferred checks and real commits."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError

from packages.helios_core.domains.menu.commands import persist_menu, read_aggregate
from packages.helios_core.domains.menu.contracts import (
    ItemInput,
    MenuAggregate,
    ModifierInput,
    SectionInput,
    Target,
    VariantInput,
)
from packages.helios_core.domains.menu.models import (
    EvidenceLink,
    MenuApplicability,
    MenuItem,
    MenuModifier,
    MenuSection,
    MenuVariant,
    PriceObservation,
)
from packages.helios_core.identity import SubjectChangeMember, SubjectNotEligibleError
from packages.helios_core.provenance import Evidence, SourceRecordVersion
from test.menu_support import aggregate, force, inherited, raw_page, raw_page_support
from test.provider_support import pending_change
from test.test_menu_replay import menu_scopes as menu_scopes
from test.test_provider_concurrency import mutate

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from test.provider_support import ScopeFixture


def rejected(error: pytest.ExceptionInfo[DBAPIError], constraint: str | None = None) -> None:
    assert getattr(error.value.orig, "sqlstate", None) in {
        "23514",
        "23503",
        "23505",
        "23502",
        "22P02",
        "22003",
    }
    if constraint:
        assert error.value.orig.diag.constraint_name == constraint  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "change",
    [
        "readiness",
        "parent_readiness",
        "parent_feature",
        "organization_feature",
        "unassign",
        "remap",
        "retire",
        "parent_retire",
        "split",
        "merge",
    ],
)
@pytest.mark.parametrize("raw", [False, True])
def test_scope_rejected_at_insert(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], change: str, raw: bool
) -> None:
    factory, scope = menu_scopes
    with factory.begin() as writer:
        mutate(writer, scope, change)
    with factory() as writer, pytest.raises((DBAPIError, SubjectNotEligibleError)):
        (raw_page if raw else persist_menu)(writer, aggregate(scope))


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_kind": "place"},
        {"subject_kind": None},
        {"subject_id": None},
        {"subject_kind": "organization"},
        {"resolution_event_id": 9223372036854775807},
        {"observed_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"created_transaction_id": 1},
        {"accepted_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
)
def test_forged_page_rejected(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], overrides: dict[str, Any]
) -> None:
    factory, scope = menu_scopes
    with factory() as writer, pytest.raises(DBAPIError):
        raw_page(writer, aggregate(scope), **overrides)


@pytest.mark.parametrize("boundary", ["forced", "commit"])
@pytest.mark.parametrize(
    "missing", ["page", "section", "item", "applicability", "price", "variant", "modifier"]
)
def test_missing_support_fails_outer_boundary(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], boundary: str, missing: str
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory() as writer:
        page = raw_page(writer, value)
        if missing != "page":
            raw_page_support(writer, page, scope.local_input.evidence_id)
        section = writer.execute(
            insert(MenuSection)
            .values(
                page_id=page,
                section_key="food",
                name="Food",
                position=0,
                effect="replace",
                support_kind="direct",
            )
            .returning(MenuSection.id)
        ).scalar_one()
        item = writer.execute(
            insert(MenuItem)
            .values(
                page_id=page,
                section_id=section,
                item_key="burger",
                name="Burger",
                position=0,
                dietary_tags=[],
                effect="replace",
                support_kind="direct",
            )
            .returning(MenuItem.id)
        ).scalar_one()
        app = writer.execute(
            insert(MenuApplicability)
            .values(page_id=page, applicability_key="lunch", channel="dine_in")
            .returning(MenuApplicability.id)
        ).scalar_one()
        price = writer.execute(
            insert(PriceObservation)
            .values(
                page_id=page,
                observation_key="p",
                item_id=item,
                applicability_id=app,
                price_kind="absolute",
                price_state="priced",
                amount_minor=0,
                currency_code="USD",
                confidence=1,
            )
            .returning(PriceObservation.id)
        ).scalar_one()
        variant = writer.execute(
            insert(MenuVariant)
            .values(
                page_id=page,
                item_id=item,
                variant_key="v",
                label="Large",
                position=0,
                effect="replace",
                support_kind="direct",
            )
            .returning(MenuVariant.id)
        ).scalar_one()
        modifier = writer.execute(
            insert(MenuModifier)
            .values(
                page_id=page,
                item_id=item,
                modifier_key="m",
                label="Cheese",
                required=False,
                position=0,
                effect="replace",
                support_kind="direct",
            )
            .returning(MenuModifier.id)
        ).scalar_one()
        for kind, row_id in (
            ("section", section),
            ("item", item),
            ("applicability", app),
            ("price", price),
            ("variant", variant),
            ("modifier", modifier),
        ):
            if missing != kind:
                writer.execute(
                    insert(EvidenceLink).values(
                        page_id=page,
                        page_target=False,
                        evidence_id=scope.local_input.evidence_id,
                        **{kind + "_id": row_id},
                    )
                )
        with pytest.raises(DBAPIError) as error:
            force(writer) if boundary == "forced" else writer.commit()
        rejected(error, "ck_menu_support")
        writer.rollback()
    with factory() as reader:
        assert (
            reader.scalar(text("SELECT count(*) FROM menu.menu_page WHERE id=:id"), {"id": page})
            == 0
        )


@pytest.mark.parametrize(
    "table",
    [
        "currency",
        "menu_page",
        "menu_section",
        "menu_item",
        "menu_variant",
        "menu_modifier",
        "menu_applicability",
        "price_observation",
        "evidence_link",
    ],
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_every_table_is_immutable(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], table: str, operation: str
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    evidence = (scope.local_input.evidence_id,)
    value = replace(
        value,
        variants=(
            VariantInput(
                variant_key="large",
                item_key="burger",
                label="Large",
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
            ),
        ),
        modifiers=(
            ModifierInput(
                modifier_key="cheese",
                item_key="burger",
                label="Cheese",
                required=False,
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
            ),
        ),
    )
    with factory.begin() as writer:
        persist_menu(writer, value)
    key = "code" if table == "currency" else "id"
    statement = (
        f"UPDATE menu.{table} SET {key}={key}"
        if operation == "UPDATE"
        else f"{operation} {'FROM ' if operation == 'DELETE' else ''}menu.{table}"
    )
    with factory() as writer, pytest.raises(DBAPIError) as error:
        writer.execute(text(statement))
    # PostgreSQL can reject TRUNCATE of an FK provider before its trigger runs.
    assert getattr(error.value.orig, "sqlstate", None) in {"23514", "0A000"}


@pytest.mark.parametrize("kind", ["node", "link"])
def test_late_membership_rejected(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], kind: str
) -> None:
    factory, scope = menu_scopes
    with factory.begin() as writer:
        result = persist_menu(writer, aggregate(scope))
    with factory() as writer, pytest.raises(DBAPIError) as error:
        if kind == "link":
            raw_page_support(writer, result.page_id, scope.local_input.evidence_id)
        else:
            writer.execute(
                insert(MenuSection).values(
                    page_id=result.page_id,
                    section_key="late",
                    name="Late",
                    position=0,
                    effect="replace",
                    support_kind="direct",
                )
            )
    rejected(error, "ck_menu_member_transaction")


@pytest.mark.parametrize("target", ["self", "parent", "survivor"])
@pytest.mark.parametrize("apply", [False, True])
def test_pending_lineage_blocks_every_member(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], target: str, apply: bool
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        page = raw_page(writer, aggregate(scope))
        raw_page_support(writer, page, scope.local_input.evidence_id)
        subject = scope.place_id if target == "parent" else scope.establishment.subject_id
        kind = "place" if target == "parent" else "establishment"
        change = pending_change(
            writer, subject, kind, "merge" if target == "survivor" else "retire"
        )
        if target == "survivor":
            from packages.helios_core.identity import create_establishment

            other = create_establishment(
                writer,
                organization_subject_id=scope.organization.subject_id,
                place_subject_id=scope.place_id,
                valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            )
            writer.add_all(
                [
                    SubjectChangeMember(
                        subject_change_id=change.id,
                        subject_id=other.id,
                        subject_kind=kind,
                        role="input",
                    ),
                    SubjectChangeMember(
                        subject_change_id=change.id,
                        subject_id=subject,
                        subject_kind=kind,
                        role="output",
                    ),
                ]
            )
            writer.flush()
        if apply:
            force(writer)
        if target == "survivor" and apply:
            # Completed surviving merge keeps the exact scope eligible.
            assert raw_page(writer, aggregate(scope, root="after-merge"))
        else:
            with pytest.raises(DBAPIError) as error:
                writer.execute(
                    insert(MenuSection).values(
                        page_id=page,
                        section_key="late",
                        name="Late",
                        position=0,
                        effect="replace",
                        support_kind="direct",
                    )
                )
            rejected(error, "ck_resolved_scope_admission")


@pytest.mark.parametrize("change", ["remap", "retire", "parent_retire"])
def test_complete_acceptance_then_scope_change_commits_history(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], change: str
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as writer:
        result = persist_menu(writer, value)
        mutate(writer, scope, change)
        force(writer)
    with factory.begin() as reader:
        assert read_aggregate(reader, result.page_id)[0] == value
        assert persist_menu(reader, value).replayed


@pytest.mark.parametrize(
    "evidence_kind",
    ["capture", "wrong_version", "wrong_capture", "uncommitted", "uncommitted_savepoint"],
)
def test_evidence_exact_ownership_and_committed_input(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], evidence_kind: str
) -> None:
    factory, scope = menu_scopes
    with factory.begin() as setup:
        capture = Evidence(
            capture_id=scope.local_input.capture_id, locator="capture", excerpt_hash="hash"
        )
        wrong = Evidence(
            capture_id=scope.shared_input.capture_id, locator="wrong", excerpt_hash="hash"
        )
        setup.add_all([capture, wrong])
        setup.flush()
        evidence = (
            capture.id
            if evidence_kind == "capture"
            else wrong.id
            if evidence_kind == "wrong_capture"
            else scope.shared_input.evidence_id
        )
    with factory() as writer:
        if evidence_kind.startswith("uncommitted"):
            if evidence_kind.endswith("savepoint"):
                with writer.begin_nested():
                    pending = Evidence(
                        source_record_version_id=scope.local_input.source_record_version_id,
                        locator="pending",
                        excerpt_hash="hash",
                    )
                    writer.add(pending)
                    writer.flush()
            else:
                pending = Evidence(
                    source_record_version_id=scope.local_input.source_record_version_id,
                    locator="pending",
                    excerpt_hash="hash",
                )
                writer.add(pending)
                writer.flush()
            evidence = pending.id
        page = raw_page(writer, aggregate(scope))
        if evidence_kind == "capture":
            raw_page_support(writer, page, evidence)
            force(writer)
            writer.commit()
        else:
            with pytest.raises(DBAPIError) as error:
                raw_page_support(writer, page, evidence)
            rejected(error, "ck_menu_evidence")


def test_uncommitted_version_is_not_admissible(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        original = writer.get(SourceRecordVersion, scope.local_input.source_record_version_id)
        assert original
        with writer.begin_nested():
            version = SourceRecordVersion(
                source_record_id=original.source_record_id,
                source_id=original.source_id,
                observed_at=original.observed_at,
                content_hash="new",
                source_payload={},
            )
            writer.add(version)
            writer.flush()
        value = aggregate(scope)
        value = replace(value, page=replace(value.page, source_record_version_id=version.id))
        with pytest.raises(DBAPIError) as error:
            raw_page(writer, value)
        rejected(error, "ck_menu_version")


def test_structural_grouping_and_individual_modifiers(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    evidence = (scope.local_input.evidence_id,)
    value = replace(
        value,
        sections=(
            SectionInput(
                section_key="Unsectioned",
                name="Unsectioned",
                position=0,
                effect="replace",
                support_kind="structural",
            ),
        ),
        items=(replace(value.items[0], section_key="Unsectioned", source_native_key=None),),
        modifiers=(
            ModifierInput(
                modifier_key="remove",
                section_key="Unsectioned",
                label="Remove cheese",
                required=True,
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
            ),
        ),
        prices=(
            replace(
                value.prices[0],
                target=Target(kind="modifier", key="remove"),
                price_kind="delta",
                amount_minor=-125,
            ),
        ),
    )
    with factory.begin() as writer:
        result = persist_menu(writer, value)
        force(writer)
    with factory() as reader:
        assert read_aggregate(reader, result.page_id)[0] == value


@pytest.mark.parametrize(
    "defect",
    [
        "copied_payload",
        "wrong_parent",
        "duplicate_base",
        "suppressed_child",
        "suppressed_price",
        "native_path",
        "empty_structural",
        "structural_evidence",
    ],
)
def test_graph_shapes_and_base_correspondence(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], defect: str
) -> None:
    factory, scope = menu_scopes
    with factory.begin() as writer:
        base = persist_menu(writer, aggregate(scope, shared=True))
    value = inherited(aggregate(scope), base)
    evidence = (scope.local_input.evidence_id,)
    if defect == "copied_payload":
        value = replace(value, items=(replace(value.items[0], name="Copied"),))
    elif defect == "wrong_parent":
        value = replace(
            value,
            sections=value.sections
            + (
                SectionInput(
                    section_key="other",
                    name="Other",
                    position=1,
                    effect="replace",
                    support_kind="direct",
                    evidence_ids=evidence,
                ),
            ),
            items=(replace(value.items[0], section_key="other"),),
        )
    elif defect == "duplicate_base":
        value = replace(value, items=value.items + (replace(value.items[0], item_key="duplicate"),))
    elif defect == "suppressed_child":
        value = replace(
            value,
            sections=(
                replace(
                    value.sections[0],
                    effect="suppress",
                    support_kind="direct",
                    evidence_ids=evidence,
                ),
            ),
        )
    elif defect == "suppressed_price":
        value = replace(
            value,
            items=(
                replace(
                    value.items[0], effect="suppress", support_kind="direct", evidence_ids=evidence
                ),
            ),
        )
    elif defect == "native_path":
        value = aggregate(scope)
        value = replace(value, sections=(replace(value.sections[0], source_native_key=None),))
    else:
        value = MenuAggregate(
            page=value.page,
            sections=(
                SectionInput(
                    section_key="Unsectioned",
                    name="Unsectioned",
                    position=0,
                    effect="replace",
                    support_kind="structural",
                    evidence_ids=evidence if defect == "structural_evidence" else (),
                ),
            ),
        )
    with factory() as writer, pytest.raises(DBAPIError) as error:
        persist_menu(writer, value)
    rejected(error)


@pytest.mark.parametrize("case", ["cross_page", "cycle"])
def test_raw_graph_fails_deferred_boundary(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], case: str
) -> None:
    factory, scope = menu_scopes
    with factory.begin() as setup:
        base = persist_menu(setup, aggregate(scope, shared=True))
    with factory() as writer:
        page = raw_page(writer, aggregate(scope))
        raw_page_support(writer, page, scope.local_input.evidence_id)
        if case == "cycle":
            row = writer.execute(text("SELECT nextval('menu.menu_section_id_seq')")).scalar_one()
            writer.execute(
                insert(MenuSection).values(
                    id=row,
                    page_id=page,
                    section_key="cycle",
                    parent_section_id=row,
                    name="Cycle",
                    position=0,
                    effect="replace",
                    support_kind="direct",
                )
            )
        else:
            row = writer.execute(
                insert(MenuItem)
                .values(
                    page_id=page,
                    item_key="cross",
                    section_id=next(m.id for m in base.members if m.table == "menu_section"),
                    name="Cross",
                    position=0,
                    dietary_tags=[],
                    effect="replace",
                    support_kind="direct",
                )
                .returning(MenuItem.id)
            ).scalar_one()
        writer.execute(
            insert(EvidenceLink).values(
                page_id=page,
                page_target=False,
                evidence_id=scope.local_input.evidence_id,
                **{("section_id" if case == "cycle" else "item_id"): row},
            )
        )
        with pytest.raises(DBAPIError) as error:
            force(writer)
        rejected(error)


@pytest.mark.parametrize("amount", [1.5, True, Decimal("1"), 2**63])
def test_money_dto_never_coerces(amount: Any) -> None:
    # A standalone price contract needs no database.
    from packages.helios_core.domains.menu.contracts import PriceInput

    with pytest.raises(ValueError):
        PriceInput(
            observation_key="p",
            target=Target(kind="item", key="i"),
            applicability_key="c",
            price_kind="absolute",
            price_state="priced",
            amount_minor=amount,
            currency_code="USD",
            confidence=Decimal("1"),
            evidence_ids=(1,),
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"amount_minor": -1},
        {"price_state": "unknown"},
        {"price_state": "unavailable"},
        {"amount_minor": None},
        {"currency_code": "EUR"},
        {"currency_code": None},
        {"confidence": Decimal("NaN")},
        {"amount_minor": "1.5"},
        {"amount_minor": 2**63},
        {"price_kind": "delta"},
    ],
)
def test_raw_money_shape(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], patch: dict[str, Any]
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        result = persist_menu(writer, aggregate(scope))
        item = next(m.id for m in result.members if m.table == "menu_item")
        app = next(m.id for m in result.members if m.table == "menu_applicability")
        values = {
            "page_id": result.page_id,
            "observation_key": "bad",
            "item_id": item,
            "applicability_id": app,
            "price_kind": "absolute",
            "price_state": "priced",
            "amount_minor": 1,
            "currency_code": "USD",
            "confidence": 1,
        }
        values.update(patch)
        with pytest.raises(DBAPIError) as error:
            writer.execute(insert(PriceObservation).values(**values))
        rejected(error)


@pytest.mark.parametrize("conflict", ["channel", "period", "empty", "unspecified", "duplicate"])
@pytest.mark.parametrize("base_path", [False, True])
def test_context_intersects_full_ancestor_path(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], conflict: str, base_path: bool
) -> None:
    factory, scope = menu_scopes
    start = datetime(2026, 9, 17, 11, tzinfo=UTC)
    source = aggregate(scope, shared=base_path)
    source = replace(
        source,
        sections=(replace(source.sections[0], applicability_key="lunch"),),
        applicability=(
            replace(source.applicability[0], valid_from=start, valid_to=start + timedelta(hours=3)),
        ),
    )
    if base_path:
        with factory.begin() as setup:
            base = persist_menu(setup, source)
        value = inherited(aggregate(scope), base)
    else:
        value = source
    context = replace(
        value.applicability[0],
        applicability_key="price-context",
        valid_from=start,
        valid_to=start + timedelta(hours=3),
    )
    if conflict == "channel":
        context = replace(context, channel="takeaway")
    elif conflict == "period":
        context = replace(context, service_period="dinner")
    elif conflict == "empty":
        context = replace(context, valid_from=start + timedelta(hours=4), valid_to=None)
    elif conflict == "unspecified":
        context = replace(context, channel="unspecified")
    if conflict == "duplicate" and base_path:
        context = replace(context, valid_from=None, valid_to=None)
    value = replace(
        value,
        applicability=value.applicability + (context,),
        prices=(replace(value.prices[0], applicability_key="price-context"),),
    )
    with factory() as writer, pytest.raises(DBAPIError) as error:
        persist_menu(writer, value)
    rejected(error)


@pytest.mark.parametrize(
    "model",
    [
        MenuSection,
        MenuItem,
        MenuVariant,
        MenuModifier,
        MenuApplicability,
        PriceObservation,
        EvidenceLink,
    ],
)
def test_every_member_rechecks_live_scope(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], model: Any
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        result = persist_menu(writer, aggregate(scope))
        mutate(writer, scope, "remap")
        with pytest.raises(DBAPIError) as error:
            writer.execute(insert(model).values(page_id=result.page_id))
        rejected(error, "ck_resolved_scope_admission")


@pytest.mark.parametrize("state", ["unknown", "unavailable", "priced"])
def test_explicit_price_states_are_exact_claims(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], state: Any
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    value = replace(
        value,
        prices=(
            replace(
                value.prices[0], price_state=state, amount_minor=0 if state == "priced" else None
            ),
        ),
    )
    with factory.begin() as writer:
        result = persist_menu(writer, value)
        force(writer)
    with factory() as reader:
        assert read_aggregate(reader, result.page_id)[0] == value


def test_deep_graph_variant_and_mapped_full_replacement_clears_null(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    from test.menu_support import successor

    factory, scope = menu_scopes
    shared = aggregate(scope, shared=True)
    evidence = (scope.shared_input.evidence_id,)
    shared = replace(
        shared,
        sections=shared.sections
        + (
            SectionInput(
                section_key="nested",
                parent_section_key="food",
                name="Nested",
                source_native_key="nested",
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
            ),
        ),
        items=(replace(shared.items[0], section_key="nested"),),
        variants=(
            VariantInput(
                variant_key="large",
                item_key="burger",
                label="Large",
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
            ),
        ),
    )
    with factory.begin() as writer:
        base = persist_menu(writer, shared)
    by_key = {(m.table, m.key): m.id for m in base.members}
    evidence = (scope.local_input.evidence_id,)
    local = aggregate(scope)
    local = replace(
        local,
        page=replace(local.page, base_organization_page_id=base.page_id),
        sections=(
            SectionInput(
                section_key="food",
                effect="inherit",
                support_kind="inherited",
                base_section_id=by_key["menu_section", ("food",)],
            ),
            SectionInput(
                section_key="nested",
                parent_section_key="food",
                effect="inherit",
                support_kind="inherited",
                base_section_id=by_key["menu_section", ("nested",)],
            ),
        ),
        items=(
            replace(
                local.items[0],
                section_key="nested",
                description=None,
                base_item_id=by_key["menu_item", ("burger",)],
            ),
        ),
        variants=(
            VariantInput(
                variant_key="large",
                item_key="burger",
                effect="inherit",
                support_kind="inherited",
                base_variant_id=by_key["menu_variant", ("burger", "large")],
            ),
        ),
        prices=(
            replace(local.prices[0], target=Target(kind="variant", key="large", item_key="burger")),
        ),
    )
    with factory.begin() as writer:
        first = persist_menu(writer, local)
        force(writer)
    with factory() as reader:
        assert read_aggregate(reader, first.page_id)[0].items[0].description is None
    suppressed = replace(
        successor(local, first.page_id),
        items=(
            ItemInput(
                item_key="burger",
                section_key="nested",
                effect="suppress",
                support_kind="direct",
                base_item_id=by_key["menu_item", ("burger",)],
                evidence_ids=evidence,
            ),
        ),
        variants=(),
        prices=(),
        applicability=(),
    )
    with factory.begin() as writer:
        persist_menu(writer, suppressed)
        force(writer)


@pytest.mark.parametrize("defect", ["uncommitted", "other_operator"])
def test_pin_requires_committed_operator_base(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], defect: str
) -> None:
    from test.provider_support import seed_scope

    factory, scope = menu_scopes
    with factory.begin() as setup:
        other = seed_scope(setup)
    with factory() as writer:
        base = persist_menu(
            writer, aggregate(other if defect == "other_operator" else scope, shared=True)
        )
        if defect == "other_operator":
            writer.commit()
        with pytest.raises(DBAPIError) as error:
            persist_menu(writer, inherited(aggregate(scope), base))
        rejected(error, "ck_menu_base")


def test_complete_local_then_base_withdrawal_is_history(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    from test.menu_support import successor

    factory, scope = menu_scopes
    shared = aggregate(scope, shared=True)
    with factory.begin() as setup:
        base = persist_menu(setup, shared)
    local = inherited(aggregate(scope), base)
    with factory.begin() as writer:
        accepted = persist_menu(writer, local)
        persist_menu(
            writer,
            MenuAggregate(
                page=replace(successor(shared, base.page_id).page, operation="withdrawal")
            ),
        )
        force(writer)
    with factory() as reader:
        assert read_aggregate(reader, accepted.page_id)[0] == local


@pytest.mark.parametrize(
    "patch",
    [
        {"valid_from": "infinity"},
        {"valid_to": "-infinity"},
        {"service_period": " "},
        {"channel": "delivery"},
    ],
)
def test_raw_nonfinite_and_invalid_context_rejected(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], patch: dict[str, Any]
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        page = raw_page(writer, aggregate(scope))
        values = {"page_id": page, "applicability_key": "bad", "channel": "dine_in"}
        values.update(patch)
        with pytest.raises(DBAPIError) as error:
            writer.execute(insert(MenuApplicability).values(**values))
        rejected(error)


def test_compatible_narrowed_contexts_and_reordered_replay(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    start = datetime(2026, 9, 17, 11, tzinfo=UTC)
    narrow = replace(value.applicability[0], valid_from=start, valid_to=start + timedelta(hours=3))
    wide = replace(
        narrow,
        applicability_key="wide",
        valid_from=start - timedelta(hours=1),
        valid_to=start + timedelta(hours=4),
    )
    value = replace(
        value,
        sections=(replace(value.sections[0], applicability_key="lunch"),),
        applicability=(narrow, wide),
        prices=value.prices
        + (replace(value.prices[0], observation_key="wide-price", applicability_key="wide"),),
    )
    with factory.begin() as writer:
        first = persist_menu(writer, value)
        force(writer)
    reordered = replace(
        value,
        applicability=tuple(reversed(value.applicability)),
        prices=tuple(reversed(value.prices)),
    )
    with factory() as writer:
        replay = persist_menu(writer, reordered)
        assert replay.replayed and replay.members == first.members


def test_omitted_inherited_child_retains_mapped_ancestor_context(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    shared = aggregate(scope, shared=True)
    shared = replace(
        shared,
        items=(replace(shared.items[0], applicability_key="lunch"),),
        applicability=(replace(shared.applicability[0], channel="takeaway"),),
    )
    with factory.begin() as setup:
        base = persist_menu(setup, shared)
    local = inherited(aggregate(scope), base)
    section = replace(
        aggregate(scope).sections[0],
        base_section_id=local.sections[0].base_section_id,
        applicability_key="lunch",
    )
    local = replace(local, sections=(section,), items=(), prices=())
    with factory() as writer, pytest.raises(DBAPIError) as error:
        persist_menu(writer, local)
    rejected(error, "ck_menu_context_intersection")


@pytest.mark.parametrize("value", ["\tFood", "Food\n", "\u00a0Food", "Food\u3000"])
def test_raw_keys_and_labels_use_complete_whitespace_trim(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], value: str
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        page = raw_page(writer, aggregate(scope))
        with pytest.raises(DBAPIError) as error:
            writer.execute(
                insert(MenuSection).values(
                    page_id=page,
                    section_key="food",
                    name=value,
                    position=0,
                    effect="replace",
                    support_kind="direct",
                )
            )
        rejected(error, "ck_menu_section_text")
