"""The schema.org JSON-LD menu reader (ADR-0013 §1) on synthetic pages."""

from __future__ import annotations

import json

from packages.helios_parsing.jsonld import MenuItem, Offer, menu_items, validator_rows
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, validate

_MENU = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Restaurant", "name": "Taqueria"},
        {
            "@type": "Menu",
            "hasMenuSection": [
                {
                    "@type": "MenuSection",
                    "name": "Tacos",
                    "hasMenuItem": [
                        {
                            "@type": "MenuItem",
                            "name": " Carne Asada ",
                            "description": "Grilled steak",
                            "offers": {"@type": "Offer", "price": "3.50", "priceCurrency": "USD"},
                        },
                        {
                            "@type": ["MenuItem", "Product"],
                            "name": "Al Pastor",
                            "offers": [{"price": 3}, {"price": "$4.25"}],
                        },
                    ],
                    "hasMenuSection": {
                        "@type": "MenuSection",
                        "name": "Specials",
                        "hasMenuItem": {
                            "@type": "MenuItem",
                            "name": "Birria",
                            "offers": {"@type": "AggregateOffer", "lowPrice": 5},
                        },
                    },
                },
                {
                    "@type": "MenuSection",
                    "name": "Drinks",
                    "hasMenuItem": [
                        {"@type": "MenuItem", "name": "Horchata"},
                        {"@type": "MenuItem", "name": "Mezcal", "offers": {"price": "NaN"}},
                        {"@type": "MenuItem", "name": "Case", "offers": {"price": "1,200"}},
                        {"@type": "MenuItem", "name": "", "offers": {"price": "2"}},
                    ],
                },
            ],
        },
    ],
}


def _page(payload: object, body: str = "") -> str:
    return (
        '<html><head><script type="application/ld+json">'
        f"{json.dumps(payload)}</script>"
        "<script type='application/ld+json'>{not json</script></head>"
        f"<body>{body}</body></html>"
    )


def test_reads_menu_sections_items_and_offers() -> None:
    assert menu_items(_page(_MENU)) == [
        MenuItem("Carne Asada", "Tacos", "Grilled steak", (Offer("3.50", "USD"),)),
        MenuItem("Al Pastor", "Tacos", None, (Offer("3.00", None), Offer("4.25", None))),
        MenuItem("Birria", "Specials", None, (Offer("5.00", None),)),
        MenuItem("Horchata", "Drinks", None, ()),
        MenuItem("Mezcal", "Drinks", None, ()),  # a non-finite price is no price
        MenuItem("Case", "Drinks", None, ()),  # 1,200 is out of range
    ]


def test_no_json_ld_means_no_items() -> None:
    assert menu_items("<html><body><p>Tacos $3</p></body></html>") == []


def test_validator_rows_one_per_offer_with_currency() -> None:
    items = [
        MenuItem("Al Pastor", "Tacos", None, (Offer("3.00", None), Offer("4.25", "EUR"))),
        MenuItem("Horchata", "Drinks", None, ()),
    ]
    assert validator_rows(items) == [
        Row("Al Pastor", "3.00", section="Tacos", currency="USD"),
        Row("Al Pastor", "4.25", section="Tacos", currency="EUR"),
        Row("Horchata", None, section="Drinks"),
    ]


def test_json_ld_prices_must_be_on_the_visible_page() -> None:
    """A structured price the page doesn't print is downgraded; an item the page
    doesn't show at all is rejected."""
    body = "<h2>Tacos</h2><p>Carne Asada $3.50</p><p>Al Pastor $3.25</p><p>Birria $5</p>"
    html = _page(_MENU, body)
    rows = validator_rows(menu_items(html))
    decisions = {
        (v.row.item, v.row.amount): (v.decision, v.reasons)
        for v in validate(segment(html), rows).verdicts
    }
    assert decisions[("Carne Asada", "3.50")] == ("accept", ())
    assert decisions[("Al Pastor", "3.00")] == ("downgrade", ("price_not_grounded",))
    assert decisions[("Al Pastor", "4.25")] == ("downgrade", ("price_not_grounded",))
    assert decisions[("Birria", "5.00")] == ("accept", ())
    assert decisions[("Horchata", None)] == ("reject", ("name_not_grounded",))
