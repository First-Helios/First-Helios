#!/usr/bin/env python3
"""
scripts/detect_cross_employer_leaks.py — Flag deals whose text explicitly
names a *different* restaurant than the employer they're assigned to.

Known real examples:
  - Freddie's Place deal text mentions "Fresa's Happy Hour"
  - Barton BBQ deal text mentions "Green Mesquite BBQ"

Strategy (high-precision):
  Only check against employers that actually have meal deals in our DB
  (typically ~200-500 rows, vs 45K total employers).  The employer name
  must appear as a ≥2-word phrase (or a ≥8-char single distinctive word)
  verbatim in the deal text.

Confidence:
  high   — foreign employer's name found AND this employer's name absent
  medium — both names found (shared promo copy, may be legit)

Usage:
  PYTHONPATH=. python scripts/detect_cross_employer_leaks.py
  PYTHONPATH=. python scripts/detect_cross_employer_leaks.py --apply
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict

from sqlalchemy import distinct

from core.database import LocalEmployer, MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_GENERIC = {
    # Restaurant types
    "bar", "grill", "grille", "cafe", "kitchen", "tavern", "bbq", "pizza",
    "sub", "subs", "restaurant", "house", "place", "room", "shop", "bistro",
    "deli", "diner", "eatery", "food", "eats", "express", "fresh", "local",
    "pub", "cantina", "group", "bakery", "sushi", "ramen", "tacos", "taco",
    "wings", "burger", "burgers", "steak", "steaks", "chicken", "coffee",
    "tea", "wine", "brewing", "taproom", "donuts", "kebab", "kabob",
    "pies", "pie", "counter", "corner", "table", "main", "original",
    "classic", "market", "lounge", "hall", "garden", "patio", "yard",
    # Corporate suffixes
    "inc", "llc", "corp", "company", "group",
    # Locations
    "texas", "austin", "north", "south", "east", "west", "central",
    "downtown", "domain", "atx", "street", "avenue", "road", "blvd",
    # Cuisines
    "american", "mexican", "italian", "chinese", "thai", "japanese",
    "indian", "mediterranean", "french", "greek", "korean", "vietnamese",
    # Menu/deal words that appear in employer names but also in every deal
    "cocktails", "cocktail", "drinks", "drink", "draft", "drafts",
    "starters", "appetizers", "specials", "special", "deals", "deal",
    "happy", "hour", "lunch", "dinner", "brunch", "breakfast",
    "price", "prices", "discount", "discounts", "offer", "offers",
    "free", "half", "percent", "daily", "weekly", "night", "nights",
    "thank", "enjoy", "welcome", "visit", "choose", "first", "order",
    "your", "with", "from", "about", "into", "this", "that", "here",
    "more", "best", "great", "good", "love", "take", "join",
}

_TOKEN_RE = re.compile(r"[a-z0-9'&]+")


def _clean(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"\s*[-–|]\s*.*$", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _matchable_phrases(clean_name: str) -> list[str]:
    """Return the cleaned full name + 2-word substrings (both words ≥ 5 chars)."""
    phrases: list[str] = []
    words = clean_name.split()

    # Full name if ≥ 2 non-generic words each ≥ 4 chars
    non_gen = [w.strip("'&") for w in words if w.strip("'&") not in _GENERIC and len(w.strip("'&")) >= 4]
    if len(non_gen) >= 2 and len(clean_name) >= 8:
        phrases.append(clean_name)

    # 2-word phrases where both words are ≥ 5 chars and not generic
    for i in range(len(words) - 1):
        w1 = words[i].strip("'&")
        w2 = words[i + 1].strip("'&")
        if (len(w1) >= 5 and w1 not in _GENERIC
                and len(w2) >= 5 and w2 not in _GENERIC):
            phrases.append(f"{words[i]} {words[i+1]}")

    return list(dict.fromkeys(phrases))  # deduplicate, preserve order


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect cross-employer content leaks")
    parser.add_argument("--apply", action="store_true",
                        help="Set is_active=False on high-confidence leaks")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        # Only build phrase index from employers that have at least one deal
        deal_employer_ids: set[int] = {
            row[0] for row in
            session.query(distinct(MealDeal.local_employer_id))
            .filter(MealDeal.local_employer_id.isnot(None))
            .all()
        }
        logger.info("%d employers have at least one deal.", len(deal_employer_ids))

        employers_with_deals = (
            session.query(LocalEmployer)
            .filter(LocalEmployer.id.in_(deal_employer_ids))
            .all()
        )

        emp_clean: dict[int, str] = {}
        emp_phrases: dict[int, list[str]] = {}

        # phrase → [employer_id list]
        phrase_owners: dict[str, list[int]] = defaultdict(list)

        for emp in employers_with_deals:
            c = _clean(emp.name or "")
            emp_clean[emp.id] = c
            phrases = _matchable_phrases(c)
            emp_phrases[emp.id] = phrases
            for p in phrases:
                phrase_owners[p].append(emp.id)

        # Drop phrases shared by ≥ 4 employers (still too generic)
        phrase_index = {p: owners for p, owners in phrase_owners.items()
                        if 1 <= len(owners) <= 3}

        logger.info("Phrase index: %d phrases across %d employers.", len(phrase_index), len(employers_with_deals))

        # Scan deals
        rows = (
            session.query(MealDeal, LocalEmployer)
            .join(LocalEmployer, MealDeal.local_employer_id == LocalEmployer.id)
            .filter(MealDeal.is_active.is_(True))
            .all()
        )
        logger.info("Scanning %d active deals...", len(rows))

        high_conf: list[tuple[MealDeal, LocalEmployer, list[str]]] = []
        medium_conf: list[tuple[MealDeal, LocalEmployer, list[str]]] = []

        for deal, emp in rows:
            text = " ".join(filter(None, (
                deal.deal_name, deal.deal_description, deal.raw_scraped_text,
            ))).lower()
            if not text or len(text) < 15:
                continue

            foreign_hits: list[str] = []
            for phrase, owners in phrase_index.items():
                if phrase not in text:
                    continue
                other_ids = [oid for oid in owners if oid != emp.id]
                if not other_ids:
                    continue
                foreign_hits.append(phrase)

            if not foreign_hits:
                continue

            own_clean = emp_clean.get(emp.id, "")
            own_in_text = bool(own_clean) and own_clean in text

            if own_in_text:
                medium_conf.append((deal, emp, foreign_hits))
            else:
                high_conf.append((deal, emp, foreign_hits))

        logger.info("")
        logger.info("Cross-employer leak report:")
        logger.info("  %-30s %d", "high confidence leaks", len(high_conf))
        logger.info("  %-30s %d", "medium confidence (ambiguous)", len(medium_conf))

        if high_conf:
            logger.info("")
            logger.info("High-confidence leaks:")
            for deal, emp, hits in high_conf:
                logger.info(
                    "  id=%d emp=%r\n    name=%r\n    foreign phrases: %r",
                    deal.id, (emp.name or "")[:40],
                    (deal.deal_name or "")[:70], hits[:4],
                )

        if medium_conf:
            logger.info("")
            logger.info("Medium-confidence (first 10):")
            for deal, emp, hits in medium_conf[:10]:
                logger.info(
                    "  id=%d emp=%r name=%r  foreign: %r",
                    deal.id, (emp.name or "")[:30],
                    (deal.deal_name or "")[:50], hits[:2],
                )

        if not args.apply:
            logger.info("")
            logger.info("DRY RUN. Re-run with --apply to deactivate high-conf leaks.")
            return

        deactivated = 0
        for deal, _, _ in high_conf:
            if deal.is_active is not False:
                deal.is_active = False
                deactivated += 1

        session.commit()
        logger.info("Committed: %d high-confidence leaks deactivated.", deactivated)
    except Exception as exc:
        session.rollback()
        logger.error("Detection failed: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
