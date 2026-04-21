#!/usr/bin/env python3
"""
scripts/cleanup_meal_deals.py — One-time data cleanup for meal_deals.

Implements plan item L:
  1. Delete $0.00 deals.
  2. Delete sub-$1.00 non-food deals (add-on prices masquerading as deals).
  3. Delete nav / boilerplate deals that slipped past the junk filter.
  4. Delete TCBY J.Crew retail leak (apparel/clearance in food rows).
  5. Delete event/spam promos ("$1,500 off event booking").
  6. Reclassify unknown-price_type discount rows ("$X off") → discount_amount.
  7. Reclassify unknown-price_type percentage rows ("half off") → percentage_off + discount_percentage.

Safe to run repeatedly.  Dry-run by default.

Usage:
  PYTHONPATH=. python scripts/cleanup_meal_deals.py           # dry-run
  PYTHONPATH=. python scripts/cleanup_meal_deals.py --apply   # commit
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict

from sqlalchemy import or_, and_

from core.database import LocalEmployer, MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ── Patterns ────────────────────────────────────────────────────────────────

_FOOD_KW_RE = re.compile(
    r"\b(?:wing|wings|taco|tacos|slider|sliders|nugget|nuggets|fry|fries"
    r"|oyster|oysters|shrimp|dumpling|dumplings|pierogi|pierogies"
    r"|egg\s+roll|spring\s+roll|corn\s+dog|mozzarella\s+stick"
    r"|bone[- ]?in|boneless)\b",
    re.IGNORECASE,
)

_NAV_JUNK_PATTERNS = [
    r"^\s*main navigation\s*$",
    r"^\s*select a location\b",
    r"^\s*values\s*$",
    r"^\s*what we value\s*$",
    r"^\s*values in action\s*$",
    r"^\s*wanna save",
    r"^\s*check out how you can save",
    r"^\s*who doesn['\u2019]?t love a good deal",
    r"^\s*international sites",
    r"^\s*open menu close menu",
    r"^\s*learn more",
    r"^\s*skip to",
]

_RETAIL_KW_RE = re.compile(
    r"\b(?:clearance|apparel|clothing|accessories|jewelry|j\.?\s*crew|outerwear|denim|sweater|dress\s+shirt)\b",
    re.IGNORECASE,
)

_EVENT_SPAM_RE = re.compile(
    r"\b(?:book\s+(?:a|an|your)\s+(?:event|party|venue)"
    r"|catering\s+package"
    r"|private\s+dining\s+package"
    r"|rehearsal\s+dinner"
    r"|\$\d[\d,]{2,}\s+off\s+(?:when|event|booking))\b",
    re.IGNORECASE,
)

_DOLLAR_OFF_RE = re.compile(r"\$\s*\d+(?:\.\d{2})?\s*off", re.IGNORECASE)
_PERCENT_OFF_RE = re.compile(
    r"(?:(\d{1,2})%\s*off)|(?:half\s*(?:off|price))|(?:½\s*(?:off|price))",
    re.IGNORECASE,
)


def _matches_nav_junk(name: str | None) -> bool:
    if not name:
        return False
    low = name.strip().lower()
    return any(re.match(p, low) for p in _NAV_JUNK_PATTERNS)


def _is_sub_dollar_non_food(deal: MealDeal) -> bool:
    if deal.price is None or deal.price <= 0 or deal.price >= 1.00:
        return False
    # Allow if food keyword present
    text = " ".join(filter(None, (deal.deal_name, deal.deal_description, deal.raw_scraped_text)))
    return not _FOOD_KW_RE.search(text)


def _is_retail_leak(deal: MealDeal, employer_name: str | None) -> bool:
    # TCBY / dessert chains don't sell apparel — if the deal mentions retail it's a leak.
    if not employer_name:
        return False
    if not re.search(r"\b(tcby|frozen yogurt|ice cream|ice-cream|dessert|bakery)\b", employer_name, re.IGNORECASE):
        return False
    text = " ".join(filter(None, (deal.deal_name, deal.deal_description, deal.raw_scraped_text)))
    return bool(_RETAIL_KW_RE.search(text))


def _is_event_spam(deal: MealDeal) -> bool:
    text = " ".join(filter(None, (deal.deal_name, deal.deal_description, deal.raw_scraped_text)))
    return bool(_EVENT_SPAM_RE.search(text))


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up junk rows in meal_deals")
    parser.add_argument("--apply", action="store_true", help="Commit changes")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        rows = (
            session.query(MealDeal, LocalEmployer.name)
            .outerjoin(LocalEmployer, MealDeal.local_employer_id == LocalEmployer.id)
            .all()
        )
        logger.info("Loaded %d meal_deals rows.", len(rows))

        # Buckets
        to_delete: dict[str, list[MealDeal]] = defaultdict(list)
        to_reclass: list[tuple[MealDeal, dict]] = []

        for deal, emp_name in rows:
            # ── Deletion buckets ────────────────────────────────────────────
            if deal.price is not None and deal.price == 0.00:
                to_delete["$0.00 deals"].append(deal)
                continue
            if _is_sub_dollar_non_food(deal):
                to_delete["sub-$1 non-food"].append(deal)
                continue
            if _matches_nav_junk(deal.deal_name):
                to_delete["nav / boilerplate"].append(deal)
                continue
            if _is_retail_leak(deal, emp_name):
                to_delete["retail leak"].append(deal)
                continue
            if _is_event_spam(deal):
                to_delete["event / venue spam"].append(deal)
                continue

            # ── Reclassification (price_type correction) ────────────────────
            text = " ".join(filter(None, (deal.deal_name, deal.deal_description, deal.raw_scraped_text)))
            if (deal.price_type is None or deal.price_type == "unknown") and deal.price is not None:
                if _DOLLAR_OFF_RE.search(text):
                    to_reclass.append((deal, {"price_type": "discount_amount"}))
                    continue

            pct = _PERCENT_OFF_RE.search(text)
            if pct and (deal.discount_percentage is None or deal.price_type != "percentage_off"):
                pct_val = float(pct.group(1)) if pct.group(1) else 50.0
                changes = {}
                if deal.discount_percentage != pct_val:
                    changes["discount_percentage"] = pct_val
                if deal.price_type != "percentage_off":
                    changes["price_type"] = "percentage_off"
                if changes:
                    to_reclass.append((deal, changes))

        # Report
        logger.info("")
        logger.info("Deletion plan:")
        total_del = 0
        for bucket, items in to_delete.items():
            logger.info("  %-25s %d", bucket, len(items))
            total_del += len(items)
        logger.info("  %-25s %d", "TOTAL DELETIONS", total_del)

        logger.info("")
        logger.info("Reclassification plan: %d rows", len(to_reclass))

        # Samples
        logger.info("")
        logger.info("Sample deletions:")
        for bucket, items in to_delete.items():
            if items:
                d = items[0]
                logger.info(
                    "  [%s] id=%d name=%r price=%s",
                    bucket, d.id, (d.deal_name or "")[:50], d.price,
                )

        if to_reclass:
            logger.info("")
            logger.info("Sample reclassifications:")
            for deal, changes in to_reclass[:5]:
                logger.info("  id=%d name=%r  ->  %s", deal.id, (deal.deal_name or "")[:50], changes)

        if not args.apply:
            logger.info("")
            logger.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        # Apply deletions
        for items in to_delete.values():
            for d in items:
                session.delete(d)

        # Apply reclassifications
        for deal, changes in to_reclass:
            for col, val in changes.items():
                setattr(deal, col, val)

        session.commit()
        logger.info("")
        logger.info("Committed: %d deletions, %d reclassifications.",
                    total_del, len(to_reclass))
    except Exception as exc:
        session.rollback()
        logger.error("Cleanup failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
