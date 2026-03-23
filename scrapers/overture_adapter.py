"""
scrapers/overture_adapter.py

Queries Overture Maps Places dataset via DuckDB directly from S3.
No full download of the 64M POI dataset — bbox + filter queries only.
First-run installs DuckDB spatial/httpfs extensions (~30 sec pause — do not kill).

Two modes:
  chain  — named brand lookup (cross-validates AllThePlaces chain data)
  local  — category lookup excluding known chains (populates local_employers table)

License: CDLA Permissive v2 — derivative products permitted.
Depends on: duckdb (pip install duckdb overturemaps)
Called by: CLI for initial population, scheduler weekly

Usage:
    python scrapers/overture_adapter.py --mode chain --chain starbucks --region austin_tx
    python scrapers/overture_adapter.py --mode local --industry coffee_cafe --region austin_tx
"""

import logging
import sys
from datetime import datetime

import duckdb

sys.path.insert(0, ".")
from backend.database import LocalEmployer, Store, get_session, init_db
from config.loader import get_config
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)
config = get_config()

# Populated at ingest time from ref_brands; avoids repeated DB lookups per feature
_BRAND_INDUSTRY_CACHE: dict[str, str] = {}


def _get_overture_s3_path() -> str:
    """Get the S3 parquet path for the latest Overture Maps release."""
    try:
        from overturemaps.core import get_latest_release
        release = get_latest_release()
    except Exception:
        release = "2026-03-18.0"  # fallback
    return (
        f"s3://overturemaps-us-west-2/release/{release}"
        "/theme=places/type=place/*"
    )

# Overture category → industry mapping
# Covers all physical-location employer categories — food, trades, healthcare, auto, personal care, etc.
CATEGORY_INDUSTRY_MAP: dict[str, str] = {
    # ── Food & Beverage ──────────────────────────────────────────────────────
    "coffee_shop":           "coffee_cafe",
    "cafe":                  "coffee_cafe",
    "donut_shop":            "coffee_cafe",
    "tea_house":             "coffee_cafe",
    "fast_food_restaurant":  "fast_food",
    "sandwich_shop":         "fast_food",
    "burger_restaurant":     "fast_food",
    "pizza_restaurant":      "fast_food",
    "mexican_restaurant":    "fast_food",
    "taco_restaurant":       "fast_food",
    "food_truck":            "fast_food",
    "restaurant":            "food_full_service",
    "american_restaurant":   "food_full_service",
    "barbecue_restaurant":   "food_full_service",
    "bakery":                "food_full_service",
    "bar":                   "bar_nightlife",
    # ── Retail ──────────────────────────────────────────────────────────────
    "grocery_store":         "retail_general",
    "convenience_store":     "retail_general",
    "clothing_store":        "retail_general",
    "department_store":      "retail_general",
    "furniture_store":       "retail_general",
    "electronics":           "retail_general",
    "jewelry_store":         "retail_general",
    "liquor_store":          "retail_general",
    "flowers_and_gifts_shop":"retail_general",
    "mobile_phone_store":    "retail_general",
    "retail":                "retail_general",
    "pharmacy":              "retail_pharmacy",
    # ── Hospitality ─────────────────────────────────────────────────────────
    "hotel":                 "hospitality",
    "motel":                 "hospitality",
    # ── Automotive ──────────────────────────────────────────────────────────
    "automotive_repair":     "auto_services",
    "auto_body_shop":        "auto_services",
    "gas_station":           "auto_services",
    "key_and_locksmith":     "auto_services",
    "car_dealer":            "auto_dealer",
    # ── Personal Care & Beauty ───────────────────────────────────────────────
    "beauty_salon":          "personal_care",
    "hair_salon":            "personal_care",
    "nail_salon":            "personal_care",
    "barber":                "personal_care",
    "spas":                  "personal_care",
    "massage_therapy":       "personal_care",
    "massage":               "personal_care",
    "beauty_and_spa":        "personal_care",
    "medical_spa":           "personal_care",
    "tattoo_and_piercing":   "personal_care",
    # ── Fitness ─────────────────────────────────────────────────────────────
    "gym":                   "fitness",
    "martial_arts_club":     "fitness",
    # ── Skilled Trades & Home Services ──────────────────────────────────────
    "hvac_services":         "skilled_trades",
    "contractor":            "skilled_trades",
    "roofing":               "skilled_trades",
    "landscaping":           "skilled_trades",
    "home_service":          "skilled_trades",
    "home_cleaning":         "skilled_trades",
    "construction_services": "skilled_trades",
    "building_supply_store": "skilled_trades",
    "industrial_equipment":  "skilled_trades",
    # ── Healthcare ──────────────────────────────────────────────────────────
    "doctor":                "healthcare",
    "dentist":               "healthcare",
    "chiropractor":          "healthcare",
    "physical_therapy":      "healthcare",
    "hospital":              "healthcare",
    "medical_center":        "healthcare",
    "optometrist":           "healthcare",
    "health_and_medical":    "healthcare",
    "counseling_and_mental_health": "healthcare",
    "naturopathic_holistic": "healthcare",
    "veterinarian":          "healthcare",
    # ── Finance ─────────────────────────────────────────────────────────────
    "bank_credit_union":     "finance",
    "banks":                 "finance",
    "financial_service":     "finance",
    "insurance_agency":      "finance",
    # ── Education ───────────────────────────────────────────────────────────
    "elementary_school":     "education",
    "preschool":             "education",
    "college_university":    "education",
    "education":             "education",
    # ── Staffing / Professional ──────────────────────────────────────────────
    "employment_agencies":        "staffing",
    "it_service_and_computer_repair": "tech_services",
    "printing_services":          "professional_services",
    # ── Upward Mobility: Professional / Office ───────────────────────────────
    "professional_services":      "professional_services",
    "software_development":       "tech_services",
    "corporate_office":           "professional_services",
    "lawyer":                     "professional_services",
    "legal_services":             "professional_services",
    "marketing_agency":           "professional_services",
    "advertising_agency":         "professional_services",
    "financial_advising":         "finance",
    "mortgage_broker":            "finance",
    "mortgage_lender":            "finance",
    "information_technology_company": "tech_services",
    "accountant":                 "professional_services",
    "interior_design":            "professional_services",
    "engineering_services":       "professional_services",
    "event_planning":             "professional_services",
    "architectural_designer":     "professional_services",
    "credit_union":               "finance",
    # ── Additional Healthcare ────────────────────────────────────────────────
    "general_dentistry":          "healthcare",
    "pediatrician":               "healthcare",
    "obstetrician_and_gynecologist": "healthcare",
    "cardiologist":               "healthcare",
    "orthopedist":                "healthcare",
    "acupuncture":                "healthcare",
    "home_health_care":           "healthcare",
    "retirement_home":            "healthcare",
    # ── Additional Skilled Trades ────────────────────────────────────────────
    "plumbing":                   "skilled_trades",
    "electrician":                "skilled_trades",
    "garage_door_service":        "skilled_trades",
    "home_improvement_store":     "skilled_trades",
    # ── Additional Auto ──────────────────────────────────────────────────────
    "used_car_dealer":            "auto_dealer",
    "car_wash":                   "auto_services",
    "tire_dealer_and_repair":     "auto_services",
    "automotive_parts_and_accessories": "auto_services",
    "automotive":                 "auto_services",
    # ── Additional Fitness / Wellness ────────────────────────────────────────
    "yoga_studio":                "fitness",
    "dance_school":               "fitness",
    # ── Additional Food ──────────────────────────────────────────────────────
    "ice_cream_shop":             "food_full_service",
    "smoothie_juice_bar":         "food_full_service",
    # ── Additional Retail ────────────────────────────────────────────────────
    "shoe_store":                 "retail_general",
    "womens_clothing_store":      "retail_general",
    "cosmetic_and_beauty_supplies": "retail_general",
    "pet_store":                  "retail_general",
    # ── Logistics ────────────────────────────────────────────────────────────
    "courier_and_delivery_services": "logistics",
    # ── Nonprofit / Community ────────────────────────────────────────────────
    "community_services_non_profits": "nonprofit",
    "social_service_organizations":   "nonprofit",
}

# Categories that represent upward mobility from service/entry-level work.
# These employers are destinations a food service / retail / hospitality worker
# could realistically target for career advancement — or entry points for
# workers coming from outside the service sector.
UPWARD_MOBILITY_CATEGORIES: set[str] = {
    # Office / professional
    "professional_services", "corporate_office", "marketing_agency",
    "advertising_agency", "interior_design", "engineering_services",
    "event_planning", "architectural_designer", "printing_services",
    "accountant",
    # Tech
    "software_development", "information_technology_company",
    "it_service_and_computer_repair", "tech_services",
    # Legal / finance
    "lawyer", "legal_services", "financial_advising", "financial_service",
    "mortgage_broker", "mortgage_lender", "bank_credit_union", "banks",
    "credit_union", "insurance_agency",
    # Staffing / employment
    "employment_agencies", "staffing",
    # Education
    "education", "college_university", "elementary_school", "preschool",
    "dance_school",
    # Skilled trades (certification-based, good wages)
    "hvac_services", "electrician", "plumbing", "contractor",
    "roofing", "construction_services",
    # Healthcare (many non-clinical roles)
    "hospital", "medical_center", "home_health_care",
    # Nonprofit / community
    "community_services_non_profits", "social_service_organizations",
    # Hospitality management
    "hotel", "motel",
    # Logistics
    "courier_and_delivery_services",
}

# Chain names to exclude from local employer queries (lowercase LIKE patterns)
CHAIN_EXCLUSIONS: list[str] = [
    "starbucks",
    "dutch bros",
    "mcdonald",
    "dunkin",
    "taco bell",
    "subway",
    "chick-fil-a",
    "whataburger",
    "wendy",
    "burger king",
    "domino",
    "pizza hut",
    "panda express",
    "chipotle",
    "sonic",
    "popeyes",
    "jack in the box",
    "in-n-out",
    "five guys",
    "panera",
    "tim horton",
    "peet",
    "caribou",
    "coffee bean",
    "costa coffee",
    "walmart",
    "target",
    "costco",
    "heb",
    "kroger",
    "whole foods",
    "trader joe",
    "aldi",
    "cvs",
    "walgreen",
    "holiday inn",
    "marriott",
    "hilton",
    "hyatt",
    "best western",
]


def _bbox_from_region(region: str) -> dict[str, float]:
    """Compute bounding box from region config."""
    region_cfg = config.get("regions", {}).get(region, {})
    if "bbox" in region_cfg:
        return region_cfg["bbox"]
    lat = region_cfg.get("center_lat", 30.2672)
    lng = region_cfg.get("center_lng", -97.7431)
    r = region_cfg.get("radius_mi", 25) / 69.0
    return {"west": lng - r, "east": lng + r, "south": lat - r, "north": lat + r}


def _get_duckdb_conn() -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection with spatial and httpfs extensions loaded."""
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; INSTALL httpfs; LOAD spatial; LOAD httpfs;")
    conn.execute("SET s3_region='us-west-2';")
    return conn


class OvertureChainAdapter(BaseScraper):
    """Queries Overture for chain store locations.

    Cross-validates AllThePlaces data and fills geographic gaps.
    Upserts into the stores table.
    """

    name = "overture_chain"
    chain = "starbucks"

    CHAIN_NAME_FILTERS: dict[str, str] = {
        "starbucks": "%starbucks%",
        "dutch_bros": "%dutch bros%",
        "mcdonalds": "%mcdonald%",
        "target_retail": "%target%",
        "whataburger": "%whataburger%",
        "chipotle": "%chipotle%",
    }

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            name_filter = self.CHAIN_NAME_FILTERS.get(self.chain)
            if not name_filter:
                logger.warning("[Overture] No name filter for chain: %s", self.chain)
                return []

            bbox = _bbox_from_region(region)
            s3_path = _get_overture_s3_path()

            query = f"""
            SELECT
                id,
                names.primary AS name,
                categories.primary AS category,
                addresses[1].freeform AS address,
                ST_X(geometry) AS lng,
                ST_Y(geometry) AS lat,
                confidence
            FROM read_parquet('{s3_path}', hive_partitioning=1)
            WHERE names.primary ILIKE '{name_filter}'
              AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
              AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
              AND confidence > 0.8
            """

            logger.info("[Overture] Connecting to S3 for chain=%s region=%s", self.chain, region)
            conn = _get_duckdb_conn()
            logger.info("[Overture] Querying (first run installs extensions, ~30s)...")
            import time as _t
            from backend.tracked_request import log_external
            _t0 = _t.time()
            rows = conn.execute(query).fetchall()
            _lat_ms = int((_t.time() - _t0) * 1000)
            conn.close()
            log_external(
                "overture_s3", "chain_query",
                url=s3_path, success=True,
                latency_ms=_lat_ms, data_items=len(rows),
            )

            cols = ["overture_id", "name", "category", "address", "lng", "lat", "confidence"]
            places = [dict(zip(cols, r)) for r in rows]
            logger.info("[Overture] Found %d %s locations", len(places), self.chain)

            chain_cfg = config.get("chains", {}).get(self.chain, {})
            signals: list[ScraperSignal] = []

            engine = init_db()
            session = get_session(engine)
            try:
                for p in places:
                    oid = str(p["overture_id"])
                    store_num = f"OV-{self.chain.upper()[:2]}-{oid[-8:]}"
                    existing = session.query(Store).filter_by(store_num=store_num).first()
                    if existing:
                        existing.lat = p["lat"]
                        existing.lng = p["lng"]
                        existing.last_seen = datetime.utcnow()
                    else:
                        session.add(
                            Store(
                                store_num=store_num,
                                chain=self.chain,
                                industry=chain_cfg.get("industry", "unknown"),
                                store_name=p["name"] or self.chain.title(),
                                address=p["address"] or "",
                                lat=p["lat"],
                                lng=p["lng"],
                                region=region,
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                                is_active=True,
                            )
                        )
                    signals.append(
                        ScraperSignal(
                            store_num=store_num,
                            chain=self.chain,
                            source=self.name,
                            signal_type="store_presence",
                            value=float(p["confidence"] or 0),
                            metadata={
                                "overture_id": oid,
                                "address": p["address"],
                                "lat": p["lat"],
                                "lng": p["lng"],
                                "category": p["category"],
                            },
                            observed_at=datetime.utcnow(),
                        )
                    )
                session.commit()
                logger.info(
                    "[Overture] Upserted %d %s chain stores", len(signals), self.chain
                )
            except Exception as db_e:
                session.rollback()
                logger.error("[Overture] DB write failed (chain): %s", db_e)
            finally:
                session.close()

            return signals

        except Exception as e:
            logger.error("[Overture] chain scrape() failed for %s/%s: %s", self.chain, region, e)
            return []


class OvertureLocalAdapter(BaseScraper):
    """Queries Overture for local (non-chain) employers by category.

    Populates the local_employers table used by the targeting score
    local_alternatives component.
    """

    name = "overture_local"
    chain = "local"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            bbox = _bbox_from_region(region)
            categories = list(CATEGORY_INDUSTRY_MAP.keys())

            cat_filter = " OR ".join(
                f"categories.primary = '{c}'" for c in categories
            )
            chain_filter = " AND ".join(
                f"lower(names.primary) NOT LIKE '%{c}%'" for c in CHAIN_EXCLUSIONS
            )
            s3_path = _get_overture_s3_path()

            query = f"""
            SELECT
                id,
                names.primary AS name,
                categories.primary AS category,
                addresses[1].freeform AS address,
                ST_X(geometry) AS lng,
                ST_Y(geometry) AS lat,
                confidence
            FROM read_parquet('{s3_path}', hive_partitioning=1)
            WHERE ({cat_filter})
              AND ({chain_filter})
              AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
              AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
              AND confidence > 0.7
            """

            logger.info("[Overture] Querying local employers for region=%s", region)
            conn = _get_duckdb_conn()
            import time as _t
            from backend.tracked_request import log_external
            _t0 = _t.time()
            rows = conn.execute(query).fetchall()
            _lat_ms = int((_t.time() - _t0) * 1000)
            conn.close()
            log_external(
                "overture_s3", "local_query",
                url=s3_path, success=True,
                latency_ms=_lat_ms, data_items=len(rows),
            )

            cols = ["overture_id", "name", "category", "address", "lng", "lat", "confidence"]
            places = [dict(zip(cols, r)) for r in rows]
            logger.info("[Overture] Found %d local employer locations", len(places))

            signals: list[ScraperSignal] = []
            engine = init_db()
            session = get_session(engine)
            try:
                for p in places:
                    oid = str(p["overture_id"])
                    industry = CATEGORY_INDUSTRY_MAP.get(str(p["category"] or ""), "unknown")
                    existing = (
                        session.query(LocalEmployer).filter_by(overture_id=oid).first()
                    )
                    if existing:
                        existing.last_seen = datetime.utcnow()
                        existing.confidence = p["confidence"]
                    else:
                        session.add(
                            LocalEmployer(
                                overture_id=oid,
                                name=p["name"] or "Unknown",
                                category=p["category"],
                                industry=industry,
                                address=p["address"] or "",
                                lat=p["lat"],
                                lng=p["lng"],
                                region=region,
                                confidence=p["confidence"],
                                is_active=True,
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                            )
                        )
                    signals.append(
                        ScraperSignal(
                            store_num=f"LOCAL-{oid[-8:]}",
                            chain="local",
                            source=self.name,
                            signal_type="local_presence",
                            value=float(p["confidence"] or 0),
                            metadata={
                                "overture_id": oid,
                                "name": p["name"],
                                "category": p["category"],
                                "industry": industry,
                                "address": p["address"],
                                "lat": p["lat"],
                                "lng": p["lng"],
                            },
                            observed_at=datetime.utcnow(),
                        )
                    )
                session.commit()
                logger.info("[Overture] Upserted %d local employers", len(signals))
            except Exception as db_e:
                session.rollback()
                logger.error("[Overture] DB write failed (local): %s", db_e)
            finally:
                session.close()

            return signals

        except Exception as e:
            logger.error("[Overture] local scrape() failed for %s: %s", region, e)
            return []


def ingest_local_geojson(geojson_path: str, region: str = "austin_tx") -> dict:
    """Ingest cached Overture GeoJSON file into chain_locations and local_employers.

    Reads local cached GeoJSON (instead of S3 DuckDB queries) and:
      - Matches known chains by name pattern
      - Maps categories to industries for local employers
      - Upserts to appropriate tables

    Args:
        geojson_path: Path to local .geojson file
        region: Region key for all records (default: austin_tx)

    Returns:
        dict with chain_locations and local_employers counts
    """
    import json
    from pathlib import Path

    geojson_file = Path(geojson_path)
    if not geojson_file.exists():
        logger.error("[Overture Local] File not found: %s", geojson_path)
        return {"error": "File not found", "chain_locations": 0, "local_employers": 0}

    logger.info("[Overture Local] Loading GeoJSON from %s", geojson_file.name)

    try:
        engine = init_db()
        session = get_session(engine)
    except Exception as e:
        logger.error("[Overture Local] Failed to initialize DB: %s", e)
        return {"error": str(e), "chain_locations": 0, "local_employers": 0}

    chain_count = 0
    local_count = 0
    skipped_count = 0

    # Build brand_key → internal_industry lookup so chain rows get correct industry on insert
    global _BRAND_INDUSTRY_CACHE
    try:
        from sqlalchemy import text as _text
        _rows = session.execute(_text("SELECT brand_key, internal_industry FROM ref_brands")).fetchall()
        _BRAND_INDUSTRY_CACHE = {r[0]: r[1] for r in _rows if r[1]}
    except Exception:
        _BRAND_INDUSTRY_CACHE = {}

    try:
        with open(geojson_file) as f:
            geojson_data = json.load(f)

        features = geojson_data.get("features", [])
        logger.info("[Overture Local] Processing %d features", len(features))

        for feature in features:
            try:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [None, None])

                # Extract fields
                overture_id = props.get("id", "")
                store_name = props.get("names", {}).get("primary", "")
                category_primary = props.get("categories", {}).get("primary", "")
                confidence = props.get("confidence", 0.5)
                coords_lng = float(coords[0]) if coords[0] is not None else None
                coords_lat = float(coords[1]) if coords[1] is not None else None

                # Get address
                addresses = props.get("addresses", [])
                address_str = ""
                if addresses:
                    addr = addresses[0]
                    parts = [
                        addr.get("freeform", ""),
                        addr.get("locality", ""),
                        addr.get("region", ""),
                    ]
                    address_str = ", ".join(p for p in parts if p)

                # Get brand name
                brand_name = props.get("brand", {}).get("names", {}).get("primary", None)

                # Check if it's a known chain
                is_chain = False
                chain_key = None
                if brand_name:
                    brand_lower = brand_name.lower()
                    for ckey, pattern in OvertureChainAdapter.CHAIN_NAME_FILTERS.items():
                        # Pattern like "%starbucks%" → check if brand contains "starbucks"
                        search_str = pattern.strip("%")
                        if search_str.lower() in brand_lower:
                            is_chain = True
                            chain_key = ckey
                            break

                if is_chain and chain_key:
                    # Upsert to chain_locations
                    store_num = f"OV-{chain_key.upper()}-{overture_id[-8:]}"
                    # Resolve industry from ref_brands if available
                    _brand_industry = _BRAND_INDUSTRY_CACHE.get(chain_key, "unknown")
                    store = Store(
                        store_num=store_num,
                        brand_key=chain_key,
                        chain=brand_name or "Unknown Chain",
                        industry=_brand_industry,
                        store_name=store_name,
                        address=address_str,
                        lat=coords_lat,
                        lng=coords_lng,
                        region=region,
                        source_discovery="overture_local",
                        is_active=props.get("operating_status", "unknown") == "open",
                    )
                    session.merge(store)
                    chain_count += 1

                else:
                    # Try to map category to industry
                    industry = CATEGORY_INDUSTRY_MAP.get(category_primary, None)

                    # Skip if category doesn't map and name looks like a chain
                    if not industry:
                        name_lower = (store_name or "").lower()
                        is_excluded_chain = any(
                            ex in name_lower for ex in CHAIN_EXCLUSIONS
                        )
                        if is_excluded_chain:
                            skipped_count += 1
                            continue

                        # Skip uncategorized
                        skipped_count += 1
                        continue

                    # Upsert to local_employers (must query first — autoincrement PK)
                    is_mobility = (
                        category_primary in UPWARD_MOBILITY_CATEGORIES
                        or industry in UPWARD_MOBILITY_CATEGORIES
                    )
                    existing_local = (
                        session.query(LocalEmployer)
                        .filter_by(overture_id=overture_id)
                        .first()
                    )
                    if existing_local:
                        existing_local.name = store_name or existing_local.name
                        existing_local.category = category_primary
                        existing_local.industry = industry
                        existing_local.address = address_str or existing_local.address
                        existing_local.lat = coords_lat
                        existing_local.lng = coords_lng
                        existing_local.confidence = confidence
                        existing_local.upward_mobility = is_mobility
                        existing_local.last_seen = datetime.utcnow()
                    else:
                        session.add(LocalEmployer(
                            overture_id=overture_id,
                            name=store_name or f"POI {overture_id[-6:]}",
                            category=category_primary,
                            industry=industry,
                            address=address_str,
                            lat=coords_lat,
                            lng=coords_lng,
                            region=region,
                            source_discovery="overture_local",
                            confidence=confidence,
                            upward_mobility=is_mobility,
                            is_active=props.get("operating_status", "unknown") == "open",
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        ))
                    local_count += 1

                # Commit every 500 records
                if (chain_count + local_count) % 500 == 0:
                    session.commit()
                    logger.debug(
                        "[Overture Local] Committed %d + %d records",
                        chain_count,
                        local_count,
                    )

            except Exception as row_e:
                logger.debug("[Overture Local] Error processing feature: %s", row_e)
                continue

        session.commit()
        logger.info(
            "[Overture Local] Ingestion complete: %d chains, %d local employers, %d skipped",
            chain_count,
            local_count,
            skipped_count,
        )
        return {
            "chain_locations": chain_count,
            "local_employers": local_count,
            "skipped": skipped_count,
        }

    except Exception as e:
        logger.error("[Overture Local] GeoJSON ingestion failed: %s", e, exc_info=True)
        session.rollback()
        return {"error": str(e), "chain_locations": 0, "local_employers": 0}
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    from backend.ingest import ingest_signals

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Overture Maps POI scraper")
    parser.add_argument("--mode", choices=["chain", "local"], default=None)
    parser.add_argument("--chain", default="starbucks")
    parser.add_argument("--industry", default="coffee_cafe")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--local-file", type=str, help="Path to local GeoJSON file for ingestion")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Local GeoJSON file ingestion
    if args.local_file:
        print(f"\nIngesting from local GeoJSON: {args.local_file}")
        result = ingest_local_geojson(args.local_file, region=args.region)
        print(f"Result: {result}")
        sys.exit(0)

    # S3-based ingestion (existing mode)
    if not args.mode:
        parser.error("--mode is required unless using --local-file")

    if args.mode == "chain":
        adapter: BaseScraper = OvertureChainAdapter()
        adapter.chain = args.chain  # type: ignore[attr-defined]
    else:
        adapter = OvertureLocalAdapter()

    signals = adapter.scrape(args.region)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Found {len(signals)} locations")
    for s in signals[:5]:
        m = s.metadata
        print(
            f"  {s.store_num}  {m.get('name') or s.store_num}"
            f"  ({m.get('lat', 0):.4f}, {m.get('lng', 0):.4f})"
        )
    if len(signals) > 5:
        print(f"  ... and {len(signals) - 5} more")

    if not args.dry_run and signals:
        ingest_signals(signals, region=args.region)
        print(f"Ingested {len(signals)} signals.")
