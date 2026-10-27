"""The wrong-place page check ``place-v1`` (ADR-0015 Amendment 2), pure parts.

Pages are segmented HTML, as discovery and the sweep see them. The area is a
small Austin one; the cases are the shapes the P8-18 sweep found on stored pages.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from apps.discovery.place_check import (
    PlaceArea,
    VenuePlace,
    foreign_slugs,
    mentions,
    place_verdict,
    slug,
)
from packages.helios_parsing.segment import segment

AREA = PlaceArea(
    localities=frozenset({"austin", "round rock"}),
    postcodes=frozenset({"78701", "78752"}),
    regions=frozenset({"TX"}),
    gazetteer=frozenset({"las-vegas", "scottsdale", "southlake"}),
)
VENUE = VenuePlace(locality="Austin", region="TX", postcode="78752")


def _verdict(
    html: str, url: str = "https://example.com/menu", area: PlaceArea = AREA
) -> tuple[bool, tuple[str, ...]]:
    verdict = place_verdict(url, segment(html), VENUE, area)
    return verdict.wrong, verdict.evidence


def test_another_restaurants_page_named_again_and_again_is_wrong_place() -> None:
    html = "".join(f"<p>Dish {n} (4) in Galloway, NJ</p>" for n in range(3))
    url = "https://www.smorefood.com/mo0r1opc/best-food-in-town--smithville-galloway-08205/order"
    assert _verdict(html, url) == (True, ("url_place", "dominant"))


def test_an_out_of_town_street_address_is_wrong_place() -> None:
    html = "<p>Pho</p><footer>11677 SW Beaverton Hillsdale Hwy, Beaverton, OR 97005</footer>"
    assert _verdict(html) == (True, ("address",))


def test_the_same_address_on_a_chain_page_is_its_head_office() -> None:
    html = "<p>Chicken</p><footer>100 Main St, Alexandria, LA 71301</footer>"
    chain = replace(AREA, chain_urls=frozenset({"https://example.com/menu"}))
    assert _verdict(html, area=chain) == (False, ())


def test_a_page_naming_the_metro_is_the_venues_own() -> None:
    html = "<p>Tacos</p><footer>720 Lamar Pl, Austin, TX 78752</footer>"
    assert _verdict(html) == (False, ())


def test_a_chain_location_list_that_includes_the_metro_is_not_wrong_place() -> None:
    places = ("Peoria, AZ", "Rogers, AR", "Lakeland, FL", "Austin, TX")
    html = "<nav>" + "".join(f"<li>{p}</li>" for p in places) + "</nav><p>Enchiladas</p>"
    wrong, _ = _verdict(html)
    assert not wrong


def test_another_locations_url_is_wrong_place_even_when_the_page_lists_austin() -> None:
    html = "<p>Event menus</p><nav><li>Austin, TX</li><li>Scottsdale, AZ</li></nav>"
    url = "https://www.roaringfork.com/scottsdale-event-menus"
    assert _verdict(html, url) == (True, ("url_place",))


def test_a_url_naming_the_metro_is_never_another_locations() -> None:
    html = "<p>Menu</p><nav><li>Austin, TX</li><li>Scottsdale, AZ</li></nav>"
    url = "https://example.com/austin-scottsdale-menu"
    assert _verdict(html, url) == (False, ("url_place",))


def test_a_gazetteer_city_in_the_url_of_a_page_that_names_no_place() -> None:
    url = "https://tiltedkilt.com/menu/las-vegas-menuxx"
    assert _verdict("<p>Wings $12</p>", url) == (True, ("url_place",))


def test_an_in_state_city_outside_the_metro_is_foreign() -> None:
    url = "https://www.brioitalian.com/menu/dinner/southlake"
    assert _verdict("<p>Pasta</p>", url) == (True, ("url_place",))
    assert _verdict("<p>Pasta</p>", "https://example.com/round-rock/menu") == (False, ())


def test_a_wine_list_is_many_places_not_one() -> None:
    wines = ("Napa Valley, CA", "Paso Robles, CA", "Columbia Valley, WA", "Napa Valley, CA")
    html = "<h2>Wines by the Glass</h2>" + "".join(f"<p>Cabernet, {w} 14</p>" for w in wines)
    assert _verdict(html) == (False, ())


@pytest.mark.parametrize(
    "text",
    [
        "Aloha, NY! Pizza",  # a dish name, not a place
        "Buffalo, TX hot, BBQ, lemon pepper",  # a wing flavour
        "MEATS, POULTRY, SEAFOOD, OR EGGS MAY INCREASE YOUR RISK",  # all caps, no ZIP
    ],
)
def test_name_shaped_mentions_are_not_places(text: str) -> None:
    assert mentions(segment(f"<p>{text}</p><p>{text}</p>")) == []


def test_an_all_caps_city_with_a_zip_is_a_place() -> None:
    (mention,) = mentions(segment("<p>6547 Allen Road, ALLEN PARK, MI 48101</p>"))
    assert (mention.city, mention.state, mention.zip) == ("ALLEN PARK", "MI", "48101")


def test_downtown_austin_is_metro_and_a_metro_zip_names_the_metro() -> None:
    assert _verdict("<p>Downtown Austin, TX</p><p>Downtown Austin, TX</p>") == (False, ())
    assert _verdict("<footer>Lakeway Dr, Lakeway, TX 78701</footer>") == (False, ())


def test_a_house_number_in_a_url_is_no_zip() -> None:
    url = "https://www.grubhub.com/restaurant/chick-fil-a-11900-us-290-manor/10931056"
    assert _verdict("<p>Sandwich</p>", url) == (False, ())


def test_the_gazetteer_takes_foreign_cities_outside_wine_lists() -> None:
    html = (
        "<nav><li>Austin, TX</li><li>Las Vegas, NV</li><li>College Station, TX</li></nav>"
        "<h2>Wine</h2><p>Napa Valley, CA</p>"
    )
    assert foreign_slugs(segment(html), AREA) == {"las-vegas", "college-station"}
    assert slug("St. Louis") == "st-louis"
