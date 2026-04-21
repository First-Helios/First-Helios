#!/usr/bin/env python3
"""
scripts/backfill_signal_quality.py — Compute signal_quality + apply
is_active gating to existing meal_deal rows.

Safe to run repeatedly.  Dry-run by default.  Uses the same scoring logic
as the ingest pipeline (collectors/meal_deals/quality.py) so row scores
stay consistent with new data.

Usage:
  PYTHONPATH=. python scripts/backfill_signal_quality.py             # dry-run
  PYTHONPATH=. python scripts/backfill_signal_quality.py --apply     # commit
  PYTHONPATH=. python scripts/backfill_signal_quality.py --apply \\
      --deactivate-review                    # also set is_active=False
                                             # for rows in the review band
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from core.database import LocalEmployer, MealDeal, init_db, get_session
from collectors.meal_deals.quality import compute_signal_quality, gate_decision

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill signal_quality on meal_deals")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument(
        "--deactivate-review",
        action="store_true",
        help="Also set is_active=False for rows scoring in the review band (0.20–0.40)",
    )
    parser.add_argument(
        "--deactivate-reject",
        action="store_true",
        help="Also set is_active=False for rows scoring below 0.20 (default: True when --apply)",
    )
    args = parser.parse_args()

    # Default: when writing, deactivate rejects
    if args.apply and not args.deactivate_reject:
        args.deactivate_reject = True

    engine = init_db()
    session = get_session(engine)

    try:
        # Join with local_employer so we can supply restaurant_name to the scorer
        rows = (
            session.query(MealDeal, LocalEmployer.name)
            .outerjoin(LocalEmployer, MealDeal.local_employer_id == LocalEmployer.id)
            .all()
        )
        total = len(rows)
        logger.info("Scoring %d meal_deal rows...", total)

        decision_counts: Counter[str] = Counter()
        quality_changed = 0
        is_active_changed = 0
        sample_low: list[tuple[int, float, str]] = []

        for deal, emp_name in rows:
            q = compute_signal_quality(
                deal_name=deal.deal_name,
                deal_description=deal.deal_description,
                price=deal.price,
                price_type=deal.price_type,
                discount_percentage=deal.discount_percentage,
                valid_days=deal.valid_days,
                valid_start_time=deal.valid_start_time,
                valid_end_time=deal.valid_end_time,
                restaurant_name=emp_name,
                raw_scraped_text=deal.raw_scraped_text,
            )
            decision, _ = gate_decision(q.total)
            decision_counts[decision] += 1

            # Record score change
            prev_quality = deal.signal_quality
            if prev_quality != q.total:
                quality_changed += 1

            # Decide new is_active
            new_is_active: bool | None = None
            if decision == "reject" and args.deactivate_reject:
                new_is_active = False
            elif decision == "review" and args.deactivate_review:
                new_is_active = False
            elif decision == "active":
                # Don't force reactivation — respect manual deactivations
                pass

            if args.apply:
                deal.signal_quality = q.total
                if new_is_active is not None and deal.is_active is not False:
                    if deal.is_active != new_is_active:
                        deal.is_active = new_is_active
                        is_active_changed += 1

            if decision != "active" and len(sample_low) < 10:
                sample_low.append((
                    deal.id, q.total, (deal.deal_name or "")[:60]
                ))

        logger.info("")
        logger.info("Decision breakdown:")
        for key in ("reject", "review", "active"):
            n = decision_counts.get(key, 0)
            pct = 100.0 * n / total if total else 0.0
            logger.info("  %-8s %6d  (%.1f%%)", key, n, pct)

        logger.info("")
        logger.info("Changes:")
        logger.info("  %-30s %d", "signal_quality updated", quality_changed)
        logger.info("  %-30s %d", "is_active deactivated", is_active_changed)

        if sample_low:
            logger.info("")
            logger.info("Sample low-scoring rows:")
            for rid, score, name in sample_low:
                logger.info("  id=%d score=%.2f name=%r", rid, score, name)

        if not args.apply:
            logger.info("")
            logger.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        session.commit()
        logger.info("")
        logger.info("Committed %d quality updates (%d deactivations).",
                    quality_changed, is_active_changed)
    except Exception as exc:
        session.rollback()
        logger.error("Backfill failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
