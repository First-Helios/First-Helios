"""The page-structure model and [5d]'s record rewrite (ADR-0021 D1; ADR-0013 Amendment 33).

Synthetic pages only. A dish card page learns its title signature, record depth and price
slot from the accepted rows; on a gated page, rows named inside another title's record move
onto that title: choice and label lines become its variants (one per choice), description
rows priced in the record take its name, and unclaimed labelled prices in the record are
attached. A short line that is no description keeps its name (a brand title over the dish
line), and a heading card on a page whose cards don't normally print a price slot is left.
"""

from __future__ import annotations

from packages.helios_parsing.dom_sections import placed_blocks
from packages.helios_parsing.page_structure import (
    ADDON,
    DESCRIPTION,
    LABEL,
    PRICE,
    PRICED,
    SYMBOLS,
    TEXT,
    TITLE,
    build,
    shape,
)
from packages.helios_parsing.page_template import _choices, induce
from packages.helios_parsing.prices import price_tokens
from packages.helios_parsing.resolve import judge
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row

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
)
DISHES = [(name, f"{20 + i}.99") for i, name in enumerate(NAMES)]


def _card(title: str, *lines: str, price: str = "") -> str:
    body = "".join(f'<p class="line">{x}</p>' for x in lines)
    slot = f'<div class="price">{price}</div>' if price else ""
    return f'<div class="card"><h3 class="title">{title}</h3>{slot}{body}</div>'


def _page(*extra: str) -> str:
    return (
        '<div class="menu">'
        + "".join(_card(n, price=f"${p}") for n, p in DISHES)
        + "".join(extra)
        + "</div>"
    )


BASE = [Row(n, p) for n, p in DISHES]
NACHOS = _card(
    "Nachos",
    "Chicken / Bistec / Pastor $14.99",
    "Shrimp / Combo $16.99",
    "Corn tostadas, topped with meat, beans, cheese and crema.",
)


def _run(html: str, rows: list[Row]):  # type: ignore[no-untyped-def]
    blocks = segment(html)
    return induce(blocks, placed_blocks(html), rows, judge(blocks, rows).verdicts), blocks


def _final(html: str, rows: list[Row]) -> list[tuple[str, str | None, str | None, str]]:
    tpl, blocks = _run(html, rows)
    judged = judge(blocks, list(tpl.rows)).verdicts
    return [(v.row.item, v.row.amount, v.row.variant, v.decision) for v in judged]


def _structure(html: str, rows: list[Row]):  # type: ignore[no-untyped-def]
    blocks = segment(html)
    index = {b.id: i for i, b in enumerate(blocks)}
    seeds = [
        (index[v.name_evidence.block_id], index[v.price_evidence.block_id])
        for v in judge(blocks, rows).verdicts
        if v.decision == "accept" and v.name_evidence and v.price_evidence
    ]
    return build(blocks, placed_blocks(html), price_tokens(blocks), seeds), blocks


def test_text_shapes() -> None:
    texts = {
        "$12.99": PRICE,
        "$360.00/48pcs": PRICE,
        "Shrimp / Combo $16.99": LABEL,
        "+$2.00": ADDON,
        "Add avocado $1.50": ADDON,
        "Grilled chicken with rice, beans and our house salsa verde $14.99": PRICED,
        "Nachos": TITLE,
        "Corn tostadas, topped with meat, beans and cheese.": DESCRIPTION,
        "Ask your server about the fresh catch": TEXT,
        "* * *": SYMBOLS,
    }
    blocks = segment("".join(f"<p>{t}</p>" for t in texts))
    prices = price_tokens(blocks)
    assert {b.text: shape(b, prices[j]) for j, b in enumerate(blocks)} == texts


def test_choices() -> None:
    assert _choices("Chicken / Bistec / Pastor") == ["Chicken", "Bistec", "Pastor"]
    assert _choices("Tofu or Paneer") == ["Tofu", "Paneer"]
    assert _choices("1/2 lb") == ["1/2 lb"]
    assert _choices("Large") == ["Large"]


def test_records_title_signature_slot_and_flat_lists() -> None:
    flat = (
        '<div class="card"><h3 class="title">Agua Fresca</h3><h3 class="title">Horchata</h3></div>'
    )
    st, blocks = _structure(_page(NACHOS, flat), BASE)
    assert st is not None and st.title_signature is not None
    assert st.title_signature[-1] == ("h3", "title")
    assert st.levels == 1 and st.slotted
    titles = {blocks[r.title].text: r for r in st.records}
    assert "Nachos" in titles and not titles["Nachos"].slot
    assert titles["Tostada Mixta"].slot
    assert "Agua Fresca" not in titles and "Horchata" not in titles  # two titles in one box
    nachos = titles["Nachos"]
    line = next(j for j, b in enumerate(blocks) if b.text.startswith("Shrimp"))
    assert st.record(line) is nachos and st.record(nachos.title) is None


def test_no_structure_without_a_matching_reparse_or_seeds() -> None:
    blocks = segment(_page())
    assert build(blocks, [], price_tokens(blocks), []) is None
    st = build(blocks, placed_blocks(_page()), price_tokens(blocks), [])
    assert st is not None and st.records == ()


def test_choice_lines_become_one_variant_per_choice() -> None:
    rows = [
        *BASE,
        Row("Nachos", None),
        Row("Chicken / Bistec / Pastor", "14.99"),
        Row("Shrimp / Combo", "16.99"),
    ]
    out = _final(_page(NACHOS), rows)
    assert ("Nachos", None, None, "downgrade") not in out  # the title's unpriced copy goes
    assert [r for r in out if r[0] == "Nachos"] == [
        ("Nachos", "14.99", "Chicken", "accept"),
        ("Nachos", "14.99", "Bistec", "accept"),
        ("Nachos", "14.99", "Pastor", "accept"),
        ("Nachos", "16.99", "Shrimp", "accept"),
        ("Nachos", "16.99", "Combo", "accept"),
    ]
    assert not any(r[0].startswith(("Chicken", "Shrimp")) for r in out)


def test_label_lines_on_a_page_whose_cards_lack_a_slot_are_left() -> None:
    # half the dish cards print their price in the slot, half in a line: the page has no
    # normal slot, so "Sauces" (no slot) may be a heading over items, and nothing moves
    cards = "".join(
        _card(n, price=f"${p}") if i % 2 else _card(n, f"Regular ${p}")
        for i, (n, p) in enumerate(DISHES)
    )
    sauces = _card("Sauces", "Salsa Verde $1.50", "Salsa Roja $1.50")
    html = f'<div class="menu">{cards}{sauces}</div>'
    rows = [*BASE, Row("Salsa Verde", "1.50"), Row("Salsa Roja", "1.50")]
    tpl, _ = _run(html, rows)
    assert tpl.anchored == () and tpl.priced_lines == ()
    assert ("Salsa Verde", "1.50") in {(r.item, r.amount) for r in tpl.rows}


def test_description_row_priced_in_the_slot_takes_the_title() -> None:
    soup = (
        '<div class="card"><h3 class="title">Kyay Oh Soup</h3>'
        '<p class="line">Rice vermicelli, chicken, tofu, mustard leaf and fish balls in broth.</p>'
        '<div class="price">$10.99</div></div>'
    )
    rows = [
        *BASE,
        Row("Kyay Oh Soup", None),
        Row("Rice vermicelli, chicken, tofu, mustard leaf and fish balls in broth.", "10.99"),
    ]
    out = _final(_page(soup), rows)
    assert [r for r in out if r[0] == "Kyay Oh Soup"] == [("Kyay Oh Soup", "10.99", None, "accept")]
    assert not any(r[0].startswith("Rice vermicelli") for r in out)


def test_a_brand_title_keeps_the_dish_line_name() -> None:
    cider = _card("AUSTIN EASTCIDERS", "Pineapple Cider", price="$7")
    out = _final(_page(cider), [*BASE, Row("Pineapple Cider", "7")])
    assert ("Pineapple Cider", "7", None, "accept") in out
    assert not any(r[0] == "AUSTIN EASTCIDERS" for r in out)


def test_attach_gives_the_title_its_unclaimed_labelled_prices() -> None:
    gumbo = _card("Chicken Gumbo", "Large $13.95", "Extra rice +$1.00", price="$9.95")
    out = _final(_page(gumbo), [*BASE, Row("Chicken Gumbo", "9.95")])
    assert [r for r in out if r[0] == "Chicken Gumbo"] == [
        ("Chicken Gumbo", "9.95", None, "accept"),
        ("Chicken Gumbo", "13.95", "Large", "accept"),
    ]  # the add-on line is never attached


def test_an_ungated_page_is_unchanged() -> None:
    html = _page(NACHOS)
    rows = [Row("Tostada Mixta", "20.99"), Row("Chicken / Bistec / Pastor", "14.99")]
    tpl, _ = _run(html, rows)
    assert not tpl.gated and tpl.rows == tuple(rows) and tpl.anchored == ()
