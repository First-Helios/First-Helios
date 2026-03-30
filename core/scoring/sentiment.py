"""
Sentiment sub-score for ChainStaffingTracker scoring engine.

Combines Reddit sentiment signals and Google Maps/Yelp review scores
into a single sentiment sub-score per store.

Depends on: config.loader
Called by: backend/scoring/engine.py
"""

import logging

from config.loader import get_score_tiers

logger = logging.getLogger(__name__)


def compute_sentiment_score(
    store_signals: dict[str, list[dict]],
) -> dict[str, dict]:
    """Compute sentiment sub-scores for all stores.

    Each signal dict should have:
      - 'signal_type': 'sentiment' or 'review_score'
      - 'value': float (0-1 for sentiment, 1-5 for reviews)
      - 'source': 'reddit', 'google_maps', 'yelp'

    Strategy:
      - Reddit sentiment: average of keyword scores (0=positive, 1=negative/stressed)
      - Review scores: inverted (lower rating = higher stress signal)
      - Combined into a 0-100 score (higher = more stress)

    Args:
        store_signals: Mapping of store_num -> list of sentiment/review signal dicts.

    Returns:
        Mapping of store_num -> {'value': float, 'tier': str}
    """
    tiers_cfg = get_score_tiers()
    all_scores: list[float] = []
    raw_scores: dict[str, float] = {}

    for store_num, signals in store_signals.items():
        if not signals:
            raw_scores[store_num] = 50.0
            continue

        sentiment_values: list[float] = []
        review_values: list[float] = []

        for sig in signals:
            sig_type = sig.get("signal_type", "")
            value = sig.get("value", 0.0)

            if sig_type == "sentiment":
                # Sentiment: 0-1 scale where 1 = high stress
                sentiment_values.append(value)
            elif sig_type == "review_score":
                # Review: 1-5 scale, invert so low rating = high stress
                # Convert to 0-1 where 1 = high stress
                inverted = max(0.0, min(1.0, 1.0 - ((value - 1.0) / 4.0)))
                review_values.append(inverted)

        # Combine: average all values
        all_values = sentiment_values + review_values
        if all_values:
            avg = sum(all_values) / len(all_values)
            raw_scores[store_num] = avg * 100  # Scale to 0-100
        else:
            raw_scores[store_num] = 50.0  # neutral if no data

    # Percentile-relative scoring
    all_raw = list(raw_scores.values())
    results: dict[str, dict] = {}

    for store_num, raw in raw_scores.items():
        # Use percentile within region
        if len(all_raw) >= 3:
            percentile = sum(1 for v in all_raw if v <= raw) / len(all_raw) * 100
        else:
            percentile = raw

        tier = "adequate"
        if percentile >= tiers_cfg["critical"]["min_percentile"]:
            tier = "critical"
        elif percentile >= tiers_cfg["elevated"]["min_percentile"]:
            tier = "elevated"

        results[store_num] = {
            "value": round(percentile, 2),
            "tier": tier,
        }

    logger.info(
        "[SentimentScore] Scored %d stores",
        len(results),
    )
    return results
