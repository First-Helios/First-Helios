"""
collectors/meal_deals/google_places_resolver.py — Resolve website URLs via Google Places API.

Gap-filler for employers that OSM Overpass couldn't resolve. Uses Google
Places Text Search to match name + address → website URL.

Cost management:
  - $32 per 1,000 Text Search requests (new Places API)
  - We have $200 free credits → ~6,250 calls max
  - Strategy: batch by brand_group first (1 lookup → apply to all locations)
  - Then individual lookups for priority locals
  - Daily budget cap enforced in code

API key loaded from GOOGLE_MAPS_API_KEY env var (never hardcoded).

Depends on: requests, core.database
Called by: CLI or scheduler (Tuesday 2:00 AM — weekly)
"""

import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import requests
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import (
    BrandGroup,
    CollectorRun,
    GooglePlacesFailure,
    LocalEmployer,
    RestaurantURL,
    get_engine,
    get_session,
    init_db,
)
from core.normalizer import make_fingerprint

logger = logging.getLogger(__name__)

# Google Places API (new)
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Budget controls
MAX_DAILY_CALLS = 200    # ~$6.40/day max
MAX_BATCH_CALLS = 500    # per run cap (changeable via CLI)


def _get_api_key() -> str:
    """Load API key from environment. Raises if not set."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY not set. Add it to .env or export it."
        )
    return key


def _normalize_url(raw: str) -> str | None:
    """Clean and validate a URL. Strips UTM/tracking query params."""
    if not raw or not raw.strip():
        return None
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        if not parsed.netloc or "." not in parsed.netloc:
            return None
        # Strip UTM and common tracking parameters for clean storage
        if parsed.query:
            clean_params = {
                k: v for k, v in parse_qs(parsed.query).items()
                if not k.lower().startswith(("utm_", "fbclid", "gclid", "mc_", "ref", "source"))
            }
            clean_query = urlencode(clean_params, doseq=True) if clean_params else ""
            parsed = parsed._replace(query=clean_query)
        parsed = parsed._replace(fragment="")
        return urlunparse(parsed).rstrip("/") if parsed.path == "/" else urlunparse(parsed)
    except Exception:
        return None


# ── Name validation ──────────────────────────────────────────────────────────

# Tokens that are too generic to use for name comparison
_NAME_STOPWORDS = frozenset({
    "restaurant", "restaurants", "bar", "grill", "cafe", "coffee",
    "the", "and", "of", "at", "n", "sports", "pub", "lounge",
    "kitchen", "house", "place", "shop", "food", "foods",
    "diner", "eatery", "bistro", "tavern", "inn",
})


def _name_tokens(name: str) -> set[str]:
    """Return significant tokens from a name for comparison."""
    fp = make_fingerprint(name)
    return {t for t in fp.split() if t not in _NAME_STOPWORDS and len(t) > 1}


def validate_place_name(query_name: str, result_name: str) -> bool:
    """Check that a Google Places result plausibly matches the queried name.

    Uses containment ratio: |intersection| / min(|query_tokens|, |result_tokens|)
    must exceed 0.5.  For 2-token names this requires BOTH tokens to match;
    for single-token names the one token must match.  This catches obvious
    mismatches like 'Wings N More' vs 'Wings-N-Things' (overlap='wings'
    = 1/2 = 0.5, not > 0.5) while allowing 'P. Terry's' vs 'P. Terry's
    Burger Stand' (overlap='terrys' = 1/1 = 1.0).
    """
    if not query_name or not result_name:
        return False
    query_tok = _name_tokens(query_name)
    result_tok = _name_tokens(result_name)
    if not query_tok or not result_tok:
        return True  # can't validate — accept rather than wrongly reject
    overlap = query_tok & result_tok
    min_size = min(len(query_tok), len(result_tok))
    return len(overlap) / min_size > 0.5


def _normalize_failure_reason(reason: str) -> str:
    """Clamp failure reasons to the DB column budget."""
    normalized = (reason or "").strip().lower()
    if normalized.startswith("name_mismatch"):
        return "name_mismatch"
    if normalized.startswith("no_website"):
        return "no_website"
    if normalized.startswith("no_result"):
        return "no_result"
    if normalized.startswith("api_error"):
        return "api_error"
    if not normalized:
        return "unknown"
    return normalized[:20]


def _record_failure(
    session,
    entity_type: str,
    entity_id: int,
    canonical_name: str,
    reason: str,
) -> None:
    """Upsert a failure record. Increments retry_count on repeat failures."""
    reason_code = _normalize_failure_reason(reason)
    stmt = pg_insert(GooglePlacesFailure).values(
        entity_type=entity_type,
        entity_id=entity_id,
        canonical_name=canonical_name,
        failure_reason=reason_code,
        failed_at=datetime.now(timezone.utc),
        retry_count=0,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_gp_failure_entity",
        set_={
            "failure_reason": stmt.excluded.failure_reason,
            "failed_at": stmt.excluded.failed_at,
            "retry_count": GooglePlacesFailure.retry_count + 1,
        },
    )
    session.execute(stmt)


def _clear_failure(session, entity_type: str, entity_id: int) -> None:
    """Remove a failure record when the entity is subsequently resolved."""
    session.query(GooglePlacesFailure).filter(
        GooglePlacesFailure.entity_type == entity_type,
        GooglePlacesFailure.entity_id == entity_id,
    ).delete(synchronize_session=False)


def resolve_place_website(
    name: str,
    address: str,
    lat: float | None = None,
    lng: float | None = None,
    api_key: str | None = None,
) -> dict | None:
    """Call Google Places Text Search to find a business and extract its website.

    Returns dict with: {website, place_id, formatted_address, rating, ...}
    or None on failure/no result.
    """
    if not api_key:
        api_key = _get_api_key()

    query = f"{name}, {address}" if address else name

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.websiteUri,places.id,places.formattedAddress,places.rating,places.displayName",
    }

    body = {"textQuery": query}

    # Bias toward the known location if we have lat/lng
    if lat and lng:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 500.0,  # meters
            }
        }

    try:
        resp = requests.post(
            PLACES_TEXT_SEARCH_URL,
            json=body,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        places = data.get("places", [])
        if not places:
            return None

        place = places[0]  # best match
        website = _normalize_url(place.get("websiteUri", ""))
        return {
            "website": website,
            "place_id": place.get("id"),
            "formatted_address": place.get("formattedAddress"),
            "rating": place.get("rating"),
            "display_name": place.get("displayName", {}).get("text"),
        }

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            logger.warning("[GooglePlaces] Rate limited — stopping batch")
            raise
        logger.warning("[GooglePlaces] HTTP error for %r: %s", name, e)
        return None
    except Exception as e:
        logger.warning("[GooglePlaces] Failed for %r: %s", name, e)
        return None


def resolve_brand_urls(
    region: str = "austin_tx",
    max_calls: int = MAX_BATCH_CALLS,
    dry_run: bool = False,
    retry_failed: bool = False,
) -> dict:
    """Resolve website URLs for brand_groups that don't have URLs yet.

    One API call per brand → fan out to all locations of that brand.
    This is the highest-ROI use of Google Places credits.
    """
    engine = init_db()
    session = get_session(engine)
    api_key = _get_api_key()

    stats = {
        "brands_checked": 0,
        "brands_resolved": 0,
        "urls_stored": 0,
        "api_calls": 0,
        "skipped_already_have": 0,
        "skipped_no_website": 0,
        "failures_recorded": 0,
        "failures_cleared": 0,
    }

    try:
        # Find brand_groups that have food employers but NO restaurant_urls from google_places
        # Subquery: brand_groups that already have at least one google_places URL
        already_resolved = session.query(
            RestaurantURL.brand_group_id
        ).filter(
            RestaurantURL.source == "google_places",
            RestaurantURL.is_active.is_(True),
            RestaurantURL.url.isnot(None),
            RestaurantURL.brand_group_id.isnot(None),
        ).distinct().subquery()

        # Also check OSM — if OSM already resolved this brand, skip it
        osm_resolved = session.query(
            RestaurantURL.brand_group_id
        ).filter(
            RestaurantURL.source == "osm",
            RestaurantURL.is_active.is_(True),
            RestaurantURL.url.isnot(None),
            RestaurantURL.brand_group_id.isnot(None),
        ).distinct().subquery()

        # Previously-failed brands (skip unless --retry-failed)
        previously_failed_brands = session.query(
            GooglePlacesFailure.entity_id
        ).filter(
            GooglePlacesFailure.entity_type == "brand_group",
        )

        if not retry_failed:
            failure_count = previously_failed_brands.count()
            if failure_count:
                logger.info(
                    "[GooglePlaces] Skipping %d previously-failed brands (use --retry-failed to include)",
                    failure_count,
                )

        # Brand groups with food employers, not yet resolved by google or OSM
        brand_filters = [
            LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
            ~BrandGroup.id.in_(session.query(already_resolved)),
            ~BrandGroup.id.in_(session.query(osm_resolved)),
        ]
        if not retry_failed:
            brand_filters.append(~BrandGroup.id.in_(previously_failed_brands))

        brands = session.query(BrandGroup).join(
            LocalEmployer, LocalEmployer.brand_group_id == BrandGroup.id
        ).filter(
            *brand_filters
        ).group_by(BrandGroup.id).order_by(
            BrandGroup.location_count.desc()  # high-location brands first
        ).limit(max_calls).all()

        logger.info("[GooglePlaces] %d brands to resolve (budget: %d calls)", len(brands), max_calls)

        now = datetime.now(timezone.utc)

        # CollectorRun for audit
        run = CollectorRun(
            source="google_places_resolver",
            fetched=len(brands),
            new=0, updated=0, skipped=0,
            run_at=now,
        )
        if not dry_run:
            session.add(run)
            session.flush()

        for brand in brands:
            if stats["api_calls"] >= max_calls:
                logger.info("[GooglePlaces] Hit call budget (%d), stopping", max_calls)
                break

            stats["brands_checked"] += 1

            # Get a representative location for this brand
            sample_emp = session.query(LocalEmployer).filter(
                LocalEmployer.brand_group_id == brand.id,
                LocalEmployer.region == region,
                LocalEmployer.is_active.is_(True),
            ).first()
            if not sample_emp:
                continue

            # Make the API call
            result = resolve_place_website(
                name=brand.canonical_name,
                address=sample_emp.address or "Austin, TX",
                lat=sample_emp.lat,
                lng=sample_emp.lng,
                api_key=api_key,
            )
            stats["api_calls"] += 1
            time.sleep(0.1)  # gentle rate limiting

            if not result:
                # API returned no matching place
                reason = "no_result"
                stats["skipped_no_website"] += 1
                if not dry_run:
                    _record_failure(session, "brand_group", brand.id, brand.canonical_name, reason)
                    stats["failures_recorded"] += 1
                else:
                    logger.info("  [DRY] FAIL (no_result): %s", brand.canonical_name)
                continue

            if not result.get("website"):
                # Place found but no website listed
                reason = "no_website"
                stats["skipped_no_website"] += 1
                if not dry_run:
                    _record_failure(session, "brand_group", brand.id, brand.canonical_name, reason)
                    stats["failures_recorded"] += 1
                else:
                    logger.info("  [DRY] FAIL (no_website): %s", brand.canonical_name)
                continue

            # Validate that Google returned the right business
            gp_name = result.get("display_name", "")
            if gp_name and not validate_place_name(brand.canonical_name, gp_name):
                reason = f"name_mismatch:{gp_name}"
                logger.warning(
                    "[GooglePlaces] Name mismatch for %r: Google returned %r — skipping",
                    brand.canonical_name, gp_name,
                )
                stats["skipped_no_website"] += 1
                if not dry_run:
                    _record_failure(session, "brand_group", brand.id, brand.canonical_name, reason)
                    stats["failures_recorded"] += 1
                continue

            stats["brands_resolved"] += 1
            website = result["website"]

            if dry_run:
                logger.info(
                    "  [DRY] %s (%d locs) → %s",
                    brand.canonical_name, brand.location_count, website,
                )
                stats["urls_stored"] += brand.location_count
                continue

            # Clear any prior failure record — this brand is now resolved
            _clear_failure(session, "brand_group", brand.id)
            stats["failures_cleared"] += 1

            # Fan out to all locations of this brand
            brand_emps = session.query(LocalEmployer).filter(
                LocalEmployer.brand_group_id == brand.id,
                LocalEmployer.region == region,
                LocalEmployer.is_active.is_(True),
            ).all()

            for emp in brand_emps:
                url_data = {
                    "local_employer_id": emp.id,
                    "brand_group_id": brand.id,
                    "url": website,
                    "source": "google_places",
                    "confidence": 0.9,
                    "is_active": True,
                    "is_permanent": True,
                    "last_checked": now,
                    "created_at": now,
                    "updated_at": now,
                }
                stmt = pg_insert(RestaurantURL).values(**url_data)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_restaurant_url_employer_source",
                    set_={
                        "brand_group_id": stmt.excluded.brand_group_id,
                        "url": stmt.excluded.url,
                        "confidence": stmt.excluded.confidence,
                        "is_active": True,
                        "is_permanent": True,
                        "last_checked": stmt.excluded.last_checked,
                        "updated_at": now,
                    },
                )
                session.execute(stmt)
                stats["urls_stored"] += 1

        if not dry_run:
            run.new = stats["urls_stored"]
            run.skipped = stats["skipped_no_website"]
            session.commit()

        logger.info(
            "[GooglePlaces] Done: %d brands resolved, %d URLs stored, %d API calls used, "
            "%d failures recorded, %d failures cleared",
            stats["brands_resolved"], stats["urls_stored"], stats["api_calls"],
            stats["failures_recorded"], stats["failures_cleared"],
        )

    except Exception as exc:
        session.rollback()
        logger.error("[GooglePlaces] Failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()

    return stats


def resolve_local_urls(
    region: str = "austin_tx",
    max_calls: int = MAX_BATCH_CALLS,
    dry_run: bool = False,
    retry_failed: bool = False,
    target_employer_ids: set[int] | None = None,
) -> dict:
    """Resolve URLs for individual local (non-chain) restaurants without any URL yet.

    Only targets employers that have NO restaurant_url from ANY source.
    This is the expensive path — one API call per employer.
    """
    engine = init_db()
    session = get_session(engine)
    api_key = _get_api_key()

    stats = {
        "checked": 0,
        "resolved": 0,
        "api_calls": 0,
        "skipped_no_website": 0,
        "failures_recorded": 0,
        "failures_cleared": 0,
    }

    try:
        # Employers with no ACTIVE restaurant_url at all
        has_url = session.query(RestaurantURL.local_employer_id).filter(
            RestaurantURL.is_active.is_(True),
            RestaurantURL.url.isnot(None),
        ).distinct().subquery()

        # Previously-failed employers (skip unless --retry-failed)
        previously_failed_emps = session.query(
            GooglePlacesFailure.entity_id
        ).filter(
            GooglePlacesFailure.entity_type == "local_employer",
        )

        if not retry_failed:
            failure_count = previously_failed_emps.count()
            if failure_count:
                logger.info(
                    "[GooglePlaces-Local] Skipping %d previously-failed employers (use --retry-failed to include)",
                    failure_count,
                )

        emp_filters = [
            LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
            ~LocalEmployer.id.in_(session.query(has_url)),
        ]
        if target_employer_ids is not None:
            target_ids = sorted(set(target_employer_ids))
            if not target_ids:
                return stats
            emp_filters.append(LocalEmployer.id.in_(target_ids))
        if not retry_failed:
            emp_filters.append(~LocalEmployer.id.in_(previously_failed_emps))

        employers = session.query(LocalEmployer).filter(
            *emp_filters
        ).order_by(
            LocalEmployer.id  # deterministic order for resumability
        ).limit(max_calls).all()

        logger.info("[GooglePlaces-Local] %d local employers to resolve", len(employers))

        now = datetime.now(timezone.utc)

        run = CollectorRun(
            source="google_places_local_resolver",
            fetched=len(employers),
            new=0, updated=0, skipped=0,
            run_at=now,
        )
        if not dry_run:
            session.add(run)
            session.flush()

        for emp in employers:
            if stats["api_calls"] >= max_calls:
                logger.info("[GooglePlaces-Local] Hit budget (%d), stopping", max_calls)
                break

            stats["checked"] += 1

            result = resolve_place_website(
                name=emp.name,
                address=emp.address or "Austin, TX",
                lat=emp.lat,
                lng=emp.lng,
                api_key=api_key,
            )
            stats["api_calls"] += 1
            time.sleep(0.1)

            if not result:
                stats["skipped_no_website"] += 1
                if not dry_run:
                    _record_failure(session, "local_employer", emp.id, emp.name, "no_result")
                    stats["failures_recorded"] += 1
                else:
                    logger.info("  [DRY] FAIL (no_result): %s", emp.name)
                continue

            if not result.get("website"):
                stats["skipped_no_website"] += 1
                if not dry_run:
                    _record_failure(session, "local_employer", emp.id, emp.name, "no_website")
                    stats["failures_recorded"] += 1
                else:
                    logger.info("  [DRY] FAIL (no_website): %s", emp.name)
                continue

            # Validate that Google returned the right business
            gp_name = result.get("display_name", "")
            if gp_name and not validate_place_name(emp.name, gp_name):
                reason = f"name_mismatch:{gp_name}"
                logger.warning(
                    "[GooglePlaces-Local] Name mismatch for %r: Google returned %r — skipping",
                    emp.name, gp_name,
                )
                stats["skipped_no_website"] += 1
                if not dry_run:
                    _record_failure(session, "local_employer", emp.id, emp.name, reason)
                    stats["failures_recorded"] += 1
                continue

            stats["resolved"] += 1

            if dry_run:
                logger.info("  [DRY] %s → %s", emp.name, result["website"])
                continue

            # Clear any prior failure record — this employer is now resolved
            _clear_failure(session, "local_employer", emp.id)
            stats["failures_cleared"] += 1

            url_data = {
                "local_employer_id": emp.id,
                "brand_group_id": emp.brand_group_id,
                "url": result["website"],
                "source": "google_places",
                "confidence": 0.9,
                "is_active": True,
                "is_permanent": True,
                "last_checked": now,
                "created_at": now,
                "updated_at": now,
            }
            stmt = pg_insert(RestaurantURL).values(**url_data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_restaurant_url_employer_source",
                set_={
                    "brand_group_id": stmt.excluded.brand_group_id,
                    "url": stmt.excluded.url,
                    "confidence": stmt.excluded.confidence,
                    "is_active": True,
                    "is_permanent": True,
                    "last_checked": stmt.excluded.last_checked,
                    "updated_at": now,
                },
            )
            session.execute(stmt)

        if not dry_run:
            run.new = stats["resolved"]
            run.skipped = stats["skipped_no_website"]
            session.commit()

        logger.info(
            "[GooglePlaces-Local] Done: %d resolved / %d checked, %d API calls, "
            "%d failures recorded, %d failures cleared",
            stats["resolved"], stats["checked"], stats["api_calls"],
            stats["failures_recorded"], stats["failures_cleared"],
        )

    except Exception as exc:
        session.rollback()
        logger.error("[GooglePlaces-Local] Failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()

    return stats


def run_google_places_resolver(
    region: str = "austin_tx",
    mode: str = "brands",
    max_calls: int = MAX_BATCH_CALLS,
    dry_run: bool = False,
    retry_failed: bool = False,
) -> dict:
    """Entry point: resolve URLs via Google Places.

    Modes:
      - "brands": Resolve brand_groups first (highest ROI)
      - "locals": Resolve individual local employers (expensive)
      - "both":   Brands first, then locals with remaining budget

    retry_failed=True includes brands/employers that previously returned no
    result or no website — useful after manual data corrections.
    """
    if mode == "brands":
        return resolve_brand_urls(region=region, max_calls=max_calls, dry_run=dry_run, retry_failed=retry_failed)
    elif mode == "locals":
        return resolve_local_urls(region=region, max_calls=max_calls, dry_run=dry_run, retry_failed=retry_failed)
    elif mode == "both":
        brand_stats = resolve_brand_urls(region=region, max_calls=max_calls, dry_run=dry_run, retry_failed=retry_failed)
        remaining = max_calls - brand_stats["api_calls"]
        if remaining > 0:
            local_stats = resolve_local_urls(region=region, max_calls=remaining, dry_run=dry_run, retry_failed=retry_failed)
            return {
                "brand_phase": brand_stats,
                "local_phase": local_stats,
                "total_api_calls": brand_stats["api_calls"] + local_stats["api_calls"],
            }
        return {"brand_phase": brand_stats, "local_phase": None, "total_api_calls": brand_stats["api_calls"]}
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'brands', 'locals', or 'both'.")


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Resolve restaurant URLs via Google Places API")
    parser.add_argument("--mode", choices=["brands", "locals", "both"], default="brands",
                        help="Resolution mode (default: brands)")
    parser.add_argument("--max-calls", type=int, default=MAX_BATCH_CALLS,
                        help=f"Max API calls per run (default: {MAX_BATCH_CALLS})")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="Include brands/employers that previously returned no result (re-spend API budget on them)",
    )
    args = parser.parse_args()

    stats = run_google_places_resolver(
        region=args.region,
        mode=args.mode,
        max_calls=args.max_calls,
        dry_run=args.dry_run,
        retry_failed=args.retry_failed,
    )
    print(f"\n--- Google Places URL Resolution Stats ---")
    if isinstance(stats.get("brand_phase"), dict):
        print("  Brand phase:")
        for k, v in stats["brand_phase"].items():
            print(f"    {k}: {v}")
        if stats.get("local_phase"):
            print("  Local phase:")
            for k, v in stats["local_phase"].items():
                print(f"    {k}: {v}")
        print(f"  Total API calls: {stats['total_api_calls']}")
    else:
        for k, v in stats.items():
            print(f"  {k}: {v}")
