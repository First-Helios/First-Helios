"""
backend/category_catalog.py

Programmatic category → industry mapping system.

Instead of a hand-maintained dict, this module:
  1. Discovers what categories actually exist in the Overture dataset (S3 query)
  2. Auto-classifies each category using ordered keyword rules
  3. Persists every (source_system, source_value) → internal_industry mapping in
     the ref_category_map table so the result grows with the data
  4. Surfaces unmapped / low-confidence categories for human review
  5. Provides a fast runtime lookup used by scrapers and the ingest pipeline

Sources supported
-----------------
  "overture"   — Overture Maps categories.primary values
  "osm"        — OpenStreetMap amenity/shop/leisure tags (future)
  "alltheplaces" — ATP place_type values (future)

Confidence tiers
----------------
  1.0  manual   — explicitly set by a human reviewer
  0.9  exact    — exact match in EXACT_OVERRIDES dict
  0.8  keyword  — matched by a keyword rule pattern
  0.1  unknown  — no rule matched; needs review
"""

import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

SOURCE_OVERTURE = "overture"

# ══════════════════════════════════════════════════════════════════════
# 1. Keyword rules — applied in ORDER, first match wins
#    Pattern is matched against the full category string (underscores preserved)
# ══════════════════════════════════════════════════════════════════════

INDUSTRY_KEYWORD_RULES: list[tuple[str, str]] = [
    # ── Hair & Beauty ────────────────────────────────────────────────
    (r"hair|barber|beauty_salon|nail|waxing|tanning|cosmetic|esthetician|eyebrow|threading|lash|brow|manicure|pedicure|blowout", "hair_beauty"),
    # ── Fitness & Wellness ───────────────────────────────────────────
    (r"gym|fitness|yoga|pilates|martial_art|karate|crossfit|spin|cycling_studio|boxing|barre|rock_climbing|trampoline|wellness_center|sports_complex", "fitness_wellness"),
    # ── Coffee & Cafe ────────────────────────────────────────────────
    (r"coffee|cafe|cafeteria|tea_house|boba|bubble_tea|donut|bakery|juice_bar|smoothie|bagel", "coffee_cafe"),
    # ── Fast Food ────────────────────────────────────────────────────
    (r"fast_food|burger|pizza|sandwich|taco|chicken_restaurant|hot_dog|wing|sub_shop|qsr|drive_through|ice_cream_shop|frozen_yogurt|pretzel", "fast_food"),
    # ── Full Service Restaurants ─────────────────────────────────────
    (r"^restaurant$|american_restaurant|italian|seafood|sushi|steakhouse|diner|buffet|barbecue|thai_restaurant|chinese_restaurant|indian_restaurant|mediterranean|french_restaurant|greek|vietnamese|japanese|mexican_restaurant|pub_food|gastropub|brunch", "full_service_restaurant"),
    # ── Grocery & Supermarket ────────────────────────────────────────
    (r"grocery|supermarket|food_market|farmers_market|butcher|fishmonger|deli|ethnic_grocery|specialty_food", "retail_grocery"),
    # ── Pharmacy & Drugstore ─────────────────────────────────────────
    (r"pharmacy|drug_store|chemist|apothecary", "pharmacy"),
    # ── Healthcare ───────────────────────────────────────────────────
    (r"urgent_care|medical_clinic|health_clinic|doctor|physician|dentist|dental|orthodontist|optometrist|ophthalmologist|chiropractor|physical_therapy|mental_health|psychiatric|dermatologist|pediatrician|obgyn|hospital|emergency_room|dialysis|laboratory|imaging", "healthcare_clinic"),
    # ── Childcare & Early Education ──────────────────────────────────
    (r"child_care|daycare|day_care|preschool|kindergarten|nursery|after_school|tutoring_center|learning_center", "childcare"),
    # ── Accommodation ────────────────────────────────────────────────
    (r"hotel|motel|inn|lodge|resort|extended_stay|bed_and_breakfast|hostel|vacation_rental|airbnb", "accommodation"),
    # ── Retail General ───────────────────────────────────────────────
    (r"clothing|department_store|electronics|furniture|hardware|home_goods|sporting_goods|toy_store|book_store|gift_shop|convenience_store|dollar_store|thrift|pawn|jewelry|pet_store|shoe_store|music_store", "retail_general"),
    # ── HVAC & Skilled Trades ────────────────────────────────────────
    (r"hvac|heating|cooling|plumber|plumbing|electrician|electrical|handyman|contractor|roofing|carpet_cleaning|pest_control|locksmith|appliance_repair", "hvac_skilled_trades"),
    # ── Auto Repair ──────────────────────────────────────────────────
    (r"auto_repair|mechanic|tire|oil_change|body_shop|car_wash|auto_parts|car_dealership|motorcycle|auto_service", "auto_repair"),
]

# Compiled for performance — done once at import time
_COMPILED_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), industry)
    for pattern, industry in INDUSTRY_KEYWORD_RULES
]

# High-confidence exact overrides (confidence=0.9) — for ambiguous categories
# where keyword rules could misfire
EXACT_OVERRIDES: dict[str, str] = {
    "spa": "hair_beauty",            # could match wellness but is primarily beauty
    "massage": "hair_beauty",        # Overture groups this under beauty services
    "restaurant": "full_service_restaurant",
    "bar": "full_service_restaurant",
    "pub": "full_service_restaurant",
    "night_club": "full_service_restaurant",
    "gas_station": "auto_repair",
    "car_rental": "auto_repair",
    "parking": "auto_repair",
    "laundromat": "retail_general",
    "dry_cleaning": "retail_general",
    "post_office": "retail_general",
    "bank": "retail_general",
    "atm": "retail_general",
    "insurance": "retail_general",
    "real_estate": "retail_general",
}


# ══════════════════════════════════════════════════════════════════════
# 2. Classification logic
# ══════════════════════════════════════════════════════════════════════

def auto_classify(category_value: str) -> tuple[str, float]:
    """Return (internal_industry, confidence) for a raw category string.

    Tries in order:
      1. Exact override dict      → confidence 0.9
      2. Keyword regex rules      → confidence 0.8
      3. Fallback unknown         → confidence 0.1
    """
    if not category_value:
        return "unknown", 0.1

    normalized = category_value.strip().lower()

    if normalized in EXACT_OVERRIDES:
        return EXACT_OVERRIDES[normalized], 0.9

    for pattern, industry in _COMPILED_RULES:
        if pattern.search(normalized):
            return industry, 0.8

    return "unknown", 0.1


# ══════════════════════════════════════════════════════════════════════
# 3. DB helpers
# ══════════════════════════════════════════════════════════════════════

def get_industry_for_category(
    category_value: str,
    source_system: str = SOURCE_OVERTURE,
    db_session=None,
) -> str:
    """Return the internal_industry for a category string.

    Lookup order:
      1. DB row in ref_category_map (includes manual overrides)
      2. Auto-classify via keyword rules and persist the result
      3. Return "unknown" if nothing matches
    """
    if not category_value:
        return "unknown"

    from backend.database import get_session, init_db
    from backend.models.reference import CategoryMapping

    own_session = db_session is None
    if own_session:
        db_session = get_session(init_db())

    try:
        row = db_session.query(CategoryMapping).filter_by(
            source_system=source_system,
            source_value=category_value,
        ).first()

        if row:
            return row.internal_industry

        # Not in DB yet — auto-classify and persist
        industry, confidence = auto_classify(category_value)
        try:
            db_session.add(CategoryMapping(
                source_system=source_system,
                source_value=category_value,
                internal_industry=industry,
                confidence=confidence,
            ))
            db_session.commit()
            logger.debug("[CategoryCatalog] Auto-classified %s → %s (%.1f)", category_value, industry, confidence)
        except Exception:
            db_session.rollback()
            # Row may have been inserted by another thread — that's fine

        return industry

    finally:
        if own_session:
            db_session.close()


def get_unmapped(source_system: str = SOURCE_OVERTURE, db_session=None) -> list[dict]:
    """Return all category rows where internal_industry='unknown' or confidence < 0.5."""
    from backend.database import get_session, init_db
    from backend.models.reference import CategoryMapping

    own_session = db_session is None
    if own_session:
        db_session = get_session(init_db())

    try:
        rows = db_session.query(CategoryMapping).filter(
            CategoryMapping.source_system == source_system,
            CategoryMapping.confidence < 0.5,
        ).order_by(CategoryMapping.confidence).all()
        return [r.to_dict() for r in rows]
    finally:
        if own_session:
            db_session.close()


def set_mapping(
    category_value: str,
    internal_industry: str,
    source_system: str = SOURCE_OVERTURE,
    db_session=None,
) -> dict:
    """Manually override a category→industry mapping (confidence=1.0)."""
    from backend.database import get_session, init_db
    from backend.models.reference import CategoryMapping

    own_session = db_session is None
    if own_session:
        db_session = get_session(init_db())

    try:
        row = db_session.query(CategoryMapping).filter_by(
            source_system=source_system,
            source_value=category_value,
        ).first()

        if row:
            row.internal_industry = internal_industry
            row.confidence = 1.0
        else:
            row = CategoryMapping(
                source_system=source_system,
                source_value=category_value,
                internal_industry=internal_industry,
                confidence=1.0,
            )
            db_session.add(row)

        db_session.commit()
        return row.to_dict()
    except Exception as e:
        db_session.rollback()
        raise
    finally:
        if own_session:
            db_session.close()


def get_all_mappings(source_system: str = SOURCE_OVERTURE, db_session=None) -> list[dict]:
    """Return all category mappings for a source system, sorted by industry."""
    from backend.database import get_session, init_db
    from backend.models.reference import CategoryMapping

    own_session = db_session is None
    if own_session:
        db_session = get_session(init_db())

    try:
        rows = db_session.query(CategoryMapping).filter_by(
            source_system=source_system,
        ).order_by(CategoryMapping.internal_industry, CategoryMapping.source_value).all()
        return [r.to_dict() for r in rows]
    finally:
        if own_session:
            db_session.close()


# ══════════════════════════════════════════════════════════════════════
# 4. Discovery — find new categories from existing DB data
# ══════════════════════════════════════════════════════════════════════

def discover_from_db(source_system: str = SOURCE_OVERTURE, db_session=None) -> dict:
    """Classify any LocalEmployer.category values not yet in ref_category_map.

    Call this on startup or after a collection run to catch categories that
    arrived without a mapping.

    Returns: {"new": N, "already_mapped": N, "unknown": N}
    """
    from backend.database import LocalEmployer, get_session, init_db
    from backend.models.reference import CategoryMapping

    own_session = db_session is None
    if own_session:
        db_session = get_session(init_db())

    counts = {"new": 0, "already_mapped": 0, "unknown": 0}

    try:
        # Distinct categories seen in local_employers
        distinct_categories = [
            row[0] for row in
            db_session.query(LocalEmployer.category).distinct().all()
            if row[0]
        ]

        # Existing mapped values
        existing = {
            row[0] for row in
            db_session.query(CategoryMapping.source_value)
            .filter_by(source_system=source_system)
            .all()
        }

        new_rows = []
        for cat in distinct_categories:
            if cat in existing:
                counts["already_mapped"] += 1
                continue

            industry, confidence = auto_classify(cat)
            new_rows.append(CategoryMapping(
                source_system=source_system,
                source_value=cat,
                internal_industry=industry,
                confidence=confidence,
            ))
            counts["new"] += 1
            if industry == "unknown":
                counts["unknown"] += 1
                logger.warning("[CategoryCatalog] Unmapped category: '%s'", cat)
            else:
                logger.debug("[CategoryCatalog] Mapped '%s' → %s", cat, industry)

        if new_rows:
            db_session.bulk_save_objects(new_rows)
            db_session.commit()

        logger.info(
            "[CategoryCatalog] discover_from_db: %d new, %d already mapped, %d unknown",
            counts["new"], counts["already_mapped"], counts["unknown"],
        )
        return counts

    except Exception as e:
        db_session.rollback()
        logger.error("[CategoryCatalog] discover_from_db failed: %s", e)
        return counts
    finally:
        if own_session:
            db_session.close()


def discover_from_overture(region: str = "austin_tx") -> dict:
    """Query Overture S3 directly for ALL distinct categories in the region bbox.

    This discovers categories that haven't been collected yet — it reads the
    full Overture taxonomy for the area and classifies every category it finds.
    Slow on first run (DuckDB downloads extensions), fast thereafter.

    Returns: {"discovered": N, "new_mappings": N, "unknown": N, "categories": [...]}
    """
    from backend.database import get_session, init_db
    from backend.models.reference import CategoryMapping

    try:
        import duckdb
        from scrapers.overture_adapter import _get_duckdb_conn, _get_overture_s3_path, _bbox_from_region
    except ImportError as e:
        logger.error("[CategoryCatalog] DuckDB/Overture not available: %s", e)
        return {"error": str(e)}

    try:
        bbox = _bbox_from_region(region)
        s3_path = _get_overture_s3_path()

        query = f"""
        SELECT
            categories.primary AS category,
            COUNT(*) AS cnt
        FROM read_parquet('{s3_path}', hive_partitioning=1)
        WHERE categories.primary IS NOT NULL
          AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
          AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
        GROUP BY categories.primary
        ORDER BY cnt DESC
        """

        logger.info("[CategoryCatalog] Querying Overture for all categories in %s...", region)
        conn = _get_duckdb_conn()
        rows = conn.execute(query).fetchall()
        conn.close()
        logger.info("[CategoryCatalog] Found %d distinct categories in %s", len(rows), region)

    except Exception as e:
        logger.error("[CategoryCatalog] Overture S3 query failed: %s", e)
        return {"error": str(e)}

    db_session = get_session(init_db())
    counts = {"discovered": len(rows), "new_mappings": 0, "unknown": 0, "categories": []}

    try:
        existing = {
            row[0] for row in
            db_session.query(CategoryMapping.source_value)
            .filter_by(source_system=SOURCE_OVERTURE)
            .all()
        }

        new_rows = []
        for (cat, cnt) in rows:
            industry, confidence = auto_classify(cat)
            counts["categories"].append({
                "category": cat,
                "count": cnt,
                "industry": industry,
                "confidence": confidence,
            })

            if cat not in existing:
                new_rows.append(CategoryMapping(
                    source_system=SOURCE_OVERTURE,
                    source_value=cat,
                    internal_industry=industry,
                    confidence=confidence,
                ))
                counts["new_mappings"] += 1
                if industry == "unknown":
                    counts["unknown"] += 1
                    logger.warning(
                        "[CategoryCatalog] Unmapped Overture category: '%s' (%d occurrences)", cat, cnt
                    )

        if new_rows:
            db_session.bulk_save_objects(new_rows)
            db_session.commit()

        logger.info(
            "[CategoryCatalog] discover_from_overture: %d discovered, %d new mappings, %d unknown",
            counts["discovered"], counts["new_mappings"], counts["unknown"],
        )
        return counts

    except Exception as e:
        db_session.rollback()
        logger.error("[CategoryCatalog] Failed to persist mappings: %s", e)
        return {"error": str(e), **counts}
    finally:
        db_session.close()


# ══════════════════════════════════════════════════════════════════════
# 5. Startup seed — ensures at least keyword-rule coverage is in DB
# ══════════════════════════════════════════════════════════════════════

def seed_from_keyword_rules(db_session=None) -> dict:
    """Populate ref_category_map by running keyword rules over all categories
    already seen in the local_employers table, and over a hardcoded bootstrap
    list of known common Overture categories.

    This is idempotent — existing manual overrides (confidence=1.0) are preserved.

    Returns: {"inserted": N, "skipped": N}
    """
    from backend.database import get_session, init_db
    from backend.models.reference import CategoryMapping

    # Bootstrap: known common Overture category strings to ensure coverage
    # even before any data is collected.  This list is NOT the truth —
    # the DB is.  Add to this list if you discover new categories in the logs.
    _BOOTSTRAP_CATEGORIES: list[str] = [
        # Coffee
        "coffee_shop", "cafe", "donut_shop", "tea_house", "juice_bar",
        "bubble_tea", "bakery", "bagel_shop", "smoothie_bar",
        # Fast Food
        "fast_food_restaurant", "burger_restaurant", "pizza_restaurant",
        "sandwich_shop", "taco_restaurant", "chicken_restaurant",
        "mexican_restaurant", "hot_dog_joint", "wing_restaurant",
        "ice_cream_shop", "frozen_yogurt_shop",
        # Full Service
        "restaurant", "american_restaurant", "italian_restaurant",
        "seafood_restaurant", "sushi_restaurant", "steakhouse", "diner",
        "buffet", "barbecue_restaurant", "thai_restaurant",
        "chinese_restaurant", "indian_restaurant", "vietnamese_restaurant",
        "japanese_restaurant", "mediterranean_restaurant", "greek_restaurant",
        "french_restaurant", "pub", "bar", "gastropub", "night_club",
        # Grocery
        "grocery_store", "supermarket", "food_market", "farmers_market",
        "butcher", "fishmonger", "deli", "specialty_food_store",
        # Retail
        "clothing_store", "department_store", "electronics_store",
        "furniture_store", "hardware_store", "home_goods_store",
        "sporting_goods_store", "toy_store", "book_store", "gift_shop",
        "convenience_store", "dollar_store", "thrift_store", "pawn_shop",
        "jewelry_store", "pet_store", "shoe_store", "music_store",
        "laundromat", "dry_cleaning",
        # Pharmacy
        "pharmacy", "drug_store",
        # Hair & Beauty
        "hair_salon", "beauty_salon", "nail_salon", "barber_shop",
        "spa", "tanning_salon", "waxing_salon", "massage",
        "cosmetics_store", "eyebrow_threading",
        # Fitness
        "gym", "fitness_center", "yoga_studio", "pilates_studio",
        "martial_arts_school", "crossfit_gym", "boxing_gym",
        "rock_climbing_gym", "dance_studio", "sports_complex",
        # Healthcare
        "urgent_care", "medical_clinic", "health_clinic", "dentist",
        "optometrist", "chiropractor", "physical_therapy",
        "mental_health_clinic", "dermatologist", "hospital",
        "dental_office", "orthodontist",
        # Childcare
        "child_care", "daycare", "preschool", "kindergarten",
        "after_school_program", "tutoring_center",
        # Accommodation
        "hotel", "motel", "inn", "resort", "extended_stay",
        "bed_and_breakfast", "hostel",
        # HVAC / Trades
        "hvac", "plumber", "electrician", "handyman", "contractor",
        "roofing", "pest_control", "locksmith", "appliance_repair",
        # Auto
        "auto_repair", "mechanic", "tire_shop", "oil_change",
        "car_wash", "auto_parts_store", "car_dealership",
        # Misc
        "bank", "atm", "post_office", "insurance", "real_estate",
        "gas_station", "car_rental", "parking",
    ]

    own_session = db_session is None
    if own_session:
        db_session = get_session(init_db())

    counts = {"inserted": 0, "skipped": 0}

    try:
        existing = {
            row[0] for row in
            db_session.query(CategoryMapping.source_value)
            .filter_by(source_system=SOURCE_OVERTURE)
            .all()
        }

        new_rows = []
        for cat in _BOOTSTRAP_CATEGORIES:
            if cat in existing:
                counts["skipped"] += 1
                continue

            industry, confidence = auto_classify(cat)
            new_rows.append(CategoryMapping(
                source_system=SOURCE_OVERTURE,
                source_value=cat,
                internal_industry=industry,
                confidence=confidence,
            ))
            counts["inserted"] += 1

        if new_rows:
            db_session.bulk_save_objects(new_rows)
            db_session.commit()

        # Also classify anything already in local_employers not yet mapped
        db_discover = discover_from_db(source_system=SOURCE_OVERTURE, db_session=db_session)
        counts["from_db"] = db_discover.get("new", 0)

        logger.info(
            "[CategoryCatalog] seed_from_keyword_rules: %d inserted, %d skipped, %d from DB",
            counts["inserted"], counts["skipped"], counts.get("from_db", 0),
        )
        return counts

    except Exception as e:
        db_session.rollback()
        logger.error("[CategoryCatalog] Seed failed: %s", e)
        return counts
    finally:
        if own_session:
            db_session.close()
