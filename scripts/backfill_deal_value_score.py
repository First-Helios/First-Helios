#!/usr/bin/env python3
"""
scripts/backfill_deal_value_score.py — Compute deal_value_score for all rows.

Sets the deal_value_score column (0.0–1.0 offer strength) on every meal_deal
row that doesn't already have one, or on all rows when --all is passed.

  deal_value_score  measures *consumer value* of the offer
  signal_quality    measures *data completeness* of the record

Usage:
  PYTHONPATH=. python scripts/backfill_deal_value_score.py           # dry-run
  PYTHONPATH=. python scripts/backfill_deal_value_score.py --apply   # commit changes
  PYTHONPATH=. python scripts/backfill_deal_value_score.py --all --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from core.database import MealDeal, init_db, get_session
from collectors.meal_deals.quality import compute_deal_value_score

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill deal_value_score on meal_deals")
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes (default: dry-run)")
    parser.add_argument("--all", dest="all_rows", action="store_true",
                        help="Recompute even rows that already have a score")
    parser.add_argument("--active-only", action="store_true",
                        help="Only process is_active=True rows")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        q = session.query(MealDeal)
        if args.active_only:
            q = q.filter(MealDeal.is_active.is_(True))
        if not args.all_rows:
            q = q.filter(MealDeal.deal_value_score.is_(None))

        rows = q.all()
        logger.info("Rows to score: %d  (dry_run=%s)", len(rows), not args.apply)

        updated = 0
        tier_counts: Counter = Counter()

        for deal in rows:
            score = compute_deal_value_score(
                price=deal.price,
                price_type=deal.price_type,
                discount_percentage=deal.discount_percentage,
                deal_name=deal.deal_name,
                deal_description=deal.deal_description,
                raw_scraped_text=deal.raw_scraped_text,
            )

            if deal.deal_value_score != score:
                deal.deal_value_score = score
                updated += 1

            # Bucket into tiers for reporting
            if score >= 0.90:
                tier_counts["T5 (BOGO/95%+)"] += 1
            elif score >= 0.70:
                tier_counts["T4 (high value)"] += 1
            elif score >= 0.50:
                tier_counts["T3 (good value)"] += 1
            elif score >= 0.30:
                tier_counts["T2 (moderate)"] += 1
            elif score > 0.0:
                tier_counts["T1 (weak)"] += 1
            else:
                tier_counts["T0 (unknown)"] += 1

        logger.info("Score changes: %d", updated)
        logger.info("")
        logger.info("Tier distribution:")
        for tier, cnt in sorted(tier_counts.items()):
            logger.info("  %-22s %d", tier, cnt)

        if args.apply:
            session.commit()
            logger.info("")
            logger.info("Committed %d updates.", updated)
        else:
            session.rollback()
            logger.info("")
            logger.info("Dry-run — pass --apply to commit.")

        return 0
    except Exception as exc:
        session.rollback()
        logger.error("Failed: %s", exc, exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
