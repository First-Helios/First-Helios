"""Synthetic checks for the stage [5] validator (run: uv run pytest spikes/menu_model)."""

from __future__ import annotations

from spikes.menu_model.segment import segment
from spikes.menu_model.validator import Row, validate

HTML = """
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


def _decide(rows: list[Row], **kw: bool) -> list[str]:
    return [v.decision for v in validate(segment(HTML), rows, **kw)]


def test_correct_rows_accept() -> None:
    rows = [
        Row("Carne Asada", "3.00"),
        Row("Al Pastor", "3"),  # shared section price
        Row("Enchiladas Verdes", "12.50"),
        Row("Fajita Plate", "15.95"),
        Row("Queso", "6.00", variant="small"),
        Row("Queso", "9.00", variant="large"),
        Row("Chips and Salsa", "4"),  # bare integer, & == and
        Row("Horchata", "3.25"),
        Row("Agua Fresca", "3.00"),
    ]
    assert _decide(rows) == ["accept"] * len(rows)


def test_invented_item_rejected() -> None:
    assert _decide([Row("Birria Tacos", "3.00")]) == ["reject"]


def test_mutated_price_downgraded() -> None:
    assert _decide([Row("Enchiladas Verdes", "12.95")]) == ["downgrade"]


def test_swapped_prices_downgraded() -> None:
    rows = [Row("Enchiladas Verdes", "15.95"), Row("Fajita Plate", "12.50")]
    assert _decide(rows) == ["downgrade", "downgrade"]


def test_same_block_binding() -> None:
    rows = [Row("Horchata", "3.00"), Row("Agua Fresca", "3.25")]
    assert _decide(rows) == ["downgrade", "downgrade"]


def test_price_from_other_section() -> None:
    # $15.95 exists on the page, but in Fajita Plate's region, not Carne Asada's.
    assert _decide([Row("Carne Asada", "15.95"), Row("Fajita Plate", "15.95")]) == [
        "downgrade",
        "accept",
    ]


def test_duplicate_and_sanity() -> None:
    rows = [
        Row("Fajita Plate", "15.95"),
        Row("Fajita Plate", "15.95"),
        Row("Enchiladas Verdes", "1250"),
    ]
    assert _decide(rows) == ["accept", "reject", "reject"]


def test_fuzzy_is_opt_in() -> None:
    assert _decide([Row("Enchilada Verdes", "12.50")]) == ["reject"]
    assert _decide([Row("Enchilada Verdes", "12.50")], fuzzy=True) == ["accept"]


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


def test_v2_far_price_run_and_boundaries() -> None:
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
    assert [v.decision for v in validate(segment(FAR), rows)] == ["accept"] * len(rows)


def test_v2_price_only_heading_is_not_a_section_price() -> None:
    rows = [Row("MMA", "7.50"), Row("PILGRIM", "7.50")]
    assert [v.decision for v in validate(segment(FAR), rows)] == ["accept", "downgrade"]


def test_v2_run_does_not_cross_into_next_item() -> None:
    # Mashed Potatoes must not borrow Corn's $3.99 even though Corn's price is near.
    rows = [Row("Mashed Potatoes", "3.99"), Row("Corn", "3.99")]
    assert [v.decision for v in validate(segment(FAR), rows)] == ["downgrade", "accept"]
