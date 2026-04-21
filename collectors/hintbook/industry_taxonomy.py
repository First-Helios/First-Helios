"""
Cross-industry deal taxonomy.

Answers: given that competitors cover deals for category X, does it belong on
our first-party map (geo-anchored venue)? Or in a broader "deal framework"
(mostly code-based / online-only)?

`map_viable=True` means the deal is naturally consumed at a physical venue
and makes sense as a map pin (restaurants, auto repair, gyms, car washes).
`map_viable=False` means the deal is typically code-based or online-only and
better served by a promo-feed UX (airlines, software subs, e-commerce coupons).
Some categories are mixed — we mark the dominant pattern and note the mix.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndustryDef:
    key: str
    label: str
    map_viable: bool
    notes: str


INDUSTRIES: dict[str, IndustryDef] = {
    "food": IndustryDef(
        "food", "Restaurants & bars", True,
        "Core meal-deal pipeline. First-party evidence required.",
    ),
    "grocery": IndustryDef(
        "grocery", "Grocery & supermarket", True,
        "Venue-anchored weekly circulars; map-viable for chains with geo presence.",
    ),
    "automotive_service": IndustryDef(
        "automotive_service", "Auto repair, oil change, tires", True,
        "Geo-anchored service coupons (Valvoline, Jiffy Lube, Firestone, Midas). "
        "Strong fit for a map; similar structure to food chains.",
    ),
    "automotive_retail": IndustryDef(
        "automotive_retail", "Auto parts retail", True,
        "AutoZone, O'Reilly, Advance Auto — chain store promos + in-store pickup. Map-viable.",
    ),
    "car_wash": IndustryDef(
        "car_wash", "Car wash & detail", True,
        "Highly location-specific; ideal map category. Often subscription + coupon mix.",
    ),
    "gas_fuel": IndustryDef(
        "gas_fuel", "Gas stations & fuel rewards", True,
        "Geo-anchored, per-station pricing. Adjacent to map UX; data is mostly app-based.",
    ),
    "fitness_gym": IndustryDef(
        "fitness_gym", "Gyms & fitness studios", True,
        "Geo-anchored membership offers. Map-viable.",
    ),
    "beauty_salon": IndustryDef(
        "beauty_salon", "Salons, barbers, spas", True,
        "Local service coupons. Groupon-heavy. Map-viable.",
    ),
    "entertainment_venue": IndustryDef(
        "entertainment_venue", "Theaters, bowling, arcades, attractions", True,
        "Venue-anchored. Map-viable.",
    ),
    "travel_hotel": IndustryDef(
        "travel_hotel", "Hotels & lodging", True,
        "Geo-anchored but typically booked online. Hybrid: map pin + promo code.",
    ),
    "travel_air": IndustryDef(
        "travel_air", "Airlines & flights", False,
        "Origin-destination, not venue-anchored. Deal-framework UX, not map.",
    ),
    "travel_rental": IndustryDef(
        "travel_rental", "Rental cars", False,
        "Booked at airports/cities but promo is code-driven. Deal-framework.",
    ),
    "travel_cruise_package": IndustryDef(
        "travel_cruise_package", "Cruises & vacation packages", False,
        "Destination-based but not map-rendered. Deal-framework.",
    ),
    "retail_apparel": IndustryDef(
        "retail_apparel", "Apparel retail", False,
        "Mostly online coupons. Deal-framework.",
    ),
    "retail_electronics": IndustryDef(
        "retail_electronics", "Consumer electronics", False,
        "Best Buy, Amazon, etc. — online coupon territory.",
    ),
    "retail_home": IndustryDef(
        "retail_home", "Home goods & furniture", False,
        "Code-based online coupons dominate.",
    ),
    "subscription_software": IndustryDef(
        "subscription_software", "SaaS & streaming", False,
        "Pure promo-code framework.",
    ),
    "pharmacy_health": IndustryDef(
        "pharmacy_health", "Pharmacy, vision, dental chains", True,
        "CVS, Walgreens, LensCrafters, Aspen Dental — geo-anchored chain offers.",
    ),
    "pet_services": IndustryDef(
        "pet_services", "Pet stores, grooming, vet", True,
        "Petco/PetSmart + local groomers. Map-viable.",
    ),
    "financial_signup": IndustryDef(
        "financial_signup", "Bank & card signup bonuses", False,
        "Not venue-based; deal-framework only.",
    ),
}


MAP_VIABLE_KEYS = frozenset(k for k, v in INDUSTRIES.items() if v.map_viable)
FRAMEWORK_ONLY_KEYS = frozenset(k for k, v in INDUSTRIES.items() if not v.map_viable)
