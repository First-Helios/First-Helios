from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from collectors.meal_deals.ingest import ingest_deal_signals
from collectors.meal_deals.models import DealSignal
from core.database import (
    BrandGroup,
    CanonicalVenue,
    CanonicalVenueAlias,
    DealApplicability,
    DealMaterialization,
    DealObservation,
    LocalEmployer,
    MealDeal,
    SiteIdentity,
)
from core.normalizer import make_fingerprint
from core.venue_identity import normalize_address_for_identity, normalize_url_for_identity


def _patch_ingest(monkeypatch, engine) -> None:
    monkeypatch.setattr("collectors.meal_deals.ingest.init_db", lambda: engine)
    monkeypatch.setattr("collectors.meal_deals.ingest.get_session", lambda eng: Session(bind=eng))


def _build_brand_group(brand_group_id: int, *, fingerprint: str, name: str) -> BrandGroup:
    return BrandGroup(
        id=brand_group_id,
        fingerprint=fingerprint,
        canonical_name=name,
        location_count=1,
    )


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
        site_status="has_site",
        is_active=True,
    )


def _build_site_identity(site_id: int, url: str) -> SiteIdentity:
    parsed = urlparse(url)
    return SiteIdentity(
        id=site_id,
        normalized_url=normalize_url_for_identity(url),
        canonical_url=url,
        host=parsed.netloc,
        path=parsed.path,
        ownership_scope="venue",
        conflict_state="clear",
    )


def test_ingest_dual_writes_observation_and_venue_applicability(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://polvosaustin.com/happy-hour"

    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(41201, fingerprint="polvos-north", name="Polvos Mexican Restaurant North"),
                _build_employer(
                    41201,
                    name="Polvos Mexican Restaurant North",
                    address="14735 Bratton Ln #205, Austin, TX",
                    brand_group_id=41201,
                    lat=30.44906,
                    lng=-97.68265,
                ),
                _build_canonical_venue(
                    9001,
                    name="Polvos Mexican Restaurant North",
                    address="14735 Bratton Ln #205, Austin, TX",
                    brand_group_id=41201,
                    lat=30.44906,
                    lng=-97.68265,
                ),
                _build_site_identity(3001, source_url),
            ]
        )
        session.flush()
        session.add(
            CanonicalVenueAlias(
                canonical_venue_id=9001,
                local_employer_id=41201,
                alias_role="primary",
                match_method="manual",
                match_confidence=1.0,
            )
        )
        session.commit()

    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Polvos Bratton",
                address="14735 Bratton Ln, Austin, TX",
                deal_name="Lunch Special",
                deal_description="Lunch combo plate for $12 with chips and salsa",
                deal_type="combo",
                price=12.0,
                price_type="absolute",
                valid_days="Mon-Fri",
                valid_start_time="11:00",
                valid_end_time="15:00",
                source="manual",
                source_url=source_url,
                collector_run_id=44,
                region="austin_tx",
                observed_at=datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc),
            )
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 1
    assert stats["observation_rows"] == 1
    assert stats["skipped"] == 0

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        applicability = session.query(DealApplicability).one()
        materialization = session.query(DealMaterialization).one()
        deal = session.query(MealDeal).one()

    assert observation.collector_run_id == 44
    assert observation.site_identity_id == 3001
    assert observation.review_state == "accepted"
    assert observation.extraction_payload["local_employer_id_hint"] == 41201
    assert applicability.applicability_scope == "venue"
    assert applicability.canonical_venue_id == 9001
    assert applicability.brand_group_id is None
    assert applicability.resolver_method == "local_employer_alias"
    assert materialization.canonical_venue_id == 9001
    assert materialization.local_employer_id == 41201
    assert materialization.restaurant_name == "Polvos Mexican Restaurant North"
    assert materialization.is_active is True
    assert deal.local_employer_id == 41201
    assert deal.brand_group_id == 41201


def test_ingest_collapses_shared_site_fanout_into_one_observation(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://shared-site.example.com/specials"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    38677,
                    name="Polvos Bratton",
                    address="14735 Bratton Ln, Austin, TX",
                    brand_group_id=None,
                    lat=30.44599,
                    lng=-97.68572,
                ),
                _build_employer(
                    41201,
                    name="Polvos North",
                    address="14735 Bratton Ln #205, Austin, TX",
                    brand_group_id=None,
                    lat=30.44906,
                    lng=-97.68265,
                ),
                _build_canonical_venue(
                    9001,
                    name="Polvos Bratton",
                    address="14735 Bratton Ln, Austin, TX",
                    brand_group_id=None,
                    lat=30.44599,
                    lng=-97.68572,
                ),
                _build_canonical_venue(
                    9002,
                    name="Polvos North",
                    address="14735 Bratton Ln #205, Austin, TX",
                    brand_group_id=None,
                    lat=30.44906,
                    lng=-97.68265,
                ),
                _build_site_identity(3002, source_url),
            ]
        )
        session.flush()
        session.add_all(
            [
                CanonicalVenueAlias(
                    canonical_venue_id=9001,
                    local_employer_id=38677,
                    alias_role="primary",
                    match_method="manual",
                    match_confidence=1.0,
                ),
                CanonicalVenueAlias(
                    canonical_venue_id=9002,
                    local_employer_id=41201,
                    alias_role="primary",
                    match_method="manual",
                    match_confidence=1.0,
                ),
            ]
        )
        session.commit()

    observed_at = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Polvos Bratton",
                address="14735 Bratton Ln, Austin, TX",
                local_employer_id=38677,
                deal_name="Happy Hour",
                deal_description="Half off appetizers and $6 margaritas",
                deal_type="happy_hour",
                price=6.0,
                price_type="absolute",
                valid_days="Mon-Fri",
                valid_start_time="15:00",
                valid_end_time="18:00",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=88,
                region="austin_tx",
                observed_at=observed_at,
            ),
            DealSignal(
                restaurant_name="Polvos North",
                address="14735 Bratton Ln #205, Austin, TX",
                local_employer_id=41201,
                deal_name="Happy Hour",
                deal_description="Half off appetizers and $6 margaritas",
                deal_type="happy_hour",
                price=6.0,
                price_type="absolute",
                valid_days="Mon-Fri",
                valid_start_time="15:00",
                valid_end_time="18:00",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=88,
                region="austin_tx",
                observed_at=observed_at,
            ),
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 2
    assert stats["observation_rows"] == 1

    with Session(engine) as session:
        observations = session.query(DealObservation).all()
        applicability = session.query(DealApplicability).order_by(DealApplicability.canonical_venue_id).all()
        materializations = session.query(DealMaterialization).order_by(DealMaterialization.canonical_venue_id).all()
        deals = session.query(MealDeal).order_by(MealDeal.local_employer_id).all()

    assert len(observations) == 1
    assert observations[0].site_identity_id == 3002
    assert len(applicability) == 2
    assert {row.canonical_venue_id for row in applicability} == {9001, 9002}
    assert {row.applicability_scope for row in applicability} == {"venue"}
    assert len(materializations) == 2
    assert {row.canonical_venue_id for row in materializations} == {9001, 9002}
    assert [deal.local_employer_id for deal in deals] == [38677, 41201]


def test_ingest_dual_writes_chain_observation_and_brand_applicability(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://chipotle.example.com/rewards/offers"

    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(500, fingerprint="chipotle", name="Chipotle"),
                _build_employer(
                    1500,
                    name="Chipotle North Austin",
                    address="11000 Domain Dr, Austin, TX",
                    brand_group_id=500,
                    lat=30.4013,
                    lng=-97.7261,
                ),
                _build_canonical_venue(
                    9500,
                    name="Chipotle North Austin",
                    address="11000 Domain Dr, Austin, TX",
                    brand_group_id=500,
                    lat=30.4013,
                    lng=-97.7261,
                ),
                _build_site_identity(3003, source_url),
            ]
        )
        session.flush()
        session.add(
            CanonicalVenueAlias(
                canonical_venue_id=9500,
                local_employer_id=1500,
                alias_role="primary",
                match_method="manual",
                match_confidence=1.0,
            )
        )
        session.commit()

    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Chipotle",
                deal_name="BOGO Entree",
                deal_description="Buy one entree, get one free for rewards members",
                deal_type="bogo",
                brand_fingerprint="chipotle",
                price_type="percentage_off",
                price=100.0,
                valid_days="Tue",
                valid_start_time="15:00",
                valid_end_time="21:00",
                source="chain_website",
                source_url=source_url,
                collector_run_id=55,
                region="austin_tx",
                observed_at=datetime(2026, 4, 16, 13, 0, 0, tzinfo=timezone.utc),
            )
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 1
    assert stats["observation_rows"] == 1

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        applicability = session.query(DealApplicability).one()
        materializations = session.query(DealMaterialization).all()
        deal = session.query(MealDeal).one()

    assert observation.collector_run_id == 55
    assert observation.site_identity_id == 3003
    assert observation.review_state == "accepted"
    assert applicability.applicability_scope == "brand"
    assert applicability.brand_group_id == 500
    assert applicability.canonical_venue_id is None
    assert applicability.resolver_method == "brand_fingerprint"
    assert len(materializations) == 1
    assert materializations[0].canonical_venue_id == 9500
    assert materializations[0].local_employer_id == 1500
    assert materializations[0].is_chain_template is True
    assert deal.brand_group_id == 500
    assert deal.is_chain_template is True


def test_ingest_inherits_valid_days_from_same_page_parent_signal(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://wingsnmore-austin.com/specials"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    41201,
                    name="Wings N More",
                    address="1200 West Howard Lane, Austin, TX",
                    brand_group_id=None,
                    lat=30.424131,
                    lng=-97.6696961,
                ),
                _build_site_identity(3005, source_url),
            ]
        )
        session.commit()

    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Wings N More",
                local_employer_id=41201,
                deal_name="Happy Hour 02:00 PM - 07:00 PM All Wings Buy One G",
                deal_description="Tuesday April 21st Tecate $2.50 11:30 AM - 11:00 PM Happy Hour 02:00 PM - 07:00 PM All Wings Buy One Get One Free | Dine-In Only 04:00 PM - 11:00 PM",
                deal_type="happy_hour",
                price=2.5,
                price_type="absolute",
                valid_days="Tue",
                valid_start_time="11:30 AM",
                valid_end_time="11:00 PM",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=91,
                region="austin_tx",
                raw_scraped_text="Tuesday April 21st Tecate $2.50 11:30 AM - 11:00 PM Happy Hour 02:00 PM - 07:00 PM All Wings Buy One Get One Free | Dine-In Only 04:00 PM - 11:00 PM",
                observed_at=datetime(2026, 4, 17, 6, 42, 36, tzinfo=timezone.utc),
            ),
            DealSignal(
                restaurant_name="Wings N More",
                local_employer_id=41201,
                deal_name="Buy One Get One Free | Dine-In Only 04:00 PM - 11:00 PM",
                deal_description="All Wings Buy One Get One Free | Dine-In Only 04:00 PM - 11:00 PM",
                deal_type="bogo",
                valid_start_time="4:00 PM",
                valid_end_time="11:00 PM",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=91,
                region="austin_tx",
                raw_scraped_text="All Wings Buy One Get One Free | Dine-In Only 04:00 PM - 11:00 PM",
                observed_at=datetime(2026, 4, 17, 6, 42, 36, tzinfo=timezone.utc),
            ),
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 2
    assert stats["quality_rejected"] == 0

    with Session(engine) as session:
        bogo_observation = session.query(DealObservation).filter(
            DealObservation.deal_type == "bogo"
        ).one()
        bogo_deal = session.query(MealDeal).filter(
            MealDeal.deal_type == "bogo"
        ).one()

    assert bogo_observation.valid_days == "Tue"
    assert bogo_deal.valid_days == "Tue"


def test_ingest_rejects_plain_menu_combo_from_food_menu_page(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://wingsnmore-austin.com/austin-pflugerville-wings-n-more-food-menu"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    41201,
                    name="Wings N More",
                    address="1200 West Howard Lane, Austin, TX",
                    brand_group_id=None,
                    lat=30.424131,
                    lng=-97.6696961,
                ),
                _build_site_identity(3006, source_url),
            ]
        )
        session.commit()

    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Wings N More",
                local_employer_id=41201,
                deal_name="French Toast Oui",
                deal_description="French Toast Oui! Oui! Only the French could creat this egg and toast combo. French Toast $8.95 With hash browns and your choice of Bacon or Sausage.",
                deal_type="combo",
                price=8.95,
                price_type="absolute",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=92,
                region="austin_tx",
                raw_scraped_text="French Toast Oui! Oui! Only the French could creat this egg and toast combo. French Toast $8.95 With hash browns and your choice of Bacon or Sausage.",
                observed_at=datetime(2026, 4, 17, 6, 42, 41, tzinfo=timezone.utc),
            )
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 0
    assert stats["quality_rejected"] == 1
    assert stats["observation_rows"] == 1

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        deals = session.query(MealDeal).all()

    assert observation.review_state == "rejected"
    assert observation.signal_quality == 0.19
    assert deals == []


def test_sqlite_upsert_preserves_temporal_fields_for_thinner_duplicate(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://wingsnmore-austin.com/specials"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    41201,
                    name="Wings N More",
                    address="1200 West Howard Lane, Austin, TX",
                    brand_group_id=None,
                    lat=30.424131,
                    lng=-97.6696961,
                ),
                _build_site_identity(3007, source_url),
            ]
        )
        session.commit()

    ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Wings N More",
                local_employer_id=41201,
                deal_name="Buy One Get One Free | Dine-In Only",
                deal_description="All Wings Buy One Get One Free | Dine-In Only",
                deal_type="bogo",
                valid_days="Tue",
                valid_start_time="4:00 PM",
                valid_end_time="11:00 PM",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=93,
                region="austin_tx",
                raw_scraped_text="All Wings Buy One Get One Free | Dine-In Only",
                observed_at=datetime(2026, 4, 17, 6, 42, 36, tzinfo=timezone.utc),
            ),
            DealSignal(
                restaurant_name="Wings N More",
                local_employer_id=41201,
                deal_name="Buy One Get One Free | Dine-In Only",
                deal_description="All Wings Buy One Get One Free | Dine-In Only",
                deal_type="bogo",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=93,
                region="austin_tx",
                raw_scraped_text="All Wings Buy One Get One Free | Dine-In Only",
                observed_at=datetime(2026, 4, 17, 6, 42, 37, tzinfo=timezone.utc),
            ),
        ],
        region="austin_tx",
    )

    with Session(engine) as session:
        deal = session.query(MealDeal).one()

    assert deal.valid_days == "Tue"
    assert deal.valid_start_time == "4:00 PM"
    assert deal.valid_end_time == "11:00 PM"


def test_rejected_signals_still_persist_as_observations(engine, monkeypatch):
    _patch_ingest(monkeypatch, engine)
    source_url = "https://example.com/thin-signal"

    with Session(engine) as session:
        session.add(_build_site_identity(3004, source_url))
        session.commit()

    stats = ingest_deal_signals(
        [
            DealSignal(
                restaurant_name="Unknown",
                deal_name="A spicy thing",
                deal_type="combo",
                source="website_scrape",
                source_url=source_url,
                collector_run_id=66,
                region="austin_tx",
                observed_at=datetime(2026, 4, 16, 14, 0, 0, tzinfo=timezone.utc),
            )
        ],
        region="austin_tx",
    )

    assert stats["total_rows"] == 0
    assert stats["quality_rejected"] == 1
    assert stats["observation_rows"] == 1

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        applicability_rows = session.query(DealApplicability).all()
        materializations = session.query(DealMaterialization).all()
        deals = session.query(MealDeal).all()

    assert observation.review_state == "rejected"
    assert observation.collector_run_id == 66
    assert observation.site_identity_id == 3004
    assert applicability_rows == []
    assert materializations == []
    assert deals == []