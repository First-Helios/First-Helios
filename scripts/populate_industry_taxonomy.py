"""
scripts/populate_industry_taxonomy.py

Seeds ref_industry_taxonomy with wage baselines from OEWS data and computes
mobility_score for each internal industry key.

Replaces the hardcoded UPWARD_MOBILITY_CATEGORIES set with data-driven scoring:
  - baseline_wage_hr = OEWS median hourly for the industry's primary occupation
  - upward_mobility  = baseline_wage_hr >= MOBILITY_THRESHOLD ($17.38/hr)
  - mobility_score   = 0-1 composite of wage lift + career ceiling

SERVICE_BASELINE   = $13.90/hr  (OEWS: fast food median, Austin MSA, 2024)
MOBILITY_THRESHOLD = $17.38/hr  (1.25 x SERVICE_BASELINE)

mobility_score formula:
  wage_lift       = (median - baseline) / baseline, capped at 1.0 (=100% lift)
  ceiling_factor  = (p90 - baseline) / baseline / 3, capped at 1.0 (=300% lift)
  mobility_score  = 0.70 * wage_lift + 0.30 * ceiling_factor

Usage:
    python scripts/populate_industry_taxonomy.py
    python scripts/populate_industry_taxonomy.py --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.database import OEWSRecord, get_engine, get_session, init_db
from backend.models.reference import IndustryTaxonomy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SERVICE_BASELINE   = 13.90
MOBILITY_THRESHOLD = SERVICE_BASELINE * 1.25

# industry_key -> (display_name, primary_occ_code, naics_code, naics2d,
#                  worker_tier, revelio_sector, revelio_soc_group,
#                  jolts_industry_code, overture_categories)
INDUSTRY_DEFINITIONS = {
    "fast_food": (
        "Fast Food & QSR", "35-3023",
        "722513", 72, "service",
        "Leisure and Hospitality", "Food Preparation and Serving Related Occupations",
        "RCU", "fast_food_restaurant,sandwich_shop,burger_restaurant,pizza_restaurant,mexican_restaurant,taco_restaurant,food_truck",
    ),
    "coffee_cafe": (
        "Coffee & Cafe", "35-0000",
        "722515", 72, "service",
        "Leisure and Hospitality", "Food Preparation and Serving Related Occupations",
        "RCU", "coffee_shop,cafe,donut_shop,tea_house",
    ),
    "food_full_service": (
        "Full-Service Restaurants", "35-0000",
        "722511", 72, "service",
        "Leisure and Hospitality", "Food Preparation and Serving Related Occupations",
        "RCU", "restaurant,american_restaurant,barbecue_restaurant,bakery,ice_cream_shop,smoothie_juice_bar",
    ),
    "bar_nightlife": (
        "Bars & Nightlife", "35-9011",
        "722410", 72, "service",
        "Leisure and Hospitality", "Food Preparation and Serving Related Occupations",
        "RCU", "bar",
    ),
    "retail_general": (
        "Retail", "41-0000",
        "44", 44, "service",
        "Trade, Transportation, and Utilities", "Sales and Related Occupations",
        "RTU", "grocery_store,convenience_store,clothing_store,department_store,furniture_store,electronics,liquor_store,shoe_store",
    ),
    "retail_pharmacy": (
        "Pharmacy & Drug Store", "29-2052",
        "4461", 44, "service",
        "Trade, Transportation, and Utilities", "Healthcare Support Occupations",
        "RTU", "pharmacy",
    ),
    "auto_services": (
        "Auto Repair & Services", "49-3023",
        "8111", 81, "trades",
        "Other Services", "Installation, Maintenance, and Repair Occupations",
        "OSV", "automotive_repair,auto_body_shop,gas_station,car_wash,tire_dealer_and_repair,automotive_parts_and_accessories",
    ),
    "auto_dealer": (
        "Auto Sales & Dealerships", "41-2031",
        "4411", 44, "service",
        "Trade, Transportation, and Utilities", "Sales and Related Occupations",
        "RTU", "car_dealer,used_car_dealer",
    ),
    "personal_care": (
        "Beauty & Personal Care", "39-5012",
        "8121", 81, "service",
        "Other Services", "Personal Care and Service Occupations",
        "OSV", "beauty_salon,hair_salon,nail_salon,barber,spas,massage_therapy,tattoo_and_piercing",
    ),
    "fitness": (
        "Fitness & Recreation", "39-9031",
        "7139", 71, "service",
        "Leisure and Hospitality", "Personal Care and Service Occupations",
        "RCU", "gym,martial_arts_club,yoga_studio,dance_school",
    ),
    "hospitality": (
        "Hotels & Hospitality", "35-0000",
        "721110", 72, "service",
        "Leisure and Hospitality", "Food Preparation and Serving Related Occupations",
        "RCU", "hotel,motel",
    ),
    "skilled_trades": (
        "Skilled Trades & Home Services", "47-0000",
        "2381", 23, "trades",
        "Construction", "Installation, Maintenance, and Repair Occupations",
        "CON", "hvac_services,contractor,roofing,landscaping,construction_services,electrician,plumbing,home_service",
    ),
    "healthcare": (
        "Healthcare", "29-0000",
        "621", 62, "professional",
        "Education and Health Services", "Healthcare Practitioners and Technical Occupations",
        "HSE", "doctor,dentist,chiropractor,physical_therapy,hospital,medical_center,optometrist,veterinarian",
    ),
    "finance": (
        "Finance & Banking", "13-0000",
        "52", 52, "professional",
        "Financial Activities", "Business and Financial Operations Occupations",
        "FSR", "bank_credit_union,banks,financial_service,insurance_agency,financial_advising,mortgage_broker,credit_union",
    ),
    "education": (
        "Education", "25-0000",
        "611", 61, "professional",
        "Education and Health Services", "Education, Training, and Library Occupations",
        "HSE", "elementary_school,preschool,college_university",
    ),
    "professional_services": (
        "Professional Services", "13-0000",
        "541", 54, "professional",
        "Professional and Business Services", "Business and Financial Operations Occupations",
        "PBS", "professional_services,corporate_office,marketing_agency,lawyer,accountant,engineering_services",
    ),
    "tech_services": (
        "Technology & IT Services", "15-0000",
        "5415", 54, "professional",
        "Professional and Business Services", "Computer and Mathematical Occupations",
        "PBS", "software_development,information_technology_company,it_service_and_computer_repair",
    ),
    "logistics": (
        "Logistics & Delivery", "53-0000",
        "492", 49, "trades",
        "Trade, Transportation, and Utilities", "Transportation and Material Moving Occupations",
        "RTU", "courier_and_delivery_services",
    ),
    "staffing": (
        "Staffing & Employment Agencies", "13-1071",
        "5613", 56, "professional",
        "Professional and Business Services", "Business and Financial Operations Occupations",
        "PBS", "employment_agencies",
    ),
    "nonprofit": (
        "Nonprofit & Community Services", "21-0000",
        "813", 81, "service",
        "Other Services", "Community and Social Service Occupations",
        "OSV", "community_services_non_profits,social_service_organizations",
    ),
}


def _mobility_score(median_hr: float | None, p90_hr: float | None) -> float:
    """Compute mobility_score (0.0-1.0) from OEWS wage percentiles.

    wage_lift:      how much the median wage exceeds the service baseline, capped at 100% lift
    ceiling_factor: how high P90 reaches above baseline, capped at 300% lift

    Score = 0.70 * wage_lift + 0.30 * ceiling_factor
    """
    if not median_hr:
        return 0.0
    lift = max(0.0, (median_hr - SERVICE_BASELINE) / SERVICE_BASELINE)
    lift_norm = min(lift, 1.0)
    if p90_hr:
        ceil_ = max(0.0, (p90_hr - SERVICE_BASELINE) / SERVICE_BASELINE)
        ceil_norm = min(ceil_ / 3.0, 1.0)
    else:
        ceil_norm = lift_norm
    return round(0.70 * lift_norm + 0.30 * ceil_norm, 4)


def populate(dry_run: bool = False) -> None:
    engine = init_db()
    session = get_session(engine)

    oews_rows = session.query(
        OEWSRecord.occ_code, OEWSRecord.wage_median_hourly, OEWSRecord.wage_90pct
    ).all()
    oews = {r.occ_code: (r.wage_median_hourly, r.wage_90pct) for r in oews_rows}
    logger.info("OEWS records loaded: %d", len(oews))
    logger.info("SERVICE_BASELINE=$%.2f  MOBILITY_THRESHOLD=$%.2f", SERVICE_BASELINE, MOBILITY_THRESHOLD)
    logger.info("")

    upserted = 0
    for industry_key, defn in INDUSTRY_DEFINITIONS.items():
        (display_name, occ_code, naics_code, naics2d, worker_tier,
         rev_sector, rev_soc, jolts_code, overture_cats) = defn

        median_hr, p90_hr = oews.get(occ_code, (None, None))
        score = _mobility_score(median_hr, p90_hr)
        is_mobility = (median_hr or 0.0) >= MOBILITY_THRESHOLD
        wage_source = "oews_austin_2024" if median_hr else None

        logger.info(
            "  %-25s  occ=%-9s  median=$%-5s  p90=$%-5s  score=%.2f  mobility=%s  tier=%s",
            industry_key, occ_code,
            f"{median_hr:.2f}" if median_hr else "N/A",
            f"{p90_hr:.2f}" if p90_hr else "N/A",
            score,
            "YES" if is_mobility else "no",
            worker_tier,
        )

        if not dry_run:
            existing = session.get(IndustryTaxonomy, industry_key)
            if existing:
                existing.display_name        = display_name
                existing.primary_occ_code    = occ_code
                existing.naics_code          = naics_code
                existing.naics2d_code        = naics2d
                existing.worker_tier         = worker_tier
                existing.revelio_sector      = rev_sector
                existing.revelio_soc_group   = rev_soc
                existing.jolts_industry_code = jolts_code
                existing.baseline_wage_hr    = median_hr
                existing.wage_source         = wage_source
                existing.upward_mobility     = is_mobility
                existing.overture_categories = overture_cats
            else:
                session.add(IndustryTaxonomy(
                    industry_key         = industry_key,
                    display_name         = display_name,
                    primary_occ_code     = occ_code,
                    naics_code           = naics_code,
                    naics2d_code         = naics2d,
                    worker_tier          = worker_tier,
                    revelio_sector       = rev_sector,
                    revelio_soc_group    = rev_soc,
                    jolts_industry_code  = jolts_code,
                    baseline_wage_hr     = median_hr,
                    wage_source          = wage_source,
                    upward_mobility      = is_mobility,
                    overture_categories  = overture_cats,
                ))
            upserted += 1

    if not dry_run:
        session.commit()
        logger.info("")
        logger.info("Upserted %d industry taxonomy rows.", upserted)
    else:
        logger.info("")
        logger.info("[DRY RUN] Would upsert %d rows.", upserted)
    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    populate(dry_run=args.dry_run)
