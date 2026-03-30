"""
backend/normalizer.py

Pure name-normalization functions. Zero DB imports — safe to import anywhere.

Pipeline for a raw business name:
  1. strip_store_number  — regex removes trailing "#404", "Store 12", "No. 5", etc.
  2. join_initials       — "H-E-B" → "HEB" so fingerprints match
  3. normalize_name      — cleanco strips legal suffixes (LLC, Inc., Corp.);
                           rigour.names.normalize_name lowercases + strips punctuation
  4. make_fingerprint    — token-sort the normalized form for a stable group key

Tools:
  - cleanco      : strips legal entity suffixes (LLC, Inc, GmbH, …)
  - rigour.names : lowercases, strips punctuation, handles accents
  - regex        : store-number patterns + hyphenated-initial collapse

All functions are idempotent and side-effect-free.
"""

import re
from functools import lru_cache

from cleanco import basename
from rigour.names import normalize_name as _rigour_normalize

# ── Store-number patterns ─────────────────────────────────────────────────────
# Applied in order to the END of the name string.
_STORE_NUMBER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\s*#\s*\d+\s*$"),               # #404, # 404
    re.compile(r"\s+No\.?\s*\d+\s*$", re.I),     # No. 1234, No 1234
    re.compile(r"\s+Store\s+\d+\s*$", re.I),     # Store 00452
    re.compile(r"\s+Location\s+\d+\s*$", re.I),  # Location 3
    re.compile(r"\s+\d{3,}\s*$"),                 # trailing 3+ digit number
]

# Collapses single-letter hyphenated abbreviations: H-E-B → HEB, A-B-C → ABC
# Applied before fingerprinting so "H-E-B" and "HEB" share the same key.
_HYPHEN_INITIALS = re.compile(r"(?<!\w)([A-Za-z])-([A-Za-z])(?!\w)")

_WHITESPACE = re.compile(r"\s{2,}")


def strip_store_number(raw: str) -> str:
    """Remove store/location identifiers from the trailing end of a name.

    Examples:
        "HEB GROCERY #404"   → "HEB GROCERY"
        "Walgreens #3421"    → "Walgreens"
        "Kroger Store 00452" → "Kroger"
        "CVS/pharmacy No. 8" → "CVS/pharmacy"
    """
    name = raw.strip()
    for pat in _STORE_NUMBER_PATTERNS:
        name = pat.sub("", name).strip()
    return name


def _join_hyphenated_initials(name: str) -> str:
    """Collapse single-letter hyphenated abbreviations.

    "H-E-B" → "HEB"   "A-1" stays (digit, not letter)
    Applied iteratively because re only matches non-overlapping.
    """
    prev = None
    while prev != name:
        prev = name
        name = _HYPHEN_INITIALS.sub(lambda m: m.group(1) + m.group(2), name)
    return name


def normalize_name(raw: str) -> str:
    """Return a clean, display-ready version of a business name.

    Steps:
      1. Strip store number (#404, Store 12, …)
      2. Collapse hyphenated initials (H-E-B → HEB)
      3. Strip legal suffixes via cleanco (LLC, Inc., Corp., Ltd., …)
      4. Title-case if the original is all-caps or all-lower
      5. Collapse internal whitespace

    Examples:
        "HEB GROCERY #404"      → "HEB Grocery"
        "H-E-B #765"            → "HEB"
        "Starbucks Coffee, LLC" → "Starbucks Coffee"
        "SHELL"                 → "Shell"
    """
    if not raw:
        return raw
    name = strip_store_number(raw)
    name = _join_hyphenated_initials(name)
    # cleanco.basename strips legal suffixes; returns None on empty string
    name = basename(name) or name
    # Title-case when input is all-caps or all-lower (preserves mixed-case like "McDonald's")
    if name == name.upper() or name == name.lower():
        name = name.title()
    name = _WHITESPACE.sub(" ", name).strip()
    return name


@lru_cache(maxsize=16_384)
def make_fingerprint(raw: str) -> str:
    """Return a stable grouping key for a business name.

    Different spellings of the same business produce the same key:
        "HEB GROCERY #404"  → "grocery heb"
        "H-E-B #765"        → "heb"            (strip + join initials → "HEB" → "heb")
        "HEB GROCERY #068"  → "grocery heb"
        "Starbucks Coffee"  → "coffee starbucks"
        "STARBUCKS COFFEE"  → "coffee starbucks"

    Algorithm:
      1. Strip store number
      2. Join hyphenated initials
      3. rigour normalize (lowercase, strip punctuation/accents)
      4. Split into tokens, sort, deduplicate
      5. Rejoin with spaces

    Cached with lru_cache — safe because inputs are strings (immutable).
    """
    if not raw:
        return ""
    name = strip_store_number(raw)
    name = _join_hyphenated_initials(name)
    normed = _rigour_normalize(name) or name.lower()
    tokens = sorted(set(normed.split()))
    return " ".join(tokens) if tokens else normed


# ── Industry mapping ──────────────────────────────────────────────────────────
# Overture category → internal industry key.
# Moved here from overture_adapter.py so the ingest layer can use it directly.

CATEGORY_INDUSTRY_MAP: dict[str, str] = {
    # Food & Beverage
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
    "ice_cream_shop":        "food_full_service",
    "smoothie_juice_bar":    "food_full_service",
    "bar":                   "bar_nightlife",
    # Retail
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
    "shoe_store":            "retail_general",
    "womens_clothing_store": "retail_general",
    "cosmetic_and_beauty_supplies": "retail_general",
    "pet_store":             "retail_general",
    "pharmacy":              "retail_pharmacy",
    # Hospitality
    "hotel":                 "hospitality",
    "motel":                 "hospitality",
    # Automotive
    "automotive_repair":     "auto_services",
    "auto_body_shop":        "auto_services",
    "gas_station":           "auto_services",
    "key_and_locksmith":     "auto_services",
    "car_wash":              "auto_services",
    "tire_dealer_and_repair":"auto_services",
    "automotive_parts_and_accessories": "auto_services",
    "automotive":            "auto_services",
    "car_dealer":            "auto_dealer",
    "used_car_dealer":       "auto_dealer",
    # Personal Care & Beauty
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
    # Fitness
    "gym":                   "fitness",
    "martial_arts_club":     "fitness",
    "yoga_studio":           "fitness",
    "dance_school":          "fitness",
    # Skilled Trades & Home Services
    "hvac_services":         "skilled_trades",
    "contractor":            "skilled_trades",
    "roofing":               "skilled_trades",
    "landscaping":           "skilled_trades",
    "home_service":          "skilled_trades",
    "home_cleaning":         "skilled_trades",
    "construction_services": "skilled_trades",
    "building_supply_store": "skilled_trades",
    "industrial_equipment":  "skilled_trades",
    "plumbing":              "skilled_trades",
    "electrician":           "skilled_trades",
    "garage_door_service":   "skilled_trades",
    "home_improvement_store":"skilled_trades",
    # Healthcare
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
    "general_dentistry":     "healthcare",
    "pediatrician":          "healthcare",
    "obstetrician_and_gynecologist": "healthcare",
    "cardiologist":          "healthcare",
    "orthopedist":           "healthcare",
    "acupuncture":           "healthcare",
    "home_health_care":      "healthcare",
    "retirement_home":       "healthcare",
    # Finance
    "bank_credit_union":     "finance",
    "banks":                 "finance",
    "financial_service":     "finance",
    "insurance_agency":      "finance",
    "financial_advising":    "finance",
    "mortgage_broker":       "finance",
    "mortgage_lender":       "finance",
    "credit_union":          "finance",
    # Education
    "elementary_school":     "education",
    "preschool":             "education",
    "college_university":    "education",
    "education":             "education",
    # Staffing / Professional
    "employment_agencies":        "staffing",
    "it_service_and_computer_repair": "tech_services",
    "printing_services":          "professional_services",
    "professional_services":      "professional_services",
    "software_development":       "tech_services",
    "corporate_office":           "professional_services",
    "lawyer":                     "professional_services",
    "legal_services":             "professional_services",
    "marketing_agency":           "professional_services",
    "advertising_agency":         "professional_services",
    "information_technology_company": "tech_services",
    "accountant":                 "professional_services",
    "interior_design":            "professional_services",
    "engineering_services":       "professional_services",
    "event_planning":             "professional_services",
    "architectural_designer":     "professional_services",
    # Logistics
    "courier_and_delivery_services": "logistics",
    # Nonprofit
    "community_services_non_profits": "nonprofit",
    "social_service_organizations":   "nonprofit",
}


def map_industry(category: str, name: str = "") -> str | None:
    """Map an Overture category string to an internal industry key.

    Returns None if the category is not in the map (caller should decide
    whether to skip or label as 'unknown').
    """
    return CATEGORY_INDUSTRY_MAP.get(category or "")


# UPWARD_MOBILITY_CATEGORIES removed.
# Mobility is now a scored float (0.0-1.0) computed from OEWS wage data in
# IndustryTaxonomy.baseline_wage_hr. See scripts/populate_industry_taxonomy.py
# and backend/ingest_layer.py (_calc_mobility_score).
