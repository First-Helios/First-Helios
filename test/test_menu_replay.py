"""Complete aggregate replay and explicit committed lifecycle."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from packages.helios_core.domains.menu.commands import persist_menu, read_aggregate
from packages.helios_core.domains.menu.contracts import MenuConflictError
from test.menu_support import aggregate, force, successor
from test.provider_support import ScopeFixture, migrate, seed_scope

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture
def menu_scopes(disposable_database_engine: Engine) -> tuple[sessionmaker[Session], ScopeFixture]:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    with factory.begin() as setup:
        scope = seed_scope(setup)
    return factory, scope


def test_exact_replay_and_correction(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as session:
        first = persist_menu(session, value)
        force(session)
    with factory.begin() as session:
        replay = persist_menu(session, value)
        assert (
            replay.replayed and replay.page_id == first.page_id and replay.members == first.members
        )
        second = persist_menu(session, successor(value, first.page_id))
        force(session)
    with factory() as session:
        assert read_aggregate(session, first.page_id)[0] == value
        times = (
            session.execute(
                text(
                    "SELECT accepted_at FROM menu.menu_page WHERE id IN (:a,:b) ORDER BY stream_revision"
                ),
                {"a": first.page_id, "b": second.page_id},
            )
            .scalars()
            .all()
        )
        assert times[1] > times[0]
        conflict = replace(value, prices=(replace(value.prices[0], amount_minor=1150),))
        with pytest.raises(MenuConflictError):
            persist_menu(session, conflict)


@pytest.mark.parametrize(
    "field", ["amount", "confidence", "support", "membership", "method", "scope"]
)
def test_conflicting_replay_payload(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], field: str
) -> None:
    from decimal import Decimal

    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as setup:
        persist_menu(setup, value)
    if field == "amount":
        conflict = replace(value, prices=(replace(value.prices[0], amount_minor=1),))
    elif field == "confidence":
        conflict = replace(value, prices=(replace(value.prices[0], confidence=Decimal("0.5")),))
    elif field == "support":
        conflict = replace(
            value,
            prices=(replace(value.prices[0], evidence_ids=(scope.shared_input.evidence_id,)),),
        )
    elif field == "membership":
        conflict = replace(value, prices=())
    elif field == "method":
        conflict = replace(value, page=replace(value.page, method_version="2"))
    else:
        conflict = replace(
            value,
            page=replace(
                value.page, subject_id=scope.organization.subject_id, subject_kind="organization"
            ),
        )
    with factory() as writer, pytest.raises(MenuConflictError):
        persist_menu(writer, conflict)


_HEAD_RULE = "successor requires the committed head and explicit lifecycle"


# Every lifecycle defect shares ck_menu_lifecycle, so the message names the rule.
@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("fork", _HEAD_RULE),
        ("skip_stream", _HEAD_RULE),
        ("skip_version", "incorrect version interpretation revision"),
        ("same_tx", _HEAD_RULE),
        ("wrong_stream", "stream must start with initial revision 1"),
        ("duplicate_initial", _HEAD_RULE),
        ("old_observation", "observation requires unused later Bronze input"),
        ("restoration_without_withdrawal", _HEAD_RULE),
    ],
)
def test_lifecycle_intent_rejected(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], defect: str, message: str
) -> None:
    from sqlalchemy.exc import DBAPIError

    from test.menu_support import raw_page, rejected

    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory() as writer:
        first = persist_menu(writer, value)
        if defect != "same_tx":
            writer.commit()
        intent = successor(value, first.page_id)
        if defect == "fork":
            persist_menu(writer, intent)
            writer.commit()
        elif defect == "skip_stream":
            intent = replace(intent, page=replace(intent.page, stream_revision=3))
        elif defect == "skip_version":
            intent = replace(intent, page=replace(intent.page, interpretation_revision=3))
        elif defect == "wrong_stream":
            intent = replace(intent, page=replace(intent.page, root_key="different"))
        elif defect == "duplicate_initial":
            intent = value
        elif defect == "old_observation":
            intent = replace(intent, page=replace(intent.page, operation="observation"))
        elif defect == "restoration_without_withdrawal":
            intent = replace(intent, page=replace(intent.page, operation="restoration"))
        with pytest.raises(DBAPIError) as error:
            raw_page(writer, intent)
        rejected(error, "ck_menu_lifecycle")
        assert error.value.orig.diag.message_primary == message  # type: ignore[union-attr]
        writer.rollback()


def test_tombstone_restoration_and_explicit_rebase(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    from sqlalchemy.exc import DBAPIError

    from packages.helios_core.domains.menu.contracts import MenuAggregate
    from test.menu_support import inherited

    factory, scope = menu_scopes
    shared = aggregate(scope, shared=True)
    with factory.begin() as writer:
        base = persist_menu(writer, shared)
    with factory.begin() as writer:
        second = persist_menu(writer, successor(shared, base.page_id))
    local = inherited(aggregate(scope), base)
    with factory.begin() as writer:
        old_local = persist_menu(
            writer, local
        )  # A NEW pin may choose an ordinarily superseded page.
        force(writer)
    withdrawal = MenuAggregate(
        page=replace(
            successor(successor(shared, base.page_id), second.page_id).page, operation="withdrawal"
        )
    )
    with factory.begin() as writer:
        tombstone = persist_menu(writer, withdrawal)
    bypass = replace(
        shared,
        page=replace(
            withdrawal.page,
            operation="correction",
            supersedes_page_id=tombstone.page_id,
            stream_revision=4,
            interpretation_revision=4,
        ),
    )
    with factory() as writer, pytest.raises(DBAPIError):
        persist_menu(writer, bypass)
    restored = replace(bypass, page=replace(bypass.page, operation="restoration"))
    with factory.begin() as writer:
        new_base = persist_menu(writer, restored)
    with factory() as writer, pytest.raises(DBAPIError):
        persist_menu(writer, successor(local, old_local.page_id))
    rebased = inherited(successor(aggregate(scope), old_local.page_id), new_base)
    with factory.begin() as writer:
        result = persist_menu(writer, rebased)
        force(writer)
    with factory() as reader:
        assert read_aggregate(reader, tombstone.page_id)[0] == withdrawal
        assert read_aggregate(reader, old_local.page_id)[0] == local
        assert read_aggregate(reader, result.page_id)[0] == rebased


def test_remap_preserves_counters_and_original_history(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    from packages.helios_core.identity import (
        create_establishment,
        mark_subject_eligible,
        remap_source_record,
    )
    from test.provider_support import decision

    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as writer:
        first = persist_menu(writer, value)
    with factory.begin() as writer:
        other = create_establishment(
            writer,
            organization_subject_id=scope.organization.subject_id,
            place_subject_id=scope.place_id,
            valid_from=decision().effective_at,
        )
        mark_subject_eligible(writer, other.id)
        event = remap_source_record(
            writer,
            source_record_id=scope.establishment.source_record_id,
            from_subject_id=scope.establishment.subject_id,
            to_subject_id=other.id,
            decision=decision(),
            evidence_ids=(scope.local_input.evidence_id,),
        )
    corrected = successor(value, first.page_id, subject_id=other.id, resolution_event_id=event.id)
    with factory.begin() as writer:
        assert persist_menu(writer, value).replayed
        second = persist_menu(writer, corrected)
        force(writer)
    with factory() as reader:
        assert (
            read_aggregate(reader, first.page_id)[0].page.subject_id
            == scope.establishment.subject_id
        )
        assert read_aggregate(reader, second.page_id)[0].page.stream_revision == 2
        assert read_aggregate(reader, second.page_id)[0].page.interpretation_revision == 2


def test_later_observation_and_older_explicit_correction(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    from datetime import timedelta

    from packages.helios_core.provenance import Evidence, SourceRecordVersion

    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as writer:
        first = persist_menu(writer, value)
    with factory.begin() as setup:
        original = setup.get(SourceRecordVersion, scope.local_input.source_record_version_id)
        assert original
        version = SourceRecordVersion(
            source_id=original.source_id,
            source_record_id=original.source_record_id,
            observed_at=original.observed_at + timedelta(hours=1),
            content_hash="later",
            source_payload={},
        )
        setup.add(version)
        setup.flush()
        evidence = Evidence(source_record_version_id=version.id, locator="$", excerpt_hash="later")
        setup.add(evidence)
        setup.flush()
    later = replace(
        value,
        page=replace(
            value.page,
            source_record_version_id=version.id,
            operation="observation",
            supersedes_page_id=first.page_id,
            stream_revision=2,
            evidence_ids=(evidence.id,),
        ),
        **{
            part: tuple(replace(row, evidence_ids=(evidence.id,)) for row in getattr(value, part))
            for part in ("sections", "items", "prices", "applicability")
        },
    )
    with factory.begin() as writer:
        second = persist_menu(writer, later)
    older = replace(
        value,
        page=replace(
            value.page,
            operation="correction",
            supersedes_page_id=second.page_id,
            stream_revision=3,
            interpretation_revision=2,
        ),
    )
    with factory.begin() as writer:
        persist_menu(writer, older)
        force(writer)


def test_duplicate_bronze_business_identity_replays_without_new_ids(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    from packages.helios_core.provenance import Evidence, SourceRecordVersion

    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory.begin() as writer:
        first = persist_menu(writer, value)
    with factory.begin() as setup:
        original = setup.get(SourceRecordVersion, scope.local_input.source_record_version_id)
        support = setup.get(Evidence, scope.local_input.evidence_id)
        assert original and support
        duplicate = SourceRecordVersion(
            source_id=original.source_id,
            source_record_id=original.source_record_id,
            capture_id=original.capture_id,
            observed_at=original.observed_at,
            content_hash=original.content_hash,
            source_payload=original.source_payload,
        )
        setup.add(duplicate)
        setup.flush()
        evidence = Evidence(
            source_record_version_id=duplicate.id,
            locator=support.locator,
            excerpt_hash=support.excerpt_hash,
        )
        setup.add(evidence)
        setup.flush()
    duplicate_value = replace(
        value,
        page=replace(
            value.page, source_record_version_id=duplicate.id, evidence_ids=(evidence.id,)
        ),
        **{
            part: tuple(replace(row, evidence_ids=(evidence.id,)) for row in getattr(value, part))
            for part in ("sections", "items", "prices", "applicability")
        },
    )
    with factory.begin() as writer:
        replay = persist_menu(writer, duplicate_value)
        assert (
            replay.replayed and replay.page_id == first.page_id and replay.members == first.members
        )
        with pytest.raises(MenuConflictError):
            persist_menu(writer, replace(duplicate_value, prices=()))
        # Canonical equality cannot substitute for exact Evidence ownership.
        with pytest.raises(MenuConflictError):
            persist_menu(
                writer,
                replace(value, page=replace(value.page, source_record_version_id=duplicate.id)),
            )


def test_reference_error_rolls_back_supported_prefix(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    bad = replace(value, items=(replace(value.items[0], section_key="missing"),))
    with factory.begin() as writer:
        with pytest.raises(ValueError):
            persist_menu(writer, bad)
        assert (
            writer.scalar(
                text("SELECT count(*) FROM menu.menu_page WHERE source_record_id=:r"),
                {"r": scope.establishment.source_record_id},
            )
            == 0
        )
        result = persist_menu(writer, value)
        force(writer)
    with factory() as reader:
        assert read_aggregate(reader, result.page_id)[0] == value
