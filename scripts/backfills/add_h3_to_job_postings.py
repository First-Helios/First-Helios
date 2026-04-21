"""
scripts/add_h3_to_job_postings.py

Migration: add h3_r7 and h3_r8 columns to job_postings, then backfill
existing rows from their lat/lng coordinates.

Safe to re-run — uses IF NOT EXISTS for column additions and skips rows
that already have h3 values (unless --force is passed).

Usage:
    python scripts/add_h3_to_job_postings.py             # add columns + backfill
    python scripts/add_h3_to_job_postings.py --dry-run   # preview only
    python scripts/add_h3_to_job_postings.py --force     # recompute all rows
"""

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text

from core.database import get_engine, get_session, init_db

logger = logging.getLogger(__name__)

_BATCH = 500


def add_columns(session, dry_run: bool = False) -> None:
    """Add h3_r7, h3_r8, and is_remote columns to job_postings if they don't exist."""
    stmts = [
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS h3_r7 VARCHAR(15)",
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS h3_r8 VARCHAR(15)",
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS is_remote BOOLEAN",
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS address_method VARCHAR(20)",
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS job_excerpt VARCHAR(600)",
        "CREATE INDEX IF NOT EXISTS ix_job_postings_h3_r7 ON job_postings (h3_r7)",
        "CREATE INDEX IF NOT EXISTS ix_job_postings_h3_r8 ON job_postings (h3_r8)",
        "CREATE INDEX IF NOT EXISTS ix_job_postings_h3r7_active ON job_postings (h3_r7, is_active)",
        "CREATE INDEX IF NOT EXISTS ix_job_postings_h3r8_active ON job_postings (h3_r8, is_active)",
        # Back-fill is_remote=True for all existing jobicy rows
        "UPDATE job_postings SET is_remote = TRUE WHERE source = 'jobicy' AND is_remote IS NULL",
    ]
    for stmt in stmts:
        logger.info("  %s", stmt)
        if not dry_run:
            session.execute(text(stmt))
    if not dry_run:
        session.commit()
        logger.info("Columns and indexes created (or already existed).")


def backfill(session, force: bool = False, dry_run: bool = False) -> dict[str, int]:
    """Compute h3_r7 / h3_r8 for every job_posting that has lat/lng."""
    try:
        import h3
    except ImportError:
        logger.error("h3 package not installed. Run: pip install h3")
        sys.exit(1)

    where = "lat IS NOT NULL AND lng IS NOT NULL"
    if not force:
        where += " AND h3_r7 IS NULL"

    count_row = session.execute(
        text(f"SELECT COUNT(*) FROM job_postings WHERE {where}")
    ).scalar()
    logger.info("Rows to backfill: %d", count_row)

    if dry_run or count_row == 0:
        return {"updated": 0, "skipped": count_row if dry_run else 0}

    offset = 0
    updated = 0

    while True:
        rows = session.execute(
            text(f"SELECT id, lat, lng FROM job_postings WHERE {where} LIMIT :lim OFFSET :off"),
            {"lim": _BATCH, "off": offset},
        ).fetchall()

        if not rows:
            break

        for row_id, lat, lng in rows:
            try:
                r7 = h3.latlng_to_cell(lat, lng, 7)
                r8 = h3.latlng_to_cell(lat, lng, 8)
                session.execute(
                    text("UPDATE job_postings SET h3_r7=:r7, h3_r8=:r8 WHERE id=:id"),
                    {"r7": r7, "r8": r8, "id": row_id},
                )
                updated += 1
            except Exception as exc:
                logger.warning("  Row %d: H3 failed (%s, %s): %s", row_id, lat, lng, exc)

        session.commit()
        offset += _BATCH
        logger.info("  Backfilled %d / %d rows...", min(offset, count_row), count_row)

    logger.info("Backfill complete: %d rows updated.", updated)
    return {"updated": updated}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Add H3 columns to job_postings and backfill")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--force",   action="store_true", help="Recompute H3 for all rows with coords")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        logger.info("=== Step 1: Add columns ===")
        add_columns(session, dry_run=args.dry_run)

        logger.info("=== Step 2: Backfill H3 cells ===")
        stats = backfill(session, force=args.force, dry_run=args.dry_run)
        logger.info("Stats: %s", stats)
    finally:
        session.close()


if __name__ == "__main__":
    main()
