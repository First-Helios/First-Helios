"""The invariance suite (ADR-0017 item 1) on a synthetic page.

A correct extraction written in another meaning-preserving style must reach the same
decision; the suite counts the gold prices whose status changes (flips).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.helios_parsing.evaluation import gold_page
from packages.helios_parsing.invariance import (
    added_flips,
    as_output,
    harness,
    invariance_page,
    perfect_rows,
    restyle,
)
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.output import ExtractorOutput
    from packages.helios_parsing.segment import Block

HTML = (
    "<h2>Drinks</h2><p>Horchata</p><p>Small $2.50</p><p>Large $3.50</p>"
    "<h2>Plates</h2><p>Tacos al Pastor</p><p>Pork, pineapple</p><p>$9.00</p>"
)
PAGE = gold_page(
    {
        "page_id": "p1",
        "page_label": "menu",
        "format": "html_list",
        "reviewed": True,
        "items": [
            {
                "name": "Horchata",
                "block": "b0002",
                "section": "Drinks",
                "prices": [
                    {"amount": "2.50", "variant": "Small"},
                    {"amount": "3.50", "variant": "Large"},
                ],
            },
            {
                "name": "Tacos al Pastor",
                "block": "b0006",
                "section": "Plates",
                "prices": [{"amount": "9.00"}],
            },
        ],
    }
)
BLOCKS = segment(HTML)


def test_styles_rewrite_only_what_they_name() -> None:
    rows = perfect_rows(PAGE)
    assert [(r.name, r.price, r.variant, r.block) for r in rows] == [
        ("Horchata", "2.50", "Small", "b0002"),
        ("Horchata", "3.50", "Large", "b0002"),
        ("Tacos al Pastor", "9.00", None, "b0006"),
    ]

    def styled(style: str) -> list[tuple[str, str, str | None, str, str]]:
        return [
            (r.name, r.price, r.variant, r.block, r.section)
            for r in restyle(rows, style, BLOCKS, PAGE)
        ]

    assert [r[2] for r in styled("variant_in_name")] == [None, None, None]
    assert [r[0] for r in styled("variant_in_name_paren")][:2] == [
        "Horchata (Small)",
        "Horchata (Large)",
    ]
    assert [r[1] for r in styled("price_short")] == ["2.5", "3.5", "9"]
    assert [r[1] for r in styled("price_dollar")] == ["$2.50", "$3.50", "$9.00"]
    assert [r[2] for r in styled("empty_v")] == ["Small", "Large", ""]
    assert [r[0] for r in styled("whitespace")][2] == " Tacos  al  Pastor "
    assert {r[4] for r in styled("section_generic")} == {"Menu"}
    # claims stay inside the item's span: the next block, or the one printing the price
    assert [r[3] for r in styled("claim_next")] == ["b0003", "b0003", "b0007"]
    assert [r[3] for r in styled("claim_price_block")] == ["b0003", "b0004", "b0008"]


def test_a_perfect_output_reads_back_through_the_pipeline_parser() -> None:
    output = as_output(perfect_rows(PAGE))
    assert [s.section for s in output.sections] == ["Drinks", "Plates"]
    assert [(r.name, r.price, r.variant) for r in output.sections[0].rows] == [
        ("Horchata", "2.50", "Small"),
        ("Horchata", "3.50", "Large"),
    ]
    assert output.sections[1].rows[0].variant == ""  # no "v" key written


def test_the_harness_reads_price_forms_and_spacing_the_same() -> None:
    c = invariance_page(PAGE, BLOCKS)
    assert c["gold_prices"] == 3
    assert c["base:accept"] == 3
    for style in ("price_short", "price_two", "price_dollar", "whitespace", "empty_v"):
        assert c[f"flip:{style}"] == 0, style


def test_a_style_dependent_decision_is_counted_as_a_flip() -> None:
    def case_sensitive(blocks: Sequence[Block], outputs: list[ExtractorOutput]) -> list[Verdict]:
        verdicts = list(harness(blocks, outputs))
        return [
            v if v.row.item[:1].isupper() else Verdict(v.row, "downgrade", ("lower_case",))
            for v in verdicts
        ]

    c = invariance_page(PAGE, BLOCKS, case_sensitive)
    assert c["flip:case_lower"] == c["lost_accept:case_lower"] == 3
    assert c["flip:case_upper"] == 0


def test_added_flips_compares_each_page_and_style() -> None:
    baseline = {"p1": {"flip:case_lower": 2}, "p2": {}}
    current = {
        "p1": {"flip:case_lower": 2, "flip:claim_next": 1},
        "p2": {},
        "p3": {"flip:section_none": 1},  # a page new to the run counts from zero
    }
    assert added_flips(baseline, current) == [
        ("p1", "claim_next", 0, 1),
        ("p3", "section_none", 0, 1),
    ]
    assert added_flips(current, baseline) == []
