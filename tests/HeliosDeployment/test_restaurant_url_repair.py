from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collectors.meal_deals.osm_url_resolver import match_and_store_urls
from core.database import (
    BrandGroup,
    CanonicalVenue,
    DealApplicability,
    DealMaterialization,
    DealObservation,
    GooglePlacesFailure,
    LocalEmployer,
    MealDeal,
    RestaurantURL,
)
from core.normalizer import make_fingerprint
from scripts.audit_url_identity import audit_name_mismatch_urls, _url_match_score
from scripts.repair_restaurant_url_mismatches import (
    audit_site_identity_mismatches,
    purge_restaurant_url_mismatches,
    recollect_cleaned_employers,
)


def _build_employer(employer_id: int, name: str, brand_group_id: int | None = None) -> LocalEmployer:
    return LocalEmployer(
        id=employer_id,
        raw_name=name,
        name=name,
        fingerprint=make_fingerprint(name),
        address=f"{employer_id} Main St, Austin, TX",
        industry="food_full_service",
        region="austin_tx",
        source="manual",
        brand_group_id=brand_group_id,
        is_active=True,
    )


def _build_brand_group(brand_group_id: int, name: str) -> BrandGroup:
    return BrandGroup(
        id=brand_group_id,
        fingerprint=make_fingerprint(name),
        canonical_name=name,
        location_count=1,
        industry="food_full_service",
    )


def test_audit_site_identity_mismatches_flags_single_bad_row(engine, monkeypatch):
    monkeypatch.setattr(
        "scripts.repair_restaurant_url_mismatches._fetch_site_identity_snapshot",
        lambda url, timeout=12: {
            "final_url": url,
            "identity_text": "El Tacorrido South Austin",
            "display_text": "El Tacorrido South Austin",
            "host": "www.eltacorrido.com",
        },
    )

    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(1, "Baby Greens"),
                _build_brand_group(2, "El Tacorrido"),
                _build_employer(1, "Baby Greens", brand_group_id=1),
                _build_employer(2, "El Tacorrido", brand_group_id=2),
                RestaurantURL(
                    id=1,
                    local_employer_id=1,
                    brand_group_id=1,
                    url="http://www.eltacorrido.com/sur.html",
                    source="google_places",
                    is_active=True,
                ),
            ]
        )
        session.commit()

        mismatches = audit_site_identity_mismatches(
            session,
            region="austin_tx",
            target_employer_ids={1},
        )

    assert len(mismatches) == 1
    assert mismatches[0]["emp_name"] == "Baby Greens"
    assert mismatches[0]["likely_owner_names"] == ["El Tacorrido"]


def test_audit_site_identity_mismatches_does_not_flag_dotted_host_chain_page(engine, monkeypatch):
    monkeypatch.setattr(
        "scripts.repair_restaurant_url_mismatches._fetch_site_identity_snapshot",
        lambda url, timeout=12: {
            "final_url": url,
            "identity_text": "",
            "display_text": "https://locations.dennys.com/tx/austin",
            "host": "locations.dennys.com",
        },
    )

    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(1, "Denny's Restaurant"),
                _build_brand_group(2, "Austin"),
                _build_employer(1, "Denny's Restaurant", brand_group_id=1),
                _build_employer(2, "Austin", brand_group_id=2),
                RestaurantURL(
                    id=1,
                    local_employer_id=1,
                    brand_group_id=1,
                    url="https://locations.dennys.com/TX/AUSTIN/200686",
                    source="google_places",
                    is_active=True,
                ),
            ]
        )
        session.commit()

        mismatches = audit_site_identity_mismatches(
            session,
            region="austin_tx",
            target_employer_ids={1},
        )

    assert mismatches == []


def test_audit_name_mismatch_urls_skips_location_label_employers(engine):
    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(1, "JuiceLand Oak Hill"),
                _build_brand_group(2, "Southwest Parkway + Mopac"),
                _build_employer(1, "JuiceLand Oak Hill", brand_group_id=1),
                _build_employer(2, "Southwest Parkway + Mopac", brand_group_id=2),
                RestaurantURL(
                    id=1,
                    local_employer_id=1,
                    brand_group_id=1,
                    url="http://www.juiceland.com",
                    source="google_places",
                    is_active=True,
                ),
                RestaurantURL(
                    id=2,
                    local_employer_id=2,
                    brand_group_id=2,
                    url="http://www.juiceland.com",
                    source="google_places",
                    is_active=True,
                ),
            ]
        )
        session.commit()

        mismatches = audit_name_mismatch_urls(session)

    assert mismatches == []


def test_url_match_score_handles_split_brand_spelling():
    assert _url_match_score("Chi Lantro Mueller", "https://www.chilantrobbq.com") > 0
    assert _url_match_score("County Line on the Hill", "http://www.countyline.com") > 0
    assert _url_match_score("PoK-e-Jo's Smokehouse", "https://pokejos.com") > 0


def test_audit_site_identity_mismatches_skips_location_label_employer(engine, monkeypatch):
    monkeypatch.setattr(
        "scripts.repair_restaurant_url_mismatches._fetch_site_identity_snapshot",
        lambda url, timeout=12: {
            "final_url": url,
            "identity_text": "JuiceLand Oak Hill",
            "display_text": "JuiceLand Oak Hill",
            "host": "www.juiceland.com",
        },
    )

    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(1, "Southwest Parkway + Mopac"),
                _build_brand_group(2, "JuiceLand Oak Hill"),
                _build_employer(1, "Southwest Parkway + Mopac", brand_group_id=1),
                _build_employer(2, "JuiceLand Oak Hill", brand_group_id=2),
                RestaurantURL(
                    id=1,
                    local_employer_id=1,
                    brand_group_id=1,
                    url="http://www.juiceland.com",
                    source="google_places",
                    is_active=True,
                ),
            ]
        )
        session.commit()

        mismatches = audit_site_identity_mismatches(
            session,
            region="austin_tx",
            target_employer_ids={1},
        )

    assert mismatches == []


def test_purge_restaurant_url_mismatches_deletes_bad_url_and_scrape_rows(engine):
    bad_url = "http://www.eltacorrido.com/sur.html"

    with Session(engine) as session:
        session.add(_build_brand_group(1, "Baby Greens"))
        session.add(_build_employer(1, "Baby Greens", brand_group_id=1))
        session.add(
            CanonicalVenue(
                id=1,
                canonical_name="Baby Greens",
                normalized_name=make_fingerprint("Baby Greens"),
                normalized_address=make_fingerprint("1 Main St Austin TX"),
                address="1 Main St, Austin, TX",
                region="austin_tx",
                brand_group_id=1,
                site_status="single_site",
                is_active=True,
            )
        )
        session.add(
            RestaurantURL(
                id=1,
                local_employer_id=1,
                brand_group_id=1,
                url=bad_url,
                source="google_places",
                is_active=True,
            )
        )
        session.add(
            GooglePlacesFailure(
                entity_type="local_employer",
                entity_id=1,
                canonical_name="Baby Greens",
                failure_reason="no_result",
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
                canonical_venue_id=1,
                brand_group_id=1,
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
                local_employer_id=1,
                brand_group_id=1,
                restaurant_name="Baby Greens",
                address="1 Main St, Austin, TX",
                lat=None,
                lng=None,
                region="austin_tx",
                applicability_scope="venue",
                is_chain_template=False,
                deal_name="Lunch Combo",
                deal_description=None,
                deal_type="combo",
                source="website_scrape",
                source_url=bad_url,
                source_observation_key="obs-1",
                resolver_method="test",
                review_state="accepted",
                is_active=True,
            )
        )
        session.add(
            MealDeal(
                id=1,
                local_employer_id=1,
                brand_group_id=1,
                is_chain_template=False,
                deal_name="Lunch Combo",
                deal_description=None,
                deal_type="combo",
                source="website_scrape",
                source_url=bad_url,
                region="austin_tx",
                is_active=True,
            )
        )
        session.commit()

        stats, cleaned_ids = purge_restaurant_url_mismatches(
            session,
            [
                {
                    "rurl_id": 1,
                    "emp_id": 1,
                    "emp_name": "Baby Greens",
                    "url": bad_url,
                    "likely_owner_names": ["El Tacorrido"],
                }
            ],
        )

    assert cleaned_ids == {1}
    assert stats["restaurant_urls_deleted"] == 1
    assert stats["meal_deals_deleted"] == 1
    assert stats["materializations_deleted"] == 1
    assert stats["applicability_deleted"] == 1
    assert stats["observations_deleted"] == 1
    assert stats["google_failures_cleared"] == 1

    with Session(engine) as session:
        assert session.query(RestaurantURL).count() == 0
        assert session.query(MealDeal).count() == 0
        assert session.query(DealMaterialization).count() == 0
        assert session.query(DealApplicability).count() == 0
        assert session.query(DealObservation).count() == 0
        assert session.query(GooglePlacesFailure).count() == 0


def test_recollect_cleaned_employers_targets_only_cleaned_ids(engine, monkeypatch):
    with Session(engine) as session:
        session.add_all(
            [
                _build_brand_group(1, "Baby Greens"),
                _build_brand_group(2, "El Tacorrido"),
                _build_employer(1, "Baby Greens", brand_group_id=1),
                _build_employer(2, "El Tacorrido", brand_group_id=2),
            ]
        )
        session.commit()

    def _fake_fetch_osm_restaurant_websites():
        return []

    def _fake_match_and_store_urls(osm_pois, region, dry_run, target_employer_ids):
        assert osm_pois == []
        assert region == "austin_tx"
        assert dry_run is False
        assert target_employer_ids == {1}
        return {"stored": 0, "matched": 0}

    def _fake_resolve_local_urls(region, max_calls, dry_run, retry_failed, target_employer_ids):
        assert region == "austin_tx"
        assert dry_run is False
        assert retry_failed is True
        assert target_employer_ids == {1}
        with Session(engine) as inner_session:
            inner_session.add(
                RestaurantURL(
                    local_employer_id=1,
                    brand_group_id=1,
                    url="https://babygreens.example.com",
                    source="google_places",
                    is_active=True,
                    is_permanent=True,
                )
            )
            inner_session.commit()
        return {"resolved": 1, "checked": 1, "api_calls": 1}

    monkeypatch.setattr(
        "scripts.repair_restaurant_url_mismatches.fetch_osm_restaurant_websites",
        _fake_fetch_osm_restaurant_websites,
    )
    monkeypatch.setattr(
        "scripts.repair_restaurant_url_mismatches.match_and_store_urls",
        _fake_match_and_store_urls,
    )
    monkeypatch.setattr(
        "scripts.repair_restaurant_url_mismatches.resolve_local_urls",
        _fake_resolve_local_urls,
    )
    monkeypatch.setattr("scripts.repair_restaurant_url_mismatches.init_db", lambda: engine)

    stats = recollect_cleaned_employers(region="austin_tx", cleaned_employer_ids={1})

    assert stats["initial_unresolved"] == 1
    assert stats["remaining_after_osm"] == 1
    assert stats["final_unresolved"] == 0
    assert stats["osm"] == {"stored": 0, "matched": 0}
    assert stats["google_local"] == {"resolved": 1, "checked": 1, "api_calls": 1}


def test_match_and_store_urls_respects_target_ids_for_brand_fanout(engine, monkeypatch):
    monkeypatch.setattr("collectors.meal_deals.osm_url_resolver.init_db", lambda: engine)
    monkeypatch.setattr("collectors.meal_deals.osm_url_resolver.get_session", lambda eng: Session(bind=eng))

    with Session(engine) as session:
        session.add(_build_brand_group(10, "Target Brand"))
        session.add_all(
            [
                _build_employer(1, "Target Location", brand_group_id=10),
                _build_employer(2, "Other Location", brand_group_id=10),
            ]
        )
        session.commit()

    stats = match_and_store_urls(
        [
            {
                "name": "Unrelated Name",
                "fingerprint": make_fingerprint("Unrelated Name"),
                "lat": 30.3,
                "lng": -97.7,
                "website": "https://targetbrand.example.com",
                "brand": "Target Brand",
            }
        ],
        region="austin_tx",
        dry_run=False,
        target_employer_ids={1},
    )

    assert stats["stored"] == 1

    with Session(engine) as session:
        rows = session.query(RestaurantURL).order_by(RestaurantURL.local_employer_id).all()
        assert len(rows) == 1
        assert rows[0].local_employer_id == 1
        assert rows[0].url == "https://targetbrand.example.com"