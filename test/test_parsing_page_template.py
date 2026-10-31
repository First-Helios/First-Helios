"""Stage [5d] page template and duplicate removal (ADR-0013 Amendment 29) on synthetic pages.

[5d] learns a page's item layout from its accepted rows and, on a gated page, adds the
template lines the model missed, drops description lines kept as items, re-grounds rows
on their dish's title and turns size labels into variants. An ungated page is unchanged.
Duplicate removal (rule "same") drops the extra copies of a printed item the model
emitted under two of its sections, when every copy cites the same printed prices.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from packages.helios_parsing.dom_sections import assign, placed_blocks
from packages.helios_parsing.menu_shape import ShapedSection, shape
from packages.helios_parsing.output import parse_output, rows_of
from packages.helios_parsing.page_template import (
    Template,
    induce,
    llm_stream,
    remove_duplicates,
)
from packages.helios_parsing.resolve import judge
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, Verdict, evidence

if TYPE_CHECKING:
    from packages.helios_parsing.segment import Block

# ---- a same-line page: "Greek Salad ..... $8.99", one dish per line
SALADS = [
    ("Greek Salad", "8.99"),
    ("Chef Salad", "9.99"),
    ("Cobb Salad", "10.49"),
    ("House Salad", "7.49"),
    ("Garden Salad", "6.99"),
    ("Wedge Salad", "8.49"),
]


def _line(name: str, price: str) -> str:
    return f'<p class="line">{name} ..... ${price}</p>'


def _salads(extra: str = "") -> str:
    """The salad lines, the line the model missed (Caesar Salad), then ``extra``."""
    return (
        '<div class="menu"><h2>Salads</h2>'
        + "".join(_line(n, p) for n, p in SALADS)
        + _line("Caesar Salad", "9.39")
        + extra
        + "</div>"
    )


SALAD_ROWS = [Row(n, p, section="Salads") for n, p in SALADS]

# ---- a split-card page: an h3 title over a price div in one card
NAMES = (
    "Tostada Mixta",
    "Ceviche Verde",
    "Mojarra Frita",
    "Caldo de Res",
    "Filete Empanizado",
    "Camarones al Mojo",
    "Pulpo Asado",
    "Tacos Gobernador",
    "Enchiladas Suizas",
    "Chile Relleno",
    "Carne Asada",
    "Pollo Loco",
    "Sopa de Mariscos",
    "Torta Ahogada",
    "Quesadilla Grande",
    "Aguachile Rojo",
    "Pescado Zarandeado",
    "Coctel Mixto",
    "Molcajete",
    "Birria de Res",
)
DISHES = [(name, f"{30 + i}.99") for i, name in enumerate(NAMES)]


def _card(name: str, price: str, desc: str = "") -> str:
    d = f'<p class="desc">{desc}</p>' if desc else ""
    return (
        f'<div class="item"><h3 class="title">{name}</h3>{d}<div class="price">{price}</div></div>'
    )


CARDS = (
    '<div class="menu">'
    + "".join(_card(n, f"${p}") for n, p in DISHES)
    + _card("Coctel de Camaron", "Pequeño $12.49 | Grande $28.99")
    + _card("Fish Tacos", "$12.00", "Our famous fish tacos with slaw and lime.")
    + _card("Huevos Rancheros", "$19.50", "Two eggs, ranchero sauce, rice and beans.")
    + _card("Flautas", "$10.99")
    + "</div>"
)
CARD_ROWS = [Row(n, p) for n, p in DISHES] + [
    Row("Pequeño", "12.49"),  # size labels in the name slot (Jarochos)
    Row("Grande", "28.99"),
    Row("Fish Tacos", "12.00"),  # grounded on the description, which repeats the name
    Row("Huevos Rancheros", None),  # the title kept unpriced ...
    Row("Eggs with ranchero sauce", "19.50"),  # ... its price on a description row
]  # Flautas: missed by the model


def _induce(html: str, rows: list[Row]) -> tuple[Template, tuple[Verdict, ...]]:
    blocks = segment(html)
    verdicts = judge(blocks, rows).verdicts
    return induce(blocks, placed_blocks(html), rows, verdicts), verdicts


def _ids(html: str) -> dict[str, str]:
    return {b.text: b.id for b in segment(html)}


def test_same_line_template_adds_the_missed_dish_and_drops_an_ingredient_row() -> None:
    html = _salads()
    html = html.replace(
        _line("Greek Salad", "8.99"),
        _line("Greek Salad", "8.99") + "<p>Lettuce, Tomato, Feta, Olives</p>",
    )
    ids = _ids(html)
    # an ingredient line priced from the dish line above it (Halal Wings)
    rows = [
        *SALAD_ROWS,
        Row(
            "Lettuce", "8.99", section="Salads", claimed_block=ids["Lettuce, Tomato, Feta, Olives"]
        ),
    ]
    tpl, verdicts = _induce(html, rows)
    assert verdicts[-1].decision == "accept"  # the validator alone keeps it
    assert tpl.gated and tpl.seeds == 7 and tpl.agree == 1.0
    assert tpl.dropped == (6,)
    caesar = ids["Caesar Salad ..... $9.39"]
    assert tpl.added == (Row("Caesar Salad", "9.39", section="Salads", claimed_block=caesar),)
    assert tpl.rows == (*SALAD_ROWS, *tpl.added)
    # the added row is judged again by the unchanged validator: accepted on its own line
    (added,) = judge(segment(html), list(tpl.rows)).verdicts[-1:]
    assert added.decision == "accept"
    assert added.price_evidence is not None and added.price_evidence.block_id == caesar


def test_split_card_template_attaches_renames_and_adds() -> None:
    tpl, _ = _induce(CARDS, CARD_ROWS)
    ids = _ids(CARDS)
    assert tpl.gated
    coctel, fish, huevos = ids["Coctel de Camaron"], ids["Fish Tacos"], ids["Huevos Rancheros"]
    n = len(DISHES)
    # ATTACH: the size labels become variants of the card's dish (no choice line, so the
    # v5 record rewrite leaves them to [5d]'s own ATTACH)
    assert tpl.anchored == ()
    assert tpl.attached == (
        (n, Row("Coctel de Camaron", "12.49", variant="Pequeño", claimed_block=coctel)),
        (n + 1, Row("Coctel de Camaron", "28.99", variant="Grande", claimed_block=coctel)),
    )
    # RE-NAME: re-grounded on the title; the description row's price goes to its title
    assert tpl.renamed == (
        (n + 2, Row("Fish Tacos", "12.00", claimed_block=fish)),
        (n + 4, Row("Huevos Rancheros", "19.50", claimed_block=huevos)),
    )
    # ADD: the card the model missed
    assert tpl.added == (Row("Flautas", "10.99", claimed_block=ids["Flautas"]),)
    assert tpl.dropped == ()
    judged = judge(segment(CARDS), list(tpl.rows)).verdicts
    assert all(v.decision == "accept" for v in judged if v.row.amount is not None)
    sections = shape(segment(CARDS), judged)
    (only,) = sections
    by_name = {it.name: it for it in only.items}
    assert "Pequeño" not in by_name and "Grande" not in by_name
    assert [v.label for v in by_name["Coctel de Camaron"].variants] == ["Pequeño", "Grande"]
    assert [p.amount_minor for p in by_name["Huevos Rancheros"].prices] == [1950]


def test_rename_drops_a_copy_the_title_already_holds() -> None:
    rows = [*CARD_ROWS, Row("Fish Tacos", "12.00")]  # also emitted on its title
    blocks = segment(CARDS)
    fish = _ids(CARDS)["Fish Tacos"]
    verdicts = list(judge(blocks, rows).verdicts)
    # the last row grounds its name on the title block, the earlier one on the description
    assert verdicts[-1].name_evidence is not None
    verdicts[-1] = Verdict(
        rows[-1],
        "downgrade",
        ("no_price_extracted",),
        evidence(blocks[[b.id for b in blocks].index(fish)], 0, 10),
    )
    tpl = induce(blocks, placed_blocks(CARDS), rows, verdicts)
    assert len(DISHES) + 2 in tpl.dropped
    assert all(k != len(DISHES) + 2 for k, _ in tpl.renamed)


def test_drop_keeps_a_printed_list_and_a_line_printing_its_amount() -> None:
    html = _salads(
        "<p>Disaronno | Frangelico | Kahlua, served neat, or on ice.</p>"
        "<p>Ranch, Blue Cheese, or Italian dressing 8.49</p>"
    )
    ids = _ids(html)
    rows = [
        *SALAD_ROWS,
        Row(
            "Disaronno",
            "9.99",
            claimed_block=ids["Disaronno | Frangelico | Kahlua, served neat, or on ice."],
        ),
        Row("Ranch", "8.49", claimed_block=ids["Ranch, Blue Cheese, or Italian dressing 8.49"]),
    ]
    tpl, verdicts = _induce(html, rows)
    assert tpl.gated
    kept = [k for k in (6, 7) if verdicts[k].decision != "reject"]
    assert kept and not set(kept) & set(tpl.dropped)


def test_blocks_off_the_template_are_left_alone() -> None:
    html = CARDS.removesuffix("</div>") + (
        # an h3 styled as another kind of block (its class signature no seed uses)
        '<div class="item"><h3 class="promo">Happy Hour</h3><div class="price">$5.00</div></div>'
        # a title whose price sits outside its card: the pattern's relation differs
        '<div class="item"><h3 class="title">Sides</h3></div>'
        '<div class="extra"><div class="price">$3.00</div></div>'
        # a note after the last card, outside its record
        '<p class="note">Ask your server about the catch of the day, market price.</p>'
        "</div>"
    )
    rows = [*CARD_ROWS, Row("Catch of the Day", None)]
    tpl, verdicts = _induce(html, rows)
    assert tpl.gated
    assert [(r.item, r.amount) for r in tpl.added] == [("Flautas", "10.99")]
    assert verdicts[-1].decision == "downgrade" and len(rows) - 1 not in tpl.dropped


def test_drop_keeps_a_line_that_prints_its_own_price() -> None:
    # on another tag path than the template's lines, so not a candidate itself
    html = _salads("<ul><li>Ranch, Blue Cheese, or Italian dressing 8.49</li></ul>")
    ranch = _ids(html)["Ranch, Blue Cheese, or Italian dressing 8.49"]
    rows = [*SALAD_ROWS, Row("Ranch", "8.49", claimed_block=ranch)]
    tpl, verdicts = _induce(html, rows)
    assert tpl.gated and verdicts[-1].decision == "accept"
    assert tpl.dropped == ()


@pytest.mark.parametrize(
    ("trap", "extra"),
    [
        pytest.param(_line("+ Add Chicken", "3.00"), [], id="addon"),
        pytest.param(_line("Served with rice, beans, and tortillas", "2.00"), [], id="description"),
        pytest.param('<p class="line">Small $2.99 Large $3.99</p>', [], id="price_labels_only"),
        pytest.param(
            '<p class="line">Fajitas</p>' + _line("Chicken", "14.00"),
            [Row("Fajitas", None, section="Salads")],
            id="dish_above_kept_unpriced",
        ),
        pytest.param("<h2>Red Wines</h2>" + _line("Malbec", "9.00"), [], id="wine_list"),
        pytest.param(_line("Greek Salad", "8.99"), [], id="name_and_price_held"),
        pytest.param(
            _line("Tuna Salad", "11.00"),
            [Row("Tuna Salad", None, section="Salads")],
            id="name_block_kept",
        ),
        pytest.param(
            '<p class="line">Big Platter</p>'
            + _line("Rice", "2.00")
            + '<p class="line">Platter $20.00</p>',
            [Row("Big Platter", "20.00", section="Salads")],
            id="inside_a_kept_item",
        ),
    ],
)
def test_add_skips(trap: str, extra: list[Row]) -> None:
    tpl, _ = _induce(_salads(trap), SALAD_ROWS + extra)
    assert tpl.gated
    # the missed dish is still added; the trap line is not
    assert [(r.item, r.amount) for r in tpl.added] == [("Caesar Salad", "9.39")]


def test_add_skips_a_line_under_the_models_wine_section() -> None:
    html = _salads()
    blocks = segment(html)
    caesar = [b.text for b in blocks].index("Caesar Salad ..... $9.39")
    verdicts = judge(blocks, SALAD_ROWS).verdicts
    # the model's raw rows (wine rows included) file the line under a wine list
    tpl = induce(blocks, placed_blocks(html), SALAD_ROWS, verdicts, [(caesar, "Red Wine")])
    assert tpl.gated and tpl.added == ()


@pytest.mark.parametrize(
    ("html", "rows"),
    [
        pytest.param(_salads(), SALAD_ROWS[:4], id="fewer_than_five_seeds"),
        pytest.param(
            # dishes split between two name layouts: no main name path
            '<div class="menu">'
            + "".join(_card(n, f"${p}") for n, p in DISHES[:5])
            + "".join(_line(n, p) for n, p in SALADS[:5])
            + _line("Caesar Salad", "9.39")
            + "</div>",
            [Row(n, p) for n, p in DISHES[:5] + SALADS[:5]],
            id="agreement_below_gate",
        ),
        pytest.param(
            # every seed its own layout: the template explains none
            '<div class="menu">'
            + "".join(
                f"<{t}>{n} ..... ${p}</{t}>"
                for t, (n, p) in zip(["p", "li", "h4", "td", "dd", "h5"], SALADS, strict=True)
            )
            + "</div>",
            SALAD_ROWS,
            id="nothing_explained",
        ),
    ],
)
def test_an_ungated_page_is_byte_identical(html: str, rows: list[Row]) -> None:
    tpl, verdicts = _induce(html, rows)
    assert not tpl.gated
    assert tpl.rows == tuple(rows)
    assert (tpl.dropped, tpl.attached, tpl.renamed, tpl.added) == ((), (), (), ())
    outputs = [parse_output(_output(rows, segment(html)))]
    stream = llm_stream(segment(html), outputs, html)
    assert (
        stream.validation.verdicts == judge(segment(html), rows_of(outputs, segment(html))).verdicts
    )


def _output(rows: list[Row], blocks: list[Block]) -> str:
    """One chunk's model answer naming ``rows`` (each on the block that prints its name)."""

    def block_of(name: str) -> str:
        return next(b.id for b in blocks if name in b.text)

    by_section: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_section.setdefault(r.section or "", []).append(
            {"b": block_of(r.item), "n": r.item, "p": r.amount or "", "v": r.variant or ""}
        )
    return json.dumps({"sections": [{"section": s, "items": rs} for s, rs in by_section.items()]})


# ---- duplicate removal
TOAST = (
    '<div class="menuGroup"><h3 class="groupName">Tacos</h3><ul class="items">'
    '<li class="menuItem"><h3 class="itemName">Shrimp Taco</h3><span>$4.00</span></li>'
    '<li class="menuItem"><h3 class="itemName">Pork Taco</h3><span>$3.50</span></li>'
    '</ul></div><div class="menuGroup"><h3 class="groupName">Drinks</h3><ul class="items">'
    '<li class="menuItem"><h3 class="itemName">Horchata</h3><span>$3.00</span></li>'
    '<li class="menuItem"><h3 class="itemName">Jamaica</h3><span>$3.25</span></li>'
    "</ul></div>"
)


def _filed(sections: tuple[ShapedSection, ...]) -> list[tuple[str | None, str]]:
    return [(s.name, it.name) for s in sections for it in s.items]


def test_duplicate_removal_same_rule() -> None:
    blocks = segment(TOAST)
    rows = [
        Row("Shrimp Taco", "4.00", section="Tacos"),
        Row("Pork Taco", "3.50", section="Tacos"),
        Row("Pork Taco", "3.50", section="Shrimp Taco"),  # re-emitted across a chunk boundary
        Row("Horchata", "3.00", section="Drinks"),
        Row("Jamaica", "3.25", section="Drinks"),
    ]
    verdicts = judge(blocks, rows).verdicts
    kept = remove_duplicates(verdicts)
    assert kept == verdicts[:2] + verdicts[3:]  # the later section's copy goes
    # copies citing different printed prices are two dishes, not copies: both stay
    other = list(verdicts)
    pe = other[2].price_evidence
    assert pe is not None
    jamaica = blocks[[b.text for b in blocks].index("$3.25")]
    other[2] = Verdict(other[2].row, "accept", (), other[2].name_evidence, evidence(jamaica, 0, 5))
    assert remove_duplicates(other) == tuple(other)
    # copies within one model section are shape's to merge, not removal's
    one = judge(blocks, [rows[1], rows[1]]).verdicts
    assert remove_duplicates(one) == one
    # unpriced copies cite no price to compare, so both stay (a second print may have been
    # grounded onto the first); priced copies of the same spans are still removed
    unpriced = judge(
        blocks,
        [Row("Pork Taco", None, section="Tacos"), Row("Pork Taco", None, section="Shrimp Taco")],
    ).verdicts
    assert all(v.name_evidence is not None and v.price_evidence is None for v in unpriced)
    assert remove_duplicates(unpriced) == unpriced
    priced = judge(blocks, rows[1:3]).verdicts
    assert remove_duplicates(priced) == priced[:1]


def test_the_survivor_is_placed_by_5c() -> None:
    rows = [
        Row("Shrimp Taco", "4.00", section="Tacos"),
        Row("Pork Taco", "3.50", section="Shrimp Taco"),  # the [3] context-line miss
        Row("Pork Taco", "3.50", section="Tacos"),  # and re-emitted under the right one
        Row("Horchata", "3.00", section="Drinks"),
        Row("Jamaica", "3.25", section="Drinks"),
    ]
    blocks = segment(TOAST)
    outputs = [parse_output(_output(rows, blocks))]
    v3 = judge(blocks, rows_of(outputs, blocks)).verdicts
    # resolve-v3: [5c]'s merge guard keeps both copies where the model put them
    assert (
        _filed(shape(blocks, v3, assign(TOAST, blocks, v3).assignment)).count(
            ("Shrimp Taco", "Pork Taco")
        )
        == 1
    )
    stream = llm_stream(blocks, outputs, TOAST)
    assert stream.duplicates == 1
    assert stream.template.rows == tuple(rows_of(outputs, blocks))  # [5d] changes nothing here
    assert stream.sections.gated
    assert _filed(shape(blocks, stream.validation.verdicts, stream.sections.assignment)) == [
        ("Tacos", "Shrimp Taco"),
        ("Tacos", "Pork Taco"),
        ("Drinks", "Horchata"),
        ("Drinks", "Jamaica"),
    ]
