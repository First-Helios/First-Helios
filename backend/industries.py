"""
backend/industries.py — Industry dimension registry.

Defines which industries the scheduler tracks, what search terms
are valid for each, what data sources apply, and what mega-corps dominate
each sector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MegaCorp:
    """A national/multinational chain the scheduler should track."""
    key: str
    display_name: str
    aliases: tuple[str, ...]  = ()
    careers_domain: Optional[str] = None
    wikidata_id: Optional[str] = None


@dataclass(frozen=True)
class IndustryDimension:
    """An industry the scheduler can collect data for."""
    key: str
    display_name: str
    description: str

    job_search_terms: tuple[str, ...]
    poi_search_terms: tuple[str, ...]
    sentiment_keywords: tuple[str, ...]

    # Common synonyms — maps user input to canonical key
    aliases: tuple[str, ...] = ()

    # BLS NAICS codes
    naics_codes: tuple[str, ...] = ()

    # Dominant chains in this sector
    mega_corps: tuple[MegaCorp, ...] = ()

    applicable_sources: tuple[str, ...] = ("alltheplaces", "overture", "osm", "qcew", "jobspy", "reddit")

    poi_freshness_days: float = 7.0
    wage_freshness_days: float = 30.0
    job_freshness_days: float = 1.0
    sentiment_freshness_days: float = 3.0


# ══════════════════════════════════════════════════════════════════════
# Industry Registry
# ══════════════════════════════════════════════════════════════════════

INDUSTRY_REGISTRY: dict[str, IndustryDimension] = {}


def _register(dim: IndustryDimension) -> IndustryDimension:
    INDUSTRY_REGISTRY[dim.key] = dim
    return dim


# ── Food Service & Cafés ─────────────────────────────────────────────

COFFEE_CAFE = _register(IndustryDimension(
    key="coffee_cafe",
    display_name="Coffee & Café",
    description="Coffee shops, tea houses, bakery cafés — where local roasters compete with Starbucks",
    aliases=("coffee", "cafe", "cafes", "coffee shop", "tea", "espresso", "roastery"),
    job_search_terms=(
        "barista", "coffee", "cafe", "shift supervisor",
        "roaster", "tea", "espresso", "bakery cafe",
    ),
    poi_search_terms=(
        "coffee shop", "café", "espresso bar", "tea house",
        "bakery", "roastery", "juice bar",
    ),
    sentiment_keywords=(
        "understaffed", "skeleton crew", "short staffed", "quitting",
        "turnover", "burned out", "overworked", "great tips",
        "good team", "well run", "love working here",
    ),
    naics_codes=("722515",),
    mega_corps=(
        MegaCorp("starbucks", "Starbucks", ("sbux",), "starbucks.wd1.myworkdayjobs.com", "Q37158"),
        MegaCorp("dutch_bros", "Dutch Bros", (), None, "Q5765571"),
        MegaCorp("peets", "Peet's Coffee", ("peets_coffee",), None, "Q1094101"),
        MegaCorp("dunkin", "Dunkin'", ("dunkin_donuts",), None, "Q1190755"),
    ),
))

FAST_FOOD = _register(IndustryDimension(
    key="fast_food",
    display_name="Fast Food & QSR",
    description="Quick-service restaurants — where local taco trucks and burger joints compete with chains",
    aliases=("qsr", "quick service", "fast food restaurant", "burger", "drive thru", "drive-thru", "drive through"),
    job_search_terms=(
        "crew member", "team member", "cashier", "drive thru",
        "shift lead", "cook", "food prep", "fast food",
    ),
    poi_search_terms=(
        "fast food", "burger", "taco", "pizza", "fried chicken",
        "sandwich shop", "wings", "drive-thru",
    ),
    sentiment_keywords=(
        "understaffed", "drive thru only", "lobby closed",
        "long wait", "always hiring", "good pay", "free meals",
    ),
    naics_codes=("722513",),
    mega_corps=(
        MegaCorp("mcdonalds", "McDonald's", ("mcd",), None, "Q38076"),
        MegaCorp("whataburger", "Whataburger", (), None, "Q376525"),
        MegaCorp("chipotle", "Chipotle", (), None, "Q465751"),
        MegaCorp("chickfila", "Chick-fil-A", ("chick_fil_a",), None, "Q491516"),
        MegaCorp("wendys", "Wendy's", (), None, "Q550258"),
    ),
))

FULL_SERVICE_RESTAURANT = _register(IndustryDimension(
    key="full_service_restaurant",
    display_name="Full Service Restaurants",
    description="Sit-down dining — where local restaurants compete with Applebee's, Chili's, etc.",
    aliases=("restaurant", "dining", "sit down", "sit-down", "full service", "casual dining", "bar and grill"),
    job_search_terms=(
        "server", "waiter", "waitress", "host", "hostess",
        "line cook", "prep cook", "dishwasher", "bartender",
        "restaurant manager", "sous chef",
    ),
    poi_search_terms=(
        "restaurant", "dining", "grill", "steakhouse",
        "seafood restaurant", "italian restaurant", "bar and grill",
    ),
    sentiment_keywords=(
        "understaffed", "bad tips", "long hours", "great tips",
        "kitchen nightmare", "love the team", "management issues",
    ),
    naics_codes=("722511",),
    mega_corps=(
        MegaCorp("applebees", "Applebee's", (), None, "Q621532"),
        MegaCorp("chilis", "Chili's", (), None, "Q1072948"),
        MegaCorp("olive_garden", "Olive Garden", (), None, "Q3045312"),
        MegaCorp("ihop", "IHOP", (), None, "Q1185675"),
    ),
))

# ── Retail ───────────────────────────────────────────────────────────

RETAIL_GENERAL = _register(IndustryDimension(
    key="retail_general",
    display_name="Retail General Merchandise",
    description="Big box and department stores — where local shops compete with Target, Walmart, etc.",
    aliases=("retail", "big box", "department store", "general merchandise", "variety store"),
    job_search_terms=(
        "retail associate", "cashier", "stocker", "sales floor",
        "team lead", "department manager", "inventory",
        "fulfillment", "customer service",
    ),
    poi_search_terms=(
        "department store", "general store", "variety store",
        "gift shop", "home goods", "dollar store",
    ),
    sentiment_keywords=(
        "understaffed", "skeleton crew", "hours cut", "no breaks",
        "good discount", "flexible hours", "overtime",
    ),
    naics_codes=("452210", "452319"),
    mega_corps=(
        MegaCorp("target", "Target", (), None, "Q137078"),
        MegaCorp("walmart", "Walmart", (), None, "Q483551"),
        MegaCorp("costco", "Costco", (), None, "Q715583"),
    ),
))

RETAIL_GROCERY = _register(IndustryDimension(
    key="retail_grocery",
    display_name="Grocery & Supermarket",
    description="Grocery stores — where local co-ops and markets compete with HEB, Kroger, etc.",
    aliases=("grocery", "supermarket", "food market", "grocery store", "market"),
    job_search_terms=(
        "grocery clerk", "produce", "deli", "bakery",
        "butcher", "cashier", "stock clerk", "grocery",
    ),
    poi_search_terms=(
        "grocery store", "supermarket", "food market",
        "organic market", "farmers market", "co-op grocery",
    ),
    sentiment_keywords=(
        "understaffed", "long lines", "shelves empty",
        "good benefits", "union", "employee owned",
    ),
    naics_codes=("445110",),
    mega_corps=(
        MegaCorp("heb", "H-E-B", (), None, "Q1615528"),
        MegaCorp("kroger", "Kroger", (), None, "Q153417"),
        MegaCorp("whole_foods", "Whole Foods", (), None, "Q1809448"),
        MegaCorp("trader_joes", "Trader Joe's", ("trader_joes",), None, "Q688825"),
    ),
))

# ── Healthcare ───────────────────────────────────────────────────────

HEALTHCARE_CLINIC = _register(IndustryDimension(
    key="healthcare_clinic",
    display_name="Healthcare Clinics & Urgent Care",
    description="Walk-in clinics and urgent care — where local practices compete with CVS MinuteClinic, etc.",
    aliases=("healthcare", "clinic", "urgent care", "medical", "walk-in", "walk in clinic", "doctor", "health"),
    job_search_terms=(
        "medical assistant", "nurse", "RN", "LVN", "CNA",
        "front desk medical", "phlebotomist", "x-ray tech",
        "urgent care", "clinic",
    ),
    poi_search_terms=(
        "urgent care", "clinic", "doctor", "medical center",
        "walk-in clinic", "family practice", "health center",
    ),
    sentiment_keywords=(
        "understaffed", "patient ratio", "burnout", "overtime",
        "good benefits", "work-life balance", "supportive team",
    ),
    naics_codes=("621111", "621493"),
    mega_corps=(
        MegaCorp("cvs_minuteclinic", "CVS MinuteClinic", ("minuteclinic",)),
        MegaCorp("walgreens_clinic", "Walgreens Health", ()),
        MegaCorp("hca", "HCA Healthcare", ()),
        MegaCorp("ascension", "Ascension Health", ()),
    ),
))

PHARMACY = _register(IndustryDimension(
    key="pharmacy",
    display_name="Pharmacy & Drugstore",
    description="Pharmacies — where local pharmacies compete with CVS, Walgreens, etc.",
    aliases=("drugstore", "drug store", "rx", "pharmacist", "compounding"),
    job_search_terms=(
        "pharmacist", "pharmacy tech", "pharmacy technician",
        "pharmacy clerk", "pharmacy manager",
    ),
    poi_search_terms=(
        "pharmacy", "drugstore", "apothecary",
        "compounding pharmacy",
    ),
    sentiment_keywords=(
        "understaffed", "pill count", "prescription volume",
        "no lunch break", "good pay", "benefits",
    ),
    naics_codes=("446110",),
    mega_corps=(
        MegaCorp("cvs", "CVS Pharmacy", (), None, "Q2078880"),
        MegaCorp("walgreens", "Walgreens", (), None, "Q1591889"),
    ),
))

# ── Accommodation ────────────────────────────────────────────────────

ACCOMMODATION = _register(IndustryDimension(
    key="accommodation",
    display_name="Hotels & Accommodation",
    description="Hotels, motels, B&Bs — where local lodging competes with Marriott, Hilton, etc.",
    aliases=("hotel", "hotels", "motel", "lodging", "hospitality", "inn", "bed and breakfast", "bnb", "resort"),
    job_search_terms=(
        "front desk", "housekeeper", "housekeeping",
        "night auditor", "hotel manager", "concierge",
        "bellhop", "valet",
    ),
    poi_search_terms=(
        "hotel", "motel", "inn", "bed and breakfast",
        "lodge", "hostel", "resort",
    ),
    sentiment_keywords=(
        "understaffed", "rooms not cleaned", "overworked",
        "good tips", "great management", "flexible schedule",
    ),
    naics_codes=("721110",),
    mega_corps=(
        MegaCorp("marriott", "Marriott", (), None, "Q264684"),
        MegaCorp("hilton", "Hilton", (), None, "Q598884"),
        MegaCorp("hyatt", "Hyatt", (), None, "Q1425063"),
    ),
))

# ── Fitness & Wellness ───────────────────────────────────────────────

FITNESS = _register(IndustryDimension(
    key="fitness_wellness",
    display_name="Fitness & Wellness",
    description="Gyms, yoga studios, spas — where local studios compete with Planet Fitness, LA Fitness",
    aliases=("fitness", "gym", "wellness", "yoga", "pilates", "crossfit", "health club", "spa"),
    job_search_terms=(
        "personal trainer", "fitness instructor", "gym attendant",
        "yoga instructor", "front desk gym", "spin instructor",
        "group fitness",
    ),
    poi_search_terms=(
        "gym", "fitness center", "yoga studio", "pilates",
        "crossfit", "martial arts", "swimming pool",
    ),
    sentiment_keywords=(
        "understaffed", "dirty equipment", "overcrowded",
        "great community", "love teaching here", "toxic culture",
    ),
    naics_codes=("713940",),
    mega_corps=(
        MegaCorp("planet_fitness", "Planet Fitness", (), None, "Q7201095"),
        MegaCorp("la_fitness", "LA Fitness", (), None, "Q6457180"),
        MegaCorp("orangetheory", "Orangetheory Fitness", (), None, "Q25005163"),
    ),
))

# ── Childcare / Education ───────────────────────────────────────────

CHILDCARE = _register(IndustryDimension(
    key="childcare",
    display_name="Childcare & Early Education",
    description="Daycares and preschools — where local centers compete with KinderCare, Bright Horizons",
    aliases=("daycare", "day care", "preschool", "early education", "early childhood", "nursery", "after school"),
    job_search_terms=(
        "daycare teacher", "preschool teacher", "childcare worker",
        "early childhood", "infant teacher", "toddler teacher",
        "after school", "nanny",
    ),
    poi_search_terms=(
        "daycare", "preschool", "childcare center",
        "learning center", "montessori", "nursery school",
    ),
    sentiment_keywords=(
        "understaffed", "ratio", "turnover", "low pay",
        "rewarding", "love the kids", "great director",
    ),
    naics_codes=("624410",),
    mega_corps=(
        MegaCorp("kindercare", "KinderCare", ()),
        MegaCorp("bright_horizons", "Bright Horizons", ()),
        MegaCorp("goddard_school", "Goddard School", ()),
    ),
))

# ── Hair & Beauty Services ───────────────────────────────────────────

HAIR_BEAUTY = _register(IndustryDimension(
    key="hair_beauty",
    display_name="Hair & Beauty Services",
    description="Hair salons, barbershops — where independent stylists compete with Great Clips, Supercuts, Sport Clips.",
    aliases=("hair", "salon", "barber", "beauty", "barbershop", "hair salon", "cosmetology", "nail", "esthetician"),
    job_search_terms=(
        "hair stylist", "hairdresser", "barber", "cosmetologist",
        "salon manager", "colorist", "shampoo assistant",
        "esthetician", "nail technician", "beauty advisor",
        "receptionist salon", "stylist assistant",
    ),
    poi_search_terms=(
        "hair salon", "barbershop", "beauty salon", "barber shop",
        "nail salon", "day spa", "beauty supply",
        "cosmetology", "waxing", "threading",
    ),
    sentiment_keywords=(
        "understaffed", "walk-ins only", "long wait", "no openings",
        "booth rent", "commission split", "low pay", "tips only",
        "great clientele", "flexible schedule", "love my chair",
        "toxic salon", "overbooked", "burnout", "high turnover",
    ),
    naics_codes=("812111", "812112"),
    mega_corps=(
        MegaCorp("great_clips", "Great Clips", (), None, "Q5598967"),
        MegaCorp("supercuts", "Supercuts", (), None, "Q7644063"),
        MegaCorp("sport_clips", "Sport Clips", ("sports_clips",), None, "Q7579634"),
        MegaCorp("fantastic_sams", "Fantastic Sams", (), None, "Q5434724"),
    ),
))

# ── Auto Repair & Maintenance ───────────────────────────────────────

AUTO_REPAIR = _register(IndustryDimension(
    key="auto_repair",
    display_name="Auto Repair & Maintenance",
    description="Oil change shops, tire centers, general repair — where independent mechanics compete with Jiffy Lube, Midas, Firestone.",
    aliases=("mechanics", "mechanic", "auto", "automotive", "car repair", "car shop", "garage", "oil change", "tire", "auto service"),
    job_search_terms=(
        "auto mechanic", "automotive technician", "lube tech",
        "oil change technician", "tire technician", "auto tech",
        "service advisor", "service writer", "brake technician",
        "alignment technician", "shop manager", "mechanic",
        "diesel mechanic", "fleet mechanic",
    ),
    poi_search_terms=(
        "auto repair", "mechanic", "oil change", "tire shop",
        "auto body", "brake shop", "muffler shop",
        "transmission repair", "auto service",
    ),
    sentiment_keywords=(
        "understaffed", "overworked", "flat rate", "flag hours",
        "no benefits", "tool costs", "good shop", "fair pay",
        "toxic management", "parts shortage", "high turnover",
        "love wrenching", "career path", "ASE certified",
    ),
    naics_codes=("811111", "811112", "811118"),
    mega_corps=(
        MegaCorp("jiffy_lube", "Jiffy Lube", (), None, "Q6192810"),
        MegaCorp("midas", "Midas", ("midas_auto",), None, "Q3312613"),
        MegaCorp("firestone", "Firestone Complete Auto Care", ("firestone_auto",), None, "Q420837"),
        MegaCorp("pep_boys", "Pep Boys", (), None, "Q3375007"),
        MegaCorp("valvoline", "Valvoline Instant Oil Change", ("valvoline_instant",), None, "Q1283718"),
    ),
))

# ── HVAC & Skilled Trades ───────────────────────────────────────────

HVAC_SKILLED_TRADES = _register(IndustryDimension(
    key="hvac_skilled_trades",
    display_name="HVAC & Skilled Trades",
    description="Heating, cooling, plumbing, electrical — where local contractors compete with franchise service chains.",
    aliases=("hvac", "plumber", "electrician", "skilled trades", "trades", "plumbing", "electrical", "contractor", "heating", "cooling", "air conditioning"),
    job_search_terms=(
        "HVAC technician", "HVAC installer", "HVAC service tech",
        "plumber", "electrician", "maintenance technician",
        "refrigeration tech", "sheet metal worker", "duct installer",
        "service plumber", "journeyman electrician", "apprentice HVAC",
        "apprentice plumber", "apprentice electrician",
        "facilities maintenance", "building maintenance",
    ),
    poi_search_terms=(
        "HVAC", "heating and cooling", "air conditioning repair",
        "plumber", "electrician", "handyman",
        "appliance repair", "water heater", "furnace repair",
    ),
    sentiment_keywords=(
        "understaffed", "overbooked", "on call 24/7", "burnout",
        "no work-life balance", "great pay", "overtime",
        "apprenticeship", "union", "journeyman", "master plumber",
        "franchise fees", "van stock costs", "commission based",
        "good benefits", "retirement", "tool allowance",
    ),
    naics_codes=("238220", "238210", "238110"),
    mega_corps=(
        MegaCorp("service_experts", "Service Experts Heating & Air", (), None, None),
        MegaCorp("aire_serv", "Aire Serv", (), None, None),
        MegaCorp("one_hour_heating", "One Hour Heating & Air Conditioning", ("one_hour_air",), None, None),
        MegaCorp("mr_electric", "Mr. Electric", (), None, None),
        MegaCorp("roto_rooter", "Roto-Rooter", (), None, "Q7370727"),
    ),
))


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def get_all_industries() -> list[dict]:
    """Return all industries as serialisable dicts."""
    return [
        {
            "key": dim.key,
            "display_name": dim.display_name,
            "description": dim.description,
            "mega_corps": [{"key": m.key, "name": m.display_name} for m in dim.mega_corps],
            "job_search_terms": list(dim.job_search_terms),
            "poi_search_terms": list(dim.poi_search_terms),
            "naics_codes": list(dim.naics_codes),
        }
        for dim in INDUSTRY_REGISTRY.values()
    ]


def get_industry(key: str) -> Optional[IndustryDimension]:
    """Look up an industry by key or alias."""
    if key in INDUSTRY_REGISTRY:
        return INDUSTRY_REGISTRY[key]
    key_lower = key.lower()
    for dim in INDUSTRY_REGISTRY.values():
        if key_lower in dim.aliases:
            return dim
    return None


def resolve_industry_key(raw: str) -> Optional[str]:
    """Return canonical industry key for raw input (key or alias), or None."""
    dim = get_industry(raw)
    return dim.key if dim else None


def get_all_mega_corps() -> list[dict]:
    """Return all mega-corps across all industries (deduplicated)."""
    seen: set[str] = set()
    out = []
    for dim in INDUSTRY_REGISTRY.values():
        for mc in dim.mega_corps:
            if mc.key not in seen:
                seen.add(mc.key)
                out.append({
                    "key": mc.key,
                    "name": mc.display_name,
                    "industry": dim.key,
                    "wikidata_id": mc.wikidata_id,
                })
    return out
