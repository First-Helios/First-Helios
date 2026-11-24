"""Course candidates export (ADR-0016 Amendment 2): Gold sections + Menu page summaries +
record keys → candidate rows the harness reads, Unsectioned counts and a summary."""

from __future__ import annotations

import pytest

from apps.menu_pipeline.course_candidates import build_export, venue_of
from packages.helios_core.domains.menu.enumeration import CurrentPageSummary
from packages.helios_core.gold.menu_read import CurrentSection
from packages.helios_parsing.course_eval import section

LLM = CurrentPageSummary(1, 40, "llm", "llm-v1", 3)
JSONLD = CurrentPageSummary(2, 41, "jsonld", "jsonld-v1", 0)
UNSECTIONED_ONLY = CurrentPageSummary(3, 42, "llm", "llm-v1", 5)
KEYS = {40: "gers-a", 41: "gers-a|doordash.com", 42: "gers-b|/brunch"}


def _section(
    page: int, key: str, name: str | None, items: tuple[str, ...], rows: int
) -> CurrentSection:
    return CurrentSection(7, "organization", 9, "main", page, key, name, items, rows)


def test_venue_is_the_gers_id_before_the_bar() -> None:
    assert [venue_of(k) for k in KEYS.values()] == ["gers-a", "gers-a", "gers-b"]


def test_export_builds_harness_rows_and_counts() -> None:
    sections = [
        _section(1, "v40:b0001:tacos", "Tacos", ("Al Pastor", "Carnitas"), 3),
        _section(2, "v41:b0002:drinks", "Drinks", ("Horchata",), 1),
        _section(1, "v40:b0009:x", " ", ("Dish",), 1),  # no usable name: counted, not a row
    ]
    result = build_export(sections, [LLM, JSONLD, UNSECTIONED_ONLY], KEYS, "2026-11-23T00:00:00")
    rows = [section(raw) for raw in result.candidates]  # the harness accepts every row
    assert [(r.venue, r.version_id, r.name_path, r.priced_items) for r in rows] == [
        ("gers-a", 40, ("Tacos",), 3),
        ("gers-a", 41, ("Drinks",), 1),
    ]
    assert result.unsectioned == {"gers-a": 3, "gers-b": 5}
    meta = result.meta
    assert (meta["venues"], meta["sections"], meta["unnamed_sections"]) == (1, 2, 1)
    assert (meta["priced_items"], meta["unsectioned_priced_items"]) == (4, 8)
    assert meta["unsectioned_share"] == 8 / 12
    assert (meta["current_pages"], meta["pages_with_candidates"]) == (3, 2)
    assert meta["method_version"] == "jsonld=jsonld-v1 | llm=llm-v1"


def test_export_refuses_a_section_on_a_page_that_is_not_current() -> None:
    with pytest.raises(ValueError, match="non-current page"):
        build_export([_section(9, "v49:b1:x", "X", ("Dish",), 1)], [LLM], KEYS, None)
