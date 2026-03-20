"""
One-time script to geocode all stores in tracker.db that have null coordinates.
Run once after implementing geocoding. Safe to re-run — skips already-geocoded stores.

Usage:
    python scripts/backfill_geocoding.py [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.database import Store, get_session, init_db
from scrapers.geocoding import geocode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Geocode all stores in tracker.db with null coordinates"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be geocoded, do not write",
    )
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        stores = (
            session.query(Store)
            .filter((Store.lat.is_(None)) | (Store.lng.is_(None)))
            .all()
        )

        logger.info("Found %d stores with null coordinates", len(stores))

        updated = 0
        failed = 0

        for store in stores:
            if not store.address:
                logger.warning("[%s] No address — skipping", store.store_num)
                failed += 1
                continue

            lat, lng = geocode(store.address)

            if lat is not None and lng is not None:
                if not args.dry_run:
                    store.lat = lat
                    store.lng = lng
                    session.commit()
                logger.info(
                    "[%s] %s → (%.4f, %.4f)",
                    store.store_num,
                    store.store_name,
                    lat,
                    lng,
                )
                updated += 1
            else:
                logger.warning(
                    "[%s] FAILED: %r", store.store_num, store.address
                )
                failed += 1

        logger.info("Done. Updated: %d  Failed: %d", updated, failed)
        if args.dry_run:
            logger.info("(dry-run — no changes written)")

    except Exception as e:
        session.rollback()
        logger.error("Backfill failed: %s", e)
    finally:
        session.close()


if __name__ == "__main__":
    main()
