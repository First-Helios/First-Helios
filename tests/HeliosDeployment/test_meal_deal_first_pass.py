from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collectors.meal_deals.ingest import ingest_deal_signals
from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.website_scraper import _copy_signal_for_location
from core.database import BrandGroup, LocalEmployer, MealDeal
from core.normalizer import make_fingerprint


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
        fingerprint=make_fingerprint(name),
        address=address,
        brand_group_id=brand_group_id,
        lat=lat,
        lng=lng,
        region="austin_tx",
        source="manual",
        is_active=True,
    )


def _build_deal(
    deal_id: int,
    *,
    employer_id: int,
    brand_group_id: int | None,
    signal_quality: float,
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
        lat=30.44605,
        lng=-97.68565,
        region="austin_tx",
        is_active=True,
    )


def test_copy_signal_for_location_preserves_extracted_fields():
    signal = DealSignal(
        restaurant_name="Polvos Bratton",
        address="14735 Bratton Ln, Austin, TX",
        local_employer_id=38677,
        brand_group_id=38677,
        deal_name="Happy Hour",
        deal_description="Half off appetizers and $6 margaritas",
        deal_type="happy_hour",
        price=6.0,
        price_type="absolute",
        discount_percentage=50.0,
        original_price=12.0,
        menu_avg_price=15.0,
        calories=720,
        calorie_price_ratio=120.0,
        valid_days="Mon-Fri",
        valid_start_time="15:00",
        valid_end_time="18:00",
        source="website_scrape",
        source_url="https://polvosaustin.com/happy-hour",
        raw_scraped_text="Half off appetizers and $6 margaritas from 3-6pm",
        signal_quality=0.88,
        deal_value_score=0.91,
        sub_deals=[{"item": "appetizers", "discount_value": 50.0}],
        metadata={"source_page": "specials"},
        observed_at=datetime(2026, 4, 16, 2, 0, 0, tzinfo=timezone.utc),
    )
    employer = _build_employer(
        41201,
        name="Polvos Mexican Restaurant North",
        address="14735 Bratton Ln #205, Austin, TX",
        brand_group_id=41201,
        lat=30.44906,
        lng=-97.68265,
    )

    copied = _copy_signal_for_location(signal, employer, region="austin_tx")

    assert copied.local_employer_id == 41201
    assert copied.brand_group_id == 41201
    assert copied.restaurant_name == employer.name
    assert copied.address == employer.address
    assert copied.price_type == "absolute"
    assert copied.discount_percentage == 50.0
    assert copied.original_price == 12.0
    assert copied.menu_avg_price == 15.0
    assert copied.valid_days == "Mon-Fri"
    assert copied.valid_start_time == "15:00"
    assert copied.valid_end_time == "18:00"
    assert copied.raw_scraped_text == signal.raw_scraped_text
    assert copied.sub_deals == signal.sub_deals
    assert copied.metadata == signal.metadata

    copied.sub_deals[0]["discount_value"] = 25.0
    copied.metadata["source_page"] = "changed"

    assert signal.sub_deals[0]["discount_value"] == 50.0
    assert signal.metadata["source_page"] == "specials"


def test_ingest_resolves_manual_signal_to_local_employer(engine, monkeypatch):
    with Session(engine) as session:
        session.add(
            BrandGroup(
                id=41201,
                fingerprint="polvos-north",
                canonical_name="Polvos Mexican Restaurant North",
                location_count=1,
            )
        )
        session.add(
            _build_employer(
                41201,
                name="Polvos Mexican Restaurant North",
                address="14735 Bratton Ln #205, Austin, TX",
                brand_group_id=41201,
                lat=30.44906,
                lng=-97.68265,
            )
        )
        session.commit()

    monkeypatch.setattr("collectors.meal_deals.ingest.init_db", lambda: engine)
    monkeypatch.setattr("collectors.meal_deals.ingest.get_session", lambda eng: Session(bind=eng))

    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Polvos Bratton",
                address="14735 Bratton Ln, Austin, TX",
                deal_name="Lunch Special",
                deal_description="Lunch combo plate for $12",
                deal_type="combo",
                price=12.0,
                source="manual",
                region="austin_tx",
            )
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 1
    assert stats["skipped"] == 0

    with Session(engine) as session:
        deal = session.query(MealDeal).one()

    assert deal.local_employer_id == 41201
    assert deal.brand_group_id == 41201
    assert deal.lat == 30.44906
    assert deal.lng == -97.68265
    assert deal.source == "manual"


def test_stats_and_brands_use_deduped_deal_semantics(client, engine):
    with Session(engine) as session:
        session.add_all(
            [
                BrandGroup(
                    id=38677,
                    fingerprint="polvos-bratton",
                    canonical_name="Polvos Bratton",
                    location_count=1,
                ),
                BrandGroup(
                    id=41201,
                    fingerprint="polvos-north",
                    canonical_name="Polvos Mexican Restaurant North",
                    location_count=1,
                ),
                _build_employer(
                    38677,
                    name="Polvos Bratton",
                    address="14735 Bratton Ln, Austin, TX",
                    brand_group_id=38677,
                    lat=30.44599,
                    lng=-97.68572,
                ),
                _build_employer(
                    41201,
                    name="Polvos Mexican Restaurant North",
                    address="14735 Bratton Ln, Austin, TX",
                    brand_group_id=41201,
                    lat=30.446054045051,
                    lng=-97.685658122487,
                ),
                _build_deal(1, employer_id=38677, brand_group_id=38677, signal_quality=0.73),
                _build_deal(2, employer_id=41201, brand_group_id=41201, signal_quality=0.83),
            ]
        )
        session.commit()

    stats_response = client.get("/api/deals/stats?region=austin_tx")
    assert stats_response.status_code == 200
    stats_payload = stats_response.get_json()

    assert stats_payload["total_deals"] == 1
    assert stats_payload["restaurant_count"] == 1
    assert stats_payload["brand_count"] == 1
    assert stats_payload["by_type"] == {"combo": 1}
    assert stats_payload["by_source"] == {"website_scrape": 1}

    brands_response = client.get("/api/deals/brands?region=austin_tx")
    assert brands_response.status_code == 200
    brands_payload = brands_response.get_json()

    assert brands_payload["count"] == 1
    assert brands_payload["brands"] == [
        {
            "fingerprint": "polvos-north",
            "name": "Polvos Mexican Restaurant North",
            "location_count": 1,
            "deal_count": 1,
        }
    ]