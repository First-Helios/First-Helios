from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collectors.meal_deals.quality import compute_signal_quality, gate_decision
from collectors.meal_deals.semantic_layer import refresh_deal_materializations
from core.database import (
    CanonicalVenue,
    CanonicalVenueAlias,
    DealApplicability,
    DealMaterialization,
    DealObservation,
    LocalEmployer,
    SiteIdentity,
)
from core.normalizer import make_fingerprint
from core.venue_identity import normalize_address_for_identity, normalize_url_for_identity
from scripts.reaudit_deal_observations import reaudit_deal_observations


def _build_employer(
    employer_id: int,
    *,
    name: str,
    address: str,
    lat: float,
    lng: float,
) -> LocalEmployer:
    return LocalEmployer(
        id=employer_id,
        raw_name=name,
        name=name,
        fingerprint=make_fingerprint(name),
        address=address,
        brand_group_id=None,
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
        brand_group_id=None,
        site_status="has_site",
        is_active=True,
    )


def test_quality_pushes_review_text_out_of_active_band():
    score = compute_signal_quality(
        deal_name="This is by far my boyfriend and I's favorite place to eat",
        deal_description="This is by far my boyfriend and I's favorite place to eat",
        restaurant_name="El Naranjo",
    )

    decision, _is_active = gate_decision(score.total)

    assert score.total < 0.4
    assert decision != "active"
    assert any("marketing/review" in reason or "missing price/discount" in reason for reason in score.reasons)


def test_reaudit_deal_observations_rebuilds_review_state_and_materializations(engine):
    source_url = "https://elnaranjo.example.com/happy-hour"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    5001,
                    name="El Naranjo",
                    address="2717 S Lamar Blvd, Austin, TX",
                    lat=30.2459,
                    lng=-97.7794,
                ),
                _build_canonical_venue(
                    9001,
                    name="El Naranjo",
                    address="2717 S Lamar Blvd, Austin, TX",
                    lat=30.2459,
                    lng=-97.7794,
                ),
                SiteIdentity(
                    id=3001,
                    normalized_url=normalize_url_for_identity(source_url),
                    canonical_url=source_url,
                    host="elnaranjo.example.com",
                    path="/happy-hour",
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
                match_method="manual",
                match_confidence=1.0,
            )
        )
        observation = DealObservation(
            source="website_scrape",
            collector_run_id=77,
            site_identity_id=3001,
            source_url=source_url,
            source_observation_key="obs-1",
            observed_at=datetime(2026, 4, 16, 18, 0, 0, tzinfo=timezone.utc),
            deal_name="This is by far my boyfriend and I's favorite place to eat",
            deal_description="This is by far my boyfriend and I's favorite place to eat",
            deal_type="happy_hour",
            raw_scraped_text="This is by far my boyfriend and I's favorite place to eat",
            extraction_payload={
                "restaurant_name": "El Naranjo",
                "region": "austin_tx",
                "metadata": {"backfill_source": "meal_deals"},
            },
            signal_quality=0.435,
            review_state="accepted",
        )
        session.add(observation)
        session.flush()
        session.add(
            DealApplicability(
                observation_id=observation.id,
                applicability_scope="venue",
                canonical_venue_id=9001,
                confidence=0.95,
                resolver_method="local_employer_alias",
                is_active=True,
            )
        )
        session.flush()
        refresh_deal_materializations(session, observation_ids=[observation.id])
        session.commit()

    with Session(engine) as session:
        stats = reaudit_deal_observations(
            session,
            source="website_scrape",
            region="austin_tx",
            backfill_source="meal_deals",
        )
        session.commit()

    assert stats["observations_scanned"] == 1
    assert stats["changed_observations"] == 1
    assert stats["review_state_updated"] == 1
    assert stats["accepted_to_review"] + stats["accepted_to_rejected"] == 1

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        materializations = session.query(DealMaterialization).all()

    assert observation.review_state in {"review", "rejected"}
    assert observation.signal_quality < 0.4
    assert materializations == [] or all(materialization.is_active is False for materialization in materializations)


def test_reaudit_deal_observations_requires_opt_in_for_promotions(engine):
    source_url = "https://hopdoddy.example.com/happy-hour"

    with Session(engine) as session:
        session.add_all(
            [
                _build_employer(
                    5002,
                    name="Hopdoddy",
                    address="1400 S Congress Ave, Austin, TX",
                    lat=30.2490,
                    lng=-97.7494,
                ),
                _build_canonical_venue(
                    9002,
                    name="Hopdoddy",
                    address="1400 S Congress Ave, Austin, TX",
                    lat=30.2490,
                    lng=-97.7494,
                ),
                SiteIdentity(
                    id=3002,
                    normalized_url=normalize_url_for_identity(source_url),
                    canonical_url=source_url,
                    host="hopdoddy.example.com",
                    path="/happy-hour",
                    ownership_scope="venue",
                    conflict_state="clear",
                ),
            ]
        )
        session.flush()
        session.add(
            CanonicalVenueAlias(
                canonical_venue_id=9002,
                local_employer_id=5002,
                alias_role="primary",
                match_method="manual",
                match_confidence=1.0,
            )
        )
        observation = DealObservation(
            source="website_scrape",
            collector_run_id=88,
            site_identity_id=3002,
            source_url=source_url,
            source_observation_key="obs-2",
            observed_at=datetime(2026, 4, 16, 19, 0, 0, tzinfo=timezone.utc),
            deal_name="Half Price Draft Beers",
            deal_description="Half price draft beers Monday through Thursday from 3pm to 6pm",
            deal_type="happy_hour",
            price_type="percentage_off",
            discount_percentage=50.0,
            valid_days="Mon-Thu",
            valid_start_time="15:00",
            valid_end_time="18:00",
            raw_scraped_text="Half price draft beers Monday through Thursday from 3pm to 6pm",
            extraction_payload={
                "restaurant_name": "Hopdoddy",
                "region": "austin_tx",
                "metadata": {"backfill_source": "meal_deals"},
            },
            signal_quality=0.2,
            review_state="review",
        )
        session.add(observation)
        session.flush()
        session.add(
            DealApplicability(
                observation_id=observation.id,
                applicability_scope="venue",
                canonical_venue_id=9002,
                confidence=0.95,
                resolver_method="local_employer_alias",
                is_active=True,
            )
        )
        session.flush()
        refresh_deal_materializations(session, observation_ids=[observation.id])
        session.commit()

    with Session(engine) as session:
        stats = reaudit_deal_observations(
            session,
            source="website_scrape",
            region="austin_tx",
            backfill_source="meal_deals",
        )
        session.commit()

    assert stats["review_to_accepted"] == 0

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        materialization = session.query(DealMaterialization).one()

    assert observation.review_state == "review"
    assert observation.signal_quality >= 0.4
    assert materialization.is_active is False

    with Session(engine) as session:
        stats = reaudit_deal_observations(
            session,
            source="website_scrape",
            region="austin_tx",
            backfill_source="meal_deals",
            allow_promotions=True,
        )
        session.commit()

    assert stats["review_to_accepted"] == 1

    with Session(engine) as session:
        observation = session.query(DealObservation).one()
        materialization = session.query(DealMaterialization).one()

    assert observation.review_state == "accepted"
    assert materialization.is_active is True