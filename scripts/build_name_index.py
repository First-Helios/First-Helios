"""
scripts/build_name_index.py

Build (or refresh) the ref_employer_name_index table from local_employers data.

Classification rules:
  national_chain  — name appears in the known-national-chain list OR has 10+ Austin locations
  regional_chain  — 3–9 Austin locations (multi-site but not national)
  local           — 1–2 Austin locations

Usage:
    python scripts/build_name_index.py
    python scripts/build_name_index.py --min-count 2   # only index names seen 2+ times
"""

import argparse
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, ".")
from backend.database import EmployerNameIndex, get_session, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Known national chains that may appear in local_employers despite the exclusion filter.
# Extend this list as new chains are discovered in the data.
NATIONAL_CHAINS: set[str] = {
    # Convenience / fuel
    "7-eleven", "circle k", "quiktrip", "chevron", "shell", "exxon", "mobil",
    "valero", "murphy usa", "racetrac", "wawa", "casey's", "ampm", "bp",
    "corner store", "txb",
    # Fast food / QSR
    "subway", "taco bell", "wendy's", "domino's pizza", "domino's", "pizza hut",
    "jack in the box", "sonic drive in", "sonic drive-in", "sonic", "panda express",
    "chick-fil-a", "little caesars pizza", "papa johns pizza", "jimmy john's",
    "mod pizza", "jersey mike's", "firehouse subs", "wingstop", "raising cane's",
    "whataburger", "mcdonald's", "burger king", "popeyes", "kfc", "starbucks",
    "dunkin", "ihop", "denny's", "cracker barrel", "olive garden", "applebee's",
    "chili's", "red lobster", "outback steakhouse", "texas roadhouse",
    "first watch", "jason's deli", "schlotzsky's", "in-n-out burger",
    "dutch bros", "dutch bros coffee", "chipotle", "chipotle mexican grill",
    "moe's southwest grill", "qdoba", "del taco", "arby's", "hardee's",
    "culver's", "whataburger", "shake shack", "five guys",
    # Grocery / retail
    "h-e-b", "heb", "kroger", "walmart", "target", "costco", "sam's club",
    "whole foods", "trader joe's", "aldi", "sprouts",
    "cvs", "walgreens", "rite aid", "dollar general", "dollar tree", "family dollar",
    "ross", "tj maxx", "marshalls", "burlington", "h&m", "gap", "old navy",
    "banana republic", "nike", "loft", "alo", "victoria's secret", "bath & body works",
    "ulta beauty", "sephora", "the home depot", "lowe's", "ace hardware",
    "best buy", "apple store", "at&t", "verizon", "t-mobile",
    # Hotels
    "marriott", "hilton", "hyatt", "holiday inn", "best western", "hampton inn",
    "courtyard", "residence inn", "fairfield inn", "moxy", "westin",
    "doubletree", "embassy suites", "homewood suites", "aloft", "springhill suites",
    "la quinta", "comfort inn", "sleep inn", "days inn", "super 8",
    # Auto
    "autozone", "o'reilly auto parts", "advance auto parts", "napa auto parts",
    "jiffy lube", "firestone", "pep boys", "midas", "mavis", "take 5 oil change",
    "christian brothers automotive", "service king", "caliber collision",
    "gerber collision", "safelite", "jiffy lube",
    "carmax", "carvana", "autonation", "hendrick automotive",
    # Fitness
    "planet fitness", "la fitness", "anytime fitness", "24 hour fitness",
    "gold's gym", "equinox", "orangetheory", "f45", "crunch fitness",
    "lifetime fitness", "life time", "pure barre", "cyclebar",
    # Personal care / beauty
    "great clips", "sport clips", "fantastic sams", "supercuts", "regis",
    "great clips", "hair cuttery", "floyd's", "floyd's 99 barbershop",
    "ulta", "fantastic sam's", "smartstyle",
    # Healthcare
    "concentra", "urgent care", "cvs minuteclinic", "medspring",
    "ut health", "ascension", "st. david's", "baylor scott & white",
    "community care", "seton", "dell seton",
    # Finance / banking
    "chase", "bank of america", "wells fargo", "citibank", "capital one",
    "regions bank", "frost bank", "comerica", "bbva", "bbva compass",
    "charles schwab", "edward jones", "ameriprise",
    # Staffing
    "manpower", "staffmark", "adecco", "kelly services", "robert half",
    "express employment", "labor ready", "trueblue",
    # Trades / home services
    "servpro", "servicemaster", "neighborly", "terminix", "orkin",
    "adt", "vivint", "sunrun",
    # Other national
    "fedex", "ups", "usps", "fedex office",
    "a&w",
}


def _normalize(name: str) -> str:
    return name.strip().lower()


def build_index(session, min_count: int = 1) -> dict:
    """Read local_employers, compute name frequencies, classify, and upsert to ref_employer_name_index."""

    from sqlalchemy import text

    rows = session.execute(text(
        "SELECT name, category, industry FROM local_employers WHERE name IS NOT NULL"
    )).fetchall()

    # Aggregate counts and collect most-common category/industry per name
    count: Counter = Counter()
    categories: defaultdict = defaultdict(Counter)
    industries: defaultdict = defaultdict(Counter)

    for name, category, industry in rows:
        count[name] += 1
        if category:
            categories[name][category] += 1
        if industry:
            industries[name][industry] += 1

    upserted = 0
    for name, cnt in count.items():
        if cnt < min_count:
            continue

        norm = _normalize(name)

        # Classify
        if norm in NATIONAL_CHAINS or cnt >= 10:
            classification = "national_chain"
            is_chain = True
            notes = "known national brand" if norm in NATIONAL_CHAINS else f"{cnt} Austin locations"
        elif cnt >= 3:
            classification = "regional_chain"
            is_chain = True
            notes = f"Austin regional — {cnt} locations"
        else:
            classification = "local"
            is_chain = False
            notes = None

        top_cat = categories[name].most_common(1)[0][0] if categories[name] else None
        top_ind = industries[name].most_common(1)[0][0] if industries[name] else None

        existing = session.get(EmployerNameIndex, name)
        if existing:
            existing.austin_location_count = cnt
            existing.classification = classification
            existing.is_chain = is_chain
            existing.industry = top_ind
            existing.category = top_cat
            existing.notes = notes
            existing.updated_at = datetime.utcnow()
        else:
            session.add(EmployerNameIndex(
                name=name,
                austin_location_count=cnt,
                classification=classification,
                industry=top_ind,
                category=top_cat,
                is_chain=is_chain,
                notes=notes,
                updated_at=datetime.utcnow(),
            ))
        upserted += 1

    session.commit()
    return {"total_names": len(count), "indexed": upserted}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-count", type=int, default=1,
                        help="Only index names seen at least this many times (default: 1)")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        result = build_index(session, min_count=args.min_count)
        logger.info("Name index built: %s", result)

        # Print summary
        from sqlalchemy import text
        summary = session.execute(text(
            "SELECT classification, COUNT(*) as names, SUM(austin_location_count) as total_locations "
            "FROM ref_employer_name_index GROUP BY classification ORDER BY total_locations DESC"
        )).fetchall()
        print("\nClassification summary:")
        for cls, names, locs in summary:
            print(f"  {cls:<20} {names:>5} unique names  {locs:>6} total locations")

    finally:
        session.close()


if __name__ == "__main__":
    main()
