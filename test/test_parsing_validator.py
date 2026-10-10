"""Validator v3 (ADR-0013 §1, §5) on synthetic pages.

The four corruption types are the ones the spike injected into gold rows to
measure the catch rate (mutated price, swapped prices, invented item, a price
from another section).
"""

from __future__ import annotations

import hashlib

from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, Validation, validate

MENU = """
<h2>Tacos — all tacos $3</h2>
<div><div>Carne Asada</div><div>$3</div></div>
<div><div>Al Pastor</div></div>
<h2>Plates</h2>
<p>Enchiladas Verdes ...... $12.50</p>
<p>Fajita Plate $15.95</p>
<p>Queso small $6 / large $9</p>
<p>Chips & Salsa 4</p>
<p>Horchata $3.25 Agua Fresca $3.00</p>
"""


def _check(rows: list[Row], html: str = MENU) -> Validation:
    return validate(segment(html), rows)


def _decide(rows: list[Row], html: str = MENU) -> list[str]:
    return [v.decision for v in _check(rows, html).verdicts]


def test_correct_rows_accept() -> None:
    rows = [
        Row("Carne Asada", "3.00"),
        Row("Al Pastor", "3"),  # the section heading's shared price
        Row("Enchiladas Verdes", "12.50"),
        Row("Fajita Plate", "15.95"),
        Row("Queso", "6.00", variant="small"),
        Row("Queso", "9.00", variant="large"),
        Row("Chips and Salsa", "4"),  # a bare trailing integer; "&" reads as "and"
        Row("Horchata", "3.25"),
        Row("Agua Fresca", "3.00"),
    ]
    verdicts = _check(rows).verdicts
    assert [v.decision for v in verdicts] == ["accept"] * len(rows)
    assert verdicts[1].reasons == ("shared_section_price",)
    assert verdicts[6].reasons == ("bare_integer_price",)


def test_corruption_mutated_price_is_downgraded() -> None:
    verdict = _check([Row("Enchiladas Verdes", "12.95")]).verdicts[0]
    assert (verdict.decision, verdict.reasons) == ("downgrade", ("price_not_grounded",))
    assert verdict.name_evidence is not None and verdict.price_evidence is None


def test_corruption_swapped_prices_are_downgraded() -> None:
    rows = [Row("Enchiladas Verdes", "15.95"), Row("Fajita Plate", "12.50")]
    assert _decide(rows) == ["downgrade", "downgrade"]
    # two items printed in one block each own only the prices after their name
    assert _decide([Row("Horchata", "3.00"), Row("Agua Fresca", "3.25")]) == [
        "downgrade",
        "downgrade",
    ]


def test_corruption_invented_item_is_rejected() -> None:
    verdict = _check([Row("Birria Tacos", "3.00")]).verdicts[0]
    assert (verdict.decision, verdict.reasons) == ("reject", ("name_not_grounded",))
    assert verdict.name_evidence is None


def test_corruption_price_from_another_section_is_downgraded() -> None:
    # $15.95 is on the page, but in Fajita Plate's region, not Carne Asada's.
    rows = [Row("Carne Asada", "15.95"), Row("Fajita Plate", "15.95")]
    assert _decide(rows) == ["downgrade", "accept"]


def test_sanity_checks_reject() -> None:
    rows = [
        Row("Fajita Plate", "15.95"),
        Row("Fajita Plate", "15.95"),  # duplicate
        Row("Enchiladas Verdes", "1250"),  # implausible
        Row("Queso", "6.00", variant="small", currency="EUR"),
    ]
    verdicts = _check(rows).verdicts
    assert [(v.decision, v.reasons) for v in verdicts] == [
        ("accept", ()),
        ("reject", ("duplicate_row",)),
        ("reject", ("implausible_amount",)),
        ("reject", ("currency",)),
    ]


def test_unpriced_row_and_ungrounded_variant_are_downgraded() -> None:
    rows = [
        Row("Fajita Plate", None),
        Row("Queso", "9.00", variant="small"),  # swapped: $9 is printed as "large"
        Row("Queso", "6.00", variant="large"),
    ]
    assert [(v.decision, v.reasons) for v in _check(rows).verdicts] == [
        ("downgrade", ("no_price_extracted",)),
        ("downgrade", ("price_belongs_to_other_variant",)),
        ("downgrade", ("price_belongs_to_other_variant",)),
    ]
    medium = _check([Row("Queso", "9.00", variant="medium")]).verdicts[0]  # no such label
    assert (medium.decision, medium.reasons) == ("downgrade", ("variant_not_grounded",))


def test_fuzzy_name_matching_is_not_applied() -> None:
    assert _decide([Row("Enchilada Verdes", "12.50")]) == ["reject"]


FAR = """
<h3>Mashed Potatoes</h3><p>Allergens:</p><p>Dairy</p><p>Calories: 300</p><p>Fat: 15g</p>
<p>Truffle oil, garlic cream sauce</p><p>Order Now</p><p>from</p><p>$4.49</p>
<h3>Corn</h3><p>Allergens:</p><p>None</p><p>$3.99</p>
<h3>MMA</h3><h4>$7.50</h4><p>Burger with mayo.</p>
<h3>PILGRIM</h3><h4>$7.75</h4><p>Turkey burger.</p>
<h2>House Special</h2><h3>Black Bean Chicken</h3><div>$16.24</div>
<h2>Chicken</h2><h3>Black Bean Chicken</h3><div>$16.24</div>
<p>Crispy Roasted Duck – Half $20.95/ Whole $41.95</p>
"""


def test_price_run_reaches_past_descriptions_and_stops_at_the_next_item() -> None:
    rows = [
        Row("Mashed Potatoes", "4.49"),
        Row("Corn", "3.99"),
        Row("MMA", "7.50"),
        Row("PILGRIM", "7.75"),
        Row("Black Bean Chicken", "16.24", section="House Special"),
        Row("Black Bean Chicken", "16.24", section="Chicken"),
        Row("Crispy Roasted Duck", "20.95", variant="Half"),
        Row("Crispy Roasted Duck", "41.95", variant="Whole"),
    ]
    assert _decide(rows, FAR) == ["accept"] * len(rows)
    # a price-only heading is not a section price, and Corn's price is Corn's
    assert _decide([Row("MMA", "7.50"), Row("PILGRIM", "7.50")], FAR) == ["accept", "downgrade"]
    assert _decide([Row("Mashed Potatoes", "3.99"), Row("Corn", "3.99")], FAR) == [
        "downgrade",
        "accept",
    ]


V3 = """
<h2>Wine</h2><p>Pinot Noir</p><p>11 / 44</p>
<h2>Mains</h2><p>Charred Eggplantv</p><p>smoky, with tahini</p><p>$19.5</p>
<p>Brisket Plate</p><p>$14</p>
"""


def test_v3_one_decimal_prices_bare_pairs_diet_marks_and_description_rows() -> None:
    rows = [
        Row("Pinot Noir", "11"),
        Row("Pinot Noir", "44"),
        Row("Charred Eggplant", "19.50"),
        Row("smoky, with tahini", None),  # a description line the model emitted as an item
        Row("Brisket Plate", "14"),
    ]
    verdicts = _check(rows, V3).verdicts
    assert [v.decision for v in verdicts] == [
        "accept",
        "accept",
        "accept",
        "downgrade",
        "accept",
    ]
    assert verdicts[0].reasons == ("bare_integer_price",)


def test_price_first_layout() -> None:
    html = "<div>$8.00</div><div>Elote</div><div>Street corn, cotija</div>"
    assert _decide([Row("Elote", "8")], html) == ["accept"]


def test_evidence_locators_cite_block_spans_with_excerpt_hashes() -> None:
    blocks = segment(MENU)
    verdict = validate(blocks, [Row("Fajita Plate", "15.95")]).verdicts[0]
    name, price = verdict.name_evidence, verdict.price_evidence
    assert name is not None and price is not None
    block = next(b for b in blocks if b.text == "Fajita Plate $15.95")
    assert name.block_id == price.block_id == block.id
    assert block.text[name.start : name.end] == "Fajita Plate"
    assert block.text[price.start : price.end] == "$15.95"
    assert price.locator == f"blocks:segment-v2:{block.id}[13:19]"
    assert price.excerpt_hash == "sha256:" + hashlib.sha256(b"$15.95").hexdigest()


def test_claimed_block_picks_among_copies_of_a_name() -> None:
    html = "<h3>Burger</h3><p>$9</p><h3>Lunch</h3><h3>Burger</h3><p>$7</p>"
    blocks = segment(html)
    second = blocks[3].id
    assert _decide([Row("Burger", "7")], html) == ["downgrade"]  # first copy, $9
    assert _decide([Row("Burger", "7", claimed_block=second)], html) == ["accept"]


def test_unlabeled_price_runs_flag() -> None:
    def flagged(body: str) -> bool:
        return validate(segment(body), []).unlabeled_price_runs

    assert flagged("<p>Latte $2.85 | $3.65</p>")
    assert flagged("<p>House wine</p><p>11 / 44</p>")
    assert flagged("<p>Cold Brew</p><div>$3</div><div>$5</div>")
    assert not flagged("<p>Latte Small $2.85 | Large $3.65</p>")
    assert not flagged("<p>Cold Brew</p><div>Small $3</div><div>Large $5</div>")
    assert not flagged("<p>Cold Brew</p><div>$3/Medium</div><div>$5/Large</div>")
    assert not flagged("<p>Taco $3</p><p>Burrito $8</p>"), "labeled by their item names"
    assert not flagged("<p>Latte $3 | $3</p>"), "one amount twice is not a run"
    assert not flagged("<nav><p>$3 $5</p></nav><p>Taco $3</p>"), "chrome is not extracted"


def test_v4_a_dish_repeated_in_another_inline_menu_is_not_a_duplicate() -> None:
    html = "<h2>Lunch</h2><p>Gyoza $8</p><h2>Dinner</h2><p>Gyoza $8</p>"
    rows = [
        Row("Gyoza", "8", section="Zensai", claimed_block="b0002"),
        Row("Gyoza", "8", section="Zensai", claimed_block="b0004"),
        Row("Gyoza", "8", section="Zensai", claimed_block="b0004"),
    ]
    assert [(v.decision, v.reasons) for v in _check(rows, html).verdicts] == [
        ("accept", ()),
        ("accept", ()),
        ("reject", ("duplicate_row",)),
    ]


def test_v4_a_spaced_unit_suffix_is_the_price_label() -> None:
    html = "<p>BLUE CRAB (60-780 cal)$18.00 / LB.</p><p>RAW OYSTERS $18.00 / 6 pcs</p>"
    rows = [
        Row("Blue Crab", "18.00", variant="LB."),
        Row("Raw Oysters", "18.00", variant="6 pcs"),
        Row("Raw Oysters", "18.00", variant="12 pcs"),  # not printed with it
    ]
    assert [(v.decision, v.reasons) for v in _check(rows, html).verdicts] == [
        ("accept", ()),
        ("accept", ()),
        ("downgrade", ("price_belongs_to_other_variant",)),
    ]


DOUBLED = """
<p>$3.50</p><p>Plain Bagel</p><p>Choice of bagel</p><p>$3.50</p>
<p>$4.00</p><p>Everything Bagel</p><p>With seeds</p><p>$4.00</p>
"""


def test_v4_a_price_printed_twice_binds_to_its_own_item() -> None:
    # every price above the name and again below the description: the next item's
    # upper copy ($4.00) follows this item's lower one and is not this item's price
    assert _decide([Row("Plain Bagel", "4.00")], DOUBLED) == ["downgrade"]
    assert _decide([Row("Plain Bagel", "3.50")], DOUBLED) == ["accept"]
    assert _decide([Row("Everything Bagel", "4.00")], DOUBLED) == ["accept"]
    # a size run under each item, the same on every item, is still the item's own
    sizes = "<p>Cheese</p><p>$9</p><p>$15</p><p>Pepperoni</p><p>$9</p><p>$15</p>"
    assert _decide([Row("Pepperoni", "9"), Row("Pepperoni", "15")], sizes) == ["accept"] * 2


def test_v4_an_add_on_price_grounds_no_item_price() -> None:
    html = "<p>Bagel with Cream Cheese $3.50 (vegan +$1)</p><p>Avocado +$1.50 | Queso $1.00</p>"
    rows = [
        Row("Bagel with Cream Cheese", "3.50"),
        Row("Bagel with Cream Cheese", "1.00"),
        Row("Avocado", "1.50"),
        Row("Queso", "1.00"),
    ]
    assert [(v.decision, v.reasons) for v in _check(rows, html).verdicts] == [
        ("accept", ()),
        ("downgrade", ("addon_price",)),
        ("downgrade", ("addon_price",)),
        ("accept", ()),
    ]


def _verdicts(rows: list[Row], html: str) -> list[tuple[str, tuple[str, ...]]]:
    return [(v.decision, v.reasons) for v in _check(rows, html).verdicts]


def test_v5_marked_price_forms_ground_and_cite_the_printed_price() -> None:
    html = "<p>Veg Fried Rice</p><p>12.5 USD</p><p>Sopa</p><p>From4.5 USD</p><p>Extra $.40</p>"
    check = _check([Row("Veg Fried Rice", "12.5"), Row("Sopa", "4.50"), Row("Extra", "0.40")], html)
    assert [v.decision for v in check.verdicts] == ["accept"] * 3
    rice, sopa, extra = (v.price_evidence for v in check.verdicts)
    assert rice is not None and rice.locator == "blocks:segment-v2:b0002[0:8]", "'12.5 USD'"
    assert sopa is not None and (sopa.start, sopa.end) == (4, 11), "'4.5 USD', not 'From'"
    assert extra is not None and (extra.start, extra.end) == (6, 10), "'$.40'"
    # an unmarked one-decimal number is not a price
    assert _decide([Row("IPA", "6.2")], "<p>IPA</p><p>6.2</p><p>% ABV</p>") == ["downgrade"]


def test_v5_an_add_price_line_starts_no_run() -> None:
    html = (
        "<p>Pancakes</p><p>Buttermilk or wheat</p><p>Customize: add $.95 per cake</p>"
        "<p>Cake(1)$4.75</p>"
    )
    assert _decide([Row("Pancakes", "4.75", variant="Cake(1)")], html) == ["accept"]
    assert _verdicts([Row("Pancakes", "0.95")], html) == [("downgrade", ("price_not_grounded",))]


def test_v5_a_name_printed_again_below_is_grounded_at_its_last_copy() -> None:
    card = (
        "<p>French Fries</p><h3>French Fries</h3><p>Appetizers, Vegetarian</p>"
        "<p>Crispy and golden.</p><p>Select options $ 5.99</p><p>Add to wishlist</p>"
    )
    assert _decide([Row("French Fries", "5.99", claimed_block="b0001")], card) == ["accept"]
    # a longer name below is another item, not a copy
    tiers = "<p>Chicken Tenders</p><p>Kids Chicken Tenders</p><p>$7.50</p>"
    assert _decide([Row("Chicken Tenders", "7.50", claimed_block="b0001")], tiers) == ["accept"]


def test_v5_a_label_in_parentheses_or_glued_after_the_price() -> None:
    html = "<p>Caesar Salad</p><p>$6.99 (Sm) / $8.99 (Lg)</p><p>Prosecco</p><p>$9gl | $32btl</p>"
    rows = [
        Row("Caesar Salad", "8.99", variant="Lg"),
        Row("Caesar Salad", "6.99", variant="Lg"),
        Row("Prosecco", "32", variant="btl"),
        Row("Prosecco", "9", variant="btl"),
    ]
    assert _verdicts(rows, html) == [
        ("accept", ()),
        ("downgrade", ("variant_not_grounded",)),
        ("accept", ()),
        ("downgrade", ("variant_not_grounded",)),
    ]
    # a label printed before the price wins over a description in parentheses
    cakes = "<p>Novelty Cakes</p><p>6” – $65 (8-12 servings) | 7” – $80 (15-20 servings)</p>"
    assert _decide([Row("Novelty Cakes", "80", variant="7”")], cakes) == ["accept"]


COLUMNS = """
<h2>Draft Beers</h2><p>16oz / 20oz / Pitcher</p>
<p>HELLES — / $8.95 / —</p><p>LAGER $8 / $9.95 / $24.95</p><p>Crisp and malty.</p>
<p>IPA $8.25 / $10.25 / $25.95</p>
<h2>Taps</h2><p>16oz / 22oz / 32oz</p>
<p>Kolsch</p><p>7</p><p>/</p><p>9</p><p>/</p><p>12</p>
<p>Pilsner</p><p>6</p><p>/</p><p>8</p><p>/</p><p>10</p>
"""


def test_v5_a_column_header_labels_each_price_column() -> None:
    rows = [
        Row("Helles", "8.95", variant="20oz"),
        Row("Lager", "24.95", variant="Pitcher"),
        Row("IPA", "8.25", variant="16oz"),
        Row("IPA", "10.25", variant="16oz"),
        Row("Kolsch", "12", variant="32oz"),
        Row("Pilsner", "8", variant="22oz"),
    ]
    assert [v.decision for v in _check(rows, COLUMNS).verdicts] == [
        "accept",
        "accept",
        "accept",
        "downgrade",
        "accept",
        "accept",
    ]


def test_v5_a_description_line_under_one_item_is_no_column_header() -> None:
    wine = "<p>Crianza</p><p>Tempranillo | Rioja, Spain</p><p>12/48</p><p>Malbec</p><p>46</p>"
    assert _verdicts([Row("Crianza", "48", variant="Rioja, Spain")], wine) == [
        ("downgrade", ("variant_not_grounded",))
    ]


def test_v5_an_add_on_on_its_own_line_is_an_item() -> None:
    html = "<p>Add Sauerkraut +1</p><p>Avocado +$1.50 | Guacamole +$1.50</p>"
    rows = [Row("Add Sauerkraut", "1"), Row("Avocado", "1.50")]
    assert _verdicts(rows, html) == [
        ("accept", ("bare_integer_price",)),
        ("downgrade", ("addon_price",)),
    ]


def test_v5_names_joined_in_a_one_price_row_share_the_price() -> None:
    html = "<p>sidral, sangría & topo chico $3.25</p><p>Tea or Coffee $2</p>"
    rows = [
        Row("sidral", "3.25"),
        Row("sangría", "3.25"),
        Row("topo chico", "3.25"),
        Row("Tea", "2"),  # "A or B" is one item
        Row("Coffee", "2"),
    ]
    assert [v.decision for v in _check(rows, html).verdicts] == [
        "accept",
        "accept",
        "accept",
        "downgrade",
        "accept",
    ]
    # several prices in the block: each name keeps only its own
    inline = "<p>Chicken 14.99, Beef 15.99, Shrimp 16.99</p>"
    rows = [Row("Chicken", "16.99"), Row("Beef", "15.99"), Row("Shrimp", "16.99")]
    assert _decide(rows, inline) == ["downgrade", "accept", "accept"]


def test_v5_an_underscore_separates_a_name_from_its_price() -> None:
    html = "<p>Fried plantain with cheese. Arepas_12 OUR MENU Tajadas con Queso_8</p>"
    assert _decide([Row("Arepas", "12"), Row("Tajadas con Queso", "8")], html) == [
        "accept",
        "accept",
    ]
