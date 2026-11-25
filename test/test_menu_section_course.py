"""Silver course labels, ``menu.section_course`` (ADR-0016 §3, Amendment 3 items 3–4):
insert-only and unique per (section, labeller version), never on the structural
``Unsectioned`` grouping, read back by Gold's key, and the pinned labeller CLI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.menu_pipeline.label_courses import label_current_sections
from packages.helios_core.domains.menu.commands import persist_menu, record_section_courses
from packages.helios_core.domains.menu.contracts import ItemInput, SectionInput, Target
from packages.helios_core.domains.menu.courses import (
    load_course_pin,
    section_courses,
    sections_to_label,
)
from packages.helios_core.domains.menu.enumeration import UNSECTIONED
from packages.helios_core.domains.menu.models import COURSE_LABELS, MenuSection
from packages.helios_parsing.course_eval import COURSES
from test.menu_support import aggregate, rejected
from test.test_gold_catalog import _seed_scope as seed_open_scope
from test.test_menu_replay import menu_scopes as menu_scopes

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session, sessionmaker

    from packages.helios_core.domains.menu.contracts import MenuAggregate
    from test.provider_support import ScopeFixture

VERSION = "course-lexicon-test@000000000000"


def _with_unsectioned(value: MenuAggregate) -> MenuAggregate:
    price = value.prices[0]
    return replace(
        value,
        sections=(
            *value.sections,
            SectionInput(
                section_key=UNSECTIONED,
                name=UNSECTIONED,
                position=0,
                effect="replace",
                support_kind="structural",
            ),
        ),
        items=(
            *value.items,
            ItemInput(
                item_key="water",
                section_key=UNSECTIONED,
                name="Water",
                position=0,
                dietary_tags=(),
                effect="replace",
                support_kind="direct",
                evidence_ids=value.page.evidence_ids,
            ),
        ),
        prices=(
            *value.prices,
            replace(price, observation_key="water", target=Target(kind="item", key="water")),
        ),
    )


def _page(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> tuple[sessionmaker[Session], int, dict[str, int]]:
    """A committed page with the named ``Food`` section and a structural ``Unsectioned``."""
    factory, scope = menu_scopes
    with factory.begin() as session:
        page_id = persist_menu(session, _with_unsectioned(aggregate(scope))).page_id
    with factory() as session:
        sections = dict(
            list(
                session.execute(
                    select(MenuSection.section_key, MenuSection.id).where(
                        MenuSection.page_id == page_id
                    )
                ).tuples()
            )
        )
    return factory, page_id, sections


def test_the_vocabulary_matches_the_harness() -> None:
    assert COURSE_LABELS == COURSES


def test_labels_are_insert_only_unique_and_read_by_gold_key(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, page_id, sections = _page(menu_scopes)
    food = sections["food"]
    with factory() as session:
        todo = sections_to_label(session, VERSION, [page_id])
    assert [(s.section_id, s.name) for s in todo] == [(food, "Food")]  # never Unsectioned
    with factory.begin() as session:
        assert record_section_courses(session, VERSION, [(food, "entree", Decimal(1))]) == 1
    with factory.begin() as session:  # a second write at the same version keeps the first
        assert record_section_courses(session, VERSION, [(food, "side", Decimal(1))]) == 0
        many = [(food, None, None)] + [(food, "side", None)] * 2  # three rows, two batches
        assert record_section_courses(session, "other-version@1", many, batch=2) == 1
    with factory() as session:
        assert sections_to_label(session, VERSION, [page_id]) == []
        assert section_courses(session, VERSION, [page_id]) == {(page_id, "s-food"): "entree"}
        assert section_courses(session, "other-version@1", [page_id]) == {(page_id, "s-food"): None}
        assert section_courses(session, "unknown@1", [page_id]) == {}
    for statement in (
        "UPDATE menu.section_course SET course = 'side'",
        "DELETE FROM menu.section_course",
        "TRUNCATE menu.section_course",
    ):
        with factory() as session, pytest.raises(DBAPIError) as error:
            session.execute(text(statement))
        rejected(error, "ck_menu_immutable")


def test_the_structural_grouping_and_bad_values_are_refused(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, _page_id, sections = _page(menu_scopes)
    cases = [
        (sections[UNSECTIONED], VERSION, "entree", "ck_section_course_section"),
        (sections["food"], VERSION, "mains", "ck_section_course_course"),
        (sections["food"], " padded ", "entree", "ck_section_course_labeller"),
    ]
    for section_id, version, course, constraint in cases:
        with factory() as session, pytest.raises(DBAPIError) as error:
            session.execute(
                text(
                    "INSERT INTO menu.section_course (section_id, labeller_version, course)"
                    " VALUES (:s, :v, :c)"
                ),
                {"s": section_id, "v": version, "c": course},
            )
        rejected(error, constraint)


def _pin(tmp_path: Path, rules: dict[str, list[str]], *, tamper: bool = False) -> Path:
    lexicon = tmp_path / "lexicon.json"
    lexicon.write_text(json.dumps({"version": "lex-t", "rules": rules}), encoding="utf-8")
    digest = hashlib.sha256(lexicon.read_bytes()).hexdigest()
    pin = tmp_path / "pin.json"
    pin.write_text(
        json.dumps(
            {
                "labeller": f"lex-t@{digest[:12]}",
                "file": "lexicon.json",
                "sha256": digest,
                "passing": ["entree"],
            }
        ),
        encoding="utf-8",
    )
    if tamper:
        lexicon.write_text(json.dumps({"version": "lex-t", "rules": {}}), encoding="utf-8")
    return pin


def test_the_cli_labels_current_sections_once(
    menu_scopes: tuple[sessionmaker[Session], ScopeFixture], tmp_path: Path
) -> None:
    factory, _closed = menu_scopes
    with factory.begin() as session:  # the gate admits only an operating venue
        scope = seed_open_scope(session, uuid4().hex, "open")
    with factory.begin() as session:
        page_id = persist_menu(session, _with_unsectioned(aggregate(scope))).page_id
    pin = _pin(tmp_path, {"entree": ["food"]})
    labeller = load_course_pin(pin).labeller
    now = datetime.now(UTC)
    with factory() as session:  # dry run: counts, no rows
        dry = label_current_sections(session, at=now, pin_path=pin)
        session.rollback()
    assert dry["entree"] >= 1 and "inserted" not in dry
    with factory() as session:
        assert section_courses(session, labeller, [page_id]) == {}
    with factory.begin() as session:
        done = label_current_sections(session, at=now, pin_path=pin, commit=True)
    assert done["inserted"] == sum(n for k, n in done.items() if k != "inserted")
    with factory() as session:
        assert section_courses(session, labeller, [page_id]) == {(page_id, "s-food"): "entree"}
        structural = session.scalar(
            text(
                "SELECT count(*) FROM menu.section_course c JOIN menu.menu_section s"
                " ON s.id = c.section_id WHERE s.page_id = :p AND s.support_kind = 'structural'"
            ),
            {"p": page_id},
        )
    assert structural == 0
    with factory.begin() as session:  # nothing left to label at this version
        again = label_current_sections(session, at=now, pin_path=pin, commit=True)
    assert again == {"inserted": 0}

    with pytest.raises(ValueError, match="no longer hashes"):
        load_course_pin(_pin(tmp_path, {"entree": ["food"]}, tamper=True))
