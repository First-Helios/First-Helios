"""Extractor input and output (ADR-0013 §1) on synthetic pages: chunking, prompt v2.3,
the sparse-chunk retry, output parsing with truncated-output recovery, and the
row repairs including stitch v3."""

from __future__ import annotations

import json

from packages.helios_parsing.chunking import BLOCK_CHARS, CHUNK_CHARS, CHUNK_SOFT, chunks
from packages.helios_parsing.output import (
    ExtractorOutput,
    OutputRow,
    OutputSection,
    parse_output,
    rows_of,
)
from packages.helios_parsing.prompt import (
    GRAMMAR,
    SYSTEM_PROMPT,
    printed_prices,
    sparse_retry,
    token_cap,
)
from packages.helios_parsing.segment import segment
from packages.helios_parsing.stitch import stitch
from packages.helios_parsing.validator import Row, validate


def _lines(chunk: str) -> list[str]:
    return chunk.split("\n")


# --------------------------------------------------------------------------- chunking


def test_chunks_send_non_chrome_blocks_as_id_lines() -> None:
    blocks = segment(
        "<nav><a href='/'>Home</a></nav><h2>Tacos</h2><div>Carne Asada</div><div>$3.50</div>"
        "<footer>Call us</footer>"
    )
    [only] = chunks(blocks)
    assert _lines(only) == ["b0002 | Tacos", "b0003 | Carne Asada", "b0004 | $3.50"]


def test_chunks_cut_long_block_text() -> None:
    [only] = chunks(segment(f"<p>{'x' * 500}</p>"))
    assert only == f"b0001 | {'x' * BLOCK_CHARS}"


def test_chunks_cut_at_the_size_limit_with_a_context_line() -> None:
    html = "<h2>Tacos</h2>" + "".join(
        f"<p>Item number {n:03d} {'.' * 40} $3.50</p>" for n in range(60)
    )
    out = chunks(segment(html))
    assert len(out) > 1
    assert all(len(chunk) <= CHUNK_CHARS for chunk in out)
    first_lines, second_lines = _lines(out[0]), _lines(out[1])
    last_three = [line.split(" | ", 1)[1] for line in first_lines[-3:]]
    assert second_lines[0] == (
        "(continued from earlier on this page; heading: 'Tacos'; it ended with: "
        + " / ".join(f"'{text}'" for text in last_three)
        + ")"
    )
    ids = [line.split(" | ")[0] for chunk in out for line in _lines(chunk) if line.startswith("b")]
    assert ids == [f"b{n:04d}" for n in range(1, 62)], "every block once, in order"


def test_chunks_cut_before_a_heading_past_the_soft_limit() -> None:
    items = "".join(f"<p>Item number {n:03d} {'.' * 40} $3.50</p>" for n in range(19))
    out = chunks(segment(f"<h2>Tacos</h2>{items}<h2>Sides</h2><p>Chips $4</p>"))
    assert CHUNK_SOFT < len(out[0]) < CHUNK_CHARS - 40, "cut early, not at the hard limit"
    assert _lines(out[1])[1] == "b0021 | Sides", "the new chunk opens at the heading"


# --------------------------------------------------------------------------- prompt


def test_prompt_example_output_parses_to_its_items() -> None:
    example = SYSTEM_PROMPT.rsplit("Example output:\n", 1)[1]
    parsed = parse_output(example)
    assert not parsed.recovered
    assert [
        (s.section, [(r.name, r.price, r.variant) for r in s.rows]) for s in parsed.sections
    ] == [
        (
            "Tacos",
            [
                ("Carne Asada Taco", "3.50", ""),
                ("Horchata", "2.50", "Small"),
                ("Horchata", "3.50", "Large"),
            ],
        ),
        ("Sides", [("CHIPS AND SALSA", "4", ""), ("Elote", "5.25", "")]),
    ]
    assert GRAMMAR.strip().startswith('root    ::= "{\\"sections\\":["')


def test_token_cap_scales_with_lines_up_to_the_maximum() -> None:
    assert token_cap("b0001 | Tacos") == 40 + 64
    assert token_cap("\n".join(["b0001 | x"] * 10)) == 400 + 64
    assert token_cap("\n".join(["b0001 | x"] * 500)) == 3072


def test_printed_prices_count_block_lines_only() -> None:
    chunk = "(continued ... it ended with: '$9.99')\nb0001 | Taco $3 | Burrito 8.50\nb0002 | 12 oz"
    assert printed_prices(chunk) == 2


def _output(*prices: str) -> ExtractorOutput:
    rows = tuple(OutputRow(f"b000{i}", f"Item {i}", p, "") for i, p in enumerate(prices, 1))
    return ExtractorOutput((OutputSection("Tacos", rows),))


def test_sparse_retry_re_asks_a_priced_chunk_that_came_back_nearly_empty() -> None:
    chunk = "b0001 | Taco $3\nb0002 | Burrito $8\nb0003 | Bowl $9\nb0004 | Soda $2"
    assert sparse_retry(chunk, _output("3")) == (
        f"{chunk}\n\n(This text prints 4 prices. List every sold item in it with its price; "
        "the price is often on the line after the name.)"
    )
    assert sparse_retry(chunk, _output("3", "8")) is None, "2 of 4 priced rows is enough"
    assert sparse_retry("b0001 | Taco $3\nb0002 | Burrito $8", _output()) is None, "< 3 prices"


# --------------------------------------------------------------------------- parse_output


def test_parse_output_reads_compact_json() -> None:
    content = json.dumps(
        {"sections": [{"section": "Tacos", "items": [{"b": "b0003", "n": "Taco", "p": "3.50"}]}]},
        separators=(",", ":"),
    )
    assert parse_output(content) == ExtractorOutput(
        (OutputSection("Tacos", (OutputRow("b0003", "Taco", "3.50", ""),)),)
    )


def test_parse_output_recovers_complete_rows_of_truncated_output() -> None:
    content = (
        '{"sections":[{"section":"Tacos","items":[{"b":"b0003","n":"Taco","p":"3.50"},'
        '{"b":"b0004","n":"Burrito","p":"8","v":"Large"}]},{"section":"Sides","items":['
        '{"b":"b0009","n":"Chips","p":"4"},{"b":"b0010","n":"Que'
    )
    parsed = parse_output(content)
    assert parsed.recovered
    assert [(s.section, [r.name for r in s.rows]) for s in parsed.sections] == [
        ("Tacos", ["Taco", "Burrito"]),
        ("Sides", ["Chips"]),
    ]
    assert parsed.priced_rows == 3


def test_parse_output_recovers_items_before_any_section_and_non_objects() -> None:
    assert parse_output('{"b":"b0001","n":"Taco","p":"3"}, {"b":') == ExtractorOutput(
        (OutputSection("", (OutputRow("b0001", "Taco", "3", ""),)),), recovered=True
    )
    assert parse_output("[]") == ExtractorOutput((), recovered=True)
    assert parse_output("") == ExtractorOutput((), recovered=True)


# --------------------------------------------------------------------------- rows_of repairs


def _rows(rows: list[Row]) -> list[tuple[str, str | None, str | None]]:
    return [(r.item, r.amount, r.variant) for r in rows]


def _one_chunk(*rows: tuple[str, str, str, str], section: str = "Menu") -> list[ExtractorOutput]:
    return [ExtractorOutput((OutputSection(section, tuple(OutputRow(*r) for r in rows)),))]


def test_rows_of_repairs_slots_and_variants_and_drops_duplicates() -> None:
    blocks = segment("<p>Chips 4</p><p>Taco 3</p><p>Orange Chicken (L) 9</p>")
    rows = rows_of(
        _one_chunk(
            ("b0001", " Chips ", "", "4"),  # price in the variant slot
            ("b0002", "Taco", "3", "2"),  # a bare number is not a size
            ("b0003", "Orange Chicken (L)", "9", "L"),  # variant copied from the name
            ("b0003", "Orange Chicken (L)", "9", "L"),  # exact duplicate
            ("b0003", "", "9", ""),  # no name: not a row
        ),
        blocks,
    )
    assert _rows(rows) == [
        ("Chips", "4", None),
        ("Taco", "3", None),
        ("Orange Chicken (L)", "9", None),
    ]
    assert [(r.section, r.claimed_block) for r in rows][0] == ("Menu", "b0001")


STITCH_PAGE = """
<h2>Drinks</h2>
<h4>Horchata</h4><p>$2.50/Small</p><p>$3.50/Large</p>
<h4>Elote</h4><p>Grilled corn, cotija, chile and lime.</p><p>5.25</p>
<h4>Fog Cutter</h4><p>A bright tiki classic with rum, gin and brandy.</p><p>$14</p>
<h4>Red Wine</h4><p>Glass $7</p><p>Bottle $26</p>
<h2>Coffee</h2><p>Soup 20.24</p><p>$20.24</p><p>Americano $2/$3</p>
"""


def test_stitch_merges_price_lines_into_the_item_above() -> None:
    blocks = segment(STITCH_PAGE)
    rows = [
        Row("Horchata", None, claimed_block="b0002"),
        Row("$2.50/Small", "2.50", "Small", claimed_block="b0003"),
        Row("$3.50/Large", "3.50", "Large", claimed_block="b0004"),
    ]
    assert _rows(stitch(rows, blocks)) == [
        ("Horchata", "2.50", "Small"),
        ("Horchata", "3.50", "Large"),
    ]


def test_stitch_fills_a_price_printed_below_a_description() -> None:
    blocks = segment(STITCH_PAGE)
    assert _rows(stitch([Row("Elote", None, claimed_block="b0005")], blocks)) == [
        ("Elote", "5.25", None)
    ]


def test_stitch_drops_a_sentence_line_under_a_heading_item() -> None:
    blocks = segment(STITCH_PAGE)
    rows = [
        Row("Fog Cutter", None, claimed_block="b0008"),
        Row("A bright tiki classic with rum, gin and brandy.", None, claimed_block="b0009"),
    ]
    assert _rows(stitch(rows, blocks)) == [("Fog Cutter", "14", None)]


def test_stitch_completes_labelled_variants_from_the_run_below() -> None:
    blocks = segment(STITCH_PAGE)
    rows = [Row("Red Wine", "7", claimed_block="b0011")]
    assert _rows(stitch(rows, blocks)) == [("Red Wine", "7", None), ("Red Wine", "26", "Bottle")]


def test_stitch_drops_an_echoed_price_and_completes_inline_prices() -> None:
    blocks = segment(STITCH_PAGE)
    rows = [
        Row("Soup", "20.24", claimed_block="b0015"),
        Row("$20.24", "20.24", claimed_block="b0016"),  # the same price, echoed as an item
        Row("Americano", "2", claimed_block="b0017"),
    ]
    stitched = stitch(rows, blocks)
    assert _rows(stitched)[:2] == [("Soup", "20.24", None), ("Americano", "2", None)]
    assert [r.amount for r in stitched[2:]] == ["3"]


def test_stitched_rows_pass_the_validator() -> None:
    blocks = segment(STITCH_PAGE)
    rows = rows_of(
        _one_chunk(
            ("b0002", "Horchata", "", ""),
            ("b0003", "$2.50/Small", "2.50", "Small"),
            ("b0004", "$3.50/Large", "3.50", "Large"),
            ("b0005", "Elote", "", ""),
            ("b0008", "Fog Cutter", "", ""),
            ("b0011", "Red Wine", "7", "Glass"),
            ("b0017", "Americano", "2", ""),
        ),
        blocks,
    )
    assert _rows(rows) == [
        ("Horchata", "2.50", "Small"),
        ("Horchata", "3.50", "Large"),
        ("Elote", "5.25", None),
        ("Fog Cutter", "14", None),
        ("Red Wine", "7", "Glass"),
        ("Red Wine", "26", "Bottle"),
        ("Americano", "2", None),
        ("Americano", "3", None),
    ]
    assert {v.decision for v in validate(blocks, rows).verdicts} == {"accept"}
