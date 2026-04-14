#!/usr/bin/env python3
"""
scripts/purge_junk_deals.py — Remove low-quality meal deal rows from the database.

Applies the same quality filters now enforced at collection time to
retroactively clean rows that were ingested before the filters existed.

Categories of junk removed:
  1. Spam / ad injection (casino, gambling, pharma copy)
  2. Navigational boilerplate (footer, header, nav text)
  3. Deals with no semantic content (no price, no time/day, just a keyword echo)

Usage:
  PYTHONPATH=. python scripts/purge_junk_deals.py              # dry-run
  PYTHONPATH=. python scripts/purge_junk_deals.py --apply       # actually delete
"""

import argparse
import logging
import re
import sys
from datetime import datetime

from sqlalchemy import func

from core.database import MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Filters (mirrored from website_scraper.py) ──────────────────────────────

_SPAM_PHRASES = [
    "casino", "gambling", "gamstop", "slot machine",
    "poker", "roulette", "blackjack", "betting",
    "live dealer", "online casino", "sports betting",
    "erectile", "viagra", "cbd gummies",
    "crypto", "bitcoin", "nft",
]

_BOILERPLATE_PHRASES = [
    "privacy", "terms of use", "site map", "cookie",
    "toggle header", "toggle menu", "toggle nav",
    "newsroom", "gift card", "careers", "about us",
    "rewards", "sign in", "log in", "sign up",
    "download the app", "mobile app",
    "international sites", "franchise",
    "copyright", "all rights reserved",
    "skip to content", "skip to main",
    "open menu close menu",
    "locations specials jobs",
]

# Price pattern
_PRICE_RE = re.compile(r"\$\d{1,3}\.?\d{0,2}")
# Time pattern
_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.IGNORECASE)
# Day pattern
_DAY_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tue|wed|thu|fri|sat|sun"
    r"|mon-fri|mon-sat|mon-sun)\b",
    re.IGNORECASE,
)

_SELF_VALIDATING = {
    "bogo", "buy one get one", "buy one, get one",
    "kids eat free", "happy hour",
    "half off", "half price", "% off",
}

_DEAL_KEYWORDS = [
    "special", "specials", "deal", "deals", "combo", "bogo",
    "buy one", "happy hour", "kids eat free", "early bird",
    "lunch special", "dinner special", "daily special",
    "meal deal", "value meal", "discount",
    "limited time", "save", "promotion", "offer",
    "half off", "half price", "% off",
    "for the price of", "2 for",
]

# Word-boundary regex for keywords (prevents 'special' matching 'specialty')
_DEAL_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _DEAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Negative-context patterns — override deal keyword matches
_NEGATIVE_CONTEXT_PATTERNS = [
    re.compile(r"\bspecial\s+occasion", re.IGNORECASE),
    re.compile(r"\bno\s+substitution", re.IGNORECASE),
    re.compile(r"\bpre-?order\b", re.IGNORECASE),
    re.compile(r"\bskip\s+to\s+(?:content|main)", re.IGNORECASE),
    re.compile(r"open\s+menu.*close\s+menu", re.IGNORECASE),
]


def _is_junk(deal_name: str, deal_description: str | None, source: str = "") -> tuple[bool, str]:
    """Return (is_junk, reason) for a meal deal row."""
    text = f"{deal_name} {deal_description or ''}".strip()
    lower = text.lower()

    # 1. Spam / ad injection (always purge regardless of source)
    for sp in _SPAM_PHRASES:
        if sp in lower:
            return True, f"spam:{sp}"

    # 2. Navigation / boilerplate (always purge)
    for bp in _BOILERPLATE_PHRASES:
        if bp in lower:
            return True, f"boilerplate:{bp}"

    # For chain_website source, only purge spam + boilerplate above.
    # Chain deals already passed chain_deals.py quality filters.
    if source == "chain_website":
        return False, ""

    # 3. Negative context (overrides keywords)
    if any(pat.search(text) for pat in _NEGATIVE_CONTEXT_PATTERNS):
        return True, "negative_context"

    # 4. No deal keyword at all (word-boundary matched)
    has_keyword = bool(_DEAL_KEYWORD_RE.search(text))
    if not has_keyword:
        return True, "no_deal_keyword"

    # 5. Has keyword but no price and no self-validating phrase → junk
    if any(kw in lower for kw in _SELF_VALIDATING):
        return False, ""
    has_price = bool(_PRICE_RE.search(text))
    if has_price:
        return False, ""

    # Keyword only, no price → junk
    return True, "keyword_only_no_price"


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge junk meal deal rows")
    parser.add_argument("--apply", action="store_true", help="Actually delete rows (default is dry-run)")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        all_deals = session.query(MealDeal).all()
        logger.info("Total meal_deals rows: %d", len(all_deals))

        junk_ids: list[int] = []
        reasons: dict[str, int] = {}

        for deal in all_deals:
            is_junk, reason = _is_junk(deal.deal_name, deal.deal_description, deal.source)
            if is_junk:
                junk_ids.append(deal.id)
                reasons[reason] = reasons.get(reason, 0) + 1
                logger.info(
                    "  JUNK [%s] id=%d name=%r",
                    reason, deal.id, deal.deal_name[:60],
                )

        logger.info("")
        logger.info("Junk breakdown:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            logger.info("  %-35s %d", reason, count)
        logger.info("  %-35s %d", "TOTAL JUNK", len(junk_ids))
        logger.info("  %-35s %d", "CLEAN (keeping)", len(all_deals) - len(junk_ids))

        if not junk_ids:
            logger.info("No junk found. Database is clean.")
            return

        if args.apply:
            deleted = session.query(MealDeal).filter(
                MealDeal.id.in_(junk_ids)
            ).delete(synchronize_session="fetch")
            session.commit()
            logger.info("\nDELETED %d junk rows.", deleted)
        else:
            logger.info(
                "\nDRY RUN: Would delete %d rows. Re-run with --apply to execute.",
                len(junk_ids),
            )
    except Exception as exc:
        session.rollback()
        logger.error("Failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
