"""The place check: ``place-v1`` (ADR-0015 Amendment 2) and ADR-0025 D2′, pure parts.

Pages are segmented HTML, as discovery and the sweep see them. The area is a
small Austin one; the cases are the shapes the P8-18 sweep found on stored pages.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from apps.discovery.place_check import (
    STRUCK_PRICE,
    PlaceArea,
    VenuePlace,
    foreign_slugs,
    mentions,
    other_location_places,
    place_failure,
    place_verdict,
    slug,
    store_catalog,
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


# --------------------------------------------------------------------------- #
# Another location's page (ADR-0025 D2′): the URL names another place of the metro.
# --------------------------------------------------------------------------- #

METRO = replace(
    AREA,
    localities=frozenset({"austin", "round rock", "driftwood", "cedar park"}),
    principal="austin",
)
ROUND_ROCK = VenuePlace(locality="Round Rock", region="TX", postcode="78664")


def test_a_url_naming_another_metro_place_is_another_locations() -> None:
    url = "https://www.saltlickbbq.com/round-rock-menu"
    assert other_location_places(url, VENUE, METRO) == ("round-rock",)
    assert other_location_places("https://x.com/menus/driftwood", ROUND_ROCK, METRO) == (
        "driftwood",
    )
    assert other_location_places("https://x.com/menu/las-vegas", VENUE, METRO) == ("las-vegas",)


def test_a_url_naming_the_venues_locality_is_its_own() -> None:
    url = "https://www.saltlickbbq.com/round-rock-menu"
    assert other_location_places(url, ROUND_ROCK, METRO) == ()
    assert other_location_places("https://x.com/round-rock/driftwood", ROUND_ROCK, METRO) == ()


def test_the_principal_city_says_nothing_for_a_suburb_venue() -> None:
    url = "https://www.flowerchild.com/austin-westlake-menu"
    assert other_location_places(url, ROUND_ROCK, METRO) == ()


def test_no_place_no_locality_or_a_short_run_is_not_judged() -> None:
    assert other_location_places("https://x.com/dinner-menu", VENUE, METRO) == ()
    nowhere = VenuePlace(locality=None, region="TX", postcode=None)
    assert other_location_places("https://x.com/round-rock-menu", nowhere, METRO) == ()
    short = replace(METRO, gazetteer=frozenset({"ely"}))
    assert other_location_places("https://x.com/ely-menu", VENUE, short) == ()


def test_only_the_path_counts_not_the_host_or_query() -> None:
    url = "https://roundrock-bbq.com/menu?location=round-rock"
    assert other_location_places(url, VENUE, METRO) == ()


def test_place_failure_tells_another_metro_from_another_location() -> None:
    blocks = segment("<p>Brisket $20</p>")
    url = "https://www.saltlickbbq.com/round-rock-menu"
    assert place_failure(url, blocks, VENUE, METRO, own_site=True) == "other_location"
    assert place_failure(url, blocks, VENUE, METRO, own_site=False) is None
    vegas = "https://tiltedkilt.com/menu/las-vegas-menu"
    assert place_failure(vegas, blocks, VENUE, METRO, own_site=True) == "wrong_place"


# (ADR-0015 Amendment 4, place-v3) a store catalog, in the shapes P8-24 found stored


def _items(n: int, struck: str) -> str:
    return "".join(
        f"<div><p>Organic Chia Seeds 32 Oz (Pack of {k})</p><p>$14.12</p><p>{struck}</p>"
        "<p>Add to cart</p></div>"
        for k in range(n)
    )


def test_a_grocery_listing_with_list_prices_is_a_store_catalog() -> None:
    assert store_catalog(segment(_items(3, "Typical price:$27.94")))
    assert store_catalog(segment(_items(3, "List Price:$10.99")))
    assert store_catalog(segment(_items(3, "current price $11.15, Was $12.85")))
    assert store_catalog(segment(_items(3, "Compare at $9.00")))


def test_one_or_two_struck_prices_or_chrome_ones_are_no_catalog() -> None:
    assert not store_catalog(segment(_items(2, "Was $12.85")))  # a menu's one promo
    chrome = "".join(f"<footer><p>List Price: ${k}</p></footer>" for k in range(5))
    assert not store_catalog(segment("<p>Brisket $20</p>" + chrome))


def test_unit_prices_packs_and_a_stray_marker_on_a_menu_stay_below_the_bar() -> None:
    # unit prices and pack sizes are menu shapes too (BBQ by the pound, beer six-packs);
    # "Regular Price" without an amount is a specials table's header, not a struck price
    menu = (
        "<h2>Daily specials</h2><p>Regular Price</p><p>Chicken Fried Steak</p><p>$14.99</p>"
        "<p>Brisket (by the lb) $24.99/lb</p><p>Beer 6-pack $12</p>"
        "<p>It was $9.99 on Monday</p><p>The list price of wine varies</p>"
    )
    blocks = segment(menu)
    assert sum(1 for b in blocks if STRUCK_PRICE.search(b.text)) == 2  # the last two
    assert not store_catalog(blocks)


def test_place_failure_names_a_store_catalog_first() -> None:
    blocks = segment(_items(3, "Typical price:$27.94"))
    url = "https://www.amazon.com/fmc/everyday-essentials-category"
    assert place_failure(url, blocks, VENUE, METRO, own_site=True) == "store_catalog"
    assert place_failure(url, blocks, VENUE, METRO, own_site=False) == "store_catalog"
