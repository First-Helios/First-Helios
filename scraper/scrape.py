"""
Legacy CLI wrapper for the Starbucks careers API scraper.

This file preserves the original CLI interface:
    python scraper/scrape.py --location "Austin, TX, US" --radius 25

Internally delegates to scrapers/careers_api.py.

DO NOT DELETE THIS FILE — the legacy CLI must remain functional.
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


def _location_to_region(location: str) -> str:
    """Convert a location string to a region key.

    'Austin, TX, US' -> 'austin_tx'
    """
    parts = location.lower().replace(",", "").split()
    if len(parts) >= 2:
        city = parts[0].strip()
        state = parts[1].strip()
        return f"{city}_{state}"
    return "austin_tx"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Scrape Starbucks careers API (legacy CLI)"
    )
    parser.add_argument(
        "--location",
        default="Austin, TX, US",
        help="Location string (default: Austin, TX, US)",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=25,
        help="Search radius in miles (default: 25)",
    )
    parser.add_argument(
        "--chain",
        default="starbucks",
        help="Chain key (default: starbucks)",
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Skip database ingestion",
    )
    args = parser.parse_args()

    region = _location_to_region(args.location)
    logger.info(
        "Legacy scraper: location='%s' -> region='%s', radius=%d mi",
        args.location,
        region,
        args.radius,
    )

    from scrapers.careers_api import scrape_careers_api

    signals = scrape_careers_api(
        region=region,
        chain=args.chain,
        radius_mi=args.radius,
        ingest=not args.no_ingest,
    )

    logger.info("Scrape complete: %d signals", len(signals))

    # Print summary
    if signals:
        stores = set(s.store_num for s in signals)
        logger.info("Unique stores: %d", len(stores))
        logger.info("Listings found: %d", len(signals))
    else:
        logger.info("No listings found")


if __name__ == "__main__":
    main()
