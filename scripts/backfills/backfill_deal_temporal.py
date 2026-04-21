#!/usr/bin/env python3
"""
scripts/backfills/backfill_deal_temporal.py — Re-parse valid_days / valid_start_time /
valid_end_time for existing meal_deal rows using the improved temporal extractor.

Safe to run repeatedly.  Only updates rows where the new extractor finds a
value AND the existing column is empty.  Never overwrites manually-set data.

Usage:
  PYTHONPATH=. python scripts/backfills/backfill_deal_temporal.py          # dry-run
  PYTHONPATH=. python scripts/backfills/backfill_deal_temporal.py --apply  # write changes
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.database import MealDeal, init_db, get_session
from collectors.meal_deals.temporal import extract_days, extract_times

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _pick_text(deal: MealDeal) -> str:
    """Assemble the best text to parse: raw_scraped_text → description → name."""
    parts = [
        deal.raw_scraped_text or "",
        deal.deal_description or "",
        deal.deal_name or "",
    ]
    # Dedup while preserving order so we don't double-count
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return " ".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill temporal fields on meal_deals")
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry-run)")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing valid_* values too (default: only fill NULLs)",
    )
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    stats = {
        "scanned": 0,
        "days_filled": 0,
        "start_filled": 0,
        "end_filled": 0,
        "unchanged": 0,
    }

    try:
        deals = session.query(MealDeal).all()
        stats["scanned"] = len(deals)
        logger.info("Scanning %d meal_deal rows...", len(deals))

        updates: list[tuple[MealDeal, dict]] = []

        for deal in deals:
            text = _pick_text(deal)
            if not text.strip():
                stats["unchanged"] += 1
                continue

            new_days = extract_days(text)
            new_start, new_end = extract_times(text)

            changes: dict = {}

            if new_days and (args.overwrite or not deal.valid_days):
                if new_days != deal.valid_days:
                    changes["valid_days"] = new_days
            if new_start and (args.overwrite or not deal.valid_start_time):
                if new_start != deal.valid_start_time:
                    changes["valid_start_time"] = new_start
            if new_end and (args.overwrite or not deal.valid_end_time):
                if new_end != deal.valid_end_time:
                    changes["valid_end_time"] = new_end

            if not changes:
                stats["unchanged"] += 1
                continue

            updates.append((deal, changes))
            if "valid_days" in changes:
                stats["days_filled"] += 1
            if "valid_start_time" in changes:
                stats["start_filled"] += 1
            if "valid_end_time" in changes:
                stats["end_filled"] += 1

        # Report
        logger.info("")
        logger.info("Backfill summary:")
        logger.info("  %-30s %d", "rows scanned", stats["scanned"])
        logger.info("  %-30s %d", "valid_days to fill", stats["days_filled"])
        logger.info("  %-30s %d", "valid_start_time to fill", stats["start_filled"])
        logger.info("  %-30s %d", "valid_end_time to fill", stats["end_filled"])
        logger.info("  %-30s %d", "rows with no change", stats["unchanged"])

        # Show a sample of 10 planned updates for visual check
        if updates:
            logger.info("")
            logger.info("Sample of %d planned updates:", min(10, len(updates)))
            for deal, changes in updates[:10]:
                logger.info(
                    "  id=%d name=%r  ->  %s",
                    deal.id, (deal.deal_name or "")[:50], changes,
                )

        if not args.apply:
            logger.info("")
            logger.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        # Apply
        for deal, changes in updates:
            for col, val in changes.items():
                setattr(deal, col, val)

        session.commit()
        logger.info("")
        logger.info("Committed %d row updates.", len(updates))
    except Exception as exc:
        session.rollback()
        logger.error("Backfill failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
