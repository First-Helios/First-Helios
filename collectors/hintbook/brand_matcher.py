"""Brand-vocabulary matcher for hintbook replay.

Loads canonical brand names from the production `brand_groups` table (and
optionally from `config/chains.yaml`) and exposes a strict matcher that
replaces the weak heuristic in `collectors.hintbook.parsing.normalize_brand_hint`.

Design notes
------------
- Read-only. No writes to DB.
- Loaded once per process; safe to reuse across many bundles.
- Word-boundary, case-insensitive matching on the concatenation of
  headline + body_excerpt.
- Returns the single highest-confidence canonical brand fingerprint per
  record (not a list). Ties broken by (a) headline presence, then (b)
  length of brand name (longer = more specific), then (c) alpha order.

This matcher is a quality-check helper only. It never marks a record as
ingest-eligible first-party evidence.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

logger = logging.getLogger(__name__)

_MIN_LOCATION_COUNT = 3
_SKIP_TOKENS = {"store", "shop", "restaurant", "pharmacy", "atm", "bank", "station", "location"}


@dataclass(frozen=True)
class BrandVocabEntry:
    canonical_name: str
    slug: str
    industry: str | None
    location_count: int


@dataclass(frozen=True)
class BrandMatch:
    slug: str
    canonical_name: str
    industry: str | None
    hits_in_headline: int
    hits_total: int


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


_SMART_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def _normalize_quotes(text: str) -> str:
    return (text or "").translate(_SMART_QUOTES)


def load_brand_vocab_from_db(
    min_location_count: int = _MIN_LOCATION_COUNT,
) -> list[BrandVocabEntry]:
    """Load brand_groups rows with sufficient footprint."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("psycopg is required to load brand vocabulary") from exc

    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set; cannot load brand vocabulary")

    vocab: list[BrandVocabEntry] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT canonical_name, industry, location_count
            FROM brand_groups
            WHERE location_count >= %s
              AND canonical_name IS NOT NULL
              AND length(canonical_name) >= 3
            ORDER BY location_count DESC
            """,
            (min_location_count,),
        )
        for canonical_name, industry, location_count in cur.fetchall():
            slug = _slugify(canonical_name)
            if not slug or slug in _SKIP_TOKENS:
                continue
            vocab.append(
                BrandVocabEntry(
                    canonical_name=canonical_name,
                    slug=slug,
                    industry=industry,
                    location_count=int(location_count),
                )
            )
    return vocab


@lru_cache(maxsize=1)
def _default_vocab() -> tuple[BrandVocabEntry, ...]:
    try:
        entries = load_brand_vocab_from_db()
    except Exception as exc:
        logger.warning("brand_matcher: DB vocab load failed (%s); falling back to empty vocab", exc)
        return tuple()
    return tuple(entries)


def _compile_pattern(name: str) -> re.Pattern[str]:
    # Escape, then allow flexible whitespace + optional apostrophes within tokens.
    # e.g. "Papa Johns Pizza" matches "Papa John's Pizza" and "Papa Johns Pizza".
    tokens = re.split(r"\s+", name.strip())
    parts = [re.escape(tok).replace(r"\'", "'?").replace("'", "'?") for tok in tokens]
    inner = r"\s+".join(parts)
    # Word boundary ONLY at the edges; internal apostrophes already relaxed.
    return re.compile(rf"\b{inner}\b", re.IGNORECASE)


@lru_cache(maxsize=2048)
def _pattern_for(canonical_name: str) -> re.Pattern[str]:
    return _compile_pattern(canonical_name)


def match_brand_in_text(
    *,
    headline: str,
    body: str,
    vocab: Iterable[BrandVocabEntry] | None = None,
) -> BrandMatch | None:
    """Return the highest-confidence brand match across (headline, body)."""
    entries = tuple(vocab) if vocab is not None else _default_vocab()
    if not entries:
        return None

    head = _normalize_quotes(headline or "")
    total = f"{head}\n{_normalize_quotes(body or '')}"

    best: BrandMatch | None = None
    for entry in entries:
        pattern = _pattern_for(entry.canonical_name)
        total_hits = len(pattern.findall(total))
        if total_hits == 0:
            continue
        head_hits = len(pattern.findall(head))
        candidate = BrandMatch(
            slug=entry.slug,
            canonical_name=entry.canonical_name,
            industry=entry.industry,
            hits_in_headline=head_hits,
            hits_total=total_hits,
        )
        if best is None or _candidate_wins(candidate, best, entry_len=len(entry.canonical_name)):
            best = candidate
    return best


def _candidate_wins(cand: BrandMatch, cur: BrandMatch, *, entry_len: int) -> bool:
    # Prefer headline presence first, then more total hits, then longer canonical name.
    if cand.hits_in_headline != cur.hits_in_headline:
        return cand.hits_in_headline > cur.hits_in_headline
    if cand.hits_total != cur.hits_total:
        return cand.hits_total > cur.hits_total
    return len(cand.canonical_name) > len(cur.canonical_name)
