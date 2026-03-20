"""
openclaw/industries.py — Industry exploration dimensions.

Defines which industries the agent should investigate, what search terms
are valid for each, what data sources apply, and what mega-corps dominate
each sector.  The agent picks from these dimensions; it cannot invent its
own industries or brands outside this registry.

The registry is intentionally broader than what chains.yaml covers today.
The agent's job is to figure out WHERE local businesses can compete with
mega-corps in each sector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MegaCorp:
    """A national/multinational chain the agent should track."""
    key: str                         # internal slug
    display_name: str
    aliases: tuple[str, ...]  = ()   # alternate search names
    careers_domain: Optional[str] = None   # e.g. "starbucks.wd1.myworkdayjobs.com"
    wikidata_id: Optional[str] = None


@dataclass(frozen=True)
class IndustryDimension:
    """An industry the agent can explore."""
    key: str
    display_name: str
    description: str

    # Search term pools — agent picks from these, cannot invent new ones
    job_search_terms: tuple[str, ...]
    poi_search_terms: tuple[str, ...]       # for finding local competitors
    sentiment_keywords: tuple[str, ...]     # for Reddit / review sentiment

    # BLS NAICS codes to pull wage/employment data
    naics_codes: tuple[str, ...] = ()

    # Which mega-corps dominate this sector
    mega_corps: tuple[MegaCorp, ...] = ()

    # Data source applicability
    applicable_sources: tuple[str, ...] = ("alltheplaces", "overture", "osm", "bls", "jobspy", "reddit")

    # How often data goes stale (days)
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
    naics_codes=("722515",),  # Snack and non-alcoholic beverage bars
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
    naics_codes=("722513",),  # Limited-service restaurants
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
    naics_codes=("722511",),  # Full-service restaurants
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
    naics_codes=("452210", "452319"),  # Department stores, general merch
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
    naics_codes=("445110",),  # Supermarkets
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
    naics_codes=("621111", "621493"),  # Offices of physicians, freestanding ER
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
    naics_codes=("446110",),  # Pharmacies
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
    naics_codes=("721110",),  # Hotels and motels
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
    naics_codes=("713940",),  # Fitness and recreational sports centers
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
    naics_codes=("624410",),  # Child day care services
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
    description="Hair salons, barbershops, beauty services — where independent stylists and shop owners compete with Great Clips, Supercuts, Sport Clips. Local owners often pay better (booth rent vs commission) but lack recruiting reach.",
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
    naics_codes=("812111", "812112"),  # Barber shops, Beauty salons
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
    description="Oil change shops, tire centers, general repair — where independent mechanics and local shops compete with Jiffy Lube, Midas, Firestone. Local shops often pay significantly more for skilled techs but can't recruit against franchise ad budgets.",
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
    naics_codes=("811111", "811112", "811118"),  # General auto repair, Exhaust/Transmission, Other
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
    description="Heating, cooling, plumbing, electrical — where local contractors compete with franchise service chains like Service Experts, Aire Serv, Mr. Electric. Skilled tradespeople are in extreme demand; local shops often pay $5-15/hr more but have zero recruiting presence.",
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
    naics_codes=("238220", "238210", "238110"),  # Plumbing/HVAC, Electrical, Poured concrete
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
    """Return all industries as dicts for the agent/API."""
    out = []
    for dim in INDUSTRY_REGISTRY.values():
        out.append({
            "key": dim.key,
            "display_name": dim.display_name,
            "description": dim.description,
            "mega_corps": [{"key": m.key, "name": m.display_name} for m in dim.mega_corps],
            "job_search_terms": list(dim.job_search_terms),
            "poi_search_terms": list(dim.poi_search_terms),
            "naics_codes": list(dim.naics_codes),
        })
    return out


def get_industry(key: str) -> Optional[IndustryDimension]:
    """Look up an industry by key."""
    return INDUSTRY_REGISTRY.get(key)


def get_valid_search_terms(industry_key: str, term_type: str = "job") -> set[str]:
    """Return the valid search terms for an industry.

    Args:
        industry_key: e.g. "coffee_cafe"
        term_type: "job" | "poi" | "sentiment"
    """
    dim = INDUSTRY_REGISTRY.get(industry_key)
    if not dim:
        return set()
    if term_type == "poi":
        return set(dim.poi_search_terms)
    if term_type == "sentiment":
        return set(dim.sentiment_keywords)
    return set(dim.job_search_terms)


def get_all_mega_corps() -> list[dict]:
    """Return all mega-corps across all industries."""
    seen = set()
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
