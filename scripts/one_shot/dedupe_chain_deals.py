#!/usr/bin/env python3
"""
scripts/dedupe_chain_deals.py — Collapse chain-deal fan-out duplicates.

For every distinct (brand_group_id, deal_name, source) where source is a
chain source and multiple rows exist (one per location), we:

  1. Pick one "template" row (the one with the highest signal_quality,
     breaking ties by lowest id for stability).
  2. Clear its local_employer_id (now nullable) and set is_chain_template=True.
  3. Delete the other fan-out copies for that group.

Queries that want per-location chain deals should JOIN on brand_group_id:

    SELECT md.*, le.id AS location_id, le.name
    FROM meal_deals md
    JOIN local_employers le
      ON le.brand_group_id = md.brand_group_id
      AND le.region = md.region
    WHERE md.is_chain_template = TRUE;

Safe to run repeatedly (re-selects template of already-deduped groups).
Dry-run by default; --apply commits.

Usage:
  PYTHONPATH=. python scripts/dedupe_chain_deals.py           # dry-run
  PYTHONPATH=. python scripts/dedupe_chain_deals.py --apply   # commit
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

from sqlalchemy import or_

from core.database import MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Sources that fan out per-location and should be collapsed into templates
_CHAIN_SOURCES = ("chain_website",)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate chain-deal fan-out rows")
    parser.add_argument("--apply", action="store_true", help="Commit changes")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        rows = (
            session.query(MealDeal)
            .filter(MealDeal.source.in_(_CHAIN_SOURCES))
            .filter(MealDeal.brand_group_id.isnot(None))
            .all()
        )
        logger.info("Loaded %d chain_website rows with brand_group_id set.", len(rows))

        # Group by (brand_group_id, deal_name, source)
        groups: dict[tuple, list[MealDeal]] = defaultdict(list)
        for r in rows:
            key = (r.brand_group_id, r.deal_name, r.source)
            groups[key].append(r)

        logger.info("%d unique (brand_group, deal_name, source) groups.", len(groups))

        templates_created = 0
        rows_to_delete: list[MealDeal] = []
        rows_to_promote: list[MealDeal] = []  # becomes template
        sample: list[tuple[int, str, int, int]] = []

        for key, items in groups.items():
            # Already deduped?  (single row and already a template)
            if len(items) == 1 and items[0].is_chain_template:
                continue

            # Pick the template: highest signal_quality, then lowest id.
            items_sorted = sorted(
                items,
                key=lambda r: (-(r.signal_quality or 0.0), r.id),
            )
            template = items_sorted[0]
            others = items_sorted[1:]

            rows_to_promote.append(template)
            rows_to_delete.extend(others)
            templates_created += 1

            if len(sample) < 10:
                sample.append((
                    template.brand_group_id, template.deal_name,
                    len(items), len(others),
                ))

        logger.info("")
        logger.info("Plan:")
        logger.info("  %-35s %d", "templates to create / update", len(rows_to_promote))
        logger.info("  %-35s %d", "duplicate rows to delete", len(rows_to_delete))

        if sample:
            logger.info("")
            logger.info("Sample groups:")
            for bgid, name, total, delete_count in sample:
                logger.info("  brand_group=%d %r: %d rows → 1 template + %d deletions",
                            bgid, (name or "")[:50], total, delete_count)

        if not args.apply:
            logger.info("")
            logger.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        # Apply: promote templates first, then delete the duplicates.
        for t in rows_to_promote:
            t.is_chain_template = True
            t.local_employer_id = None
            t.lat = None
            t.lng = None

        session.flush()

        for d in rows_to_delete:
            session.delete(d)

        session.commit()
        logger.info("")
        logger.info("Committed: %d templates, %d duplicates deleted.",
                    len(rows_to_promote), len(rows_to_delete))
    except Exception as exc:
        session.rollback()
        logger.error("Dedup failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
