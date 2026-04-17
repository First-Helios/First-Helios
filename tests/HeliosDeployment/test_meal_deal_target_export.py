from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collectors.meal_deals.google_places_resolver import _normalize_failure_reason
from collectors.meal_deals.website_scraper import load_website_scrape_target_groups
from core.database import LocalEmployer, RestaurantURL


def _build_employer(employer_id: int, name: str) -> LocalEmployer:
    return LocalEmployer(
        id=employer_id,
        raw_name=name,
        name=name,
        fingerprint=name.lower().replace(" ", "-"),
        address=f"{employer_id} Main St, Austin, TX",
        industry="food_full_service",
        region="austin_tx",
        source="manual",
        is_active=True,
    )


def test_normalize_failure_reason_clamps_name_mismatch_details():
    assert _normalize_failure_reason("name_mismatch:Lazarus Brewing Co. Airport Blvd.") == "name_mismatch"
    assert _normalize_failure_reason("NO_RESULT") == "no_result"
    assert _normalize_failure_reason("") == "unknown"


def test_load_website_scrape_target_groups_dedupes_by_normalized_url(engine):
    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(1, "Alpha Cafe"),
                _build_employer(2, "Alpha Cafe North"),
                _build_employer(3, "Bravo Bistro"),
            ]
        )
        session.add_all(
            [
                RestaurantURL(
                    local_employer_id=1,
                    url="https://alpha.example.com/",
                    source="manual",
                    is_active=True,
                    last_checked=None,
                ),
                RestaurantURL(
                    local_employer_id=2,
                    url="https://alpha.example.com",
                    source="osm",
                    is_active=True,
                    last_checked=None,
                ),
                RestaurantURL(
                    local_employer_id=3,
                    url="https://bravo.example.com",
                    source="manual",
                    is_active=True,
                    last_checked=datetime(2026, 4, 1, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()

        group_items, total_rows = load_website_scrape_target_groups(
            session,
            region="austin_tx",
            max_sites=10,
            skip_checked_days=0,
        )

    assert total_rows == 3
    assert len(group_items) == 2
    assert group_items[0][0] == "https://alpha.example.com"
    assert len(group_items[0][1]) == 2
    assert group_items[1][0] == "https://bravo.example.com"