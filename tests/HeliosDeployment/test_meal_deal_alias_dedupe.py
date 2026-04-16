from datetime import datetime, timezone

from collectors.meal_deals.routes import _collapse_duplicate_deals
from core.database import LocalEmployer, MealDeal
from core.venue_identity import likely_same_venue


def _build_employer(
    employer_id: int,
    *,
    name: str,
    address: str,
    brand_group_id: int | None,
    lat: float,
    lng: float,
) -> LocalEmployer:
    return LocalEmployer(
        id=employer_id,
        raw_name=name,
        name=name,
        address=address,
        brand_group_id=brand_group_id,
        lat=lat,
        lng=lng,
        region="austin_tx",
        source="overture",
    )


def _build_deal(
    deal_id: int,
    *,
    employer_id: int,
    brand_group_id: int | None,
    lat: float,
    lng: float,
    signal_quality: float = 0.73,
) -> MealDeal:
    return MealDeal(
        id=deal_id,
        local_employer_id=employer_id,
        brand_group_id=brand_group_id,
        is_chain_template=False,
        deal_name="Combo Plate $18",
        deal_description="Combo Plate special",
        deal_type="combo",
        price=18.0,
        price_type="absolute",
        source="website_scrape",
        source_url="https://polvosaustin.com/austin-polvos-south-food-menu",
        verified_at=datetime(2026, 4, 16, 1, 10, 52, tzinfo=timezone.utc),
        signal_quality=signal_quality,
        lat=lat,
        lng=lng,
        region="austin_tx",
        is_active=True,
    )


def test_likely_same_venue_matches_polvos_aliases():
    assert likely_same_venue(
        name_a="Polvos Bratton",
        address_a="14735 Bratton Ln, Austin, TX",
        url_a="https://polvosaustin.com/austin-barton-creek-mall-polvos-barton-creek-locations",
        lat_a=30.44599,
        lng_a=-97.68572,
        name_b="Polvos Mexican Restaurant North",
        address_b="14735 Bratton Ln #205, Austin, TX",
        url_b="https://polvosaustin.com/austin-barton-creek-mall-polvos-barton-creek-locations",
        lat_b=30.44906,
        lng_b=-97.68265,
    )


def test_likely_same_venue_matches_nearby_address_variants():
    assert likely_same_venue(
        name_a="Yard House",
        address_a="11800 Domain Blvd, Austin, TX",
        url_a="https://www.yardhouse.com/locations/tx/austin/austin-domain/8378",
        lat_a=30.40110,
        lng_a=-97.72510,
        name_b="Yardhouse Domain",
        address_b="11811 Domain Dr, Austin, TX",
        url_b="https://www.yardhouse.com/locations/tx/austin/austin-domain/8378",
        lat_b=30.40142,
        lng_b=-97.72482,
    )


def test_collapse_duplicate_deals_prefers_canonical_alias_row():
    employers = {
        38677: _build_employer(
            38677,
            name="Polvos Bratton",
            address="14735 Bratton Ln, Austin, TX",
            brand_group_id=38677,
            lat=30.44599,
            lng=-97.68572,
        ),
        41201: _build_employer(
            41201,
            name="Polvos Mexican Restaurant North",
            address="14735 Bratton Ln, Austin, TX",
            brand_group_id=41201,
            lat=30.446054045051,
            lng=-97.685658122487,
        ),
        42350: _build_employer(
            42350,
            name="Polvos Mexican Restaurant North",
            address="14735 Bratton Ln #205, Austin, TX",
            brand_group_id=41201,
            lat=30.44906,
            lng=-97.68265,
        ),
    }

    deals = [
        _build_deal(1, employer_id=38677, brand_group_id=38677, lat=30.44599, lng=-97.68572),
        _build_deal(2, employer_id=41201, brand_group_id=41201, lat=30.446054045051, lng=-97.685658122487, signal_quality=0.83),
        _build_deal(3, employer_id=42350, brand_group_id=41201, lat=30.44906, lng=-97.68265),
    ]

    collapsed = _collapse_duplicate_deals(deals, employers)

    assert len(collapsed) == 1
    assert collapsed[0].id == 2
    assert collapsed[0].local_employer_id == 41201


def test_collapse_duplicate_deals_keeps_real_multi_location_rows():
    employers = {
        101: _build_employer(
            101,
            name="ThunderCloud Subs",
            address="3801 S Congress Ave, Austin, TX",
            brand_group_id=5001,
            lat=30.2267,
            lng=-97.7602,
        ),
        102: _build_employer(
            102,
            name="ThunderCloud Subs",
            address="2500 W Anderson Ln, Austin, TX",
            brand_group_id=5001,
            lat=30.3578,
            lng=-97.7334,
        ),
    }

    deals = [
        MealDeal(
            id=10,
            local_employer_id=101,
            brand_group_id=5001,
            is_chain_template=False,
            deal_name="$7.99 Lunch Combo",
            deal_description="Lunch combo",
            deal_type="combo",
            price=7.99,
            price_type="absolute",
            source="website_scrape",
            source_url="https://thundercloud.com/menu/lunch-specials",
            verified_at=datetime(2026, 4, 16, 1, 10, 52, tzinfo=timezone.utc),
            signal_quality=0.8,
            lat=30.2267,
            lng=-97.7602,
            region="austin_tx",
            is_active=True,
        ),
        MealDeal(
            id=11,
            local_employer_id=102,
            brand_group_id=5001,
            is_chain_template=False,
            deal_name="$7.99 Lunch Combo",
            deal_description="Lunch combo",
            deal_type="combo",
            price=7.99,
            price_type="absolute",
            source="website_scrape",
            source_url="https://thundercloud.com/menu/lunch-specials",
            verified_at=datetime(2026, 4, 16, 1, 10, 52, tzinfo=timezone.utc),
            signal_quality=0.8,
            lat=30.3578,
            lng=-97.7334,
            region="austin_tx",
            is_active=True,
        ),
    ]

    collapsed = _collapse_duplicate_deals(deals, employers)

    assert len(collapsed) == 2
    assert {deal.local_employer_id for deal in collapsed} == {101, 102}