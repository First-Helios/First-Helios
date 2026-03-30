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
from backend.database import Store, get_session, init_db
from backend.ingest_layer import ingest_employers_bulk
from backend.normalizer import CATEGORY_INDUSTRY_MAP, map_industry
from config.loader import get_config
from collectors.base import BaseScraper, ScraperSignal

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

# CATEGORY_INDUSTRY_MAP moved to backend/normalizer.py — imported above.

_CATEGORY_INDUSTRY_MAP_PLACEHOLDER: dict[str, str] = {
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
# UPWARD_MOBILITY_CATEGORIES moved to backend/normalizer.py — imported above.

# No chain exclusions — all employers (brands and local) are ingested into local_employers.
# Classification as brand vs. local is done post-ingest by classify_local_employers.py
# using location_count (name frequency in Austin data). location_count >= CHAIN_THRESHOLD
# marks a record as a brand; below threshold is treated as a local operator.
CHAIN_EXCLUSIONS: list[str] = []


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
    """Ingest cached Overture GeoJSON into local_employers via the ingest layer.

    All records (brands and local) go through backend.ingest_layer.ingest_employers_bulk,
    which normalizes names, fingerprints, upserts brand_groups, and deduplicates.
    No direct DB writes happen here.

    Args:
        geojson_path: Path to local .geojson file
        region: Region key for all records (default: austin_tx)

    Returns:
        dict with local_employers count and skipped count
    """
    import json
    from pathlib import Path

    geojson_file = Path(geojson_path)
    if not geojson_file.exists():
        logger.error("[Overture] File not found: %s", geojson_path)
        return {"error": "File not found", "local_employers": 0, "skipped": 0}

    logger.info("[Overture] Loading GeoJSON from %s", geojson_file.name)

    try:
        with open(geojson_file) as f:
            geojson_data = json.load(f)
    except Exception as e:
        logger.error("[Overture] Failed to read GeoJSON: %s", e)
        return {"error": str(e), "local_employers": 0, "skipped": 0}

    features = geojson_data.get("features", [])
    logger.info("[Overture] Parsing %d features…", len(features))

    records: list[dict] = []
    skipped = 0

    for feature in features:
        try:
            props = feature.get("properties", {})
            geom  = feature.get("geometry", {})
            coords = geom.get("coordinates", [None, None])

            store_name       = props.get("names", {}).get("primary", "") or ""
            category_primary = props.get("categories", {}).get("primary", "") or ""
            confidence       = props.get("confidence", 0.5)
            lng = float(coords[0]) if coords[0] is not None else None
            lat = float(coords[1]) if coords[1] is not None else None

            # Industry must be mappable; skip uncategorized records
            industry = map_industry(category_primary)
            if not industry:
                skipped += 1
                continue

            addresses = props.get("addresses", [])
            address_str = ""
            if addresses:
                addr = addresses[0]
                address_str = ", ".join(
                    p for p in [
                        addr.get("freeform", ""),
                        addr.get("locality", ""),
                        addr.get("region", ""),
                    ] if p
                )

            records.append({
                "overture_id":  props.get("id", ""),
                "name":         store_name or f"POI {props.get('id', '')[-6:]}",
                "category":     category_primary,
                "industry":     industry,
                "address":      address_str,
                "lat":          lat,
                "lng":          lng,
                "region":       region,
                "confidence":   confidence,
                # mobility_score computed by ingest_layer from IndustryTaxonomy
                "is_active":    props.get("operating_status", "unknown") == "open",
            })
        except Exception as row_e:
            logger.debug("[Overture] Error parsing feature: %s", row_e)
            skipped += 1
            continue

    logger.info("[Overture] %d records to ingest, %d skipped (no industry mapping)", len(records), skipped)

    result = ingest_employers_bulk(records, source="overture")
    result["skipped"] = skipped + result.get("skipped", 0)
    return result


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
