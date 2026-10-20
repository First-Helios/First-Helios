"""Stage [5b] price resolution (ADR-0013 Amendments 19 and 21) on synthetic pages.

[5b] sees only the validator's no-match downgrades, refuses by default, cites the
printed price it read and tags its accepts with its own reason.
"""

from __future__ import annotations

import json

from packages.helios_parsing.output import parse_output, rows_of
from packages.helios_parsing.resolve import (
    LABEL_LINE,
    NAME_PAIR,
    NAME_PRICE,
    RESOLVERS,
    Page,
    judge,
    name_price,
    pair_position,
    resolve,
    resolved,
)
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, validate

PAIRS = "<h2>Seafood</h2><p>3/6 Catfish Dinner</p><p>$9.95/$17.99</p><p>Cod Dinner</p><p>$12.99</p>"
PAIR_ROWS = [
    Row("3/6 Catfish Dinner", "9.95", variant="3"),
    Row("3/6 Catfish Dinner", "17.99", variant="6"),
    Row("Cod Dinner", "12.99"),
]


def _decisions(html: str, rows: list[Row]) -> list[str]:
    return [v.decision for v in judge(segment(html), rows).verdicts]


def test_a_count_pair_in_a_name_grounds_the_same_order_price_pair() -> None:
    verdicts = judge(segment(PAIRS), PAIR_ROWS).verdicts
    assert [v.decision for v in verdicts] == ["accept"] * 3
    assert [v.reasons for v in verdicts[:2]] == [(NAME_PAIR, "variant_not_grounded")] * 2
    assert [resolved(v) for v in verdicts] == [True, True, False]
    assert [v.price_evidence.locator for v in verdicts[:2] if v.price_evidence] == [
        "blocks:segment-v2:b0003[0:5]",  # "$9.95"
        "blocks:segment-v2:b0003[6:12]",  # "$17.99"
    ]
    assert verdicts[2].reasons == ()  # the validator's own accept, untouched
    # in the name's own block too: "3/6 Catfish Dinner $9.95/$17.99"
    inline = "<p>3/6 Catfish Dinner $9.95/$17.99</p>"
    assert _decisions(inline, PAIR_ROWS[:2]) == ["accept", "accept"]


def test_name_pair_refuses_by_default() -> None:
    swapped = [
        Row("3/6 Catfish Dinner", "17.99", variant="3"),
        Row("3/6 Catfish Dinner", "9.95", variant="6"),
    ]
    assert _decisions(PAIRS, swapped) == ["downgrade", "downgrade"]
    for variant in ("12", "Large"):  # no count of the pair
        assert _decisions(PAIRS, [Row("3/6 Catfish Dinner", "17.99", variant=variant)]) == [
            "downgrade"
        ]
    # the pair printed in a description, not the name
    described = "<p>Catfish Dinner</p><p>3/6 pieces</p><p>$9.95/$17.99</p>"
    assert _decisions(described, [Row("Catfish Dinner", "17.99", variant="6")]) == ["downgrade"]
    # the first prices after the name are not a "/" group: "$9.95 | $17.99" is not the pair
    barred = PAIRS.replace("$9.95/$17.99", "$9.95 | $17.99")
    assert _decisions(barred, PAIR_ROWS[1:2]) == ["downgrade"]
    # another item's name comes before any price
    between = PAIRS.replace("<p>$9.95/$17.99</p>", "<p>Hushpuppies</p><p>$9.95/$17.99</p>")
    rows = [*PAIR_ROWS[1:2], Row("Hushpuppies", None)]
    assert _decisions(between, rows)[0] == "downgrade"


def test_resolve_leaves_every_other_verdict_alone() -> None:
    rows = [
        Row("3/6 Catfish Dinner", None, variant="3"),  # no price extracted
        Row("Fried Okra", "9.95"),  # not on the page: rejected
        Row("Cod Dinner", "12.99"),  # accepted by the validator
        Row("3/6 Catfish Dinner", "17.99", variant="6"),
    ]
    blocks = segment(PAIRS)
    before = validate(blocks, rows)
    after = resolve(blocks, before)
    assert after.verdicts[:3] == before.verdicts[:3]
    assert after.verdicts[3].decision == "accept"
    assert after.unlabeled_price_runs == before.unlabeled_price_runs
    assert resolve(blocks, before, ()) == before  # no resolvers: the validator's decisions
    assert judge(blocks, rows, RESOLVERS) == after


def test_repairs_keep_a_count_of_a_name_pair_for_5b() -> None:
    blocks = segment(PAIRS)
    raw = json.dumps(
        {
            "sections": [
                {
                    "section": "Seafood",
                    "items": [
                        {"b": "b0002", "n": "3/6 Catfish Dinner", "p": "9.95", "v": "3"},
                        {"b": "b0002", "n": "3/6 Catfish Dinner", "p": "17.99", "v": "6"},
                        {"b": "b0004", "n": "Cod Dinner", "p": "12.99", "v": "4"},
                    ],
                }
            ]
        }
    )
    rows = rows_of([parse_output(raw)], blocks)
    assert [r.variant for r in rows] == ["3", "6", None]  # "4" is no count of a name pair
    assert [v.decision for v in judge(blocks, rows).verdicts] == ["accept"] * 3
    assert pair_position("3/6 Catfish Dinner", "6") == (1, 2)
    assert pair_position("6/12 Wing Dings", "12") == (1, 2)
    assert pair_position("3/6 Catfish Dinner", "Large") is None
    assert pair_position("3/3 Combo", "3") is None  # not distinct counts
    assert pair_position("Matcha 5/6", None) is None


SIDES = (
    "<h2>Sides</h2><p>Cream Corn</p><p>$3.50</p><p>Small (6oz)</p>"
    "<p>Medium (16oz)</p><p>$4.50</p><p>Large (32oz)</p><p>$11.50</p>"
    "<p>BBQ Beans</p><p>$3.50</p>"
)


def test_a_label_on_its_own_line_grounds_the_price_under_it() -> None:
    rows = [
        Row("Cream Corn", "3.50"),
        Row("Cream Corn", "4.50", variant="Medium (16oz)"),
        Row("Cream Corn", "11.50", variant="Large (32oz)"),
        Row("BBQ Beans", "3.50"),
    ]
    verdicts = judge(segment(SIDES), rows).verdicts
    assert [v.decision for v in verdicts] == ["accept"] * 4
    assert [v.reasons[0] for v in verdicts[1:3]] == [LABEL_LINE, LABEL_LINE]
    assert [v.price_evidence.block_id for v in verdicts[1:3] if v.price_evidence] == [
        "b0006",  # "$4.50"
        "b0008",  # "$11.50"
    ]


def test_label_line_refuses_another_label_or_another_items_price() -> None:
    blocks = segment(SIDES)
    # "Small (6oz)" is not the line right above "$4.50": that is "Medium (16oz)"
    assert _decisions(SIDES, [Row("Cream Corn", "4.50", variant="Small (6oz)")]) == ["downgrade"]
    # a label printed under the next item's name is not this item's
    rows = [Row("Cream Corn", "3.50"), Row("BBQ Beans", "3.50", variant="Large (32oz)")]
    assert [v.decision for v in judge(blocks, rows).verdicts][1] != "accept"


INLINE = (
    "<p>Appetizers: Fried Pork Dumplings 9.99, Seaweed Salad 6.99 | Takoyaki (6 pcs) 8.99,"
    " Chicken 12.99, Noodles: Chicken 14.99, ShuMai 7.99</p>"
)


def test_a_price_printed_right_after_the_name_grounds_it() -> None:
    verdicts = judge(segment(INLINE), [Row("Takoyaki (6 pcs)", "8.99")]).verdicts
    assert verdicts[0].decision == "accept"
    if verdicts[0].reasons:  # the validator may ground it itself; [5b] then never runs
        assert verdicts[0].reasons[0] == NAME_PRICE
    blocks = segment(INLINE)
    page = Page(blocks, validate(blocks, [Row("Seaweed Salad", "6.99")]).verdicts)
    tok = name_price(page, 0, validate(blocks, [Row("Seaweed Salad", "6.99")]).verdicts[0])
    assert tok is not None
    assert blocks[0].text[tok.start : tok.end] == "6.99"


def test_name_price_refuses_a_repeated_or_glued_name_and_another_price() -> None:
    blocks = segment(INLINE)

    def resolved_by_name_price(row: Row) -> bool:
        verdict = validate(blocks, [row]).verdicts[0]
        return name_price(Page(blocks, [verdict]), 0, verdict) is not None

    assert not resolved_by_name_price(Row("Chicken", "12.99"))  # printed twice
    assert not resolved_by_name_price(Row("ShuMai", "7.99"))  # glued words
    assert not resolved_by_name_price(Row("Seaweed Salad", "9.99"))  # not its price
    assert not resolved_by_name_price(Row("Pork Dumplings", "6.99"))  # a price printed elsewhere
    assert not resolved_by_name_price(Row("Seaweed Salad", "6.99", variant="Large"))  # unprinted
