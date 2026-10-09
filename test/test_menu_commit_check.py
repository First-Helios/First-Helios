"""ADR-0005 Amendment 1: the commit check runs once per aggregate state, never less."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError

from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.contracts import (
    ItemInput,
    MenuAggregate,
    ModifierInput,
    SectionInput,
    Target,
    VariantInput,
)
from packages.helios_core.domains.menu.models import EvidenceLink, MenuSection
from test.menu_support import aggregate, raw_page, raw_page_support, rejected
from test.provider_support import migrate
from test.test_menu_replay import menu_scopes as menu_scopes

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from test.provider_support import ScopeFixture

PARENT = "7c2e4b9d1f3a"
HEAD = "db40e9424cba"
SQL_DIR = Path(__file__).resolve().parents[1] / "docs/reviews/sql"
TABLES = 8

# The pre-Amendment-1 node_path body (d83f0a21c592), inlined as the oracle.
_OLD_NODE_PATH = """
WITH RECURSIVE path AS (
    SELECT n.*, 0 AS depth, ARRAY[n.kind || ':' || n.id] AS visited, false AS cycle
    FROM menu.nodes(NULL) n WHERE n.kind = :kind AND n.id = :id
    UNION ALL
    SELECT n.*, p.depth + 1, p.visited || (n.kind || ':' || n.id),
           (n.kind || ':' || n.id) = ANY(p.visited)
    FROM path p
    JOIN menu.nodes(NULL) n ON
        (n.kind = p.parent_kind AND n.id = p.parent_id)
        OR (n.kind = p.kind AND n.id = p.base_id)
    WHERE NOT p.cycle
) SELECT kind, id, page_id, applicability_id, native_key, base_id, effect, depth, cycle FROM path
"""
_ORDER = " ORDER BY depth, kind, id"


def _sql(direction: str, boundary: str) -> str:
    return "\n".join(
        line.rstrip() for line in migrate(direction, boundary, "--sql").splitlines()
    ).rstrip()


def test_sql_snapshots() -> None:
    for direction, boundary in (("upgrade", f"{PARENT}:{HEAD}"), ("downgrade", f"{HEAD}:{PARENT}")):
        sql = _sql(direction, boundary)
        snapshot = SQL_DIR / f"2026-10-08-a1-menu-commit-check-{direction}.sql"
        assert snapshot.read_text().rstrip() == sql
        assert "CASCADE" not in sql
        assert not re.search(r"(CREATE|ALTER|DROP) TABLE", sql)
        assert sql.count("TRIGGER trg_menu_generation") == TABLES


def _section(writer: Session, page: int, key: str, evidence: int | None = None) -> None:
    """A direct section; without Evidence only the commit check rejects it."""
    section = writer.execute(
        insert(MenuSection)
        .values(
            page_id=page,
            section_key=key,
            name=key.title(),
            position=1,
            effect="replace",
            support_kind="direct",
        )
        .returning(MenuSection.id)
    ).scalar_one()
    if evidence is not None:
        writer.execute(
            insert(EvidenceLink).values(
                page_id=page, page_target=False, evidence_id=evidence, section_id=section
            )
        )


def test_insert_after_immediate_check_is_rechecked(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    with factory() as writer:
        page = persist_menu(writer, aggregate(scope)).page_id
        writer.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        writer.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        _section(writer, page, "late")
        with pytest.raises(DBAPIError) as error:
            writer.commit()
    rejected(error, "ck_menu_support")


def test_savepoint_rollback_cannot_skip_a_check(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    with factory() as writer:
        page = persist_menu(writer, value).page_id
        writer.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        writer.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        # Checked inside a savepoint at generation g + 1, then rolled back to g:
        # the memo must roll back with it, or the next insert (g + 1 again)
        # would match it and skip the check.
        nested = writer.begin_nested()
        _section(writer, page, "extra", scope.local_input.evidence_id)
        writer.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        writer.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        nested.rollback()
        _section(writer, page, "late")
        with pytest.raises(DBAPIError) as error:
            writer.commit()
    rejected(error, "ck_menu_support")


def _check_calls(writer: Session) -> int:
    return (
        writer.execute(
            text(
                "SELECT coalesce(sum(calls), 0) FROM pg_stat_xact_user_functions "
                "WHERE schemaname = 'menu' AND funcname = 'check_aggregate'"
            )
        ).scalar_one()
        or 0
    )


def test_commit_checks_each_page_once(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    value = aggregate(scope)
    items = tuple(
        replace(
            value.items[0],
            item_key=f"dish-{n}",
            name=f"Dish {n}",
            position=n,
            source_native_key=f"i-{n}",
        )
        for n in range(5)
    )
    value = replace(
        value,
        items=items,
        prices=tuple(
            replace(
                value.prices[0],
                observation_key=f"price-{n}",
                target=Target(kind="item", key=f"dish-{n}"),
            )
            for n in range(5)
        ),
    )
    with factory() as writer:
        writer.execute(text("SET LOCAL track_functions = 'pl'"))
        persist_menu(writer, value)
        rows = writer.execute(text("SELECT count(*) FROM menu.evidence_link")).scalar_one()
        assert rows > 1
        before = _check_calls(writer)
        writer.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert _check_calls(writer) - before == 1
        writer.rollback()


def _deep(scope: ScopeFixture) -> MenuAggregate:
    """A nested section, an item, a variant and a modifier on one shared page."""
    shared = aggregate(scope, shared=True)
    evidence = (scope.shared_input.evidence_id,)
    return replace(
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
        modifiers=(
            ModifierInput(
                modifier_key="extra",
                item_key="burger",
                label="Extra",
                required=False,
                position=0,
                effect="replace",
                support_kind="direct",
                evidence_ids=evidence,
            ),
        ),
    )


def test_node_path_matches_the_original(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, scope = menu_scopes
    with factory.begin() as writer:
        base = persist_menu(writer, _deep(scope))
    by_key = {(m.table, m.key): m.id for m in base.members}
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
            ItemInput(
                item_key="burger",
                section_key="nested",
                effect="inherit",
                support_kind="inherited",
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
        persist_menu(writer, local)
    with factory() as writer:
        # A self-parented section: uncommittable, so built raw and rolled back.
        page = raw_page(writer, aggregate(scope, root="cycle"))
        raw_page_support(writer, page, scope.local_input.evidence_id)
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
        nodes = writer.execute(text("SELECT kind, id FROM menu.nodes(NULL)")).all()
        assert {kind for kind, _ in nodes} == {"section", "item", "variant", "modifier"}
        cycles = crossings = 0
        for kind, node in nodes:
            new = writer.execute(
                text("SELECT * FROM menu.node_path(:kind, :id)" + _ORDER),
                {"kind": kind, "id": node},
            ).all()
            old = writer.execute(text(_OLD_NODE_PATH + _ORDER), {"kind": kind, "id": node}).all()
            assert new == old and new
            cycles += any(r.cycle for r in new)
            crossings += len({r.page_id for r in new}) > 1
        assert cycles and crossings
        writer.rollback()
