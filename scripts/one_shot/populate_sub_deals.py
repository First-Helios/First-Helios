#!/usr/bin/env python3
"""
scripts/populate_sub_deals.py — Populate meal_deals.sub_deals from raw text.

For every active row with non-empty raw_scraped_text OR deal_description,
run `extract_sub_deals()` and persist the result.  Rows whose text doesn't
decompose into ≥2 offers are skipped (sub_deals stays NULL).

Usage:
  PYTHONPATH=. python scripts/populate_sub_deals.py            # dry-run
  PYTHONPATH=. python scripts/populate_sub_deals.py --apply    # commit
  PYTHONPATH=. python scripts/populate_sub_deals.py --apply --all  # include inactive rows too
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from sqlalchemy import or_

from collectors.meal_deals.sub_deals import extract_sub_deals
from core.database import MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate meal_deals.sub_deals JSONB")
    parser.add_argument("--apply", action="store_true", help="Commit changes")
    parser.add_argument("--all", action="store_true",
                        help="Process inactive rows too (default: active only)")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        q = session.query(MealDeal).filter(
            or_(
                MealDeal.raw_scraped_text.isnot(None),
                MealDeal.deal_description.isnot(None),
            )
        )
        if not args.all:
            q = q.filter(MealDeal.is_active.is_(True))
        rows = q.all()
        logger.info("Scanning %d rows for sub_deals.", len(rows))

        updates: list[tuple[MealDeal, list[dict]]] = []
        sub_count_dist: Counter[int] = Counter()

        for deal in rows:
            text = deal.raw_scraped_text or deal.deal_description or ""
            subs = extract_sub_deals(text)
            if not subs:
                continue

            # Skip if unchanged
            if deal.sub_deals == subs:
                continue

            updates.append((deal, subs))
            sub_count_dist[len(subs)] += 1

        # Report
        logger.info("")
        logger.info("Sub-deal extraction plan:")
        logger.info("  %-30s %d", "rows to update", len(updates))
        logger.info("  %-30s %d", "sub_deal count distribution:", 0)
        for count, n in sorted(sub_count_dist.items()):
            logger.info("    %d sub_deals: %d rows", count, n)

        if updates:
            logger.info("")
            logger.info("Sample updates (first 5):")
            for deal, subs in updates[:5]:
                logger.info(
                    "  id=%d name=%r",
                    deal.id, (deal.deal_name or "")[:50],
                )
                for s in subs[:4]:
                    logger.info("    %s", s)

        if not args.apply:
            logger.info("")
            logger.info("DRY RUN — no changes written.  Re-run with --apply to commit.")
            return

        for deal, subs in updates:
            deal.sub_deals = subs

        session.commit()
        logger.info("")
        logger.info("Committed: %d rows updated with sub_deals.", len(updates))
    except Exception as exc:
        session.rollback()
        logger.error("Population failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
