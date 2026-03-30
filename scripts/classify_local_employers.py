"""
scripts/classify_local_employers.py

Classifies LocalEmployer records by Austin-area name-frequency proxy:
  1. Backfills location_count = number of times that name appears in the DB.
  2. Optionally purges records with location_count >= CHAIN_THRESHOLD.

Since we only have Austin-area data, a business appearing >= CHAIN_THRESHOLD
times is very likely a multi-location brand (Shell, 7-Eleven, McDonald's, etc.).
Businesses appearing < CHAIN_THRESHOLD times are treated as local operators.

By default this script only backfills location_count and never deletes.
Pass --purge to remove brand-like records from local_employers.

Limitation: national chains with few Austin locations will be missed until
more Texas data is ingested.

Usage:
    python scripts/classify_local_employers.py            # backfill only (safe)
    python scripts/classify_local_employers.py --threshold 5 --dry-run
    python scripts/classify_local_employers.py --purge    # backfill + delete brands
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import func

from core.database import LocalEmployer, get_session, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CHAIN_THRESHOLD_DEFAULT = 5


def run(threshold: int, dry_run: bool, purge: bool = True) -> None:
    engine = init_db()
    session = get_session(engine)

    try:
        # ── Compute name frequency ────────────────────────────────────────────
        freq_rows = (
            session.query(LocalEmployer.name, func.count(LocalEmployer.id).label("cnt"))
            .filter(LocalEmployer.is_active.is_(True))
            .group_by(LocalEmployer.name)
            .all()
        )
        freq_map: dict[str, int] = {name: cnt for name, cnt in freq_rows}
        total_names = len(freq_map)
        total_records = sum(freq_map.values())

        chain_names = {n for n, c in freq_map.items() if c >= threshold}
        local_names = {n for n, c in freq_map.items() if c < threshold}
        chain_records = sum(freq_map[n] for n in chain_names)
        local_records = sum(freq_map[n] for n in local_names)

        logger.info("Total unique names: %d (%d records)", total_names, total_records)
        logger.info(
            "Chain-like (>= %d occurrences): %d names, %d records",
            threshold, len(chain_names), chain_records,
        )
        logger.info(
            "Truly local (< %d occurrences): %d names, %d records",
            threshold, len(local_names), local_records,
        )

        top_chains = sorted(
            [(n, c) for n, c in freq_map.items() if c >= threshold],
            key=lambda x: -x[1],
        )[:20]
        logger.info("Top chain-like names:")
        for name, cnt in top_chains:
            logger.info("  %-40s %d locations", name, cnt)

        if dry_run:
            logger.info("[dry-run] No changes written.")
            return

        # ── Backfill location_count via single bulk SQL join-update ──────────
        logger.info("Updating location_count (bulk)…")
        db_path = str(engine.url).replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TEMP TABLE _freq (name TEXT PRIMARY KEY, cnt INTEGER)")
            conn.executemany("INSERT INTO _freq VALUES (?, ?)", freq_map.items())
            conn.execute(
                """
                UPDATE local_employers
                SET location_count = (
                    SELECT cnt FROM _freq WHERE _freq.name = local_employers.name
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        session.expire_all()
        null_remaining = session.query(LocalEmployer).filter(
            LocalEmployer.location_count.is_(None)
        ).count()
        chain_count_in_db = session.query(LocalEmployer).filter(
            LocalEmployer.location_count >= threshold
        ).count()
        local_count_in_db = session.query(LocalEmployer).filter(
            LocalEmployer.location_count < threshold
        ).count()
        logger.info("Records with null location_count remaining: %d", null_remaining)
        logger.info(
            "DB: chain-like (>= %d): %d | truly local (< %d): %d",
            threshold, chain_count_in_db, threshold, local_count_in_db,
        )

        # ── Purge chain-like records ──────────────────────────────────────────
        if purge and chain_count_in_db > 0:
            conn2 = sqlite3.connect(db_path)
            deleted = conn2.execute(
                "DELETE FROM local_employers WHERE location_count >= ?", (threshold,)
            ).rowcount
            conn2.commit()
            conn2.close()
            session.expire_all()
            remaining = session.query(LocalEmployer).count()
            logger.info(
                "Purged %d chain-like records. local_employers now has %d rows.",
                deleted, remaining,
            )
        elif not purge:
            logger.info(
                "Skipping purge (default). Pass --purge to remove brand-like records."
            )

    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold", type=int, default=CHAIN_THRESHOLD_DEFAULT,
        help=f"Min location count to classify as chain (default: {CHAIN_THRESHOLD_DEFAULT})",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--purge", dest="purge", action="store_true",
        help="Delete brand-like records (location_count >= threshold) after backfill",
    )
    parser.set_defaults(purge=False)
    args = parser.parse_args()
    run(threshold=args.threshold, dry_run=args.dry_run, purge=args.purge)
