"""
Wage gap sub-score for ChainStaffingTracker scoring engine.

Compares chain wages to local employer wages for the same industry/role.
Higher gap (locals pay more) = higher score = better job fair target.

Depends on: config.loader, backend.database (WageIndex)
Called by: backend/scoring/engine.py
"""

import logging

from config.loader import get_score_tiers

logger = logging.getLogger(__name__)


def compute_wage_score(
    chain_wages: dict[str, dict],
    local_avg_wage: float | None = None,
) -> dict[str, dict]:
    """Compute wage gap sub-scores for stores in a region.

    Args:
        chain_wages: Mapping of store_num -> {
            'wage_min': float|None, 'wage_max': float|None, 'wage_period': str
        }
        local_avg_wage: Average local employer wage for comparable roles.
                       If None, returns neutral scores.

    Returns:
        Mapping of store_num -> {
            'value': float (0-100),
            'tier': str,
            'chain_avg': float|None,
            'local_avg': float|None,
            'gap_pct': float|None
        }
    """
    tiers_cfg = get_score_tiers()
    results: dict[str, dict] = {}

    if local_avg_wage is None or local_avg_wage <= 0:
        # No local wage data — neutral scores for all
        for store_num in chain_wages:
            results[store_num] = {
                "value": 50.0,
                "tier": "elevated",
                "chain_avg": None,
                "local_avg": None,
                "gap_pct": None,
            }
        logger.info("[WageScore] No local wage data available, returning neutral scores")
        return results

    gap_scores: dict[str, float] = {}

    for store_num, wage_data in chain_wages.items():
        w_min = wage_data.get("wage_min")
        w_max = wage_data.get("wage_max")

        if w_min is None and w_max is None:
            gap_scores[store_num] = 50.0
            continue

        # Compute chain average wage
        if w_min is not None and w_max is not None:
            chain_avg = (w_min + w_max) / 2.0
        elif w_min is not None:
            chain_avg = w_min
        else:
            chain_avg = w_max  # type: ignore[assignment]

        # Convert yearly to hourly if needed
        period = wage_data.get("wage_period", "hourly")
        if period == "yearly" and chain_avg > 100:
            chain_avg = chain_avg / 2080  # ~40hr/week * 52 weeks

        # Gap: how much more locals pay (%)
        if chain_avg > 0:
            gap_pct = ((local_avg_wage - chain_avg) / chain_avg) * 100
        else:
            gap_pct = 0.0

        # Convert gap to 0-100 score
        # -20% gap (chain pays more) → 0, 0% gap → 50, +20% gap → 100
        score = max(0.0, min(100.0, 50.0 + (gap_pct * 2.5)))

        gap_scores[store_num] = score

    # Tier assignment
    all_scores = list(gap_scores.values())
    for store_num, score in gap_scores.items():
        if len(all_scores) >= 3:
            percentile = sum(1 for v in all_scores if v <= score) / len(all_scores) * 100
        else:
            percentile = score

        tier = "adequate"
        if percentile >= tiers_cfg["critical"]["min_percentile"]:
            tier = "critical"
        elif percentile >= tiers_cfg["elevated"]["min_percentile"]:
            tier = "elevated"

        w_data = chain_wages.get(store_num, {})
        w_min = w_data.get("wage_min")
        w_max = w_data.get("wage_max")
        chain_avg = None
        if w_min is not None and w_max is not None:
            chain_avg = (w_min + w_max) / 2.0
        elif w_min is not None:
            chain_avg = w_min
        elif w_max is not None:
            chain_avg = w_max

        gap_pct_val = None
        if chain_avg and chain_avg > 0:
            gap_pct_val = round(((local_avg_wage - chain_avg) / chain_avg) * 100, 1)

        results[store_num] = {
            "value": round(percentile, 2),
            "tier": tier,
            "chain_avg": round(chain_avg, 2) if chain_avg else None,
            "local_avg": round(local_avg_wage, 2),
            "gap_pct": gap_pct_val,
        }

    logger.info("[WageScore] Scored %d stores", len(results))
    return results
