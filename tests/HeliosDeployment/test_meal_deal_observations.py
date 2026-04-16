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