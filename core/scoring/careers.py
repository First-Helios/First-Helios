"""
Careers API sub-score for ChainStaffingTracker scoring engine.

Fixes the broken scoring model that produced 87% "critical" scores by:
  1. Age decay — fresh postings carry full weight, stale ones decay to zero.
  2. Baseline-relative scoring — percentile rank vs regional norms, not absolute counts.

Depends on: config.loader (posting_age_decay, score_tiers)
Called by: backend/scoring/engine.py
"""

import logging
from datetime import datetime

from config.loader import get_posting_age_decay, get_score_tiers

logger = logging.getLogger(__name__)


def age_weight(days_old: int) -> float:
    """Compute decay weight for a job posting based on its age.

    A posting open for 90 days is a standing requisition (weight 0).
    A posting opened 3 days ago is a real signal (weight 1.0).

    Args:
        days_old: Number of days since the posting was first observed.

    Returns:
        Weight between 0.0 and 1.0.
    """
    decay = get_posting_age_decay()
    fresh = decay["fresh_days"]
    stale = decay["stale_days"]

    if days_old <= fresh:
        return 1.0
    if days_old >= stale:
        return 0.0
    return 1.0 - ((days_old - fresh) / (stale - fresh))


def weighted_listing_count(
    listings: list[dict],
    now: datetime | None = None,
) -> float:
    """Compute age-weighted effective listing count for a store.

    Each listing contributes its age_weight to the total. A store with
    2 stale standing requisitions scores ~0, while a store with 2 fresh
    postings scores ~2.0.

    Args:
        listings: List of dicts with at least 'observed_at' (datetime or ISO str)
                  and optionally 'posted_date'.
        now: Reference time (defaults to utcnow).

    Returns:
        Sum of age weights — the effective listing count.
    """
    if now is None:
        now = datetime.utcnow()

    total = 0.0
    for listing in listings:
        # Try posted_date first, fall back to observed_at
        posted = listing.get("posted_date") or listing.get("observed_at")
        if posted is None:
            total += 0.5  # unknown age — half weight
            continue

        if isinstance(posted, str):
            try:
                posted = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                total += 0.5
                continue

        # Make both naive for comparison
        if posted.tzinfo is not None:
            posted = posted.replace(tzinfo=None)

        days_old = max(0, (now - posted).days)
        total += age_weight(days_old)

    return total


def baseline_relative_score(
    store_count: float,
    regional_counts: list[float],
) -> float:
    """Score a store relative to regional norms (percentile rank).

    A store with 2 listings is unremarkable if the regional median is 2.
    It's notable (high score) if the median is 1.

    Args:
        store_count: This store's age-weighted listing count.
        regional_counts: Age-weighted counts for all stores in the region.

    Returns:
        Percentile score 0-100. 50.0 if insufficient data.
    """
    if len(regional_counts) < 3:
        return 50.0  # not enough data — neutral

    percentile = sum(
        1 for c in regional_counts if c <= store_count
    ) / len(regional_counts)
    return percentile * 100


def compute_careers_score(
    store_listings: dict[str, list[dict]],
) -> dict[str, dict]:
    """Compute careers API sub-scores for all stores in a region.

    Args:
        store_listings: Mapping of store_num -> list of listing metadata dicts.
                       Each listing dict should have 'observed_at' and/or 'posted_date'.

    Returns:
        Mapping of store_num -> {'value': float, 'tier': str, 'weighted_count': float}
    """
    now = datetime.utcnow()
    tiers_cfg = get_score_tiers()

    # Step 1: Compute age-weighted counts per store
    weighted_counts: dict[str, float] = {}
    for store_num, listings in store_listings.items():
        weighted_counts[store_num] = weighted_listing_count(listings, now)

    # Step 2: Compute baseline-relative scores
    all_counts = list(weighted_counts.values())
    results: dict[str, dict] = {}

    for store_num, wc in weighted_counts.items():
        score = baseline_relative_score(wc, all_counts)

        # Determine tier
        tier = "adequate"
        if score >= tiers_cfg["critical"]["min_percentile"]:
            tier = "critical"
        elif score >= tiers_cfg["elevated"]["min_percentile"]:
            tier = "elevated"

        results[store_num] = {
            "value": round(score, 2),
            "tier": tier,
            "weighted_count": round(wc, 2),
        }

    logger.info(
        "[CareersScore] Scored %d stores. Distribution: %s",
        len(results),
        _tier_distribution(results),
    )
    return results


def _tier_distribution(results: dict[str, dict]) -> dict[str, int]:
    """Count stores per tier for logging."""
    dist: dict[str, int] = {"critical": 0, "elevated": 0, "adequate": 0}
    for r in results.values():
        tier = r.get("tier", "unknown")
        dist[tier] = dist.get(tier, 0) + 1
    return dist
