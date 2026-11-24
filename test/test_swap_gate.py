"""The swap gate (ADR-0030 D3): lost-venue kinds, the two bars, and its SQL on the schema."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from apps.menu_pipeline.swap_gate import (
    UNCLASSIFIED,
    GoldFacts,
    RecordFacts,
    classify,
    gate_report,
    lost_records,
    venue_kinds,
    verdict,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_RECORD = RecordFacts(
    key="r",
    menu_url="https://example.com/menu",
    public_versions=2,
    master_versions=2,
    latest_capture="ok/ 2026-11-23",
    llm_operation="observation",
    llm_priced=6,
    llm_sectioned_priced=6,
    jsonld_published=False,
)


@pytest.mark.parametrize(
    ("changes", "kind"),
    [
        ({"llm_operation": "withdrawal", "llm_priced": 0}, "r4_withdrawal"),
        ({"llm_priced": 0, "llm_sectioned_priced": 0, "master_versions": 3}, "site_change"),
        ({"llm_priced": 0, "llm_sectioned_priced": 0}, "re_extracted_to_zero"),
        ({"llm_sectioned_priced": 0}, "unsectioned"),
        ({"llm_sectioned_priced": 0, "jsonld_published": True}, "unsectioned"),
        ({"jsonld_published": True}, "jsonld_precedence"),
        ({}, UNCLASSIFIED),
        ({"llm_operation": None, "llm_priced": 0}, UNCLASSIFIED),
    ],
)
def test_classify(changes: dict[str, object], kind: str) -> None:
    assert classify(replace(_RECORD, **changes)) == kind  # type: ignore[arg-type]


def test_a_venue_is_unclassified_when_any_record_is() -> None:
    withdrawn = replace(_RECORD, llm_operation="withdrawal")
    unsectioned = replace(_RECORD, llm_sectioned_priced=0)
    assert venue_kinds([withdrawn, unsectioned, withdrawn]) == ["r4_withdrawal", "unsectioned"]
    assert venue_kinds([withdrawn, _RECORD]) == [UNCLASSIFIED]
    assert venue_kinds([]) == [UNCLASSIFIED]


def _gold(rows: int, venues: int) -> GoldFacts:
    return GoldFacts(
        current_menu_rows=rows,
        price_index_rows=0,
        median_minor=1095,
        priced_count=None,
        index_venue_count=None,
        venues=frozenset(range(venues)),
    )


def test_swap_5_passes() -> None:
    assert verdict(_gold(98_499, 1_221), _gold(99_408, 1_233), {}) == (True, [])


def test_rows_must_fall_less_than_5_percent() -> None:
    passed, _ = verdict(_gold(10_000, 100), _gold(9_501, 100), {})
    assert passed
    passed, reasons = verdict(_gold(10_000, 100), _gold(9_500, 100), {})
    assert not passed and "current_menu rows fall 5.00%" in reasons[0]


def test_venues_must_fall_less_than_5_percent() -> None:
    lost = {subject: ["r4_withdrawal"] for subject in range(95, 100)}
    passed, reasons = verdict(_gold(100, 100), _gold(100, 95), lost)
    assert not passed and reasons == ["venues with a menu fall 5.00% (bar: under 5%)"]
    assert verdict(_gold(100, 1_216), _gold(100, 1_183), {})[0], "swap 2 (-2.7%) passes"


def test_an_unclassified_venue_stops_the_gate() -> None:
    passed, reasons = verdict(
        _gold(100, 100), _gold(100, 99), {7: [UNCLASSIFIED], 8: ["unsectioned"]}
    )
    assert not passed and reasons == ["1 lost venues unclassified: [7]"]


def test_the_gate_sql_runs_on_the_schema(session: Session) -> None:
    """A schema change that breaks the gate's SQL fails here, not at a swap."""
    report = gate_report(session, session)
    assert report["passed"] and report["lost"] == []
    assert report["public"]["venues_with_menu"] == report["master"]["venues_with_menu"]
    assert lost_records(session, session, -1) == []
