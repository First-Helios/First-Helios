from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collectors.meal_deals.ingest import ingest_deal_signals
from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.semantic_layer import refresh_deal_materializations
from collectors.meal_deals.website_scraper import _copy_signal_for_location
from core.database import (
    BrandGroup,
    CanonicalVenue,
    CanonicalVenueAlias,
    DealApplicability,
    DealMaterialization,
    DealObservation,
    LocalEmployer,
    MealDeal,
    RestaurantURL,
    SiteAssignment,
    SiteIdentity,
)
from core.normalizer import make_fingerprint
from core.venue_identity import normalize_address_for_identity
from scripts.backfills.backfill_deal_observation_history import backfill_deal_observation_history
from scripts.one_shot.reset_meal_deal_dataset import reset_meal_deal_dataset


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


def _build_canonical_venue(
    venue_id: int,
    *,
    name: str,
    address: str,
    brand_group_id: int | None,
    lat: float,
    lng: float,
) -> CanonicalVenue:
    return CanonicalVenue(
        id=venue_id,
        canonical_name=name,
        normalized_name=make_fingerprint(name),
        normalized_address=normalize_address_for_identity(address),
        address=address,
        lat=lat,
        lng=lng,
        region="austin_tx",
        brand_group_id=brand_group_id,
        site_status="shared_site",
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
                _build_canonical_venue(
                    9001,
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
        session.flush()
        session.add_all(
            [
                CanonicalVenueAlias(
                    canonical_venue_id=9001,
                    local_employer_id=41201,
                    alias_role="primary",
                    match_method="manual",
                    match_confidence=1.0,
                ),
                CanonicalVenueAlias(
                    canonical_venue_id=9001,
                    local_employer_id=38677,
                    alias_role="alias",
                    match_method="manual",
                    match_confidence=0.92,
                ),
            ]
        )
        stats = backfill_deal_observation_history(session, region="austin_tx")
        session.commit()

    assert stats["observations_inserted"] == 1
    assert stats["materializations_inserted"] == 1

    list_response = client.get("/api/deals?region=austin_tx")
    assert list_response.status_code == 200
    list_payload = list_response.get_json()

    assert list_payload["count"] == 1
    assert len(list_payload["deals"]) == 1
    assert list_payload["deals"][0]["restaurant_name"] == "Polvos Mexican Restaurant North"

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


def test_reset_meal_deal_dataset_clears_canonical_and_legacy_rows(engine, monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.one_shot.reset_meal_deal_dataset.init_db", lambda: engine)
    monkeypatch.setattr("scripts.one_shot.reset_meal_deal_dataset.get_session", lambda eng: Session(bind=eng))
    monkeypatch.setattr("scripts.one_shot.reset_meal_deal_dataset.WEBSITE_SCRAPE_DEBUG_DIR", tmp_path)

    debug_file = tmp_path / "debug.json"
    debug_file.write_text("{}", encoding="utf-8")

    with Session(engine) as session:
        session.add(
            _build_employer(
                1,
                name="Polvos",
                address="14735 Bratton Ln, Austin, TX",
                brand_group_id=None,
                lat=30.44605,
                lng=-97.68565,
            )
        )
        session.add(
            _build_canonical_venue(
                1,
                name="Polvos",
                address="14735 Bratton Ln, Austin, TX",
                brand_group_id=None,
                lat=30.44605,
                lng=-97.68565,
            )
        )
        session.add(
            RestaurantURL(
                id=1,
                local_employer_id=1,
                brand_group_id=None,
                url="https://example.com",
                source="manual",
                is_active=True,
                last_http_status=200,
                has_deals_page=True,
                deals_page_url="https://example.com/menu",
            )
        )
        session.add(
            DealObservation(
                id=1,
                source="website_scrape",
                source_observation_key="obs-1",
                observed_at=datetime(2026, 4, 16, 2, 0, 0, tzinfo=timezone.utc),
                deal_name="Lunch Combo",
                deal_type="combo",
                review_state="accepted",
            )
        )
        session.flush()
        session.add(
            DealApplicability(
                id=1,
                observation_id=1,
                applicability_scope="venue",
                canonical_venue_id=None,
                brand_group_id=None,
                resolver_method="test",
                is_active=True,
            )
        )
        session.add(
            DealMaterialization(
                id=1,
                observation_id=1,
                applicability_id=1,
                canonical_venue_id=1,
                local_employer_id=None,
                brand_group_id=None,
                restaurant_name="Polvos",
                address=None,
                lat=None,
                lng=None,
                region="austin_tx",
                applicability_scope="venue",
                is_chain_template=False,
                deal_name="Lunch Combo",
                deal_description=None,
                deal_type="combo",
                source="website_scrape",
                source_url="https://example.com",
                source_observation_key="obs-1",
                resolver_method="test",
                review_state="accepted",
                is_active=True,
            )
        )
        session.add(
            MealDeal(
                id=1,
                local_employer_id=None,
                brand_group_id=None,
                is_chain_template=False,
                deal_name="Lunch Combo",
                deal_description=None,
                deal_type="combo",
                source="website_scrape",
                source_url="https://example.com",
                region="austin_tx",
                is_active=True,
            )
        )
        session.commit()

    stats = reset_meal_deal_dataset(
        apply=True,
        reset_url_state=True,
        clear_debug_cache=True,
    )

    assert stats["deleted_materializations"] == 1
    assert stats["deleted_applicability"] == 1
    assert stats["deleted_observations"] == 1
    assert stats["deleted_meal_deals"] == 1
    assert stats["reset_restaurant_urls"] == 1
    assert stats["cleared_debug_cache_files"] == 1

    with Session(engine) as session:
        assert session.query(DealMaterialization).count() == 0
        assert session.query(DealApplicability).count() == 0
        assert session.query(DealObservation).count() == 0
        assert session.query(MealDeal).count() == 0
        url = session.query(RestaurantURL).one()
        assert url.last_checked is None
        assert url.last_http_status is None
        assert url.has_deals_page is None
        assert url.deals_page_url is None


def test_deal_routes_honor_day_filter(client, engine):
    def _seed_materialization(
        session: Session,
        *,
        row_id: int,
        venue_id: int,
        name: str,
        deal_type: str,
        valid_days: str | None,
    ) -> None:
        observation_key = f"obs-{row_id}"
        session.add(
            _build_canonical_venue(
                venue_id,
                name=name,
                address=f"{venue_id} Test Ln, Austin, TX",
                brand_group_id=None,
                lat=30.40 + row_id / 1000,
                lng=-97.70 - row_id / 1000,
            )
        )
        session.add(
            DealObservation(
                id=row_id,
                source="website_scrape",
                source_observation_key=observation_key,
                observed_at=datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc),
                deal_name=name,
                deal_type=deal_type,
                valid_days=valid_days,
                review_state="accepted",
            )
        )
        session.flush()
        session.add(
            DealApplicability(
                id=row_id,
                observation_id=row_id,
                applicability_scope="venue",
                canonical_venue_id=venue_id,
                brand_group_id=None,
                resolver_method="test",
                is_active=True,
            )
        )
        session.add(
            DealMaterialization(
                id=row_id,
                observation_id=row_id,
                applicability_id=row_id,
                canonical_venue_id=venue_id,
                local_employer_id=None,
                brand_group_id=None,
                restaurant_name=name,
                address=None,
                lat=None,
                lng=None,
                region="austin_tx",
                applicability_scope="venue",
                is_chain_template=False,
                deal_name=name,
                deal_description=None,
                deal_type=deal_type,
                valid_days=valid_days,
                source="website_scrape",
                source_url=f"https://example.com/{row_id}",
                source_observation_key=observation_key,
                resolver_method="test",
                review_state="accepted",
                is_active=True,
            )
        )

    with Session(engine) as session:
        _seed_materialization(
            session,
            row_id=101,
            venue_id=9101,
            name="Tuesday Taco",
            deal_type="combo",
            valid_days="Tue",
        )
        _seed_materialization(
            session,
            row_id=102,
            venue_id=9102,
            name="Monday Burger",
            deal_type="combo",
            valid_days="Mon",
        )
        _seed_materialization(
            session,
            row_id=103,
            venue_id=9103,
            name="Weekday Lunch",
            deal_type="combo",
            valid_days="Mon-Fri",
        )
        _seed_materialization(
            session,
            row_id=104,
            venue_id=9104,
            name="Daily Happy Hour",
            deal_type="happy_hour",
            valid_days="Daily",
        )
        _seed_materialization(
            session,
            row_id=105,
            venue_id=9105,
            name="Unknown Day Deal",
            deal_type="combo",
            valid_days=None,
        )
        session.commit()

    response = client.get("/api/deals?region=austin_tx&day=Tue")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["count"] == 3
    assert {deal["deal_name"] for deal in payload["deals"]} == {
        "Tuesday Taco",
        "Weekday Lunch",
        "Daily Happy Hour",
    }
    assert {deal["valid_days"] for deal in payload["deals"]} == {"Tue", "Mon-Fri", "Daily"}

    stats_response = client.get("/api/deals/stats?region=austin_tx&day=Tue")
    assert stats_response.status_code == 200
    stats_payload = stats_response.get_json()

    assert stats_payload["total_deals"] == 3
    assert stats_payload["by_type"] == {"combo": 2, "happy_hour": 1}


def test_review_queue_lists_contested_sites_and_medium_confidence_aliases(client, engine):
    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    5001,
                    name="Satellite Bistro",
                    address="100 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2601,
                    lng=-97.7420,
                ),
                _build_employer(
                    5002,
                    name="Satellite Bar",
                    address="102 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2602,
                    lng=-97.7421,
                ),
                _build_canonical_venue(
                    9001,
                    name="Satellite Bistro",
                    address="100 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2601,
                    lng=-97.7420,
                ),
                _build_canonical_venue(
                    9002,
                    name="Satellite Bar",
                    address="102 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2602,
                    lng=-97.7421,
                ),
                SiteIdentity(
                    id=3001,
                    normalized_url="satelliteatx.com",
                    canonical_url="https://satelliteatx.com",
                    host="satelliteatx.com",
                    path="/",
                    ownership_scope="mixed",
                    conflict_state="needs_review",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                SiteAssignment(
                    site_identity_id=3001,
                    canonical_venue_id=9001,
                    assignment_scope="contested",
                    match_method="restaurant_url_backfill",
                    match_confidence=0.5,
                    is_primary=False,
                ),
                SiteAssignment(
                    site_identity_id=3001,
                    canonical_venue_id=9002,
                    assignment_scope="contested",
                    match_method="restaurant_url_backfill",
                    match_confidence=0.5,
                    is_primary=False,
                ),
                CanonicalVenueAlias(
                    canonical_venue_id=9001,
                    local_employer_id=5001,
                    alias_role="primary",
                    match_method="heuristic",
                    match_confidence=0.92,
                ),
                CanonicalVenueAlias(
                    canonical_venue_id=9002,
                    local_employer_id=5002,
                    alias_role="primary",
                    match_method="manual",
                    match_confidence=1.0,
                ),
            ]
        )
        session.commit()

    response = client.get("/api/deals/review-queue?region=austin_tx")
    assert response.status_code == 200

    payload = response.get_json()

    assert payload["summary"] == {
        "contested_sites": 1,
        "ambiguous_venue_aliases": 1,
    }
    assert payload["count"] == 2
    assert payload["items"][0]["queue_type"] == "site"
    assert payload["items"][0]["candidate_count"] == 2
    assert payload["items"][0]["normalized_url"] == "satelliteatx.com"
    assert payload["items"][1]["queue_type"] == "venue_alias"
    assert payload["items"][1]["match_confidence"] == 0.92
    assert payload["items"][1]["canonical_name"] == "Satellite Bistro"


def test_review_queue_site_action_resolves_contested_site(client, engine):
    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    5001,
                    name="Satellite Bistro",
                    address="100 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2601,
                    lng=-97.7420,
                ),
                _build_employer(
                    5002,
                    name="Satellite Bar",
                    address="102 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2602,
                    lng=-97.7421,
                ),
                _build_canonical_venue(
                    9001,
                    name="Satellite Bistro",
                    address="100 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2601,
                    lng=-97.7420,
                ),
                _build_canonical_venue(
                    9002,
                    name="Satellite Bar",
                    address="102 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2602,
                    lng=-97.7421,
                ),
                SiteIdentity(
                    id=3001,
                    normalized_url="satelliteatx.com",
                    canonical_url="https://satelliteatx.com",
                    host="satelliteatx.com",
                    path="/",
                    ownership_scope="mixed",
                    conflict_state="needs_review",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                SiteAssignment(
                    site_identity_id=3001,
                    canonical_venue_id=9001,
                    assignment_scope="contested",
                    match_method="restaurant_url_backfill",
                    match_confidence=0.5,
                    is_primary=False,
                ),
                SiteAssignment(
                    site_identity_id=3001,
                    canonical_venue_id=9002,
                    assignment_scope="contested",
                    match_method="restaurant_url_backfill",
                    match_confidence=0.5,
                    is_primary=False,
                ),
            ]
        )
        session.commit()

    response = client.post(
        "/api/deals/review-queue/actions",
        json={
            "queue_type": "site",
            "action": "resolve",
            "resolution": "venue",
            "site_identity_id": 3001,
            "canonical_venue_id": 9001,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"]["resolution"] == "venue"

    with Session(engine) as session:
        site = session.query(SiteIdentity).one()
        assignments = session.query(SiteAssignment).order_by(SiteAssignment.canonical_venue_id).all()

    assert site.conflict_state == "clear"
    assert site.ownership_scope == "venue"
    assert assignments[0].canonical_venue_id == 9001
    assert assignments[0].assignment_scope == "venue"
    assert assignments[0].is_primary is True
    assert assignments[1].canonical_venue_id == 9002
    assert assignments[1].assignment_scope == "fallback"
    assert assignments[1].is_primary is False

    queue_response = client.get("/api/deals/review-queue?region=austin_tx&kind=site")
    queue_payload = queue_response.get_json()
    assert queue_payload["summary"]["contested_sites"] == 0
    assert queue_payload["count"] == 0


def test_review_queue_venue_alias_reassign_repairs_canonical_outputs(client, engine):
    source_url = "https://example.com/lunch"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    5001,
                    name="Wrong Employer",
                    address="100 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2601,
                    lng=-97.7420,
                ),
                _build_canonical_venue(
                    9001,
                    name="Old Venue",
                    address="100 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2601,
                    lng=-97.7420,
                ),
                _build_canonical_venue(
                    9002,
                    name="New Venue",
                    address="101 Main St, Austin, TX",
                    brand_group_id=None,
                    lat=30.2602,
                    lng=-97.7421,
                ),
                SiteIdentity(
                    id=3001,
                    normalized_url="example.com/lunch",
                    canonical_url=source_url,
                    host="example.com",
                    path="/lunch",
                    ownership_scope="venue",
                    conflict_state="clear",
                ),
            ]
        )
        session.flush()
        session.add(
            CanonicalVenueAlias(
                canonical_venue_id=9001,
                local_employer_id=5001,
                alias_role="primary",
                match_method="heuristic",
                match_confidence=0.92,
            )
        )
        observation = DealObservation(
            source="website_scrape",
            collector_run_id=55,
            site_identity_id=3001,
            source_url=source_url,
            source_observation_key="obs-reassign-1",
            observed_at=datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc),
            deal_name="Lunch Special $10",
            deal_description="Lunch Special $10 Monday-Friday",
            deal_type="combo",
            price=10.0,
            price_type="absolute",
            valid_days="Mon-Fri",
            raw_scraped_text="Lunch Special $10 Monday-Friday",
            extraction_payload={
                "restaurant_name": "Wrong Employer",
                "local_employer_id_hint": 5001,
                "region": "austin_tx",
            },
            signal_quality=0.8,
            review_state="accepted",
        )
        session.add(observation)
        session.flush()
        session.add(
            DealApplicability(
                observation_id=observation.id,
                applicability_scope="venue",
                canonical_venue_id=9001,
                confidence=0.92,
                resolver_method="local_employer_alias",
                is_active=True,
            )
        )
        session.flush()
        refresh_deal_materializations(session, observation_ids=[observation.id])
        session.commit()

    response = client.post(
        "/api/deals/review-queue/actions",
        json={
            "queue_type": "venue_alias",
            "action": "reassign",
            "local_employer_id": 5001,
            "canonical_venue_id": 9002,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["result"]["canonical_venue_id"] == 9002
    assert payload["result"]["applicability_rows_updated"] == 1

    with Session(engine) as session:
        alias = session.query(CanonicalVenueAlias).one()
        applicability = session.query(DealApplicability).one()
        materialization = session.query(DealMaterialization).one()

    assert alias.canonical_venue_id == 9002
    assert alias.match_confidence == 1.0
    assert alias.match_method == "manual_review"
    assert applicability.canonical_venue_id == 9002
    assert applicability.resolver_method == "manual_review_alias"
    assert materialization.canonical_venue_id == 9002

    queue_response = client.get("/api/deals/review-queue?region=austin_tx&kind=venue")
    queue_payload = queue_response.get_json()
    assert queue_payload["summary"]["ambiguous_venue_aliases"] == 0
    assert queue_payload["count"] == 0