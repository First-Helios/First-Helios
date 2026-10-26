"""Stage [5c] section assignment from page structure (ADR-0013 Amendment 28) on synthetic pages.

[5c] files kept items under the page's own section headings when the page's
structure passes the gate, and moves nothing but sections: rows, verdicts, items,
prices and their Evidence are the same with or without it.
"""

from __future__ import annotations

from packages.helios_parsing.dom_sections import DomSections, assign
from packages.helios_parsing.evaluation import shaped_items
from packages.helios_parsing.menu_shape import ShapedSection, shape
from packages.helios_parsing.resolve import judge
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, Verdict

UUID = "3eeb5dad-0d1f-4c2b-9a4e-1f2e3d4c5b6a"


def _toast_item(name: str, price: str) -> str:
    return f'<li class="menuItem"><h3 class="itemName">{name}</h3><span>{price}</span></li>'


# A Toast-like page: group h3s over dish h3s, the dishes in a list under each group.
TOAST = (
    '<div class="menuGroup"><h3 class="groupName">Tacos</h3><ul class="items">'
    + _toast_item("Shrimp Taco", "$4.00")
    + _toast_item("Pork Taco", "$3.50")
    + '</ul></div><div class="menuGroup"><h3 class="groupName">Aguas Frescas</h3><ul class="items">'
    + _toast_item("Pineapple", "$3.00")
    + _toast_item("Orange", "$3.25")
    + "</ul></div>"
)
# The model files the dishes after a dish h3 under that dish (the [3] context-line miss).
TOAST_ROWS = [
    Row("Shrimp Taco", "4.00", section="Tacos"),
    Row("Pork Taco", "3.50", section="Shrimp Taco"),
    Row("Pineapple", "3.00", section="Aguas Frescas"),
    Row("Orange", "3.25", section="Pineapple"),
]


def _run(html: str, rows: list[Row]) -> tuple[list[Verdict], DomSections]:
    blocks = segment(html)
    verdicts = list(judge(blocks, rows).verdicts)
    return verdicts, assign(html, blocks, verdicts)


def _filed(sections: tuple[ShapedSection, ...]) -> dict[str, str | None]:
    return {item.name: section.name for section in sections for item in section.items}


def _applied(html: str, rows: list[Row]) -> tuple[tuple[ShapedSection, ...], DomSections]:
    verdicts, dom = _run(html, rows)
    return shape(segment(html), verdicts, dom.assignment), dom


def test_toast_group_headings_win_over_dish_headings() -> None:
    blocks = segment(TOAST)
    verdicts, dom = _run(TOAST, TOAST_ROWS)
    assert _filed(shape(blocks, verdicts)) == {
        "Shrimp Taco": "Tacos",
        "Pork Taco": "Shrimp Taco",
        "Pineapple": "Aguas Frescas",
        "Orange": "Pineapple",
    }
    assert dom.gated and dom.assigned_share == 1.0 and dom.wrapped_share == 1.0
    sections = shape(blocks, verdicts, dom.assignment)
    assert _filed(sections) == {
        "Shrimp Taco": "Tacos",
        "Pork Taco": "Tacos",
        "Pineapple": "Aguas Frescas",
        "Orange": "Aguas Frescas",
    }
    tacos, drinks = sections
    ids = {b.text: b.id for b in blocks}
    # keyed and evidenced on the heading block, named by its printed text
    assert tacos.key == f"{ids['Tacos']}:tacos"
    assert tacos.evidence is not None
    assert tacos.evidence.locator == f"blocks:segment-v2:{ids['Tacos']}[0:5]"
    assert drinks.key == f"{ids['Aguas Frescas']}:aguas frescas"


def test_wrapped_h2_sections_with_h3_dishes() -> None:
    def dish(name: str, price: str) -> str:
        return f'<div class="dish"><h3>{name}</h3><p>{price}</p></div>'

    # a line inside the h2 ("to share") is not a heading of its own: only an h element's
    # first block is a candidate
    html = (
        f'<section class="menu-block"><h2>Starters<div>to share</div></h2>{dish("Nachos", "$9.00")}'
        f"{dish('Queso', '$7.00')}</section>"
        f'<section class="menu-block"><h2>Mains<div>with rice</div></h2>{dish("Enchiladas", "$14.00")}'
        f"{dish('Fajitas', '$18.00')}</section>"
    )
    rows = [
        Row("Nachos", "9.00", section="Starters"),
        Row("Queso", "7.00", section="Nachos"),
        Row("Enchiladas", "14.00", section="Starters"),  # the missed heading
        Row("Fajitas", "18.00", section="Enchiladas"),
    ]
    sections, dom = _applied(html, rows)
    assert dom.gated and dom.wrapped_share == 1.0
    assert _filed(sections) == {
        "Nachos": "Starters",
        "Queso": "Starters",
        "Enchiladas": "Mains",
        "Fajitas": "Mains",
    }


def test_flat_h3_sections_are_one_style() -> None:
    html = (
        '<div class="menu"><h3>Tacos</h3><p>Shrimp Taco $4.00</p><p>Pork Taco $3.50</p>'
        "<h3>Drinks</h3><p>Horchata $2.50</p><p>Jamaica $2.50</p></div>"
    )
    rows = [
        Row("Shrimp Taco", "4.00", section="Tacos"),
        Row("Pork Taco", "3.50", section="Tacos"),
        Row("Horchata", "2.50", section="Tacos"),  # the model kept the previous heading
        Row("Jamaica", "2.50", section="Tacos"),
    ]
    sections, dom = _applied(html, rows)
    # siblings in one container: nothing is wrapped, but one heading style serves all
    assert dom.gated and dom.wrapped_share == 0.0 and dom.styles == 1
    assert _filed(sections) == {
        "Shrimp Taco": "Tacos",
        "Pork Taco": "Tacos",
        "Horchata": "Drinks",
        "Jamaica": "Drinks",
    }


def test_a_class_named_section_title_is_a_heading() -> None:
    def section(title: str, items: list[tuple[str, str]]) -> str:
        body = "".join(
            f'<div class="menu-item"><div class="menu-item-title">{name}</div>'
            f'<div class="menu-item-price-top">{price}</div></div>'
            for name, price in items
        )
        return (
            f'<div class="menu-section"><div class="menu-section-title">{title}</div>'
            f'<div class="menu-section-description">Made fresh daily</div>{body}</div>'
        )

    html = section("Salads", [("Caesar", "$10.00"), ("Cobb", "$12.00")]) + section(
        "Soups", [("Tortilla", "$6.00"), ("Lentil", "$5.00")]
    )
    rows = [
        Row("Caesar", "10.00"),
        Row("Cobb", "12.00"),
        Row("Tortilla", "6.00"),
        Row("Lentil", "5.00"),
    ]
    sections, dom = _applied(html, rows)
    assert dom.gated
    # no h1-h6 on the page: the section titles are named by their classes; the dish
    # titles ("menu-item-title") and the section's description ("...-description") are
    # not candidates
    assert _filed(sections) == {
        "Caesar": "Salads",
        "Cobb": "Salads",
        "Tortilla": "Soups",
        "Lentil": "Soups",
    }


def test_an_instance_id_on_a_note_is_not_a_heading_class() -> None:
    # a Wix-like note between items, its id "section-<uuid>"; two of them would make a
    # section style of their own if the id read as a "section" class
    html = (
        '<div class="part"><h2>Burgers</h2><div class="row"><p>Classic $9.00</p></div>'
        f'<div class="note" id="section-{UUID}">All burgers served with fries</div>'
        '<div class="row"><p>Bacon $11.00</p></div></div>'
        '<div class="part"><h2>Salads</h2><div class="row"><p>Greek $8.00</p></div>'
        f'<div class="note" id="section-{UUID[:-1]}7">Add chicken to any salad</div>'
        '<div class="row"><p>Garden $7.00</p></div></div>'
    )
    rows = [
        Row("Classic", "9.00", section="Burgers"),
        Row("Bacon", "11.00", section="Burgers"),
        Row("Greek", "8.00", section="Burgers"),
        Row("Garden", "7.00", section="Burgers"),
    ]
    sections, dom = _applied(html, rows)
    assert dom.gated
    # "section-<uuid>" names the element, not its role: the notes are no section
    assert _filed(sections) == {
        "Classic": "Burgers",
        "Bacon": "Burgers",
        "Greek": "Salads",
        "Garden": "Salads",
    }


def test_a_lone_page_title_is_no_section_and_the_page_is_unchanged() -> None:
    html = (
        "<h1>Joe's Diner Menu</h1><div class='item'><p>Burger $9.00</p></div>"
        "<div class='item'><p>Fries $3.00</p></div>"
    )
    rows = [Row("Burger", "9.00", section="Burgers"), Row("Fries", "3.00", section="Burgers")]
    verdicts, dom = _run(html, rows)
    assert not dom.gated and dom.assignment == {} and dom.assigned_share == 0.0
    blocks = segment(html)
    assert shape(blocks, verdicts, dom.assignment) == shape(blocks, verdicts)


def test_a_page_failing_the_gate_is_byte_identical() -> None:
    # half the items print before the first heading: 50 % assigned, under the 90 % gate
    html = (
        "<div class='menu'><p>Chips $2.00</p><p>Salsa $1.00</p>"
        "<h3>Tacos</h3><p>Shrimp Taco $4.00</p><h3>Drinks</h3><p>Horchata $2.50</p></div>"
    )
    rows = [
        Row("Chips", "2.00"),
        Row("Salsa", "1.00"),
        Row("Shrimp Taco", "4.00", section="Tacos"),
        Row("Horchata", "2.50", section="Tacos"),
    ]
    verdicts, dom = _run(html, rows)
    assert dom.matched and dom.assigned_share == 0.5 and not dom.gated
    assert dom.assignment == {}
    blocks = segment(html)
    assert shape(blocks, verdicts, dom.assignment) == shape(blocks, verdicts)


def test_blocks_that_differ_from_the_reparse_assign_nothing() -> None:
    blocks = segment(TOAST)
    verdicts = list(judge(blocks, TOAST_ROWS).verdicts)
    changed = TOAST.replace("Aguas Frescas", "Bebidas")
    dom = assign(changed, blocks, verdicts)
    assert not dom.matched and not dom.gated and dom.assignment == {}
    assert assign(TOAST, blocks, verdicts).gated


def test_5c_moves_only_sections() -> None:
    html = TOAST + "<p>Churros</p><p>$5.00</p>"
    rows = [
        *TOAST_ROWS,
        Row("Shrimp Taco", "4.00", variant="Each", section="Tacos"),  # rejected: unprinted label
        Row("Churros", "5.00", section="Pineapple"),
    ]
    blocks = segment(html)
    verdicts = judge(blocks, rows).verdicts
    before = shape(blocks, verdicts)
    dom = assign(html, blocks, verdicts)
    after = shape(blocks, verdicts, dom.assignment)
    assert judge(blocks, rows).verdicts == verdicts  # [5c] re-judges nothing
    assert shaped_items(before) == shaped_items(after)  # items, prices, variants, Evidence
    assert sum(len(s.items) for s in before) == sum(len(s.items) for s in after) == 5
    assert before != after  # only the sections around them moved
    assert {s.key for s in after} != {s.key for s in before}


def test_an_item_whose_move_would_merge_two_items_keeps_its_section() -> None:
    # the same printed dish emitted under two model sections stays two items
    rows = [*TOAST_ROWS, Row("Orange", "3.25", section="Aguas Frescas")]
    blocks = segment(TOAST)
    verdicts, dom = _run(TOAST, rows)
    before = shape(blocks, verdicts)
    after = shape(blocks, verdicts, dom.assignment)
    assert shaped_items(before) == shaped_items(after)
    oranges = sorted(str(s.name) for s in after for it in s.items if it.name == "Orange")
    assert oranges == ["Aguas Frescas", "Pineapple"]  # both keep the section they had
    assert _filed(after)["Pork Taco"] == "Tacos"  # the rest of the page still moves
