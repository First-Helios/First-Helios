#!/usr/bin/env python3
"""
scripts/one_shot/clean_nonfood_deals.py — Deactivate non-food / off-topic meal deals.

Targets deals that clearly don't belong in a restaurant deal feed:
  - Hotel/travel deals (stay discounts, per-night rates)
  - SaaS/software product deals (Linktree, app subscriptions)
  - Membership cards (AARP, AAA) used for hotel/travel discounts
  - Spam / gambling deals
  - Registration fees misidentified as deals
  - Implausibly high prices (> $150) with no menu context

Also handles ISSUE-001 (price_type=None despite price set):
  Rows where price IS NOT NULL and price_type IS NULL and no discount/percentage
  pattern is detectable → classified as price_type='absolute'.

Usage:
  PYTHONPATH=. python scripts/one_shot/clean_nonfood_deals.py            # dry-run
  PYTHONPATH=. python scripts/one_shot/clean_nonfood_deals.py --apply    # commit
  PYTHONPATH=. python scripts/one_shot/clean_nonfood_deals.py --apply --fix-price-type
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

from core.database import MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ── Non-food keyword patterns ────────────────────────────────────────────────

# Matches anywhere in deal_name or deal_description
_NONFOOD_SUBSTRINGS = [
    # Hotels / travel
    "per night", "off per night", "off your stay", "nights at participating",
    "nights or more", "book four nights", "hotel credit", "check in",
    "complimentary self-parking", "your travels", "spring getaway",
    "summer getaway", "aarp members save", "aaa members save",
    "where will your travels",
    # SaaS / software
    "linktree pro", "pro annual", "linktree",
    # Gambling / spam
    "wargatogel", "togel", "casino slot", "betting site",
    # Registration fees
    "to register", "registration fee",
    # Generic membership discounts used for non-food
    "save $5 off per night",
]

# Matches deal name exactly (after strip/lower)
_NONFOOD_EXACT = {
    "offer details",
    "save $5 off per night",
}

# Regex patterns for deal name/description
_NONFOOD_RE = re.compile(
    r"\b(?:hotel|motel|resort|inn\b|per\s+night|nights?\s+(?:at|or\s+more)|"
    r"off\s+your\s+stay|self.parking|linktree|wargatogel|togel|casino|"
    r"betting|aarp\s+members?|aaa\s+members?\s+save|to\s+register\b)\b",
    re.IGNORECASE,
)

# Price threshold above which a deal is likely not a food deal
_MAX_FOOD_PRICE = 150.0

# Patterns that indicate a discount_amount vs absolute confusion
_DISCOUNT_OFF_RE = re.compile(r"\$\s*\d+(?:\.\d{1,2})?\s*off\b", re.IGNORECASE)
_PCT_RE = re.compile(r"\d{1,3}\s*%\s*off|\bhalf\s+(?:off|price)\b|½", re.IGNORECASE)


def _is_nonfood(deal: MealDeal) -> tuple[bool, str]:
    """Return (True, reason) if the deal should be deactivated."""
    name = (deal.deal_name or "").strip()
    desc = (deal.deal_description or "").strip()
    combined = (name + " " + desc).lower()

    if name.lower() in _NONFOOD_EXACT:
        return True, f"exact junk name: {name!r}"

    if _NONFOOD_RE.search(combined):
        return True, f"non-food keyword in: {combined[:60]!r}"

    for sub in _NONFOOD_SUBSTRINGS:
        if sub in combined:
            return True, f"non-food substring {sub!r}"

    if deal.price and deal.price > _MAX_FOOD_PRICE:
        return True, f"price ${deal.price} > ${_MAX_FOOD_PRICE} threshold"

    return False, ""


def _should_fix_price_type(deal: MealDeal) -> bool:
    """Return True if this row should get price_type='absolute' as default."""
    if deal.price is None:
        return False
    if deal.price_type is not None and deal.price_type != "unknown":
        return False
    # Don't override if text contains discount/percentage patterns
    combined = " ".join(s for s in [deal.deal_name, deal.deal_description, deal.raw_scraped_text] if s)
    if _DISCOUNT_OFF_RE.search(combined) or _PCT_RE.search(combined):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Deactivate non-food deals; fix price_type")
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes (default: dry-run)")
    parser.add_argument("--fix-price-type", action="store_true",
                        help="Also classify price_type=NULL rows as 'absolute' (ISSUE-001)")
    parser.add_argument("--include-inactive", action="store_true",
                        help="Also check already-inactive rows")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        q = session.query(MealDeal)
        if not args.include_inactive:
            q = q.filter(MealDeal.is_active.is_(True))
        all_rows = q.all()

        logger.info("Scanning %d rows  (dry_run=%s)", len(all_rows), not args.apply)
        logger.info("")

        deactivated: list[tuple[int, str]] = []
        price_type_fixed = 0

        for deal in all_rows:
            is_bad, reason = _is_nonfood(deal)
            if is_bad:
                deal.is_active = False
                deactivated.append((deal.id, reason))

        if args.fix_price_type:
            # Scan all rows (including those just deactivated)
            all_for_pt = session.query(MealDeal).filter(
                MealDeal.price != None,  # noqa: E711
            ).all()
            for deal in all_for_pt:
                if _should_fix_price_type(deal):
                    deal.price_type = "absolute"
                    price_type_fixed += 1

        logger.info("Non-food deals to deactivate: %d", len(deactivated))
        for deal_id, reason in deactivated[:30]:
            logger.info("  id=%-6d  %s", deal_id, reason[:80])
        if len(deactivated) > 30:
            logger.info("  ... and %d more", len(deactivated) - 30)

        if args.fix_price_type:
            logger.info("")
            logger.info("price_type NULL→absolute fixes: %d", price_type_fixed)

        if args.apply:
            session.commit()
            logger.info("")
            logger.info("Committed: %d deactivated, %d price_type fixed.",
                        len(deactivated), price_type_fixed)
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
