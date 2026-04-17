"""Unit tests for collectors.meal_deals.menu_sidecar (STRUCT-01 / TARGET-01)."""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from collectors.meal_deals.menu_sidecar import (
    MenuSidecar,
    classify_course,
    classify_service_period,
    ingest_dom_fallback,
    ingest_jsonld_from_html,
    ingest_jsonld_payload,
    link_signal_to_target,
)


LAPOSADA_MENU_PAYLOAD = {
    "@context": "https://schema.org",
    "@type": "Menu",
    "@id": "https://www.laposadasouth.com/menu/limited-lunch-specials/#menu",
    "name": "LIMITED LUNCH SPECIALS",
    "description": "FAMILY PACK SPECIALS",
    "hasMenuSection": {
        "@type": "MenuSection",
        "name": "Family Packs",
        "hasMenuItem": [
            {
                "@type": "MenuItem",
                "name": "Fajita platter",
                "description": "Chicken or Beef Fajitas with sides",
                "offers": {"@type": "Offer", "price": "95.99", "priceCurrency": "USD"},
            },
            {
                "@type": "MenuItem",
                "name": "Taco Platter",
                "description": "12 Tacos with sides",
                "offers": {"@type": "Offer", "price": "54.99", "priceCurrency": "USD"},
            },
            {
                "@type": "MenuItem",
                "name": "Enchilada Platter",
                "description": "12 enchiladas with sides",
                "offers": {"@type": "Offer", "price": "59.99", "priceCurrency": "USD"},
            },
        ],
    },
}


def test_jsonld_ingest_builds_sections_items_and_prices():
    sidecar = MenuSidecar()
    ingest_jsonld_payload(LAPOSADA_MENU_PAYLOAD, page_url="https://laposadasouth.com/menu", sidecar=sidecar)

    assert len(sidecar.sections) == 2  # top-level Menu + nested MenuSection
    assert len(sidecar.items) == 3
    assert len(sidecar.price_points) == 3

    top_section = next(s for s in sidecar.sections.values() if s.name == "LIMITED LUNCH SPECIALS")
    assert top_section.service_period == "lunch"

    fajita = next(i for i in sidecar.items.values() if i.name == "Fajita platter")
    fajita_pps = [pp for pp in sidecar.price_points.values() if pp.item_key == fajita.key]
    assert len(fajita_pps) == 1
    assert fajita_pps[0].price == 95.99
    assert fajita_pps[0].currency == "USD"
    assert fajita_pps[0].source == "jsonld"

    # Entree course assignment on items driven by description keywords.
    assert any(item.course == "entree" for item in sidecar.items.values())


def test_jsonld_ingest_handles_graph_and_id_references():
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "FoodEstablishment",
                "@id": "https://example.com/#restaurant",
                "name": "Test Cafe",
                "hasMenu": {"@id": "https://example.com/#menu"},
            },
            {
                "@type": "Menu",
                "@id": "https://example.com/#menu",
                "name": "Happy Hour Menu",
                "hasMenuItem": [
                    {
                        "@type": "MenuItem",
                        "name": "House Margarita",
                        "offers": {"@type": "Offer", "price": 6.0, "priceCurrency": "USD"},
                    }
                ],
            },
        ],
    }
    sidecar = MenuSidecar()
    ingest_jsonld_payload(payload, page_url="https://example.com/menu", sidecar=sidecar)

    section = next(iter(sidecar.sections.values()))
    assert section.service_period == "happy_hour"
    assert any(item.name == "House Margarita" for item in sidecar.items.values())
    assert any(pp.price == 6.0 for pp in sidecar.price_points.values())


def test_dom_fallback_pairs_heading_with_item_list():
    html = """
    <html><body>
      <h2>Lunch Specials</h2>
      <ul>
        <li>Grilled Chicken Sandwich $9.50</li>
        <li>Cheeseburger Combo $11.00</li>
        <li>Caesar Salad $8.25</li>
      </ul>
      <h2>About Us</h2>
      <p>Our story since 1982.</p>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    sidecar = MenuSidecar()
    ingest_dom_fallback(soup, page_url="https://example.com/menu", sidecar=sidecar)

    section = next(iter(sidecar.sections.values()))
    assert section.name == "Lunch Specials"
    assert section.service_period == "lunch"
    assert section.source == "dom"

    names = {item.name for item in sidecar.items.values()}
    assert "Grilled Chicken Sandwich" in names
    prices = sorted(pp.price for pp in sidecar.price_points.values())
    assert prices == [8.25, 9.5, 11.0]
    # About Us heading must NOT produce a section (no menu-hint match).
    assert all(s.name == "Lunch Specials" for s in sidecar.sections.values())


def test_link_signal_to_target_resolves_by_path_and_name():
    sidecar = MenuSidecar()
    ingest_jsonld_payload(LAPOSADA_MENU_PAYLOAD, page_url="https://laposadasouth.com/menu", sidecar=sidecar)

    target = link_signal_to_target(
        sidecar,
        signal_ref="fajita_platter",
        page_url="https://laposadasouth.com/menu",
        context_path=["LIMITED LUNCH SPECIALS", "Family Packs"],
        primary_name="Fajita platter",
    )
    assert target is not None
    assert target["scope"] == "item"
    assert target["section_key"] is not None
    assert target["item_key"] is not None

    # Unknown item still returns a section target when the path matches.
    target2 = link_signal_to_target(
        sidecar,
        signal_ref="unknown_promo",
        page_url="https://laposadasouth.com/menu",
        context_path=["LIMITED LUNCH SPECIALS"],
        primary_name="Unknown Promo That Does Not Exist",
    )
    assert target2 is not None
    assert target2["scope"] == "section"


def test_link_signal_to_target_falls_back_to_service_period():
    sidecar = MenuSidecar()
    target = link_signal_to_target(
        sidecar,
        signal_ref="hh_beer",
        page_url="https://example.com/menu",
        context_path=[],
        primary_name=None,
        service_period="happy_hour",
    )
    assert target is not None
    assert target["scope"] == "service_period"
    assert target["service_period"] == "happy_hour"


def test_course_and_service_period_classifiers():
    assert classify_service_period("HAPPY HOUR MENU") == "happy_hour"
    assert classify_service_period("Lunch Specials") == "lunch"
    assert classify_service_period("Dinner Entrees") == "dinner"
    assert classify_service_period("Our story") is None

    assert classify_course("Appetizers") == "appetizer"
    assert classify_course("House Burgers") == "entree"
    assert classify_course("Desserts") == "dessert"
    assert classify_course("Cocktails") == "drink"


def test_sidecar_respects_entity_caps():
    sidecar = MenuSidecar()
    # Build a tiny payload repeatedly to exceed the 80-section cap.
    for i in range(120):
        payload = {
            "@type": "Menu",
            "name": f"Menu {i}",
            "hasMenuItem": [{"@type": "MenuItem", "name": f"Item {i}",
                             "offers": {"@type": "Offer", "price": "5.0"}}],
        }
        ingest_jsonld_payload(payload, page_url=f"https://ex.com/m{i}", sidecar=sidecar)

    assert len(sidecar.sections) <= 80


def test_ingest_pdf_tables_detects_price_column():
    from collectors.meal_deals.menu_sidecar import ingest_pdf_tables
    tables = [
        [
            ["Item", "Price"],
            ["House Margarita", "$6.00"],
            ["Beef Taco", "$3.50"],
            ["Chicken Quesadilla", "$9.75"],
        ],
    ]
    sidecar = MenuSidecar()
    ingest_pdf_tables(tables, page_url="https://ex.com/happy-hour.pdf",
                      section_hint="happy-hour", sidecar=sidecar)

    assert len(sidecar.sections) == 1
    section = next(iter(sidecar.sections.values()))
    assert section.service_period == "happy_hour"
    names = {i.name for i in sidecar.items.values()}
    assert names == {"House Margarita", "Beef Taco", "Chicken Quesadilla"}
    prices = sorted(pp.price for pp in sidecar.price_points.values())
    assert prices == [3.5, 6.0, 9.75]


def test_ingest_pdf_tables_rejects_non_price_tables():
    from collectors.meal_deals.menu_sidecar import ingest_pdf_tables
    tables = [
        [
            ["Calories", "Fat", "Sodium"],
            ["450", "22g", "900mg"],
            ["380", "18g", "700mg"],
        ],
    ]
    sidecar = MenuSidecar()
    ingest_pdf_tables(tables, page_url="https://ex.com/nutrition.pdf", sidecar=sidecar)
    assert sidecar.sections == {}
    assert sidecar.items == {}
    assert sidecar.price_points == {}


def test_value_profile_summary_reports_course_medians():
    sidecar = MenuSidecar()
    ingest_jsonld_payload(LAPOSADA_MENU_PAYLOAD, page_url="https://example.com/menu", sidecar=sidecar)
    vp = sidecar.value_profile()
    assert vp["has_structured_menu"] is True
    assert "entree" in vp["courses"]
    entree = vp["courses"]["entree"]
    assert entree["sample_size"] == 3
    assert entree["median"] == 59.99


def test_ingest_jsonld_from_html_tolerates_malformed_scripts():
    html = """
      <script type="application/ld+json">{ this is not json }</script>
      <script type="application/ld+json">{ "@type": "Menu", "name": "Brunch",
        "hasMenuItem": [{"@type": "MenuItem", "name": "Avocado Toast",
        "offers": {"@type": "Offer", "price": "9.00"}}] }</script>
    """
    sidecar = MenuSidecar()
    ingest_jsonld_from_html(html, page_url="https://example.com", sidecar=sidecar)
    assert any(s.name == "Brunch" for s in sidecar.sections.values())
    assert any(i.name == "Avocado Toast" for i in sidecar.items.values())
