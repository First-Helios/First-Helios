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
