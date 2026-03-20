"""
scripts/populate_reference_data.py

Downloads and loads reference / taxonomy data from public sources.
Run ONCE on initial setup, then quarterly to refresh.

Sources:
  - NAICS codes: Census Bureau (public domain)
  - Brand profiles: Wikidata SPARQL (CC-0) + manual curation
  - Regional economics: BLS QCEW + MIT Living Wage (public domain)
  - Category mappings: hand-curated crosswalk

Usage:
    python scripts/populate_reference_data.py --all
    python scripts/populate_reference_data.py --brands-only
    python scripts/populate_reference_data.py --regions-only
"""

import json
import logging
import sys
from datetime import datetime

import requests

sys.path.insert(0, ".")

from backend.database import Base, get_engine, get_session, init_db
from backend.models.reference import (
    BrandProfile,
    CategoryMapping,
    IndustryCategory,
    RegionProfile,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# NAICS Industry Codes
# Source: https://www.census.gov/naics/
# Only the food-service / retail / hospitality subtrees we care about.
# ═══════════════════════════════════════════════════════════════════════

NAICS_SEED: list[tuple] = [
    # (code, title, internal_key, parent, sector, avg_wage, avg_empl, seasonal)
    ("72",     "Accommodation and Food Services",       "accommodation_food",       None,   "food_service", None,  None, None),
    ("721",    "Accommodation",                         "accommodation",            "72",   "hospitality",  15.50, 50,   "summer_peak"),
    ("722",    "Food Services and Drinking Places",     "food_service",             "72",   "food_service", 14.50, None, None),
    ("7225",   "Restaurants and Other Eating Places",    "restaurants",              "722",  "food_service", 14.00, None, None),
    ("722511", "Full-Service Restaurants",               "full_service_restaurant",  "7225", "food_service", 15.00, 30,   "holiday_peak"),
    ("722513", "Limited-Service Restaurants",            "fast_food",                "7225", "food_service", 12.50, 25,   "flat"),
    ("722514", "Cafeterias and Buffets",                 "cafeteria",                "7225", "food_service", 12.00, 20,   "flat"),
    ("722515", "Snack and Nonalcoholic Beverage Bars",   "coffee_cafe",             "7225", "food_service", 13.00, 15,   "flat"),
    ("44",     "Retail Trade",                           "retail",                   None,   "retail",       None,  None, None),
    ("445",    "Food and Beverage Retailers",            "food_retail",              "44",   "retail",       14.00, None, None),
    ("452",    "General Merchandise Retailers",          "retail_general",           "44",   "retail",       15.00, 150,  "holiday_peak"),
]


def load_naics(session) -> None:
    """Insert or update NAICS industry rows."""
    logger.info("Loading NAICS industry codes ...")
    for row in NAICS_SEED:
        code, title, key, parent, sector, wage, emp, seasonal = row
        existing = session.query(IndustryCategory).filter_by(naics_code=code).first()
        if existing:
            existing.naics_title = title
            existing.internal_key = key
            existing.parent_naics = parent
            existing.sector = sector
            existing.avg_hourly_wage_bls = wage
            existing.avg_employees_per_location = emp
            existing.seasonal_pattern = seasonal
        else:
            session.add(IndustryCategory(
                naics_code=code,
                naics_title=title,
                internal_key=key,
                parent_naics=parent,
                sector=sector,
                avg_hourly_wage_bls=wage,
                avg_employees_per_location=emp,
                seasonal_pattern=seasonal,
            ))
    session.commit()
    n = session.query(IndustryCategory).count()
    logger.info("  ref_industry: %d rows", n)


# ═══════════════════════════════════════════════════════════════════════
# Brand Profiles
# Manual seed enriched by Wikidata SPARQL.
# ═══════════════════════════════════════════════════════════════════════

BRAND_SEED: list[dict] = [
    {
        "brand_key": "starbucks",
        "display_name": "Starbucks",
        "parent_company": "Starbucks Corporation",
        "wikidata_id": "Q37158",
        "naics_code": "722515",
        "internal_industry": "coffee_cafe",
        "is_publicly_traded": True,
        "stock_ticker": "SBUX",
        "approx_us_locations": 16000,
        "careers_url": "https://www.starbucks.com/careers/",
        "atp_spider_names": ["starbucks_us"],
        "overture_name_patterns": ["%starbucks%"],
        "osm_tags": {"brand:wikidata": "Q37158", "brand": "Starbucks"},
        "avg_starting_wage": 15.50,
        "wage_source": "glassdoor_2025",
        "typical_store_staff": 18,
        "union_presence": True,
    },
    {
        "brand_key": "dutch_bros",
        "display_name": "Dutch Bros Coffee",
        "parent_company": "Dutch Bros Inc.",
        "wikidata_id": "Q5317253",
        "naics_code": "722515",
        "internal_industry": "coffee_cafe",
        "is_publicly_traded": True,
        "stock_ticker": "BROS",
        "approx_us_locations": 900,
        "careers_url": "https://careers.dutchbros.com/",
        "atp_spider_names": ["dutch_bros"],
        "overture_name_patterns": ["%dutch bros%"],
        "osm_tags": {"brand:wikidata": "Q5317253", "brand": "Dutch Bros Coffee"},
        "avg_starting_wage": 14.00,
        "wage_source": "glassdoor_2025",
        "typical_store_staff": 12,
        "union_presence": False,
    },
    {
        "brand_key": "mcdonalds",
        "display_name": "McDonald's",
        "parent_company": "McDonald's Corporation",
        "wikidata_id": "Q38076",
        "naics_code": "722513",
        "internal_industry": "fast_food",
        "is_publicly_traded": True,
        "stock_ticker": "MCD",
        "approx_us_locations": 13400,
        "careers_url": "https://careers.mcdonalds.com/",
        "atp_spider_names": ["mcdonalds"],
        "overture_name_patterns": ["%mcdonald%"],
        "osm_tags": {"brand:wikidata": "Q38076", "brand": "McDonald's"},
        "avg_starting_wage": 13.00,
        "wage_source": "glassdoor_2025",
        "typical_store_staff": 30,
        "union_presence": False,
    },
    {
        "brand_key": "whataburger",
        "display_name": "Whataburger",
        "parent_company": "Whataburger Restaurants LLC",
        "wikidata_id": "Q376627",
        "naics_code": "722513",
        "internal_industry": "fast_food",
        "is_publicly_traded": False,
        "approx_us_locations": 900,
        "careers_url": "https://whataburger.com/careers",
        "atp_spider_names": ["whataburger"],
        "overture_name_patterns": ["%whataburger%"],
        "osm_tags": {"brand:wikidata": "Q376627", "brand": "Whataburger"},
        "avg_starting_wage": 12.50,
        "wage_source": "glassdoor_2025",
        "typical_store_staff": 25,
        "union_presence": False,
    },
    {
        "brand_key": "target_retail",
        "display_name": "Target",
        "parent_company": "Target Corporation",
        "wikidata_id": "Q1046951",
        "naics_code": "452",
        "internal_industry": "retail_general",
        "is_publicly_traded": True,
        "stock_ticker": "TGT",
        "approx_us_locations": 1950,
        "careers_url": "https://jobs.target.com/",
        "atp_spider_names": ["target_us"],
        "overture_name_patterns": ["%target%"],
        "osm_tags": {"brand:wikidata": "Q1046951", "brand": "Target"},
        "avg_starting_wage": 15.00,
        "wage_source": "company_announcement_2024",
        "typical_store_staff": 150,
        "union_presence": False,
    },
    {
        "brand_key": "chipotle",
        "display_name": "Chipotle Mexican Grill",
        "parent_company": "Chipotle Mexican Grill, Inc.",
        "wikidata_id": "Q465751",
        "naics_code": "722513",
        "internal_industry": "fast_food",
        "is_publicly_traded": True,
        "stock_ticker": "CMG",
        "approx_us_locations": 3500,
        "careers_url": "https://jobs.chipotle.com/",
        "atp_spider_names": ["chipotle"],
        "overture_name_patterns": ["%chipotle%"],
        "osm_tags": {"brand:wikidata": "Q465751", "brand": "Chipotle Mexican Grill"},
        "avg_starting_wage": 15.00,
        "wage_source": "company_announcement_2024",
        "typical_store_staff": 25,
        "union_presence": False,
    },
]


def _set_brand_json_fields(brand: BrandProfile, data: dict) -> None:
    """Set JSON-backed fields from a dict using the property setters."""
    if "atp_spider_names" in data:
        brand.atp_spider_names = data["atp_spider_names"]
    if "overture_name_patterns" in data:
        brand.overture_name_patterns = data["overture_name_patterns"]
    if "osm_tags" in data:
        brand.osm_tags = data["osm_tags"]


# Fields that are plain scalars (not JSON properties)
_BRAND_SCALAR_KEYS = {
    "display_name", "parent_company", "wikidata_id", "naics_code",
    "internal_industry", "is_chain", "is_publicly_traded", "stock_ticker",
    "approx_us_locations", "careers_url", "glassdoor_id", "indeed_query",
    "avg_starting_wage", "wage_source", "typical_store_staff", "union_presence",
}


def load_brands(session) -> None:
    """Insert or update BrandProfile rows."""
    logger.info("Loading brand profiles ...")
    for b in BRAND_SEED:
        existing = session.query(BrandProfile).filter_by(brand_key=b["brand_key"]).first()
        if existing:
            for k in _BRAND_SCALAR_KEYS:
                if k in b:
                    setattr(existing, k, b[k])
            _set_brand_json_fields(existing, b)
            existing.updated_at = datetime.utcnow()
        else:
            brand = BrandProfile(brand_key=b["brand_key"], updated_at=datetime.utcnow())
            for k in _BRAND_SCALAR_KEYS:
                if k in b:
                    setattr(brand, k, b[k])
            _set_brand_json_fields(brand, b)
            session.add(brand)
    session.commit()
    n = session.query(BrandProfile).count()
    logger.info("  ref_brands: %d rows", n)


def enrich_brands_from_wikidata(session) -> None:
    """Pull structured data from Wikidata for brands with a wikidata_id.

    This fills in parent_company, employee count, founding date, etc.
    Purely optional — fails silently.
    """
    brands = (
        session.query(BrandProfile)
        .filter(BrandProfile.wikidata_id.isnot(None))
        .all()
    )
    if not brands:
        return

    qids = " ".join(f"wd:{b.wikidata_id}" for b in brands)
    sparql = f"""
    SELECT ?item ?itemLabel ?parentLabel ?employees ?inception WHERE {{
      VALUES ?item {{ {qids} }}
      OPTIONAL {{ ?item wdt:P749 ?parent. }}
      OPTIONAL {{ ?item wdt:P1128 ?employees. }}
      OPTIONAL {{ ?item wdt:P571 ?inception. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """
    try:
        from backend.tracked_request import tracked_get
        resp = tracked_get(
            "wikidata_sparql", "brand_enrichment",
            "https://query.wikidata.org/sparql",
            params={"query": sparql, "format": "json"},
            headers={"User-Agent": "ChainStaffingTracker/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", {}).get("bindings", [])
        logger.info("  Wikidata returned %d brand enrichment rows", len(results))

        for r in results:
            qid = r["item"]["value"].split("/")[-1]
            brand = next((b for b in brands if b.wikidata_id == qid), None)
            if not brand:
                continue
            if "parentLabel" in r and not brand.parent_company:
                brand.parent_company = r["parentLabel"]["value"]
            brand.updated_at = datetime.utcnow()

        session.commit()
    except Exception as e:
        logger.warning("  Wikidata enrichment failed (non-fatal): %s", e)


# ═══════════════════════════════════════════════════════════════════════
# Region Profiles
# BLS QCEW + MIT Living Wage + Census QuickFacts
# ═══════════════════════════════════════════════════════════════════════

REGION_SEED: list[dict] = [
    {
        "region_key": "austin_tx",
        "display_name": "Austin-Round Rock, TX Metro",
        "fips_code": "12420",
        "center_lat": 30.2672,
        "center_lng": -97.7431,
        "bbox_west": -97.9383,
        "bbox_east": -97.4104,
        "bbox_south": 30.0986,
        "bbox_north": 30.5168,
        "population": 2352426,
        "median_household_income": 85000,
        "unemployment_rate": 3.2,
        "cost_of_living_index": 103.5,
        "min_wage_state": 7.25,
        "min_wage_local": None,
        "living_wage_1adult": 19.62,
        "food_service_establishments": 4200,
        "food_service_employees": 48000,
        "retail_establishments": 3100,
        "retail_employees": 42000,
    },
]


def load_regions(session) -> None:
    """Insert or update RegionProfile rows."""
    logger.info("Loading region profiles ...")
    for r in REGION_SEED:
        existing = session.query(RegionProfile).filter_by(region_key=r["region_key"]).first()
        if existing:
            for k, v in r.items():
                if k != "region_key":
                    setattr(existing, k, v)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(RegionProfile(**r, updated_at=datetime.utcnow()))
    session.commit()
    n = session.query(RegionProfile).count()
    logger.info("  ref_regions: %d rows", n)


# ═══════════════════════════════════════════════════════════════════════
# Category Mappings
# Crosswalk external taxonomy → internal industry keys
# ═══════════════════════════════════════════════════════════════════════

CATEGORY_MAP_SEED: list[tuple[str, str, str, float]] = [
    # (source_system, source_value, internal_industry, confidence)

    # -- Overture Maps categories --
    ("overture", "coffee_shop",          "coffee_cafe",              1.0),
    ("overture", "cafe",                 "coffee_cafe",              0.9),
    ("overture", "donut_shop",           "coffee_cafe",              0.8),
    ("overture", "tea_house",            "coffee_cafe",              0.7),
    ("overture", "ice_cream_shop",       "coffee_cafe",              0.6),
    ("overture", "fast_food_restaurant", "fast_food",                1.0),
    ("overture", "sandwich_shop",        "fast_food",                0.9),
    ("overture", "burger_restaurant",    "fast_food",                1.0),
    ("overture", "pizza_restaurant",     "fast_food",                0.9),
    ("overture", "mexican_restaurant",   "fast_food",                0.8),
    ("overture", "chicken_restaurant",   "fast_food",                0.9),
    ("overture", "restaurant",           "full_service_restaurant",  0.8),
    ("overture", "grocery_store",        "food_retail",              1.0),
    ("overture", "supermarket",          "food_retail",              1.0),
    ("overture", "convenience_store",    "food_retail",              0.8),
    ("overture", "department_store",     "retail_general",           1.0),
    ("overture", "clothing_store",       "retail_general",           0.8),
    ("overture", "discount_store",       "retail_general",           0.9),
    ("overture", "shopping_center",      "retail_general",           0.7),
    ("overture", "hotel",                "accommodation",            1.0),
    ("overture", "motel",                "accommodation",            1.0),

    # -- OSM tags --
    ("osm", "amenity=cafe",            "coffee_cafe",              1.0),
    ("osm", "amenity=fast_food",       "fast_food",                1.0),
    ("osm", "amenity=restaurant",      "full_service_restaurant",  0.9),
    ("osm", "shop=supermarket",        "food_retail",              1.0),
    ("osm", "shop=convenience",        "food_retail",              0.8),
    ("osm", "shop=department_store",   "retail_general",           1.0),
    ("osm", "tourism=hotel",           "accommodation",            1.0),
    ("osm", "tourism=motel",           "accommodation",            0.9),

    # -- Indeed job categories --
    ("indeed", "Food Preparation and Serving",  "food_service",    0.9),
    ("indeed", "Retail Sales",                  "retail_general",  0.8),
    ("indeed", "Barista",                       "coffee_cafe",     1.0),
    ("indeed", "Quick Service Restaurant",      "fast_food",       1.0),
    ("indeed", "Cashier",                       "retail_general",  0.7),

    # -- NAICS codes (direct) --
    ("naics", "722515", "coffee_cafe",              1.0),
    ("naics", "722513", "fast_food",                1.0),
    ("naics", "722511", "full_service_restaurant",  1.0),
    ("naics", "722514", "cafeteria",                1.0),
    ("naics", "452",    "retail_general",           1.0),
    ("naics", "445",    "food_retail",              1.0),
    ("naics", "721",    "accommodation",            1.0),

    # -- AllThePlaces (spider → industry) --
    ("atp", "starbucks_us",  "coffee_cafe",   1.0),
    ("atp", "dutch_bros",    "coffee_cafe",   1.0),
    ("atp", "mcdonalds",     "fast_food",     1.0),
    ("atp", "whataburger",   "fast_food",     1.0),
    ("atp", "chipotle",      "fast_food",     1.0),
    ("atp", "target_us",     "retail_general", 1.0),
]


def load_category_mappings(session) -> None:
    """Insert or update CategoryMapping rows."""
    logger.info("Loading category mappings ...")
    for source, value, industry, conf in CATEGORY_MAP_SEED:
        existing = session.query(CategoryMapping).filter_by(
            source_system=source, source_value=value
        ).first()
        if existing:
            existing.internal_industry = industry
            existing.confidence = conf
        else:
            session.add(CategoryMapping(
                source_system=source,
                source_value=value,
                internal_industry=industry,
                confidence=conf,
            ))
    session.commit()
    n = session.query(CategoryMapping).count()
    logger.info("  ref_category_map: %d rows", n)


# ═══════════════════════════════════════════════════════════════════════
# BLS Wage Data Pull (best-effort)
# Free V1: 25 daily queries, no key.  V2 keyed: 500/day.
# ═══════════════════════════════════════════════════════════════════════

def pull_bls_wages(session) -> None:
    """Pull latest BLS wage data for food-service occupations in Austin MSA.

    Uses the V1 (no-key) public API — limited to 25 requests/day.
    Updates avg_hourly_wage_bls on the matching IndustryCategory rows.
    """
    logger.info("Pulling BLS OES wage data (best-effort) ...")

    # OES series for Austin-Round Rock MSA (12420)
    # Format: OEUM{area}{industry}{occupation}{datatype}
    # We use annual mean hourly wage (datatype 03)
    series_map = {
        # Food prep and serving related — NAICS 722
        "OEUM001242000000035000003": ("722", "food_service"),
        # Limited-service restaurant workers — close to 722513
        "OEUM001242000000035301003": ("722513", "fast_food"),
    }

    series_ids = list(series_map.keys())
    if not series_ids:
        return

    try:
        from backend.tracked_request import tracked_post
        resp = tracked_post(
            "bls_v1_post", "wage_series_batch",
            "https://api.bls.gov/publicAPI/v1/timeseries/data/",
            json_body={
                "seriesid": series_ids,
                "startyear": "2024",
                "endyear": "2025",
            },
            headers={"User-Agent": "ChainStaffingTracker/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            logger.warning("  BLS API: %s", data.get("message", ["unknown"]))
            return

        for series in data.get("Results", {}).get("series", []):
            sid = series["seriesID"]
            if sid not in series_map:
                continue
            naics_code, label = series_map[sid]
            if not series["data"]:
                continue
            latest = series["data"][0]
            wage = float(latest["value"])
            ind = session.query(IndustryCategory).filter_by(naics_code=naics_code).first()
            if ind:
                ind.avg_hourly_wage_bls = wage
                logger.info("  %s (%s): $%.2f/hr", naics_code, label, wage)

        session.commit()
    except Exception as e:
        logger.warning("  BLS pull failed (non-fatal): %s", e)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def populate_all() -> None:
    """Create reference tables and populate everything."""
    engine = init_db()
    session = get_session(engine)
    try:
        load_naics(session)
        load_brands(session)
        enrich_brands_from_wikidata(session)
        load_regions(session)
        load_category_mappings(session)
        pull_bls_wages(session)
        logger.info("Reference data population complete.")
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Populate reference / taxonomy data")
    parser.add_argument("--all", action="store_true", help="Load everything (default)")
    parser.add_argument("--brands-only", action="store_true")
    parser.add_argument("--regions-only", action="store_true")
    parser.add_argument("--wages-only", action="store_true")
    parser.add_argument("--categories-only", action="store_true")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        any_specific = args.brands_only or args.regions_only or args.wages_only or args.categories_only
        run_all = args.all or not any_specific

        if run_all or args.brands_only:
            load_naics(session)
            load_brands(session)
            enrich_brands_from_wikidata(session)
        if run_all or args.regions_only:
            load_regions(session)
        if run_all or args.categories_only:
            load_category_mappings(session)
        if run_all or args.wages_only:
            pull_bls_wages(session)

        logger.info("Done.")
    finally:
        session.close()
