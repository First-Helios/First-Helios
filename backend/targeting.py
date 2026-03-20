"""
Targeting score computation for ChainStaffingTracker.

Answers: "If we set up a community job fair here this week, how much would it matter?"

Combines staffing stress, wage gap, geographic isolation, and local employer density
into a single ranked score per store location.

Weights (from config):
  staffing_stress:    40%
  wage_gap:           30%
  isolation:          20%
  local_alternatives: 10%

Depends on: backend.database, backend.scoring.engine, config.loader
Called by: server.py /api/targeting
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

from backend.database import Score, Store, WageIndex, get_session, init_db
from config.loader import (
    get_local_radius_mi,
    get_targeting_tiers,
    get_targeting_weights,
)

logger = logging.getLogger(__name__)


@dataclass
class TargetingResult:
    """Targeting score for a single store location."""

    store_num: str
    chain: str
    industry: str
    address: str
    lat: float
    lng: float
    staffing_stress: float          # 0-100
    wage_gap: float                 # 0-100
    isolation: float                # 0-100
    local_alternatives: float       # 0-100
    targeting_score: float          # weighted composite
    targeting_tier: str             # "prime", "strong", "moderate"
    chain_avg_wage: float | None
    local_avg_wage: float | None
    wage_premium_pct: float | None
    nearest_same_chain_mi: float
    recommended_timing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "store_num": self.store_num,
            "chain": self.chain,
            "industry": self.industry,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "staffing_stress": self.staffing_stress,
            "wage_gap": self.wage_gap,
            "isolation": self.isolation,
            "local_alternatives": self.local_alternatives,
            "targeting_score": self.targeting_score,
            "targeting_tier": self.targeting_tier,
            "chain_avg_wage": self.chain_avg_wage,
            "local_avg_wage": self.local_avg_wage,
            "wage_premium_pct": self.wage_premium_pct,
            "nearest_same_chain_mi": self.nearest_same_chain_mi,
            "recommended_timing": self.recommended_timing,
        }


def compute_targeting(
    region: str,
    industry: str | None = None,
    chain: str | None = None,
    limit: int = 10,
) -> list[TargetingResult]:
    """Compute targeting scores for stores in a region.

    Args:
        region: Region key, e.g. 'austin_tx'.
        industry: Optional industry filter, e.g. 'coffee_cafe'.
        chain: Optional chain filter, e.g. 'starbucks'.
        limit: Maximum results to return (top N by targeting score).

    Returns:
        List of TargetingResult, sorted by targeting_score descending.
    """
    engine = init_db()
    session = get_session(engine)
    weights = get_targeting_weights()
    tiers_cfg = get_targeting_tiers()
    local_radius = get_local_radius_mi()

    try:
        # ── Fetch stores ─────────────────────────────────────────────
        query = session.query(Store).filter(
            Store.region == region,
            Store.is_active.is_(True),
        )
        if chain:
            query = query.filter(Store.chain == chain)
        if industry:
            query = query.filter(Store.industry == industry)

        stores = query.all()
        if not stores:
            logger.info("[Targeting] No stores found for region=%s", region)
            return []

        # ── Fetch composite scores ───────────────────────────────────
        store_nums = [s.store_num for s in stores]
        scores = (
            session.query(Score)
            .filter(Score.store_num.in_(store_nums), Score.score_type == "composite")
            .all()
        )
        score_map = {s.store_num: s.value for s in scores}

        # ── Fetch wage scores ────────────────────────────────────────
        wage_scores = (
            session.query(Score)
            .filter(Score.store_num.in_(store_nums), Score.score_type == "wage")
            .all()
        )
        wage_score_map = {s.store_num: s.value for s in wage_scores}

        # ── Get local avg wage ───────────────────────────────────────
        local_wages = (
            session.query(WageIndex)
            .filter(WageIndex.is_chain.is_(False))
            .all()
        )
        local_avg_wage = None
        if local_wages:
            hourly_wages = []
            for w in local_wages:
                avg = None
                if w.wage_min is not None and w.wage_max is not None:
                    avg = (w.wage_min + w.wage_max) / 2.0
                elif w.wage_min is not None:
                    avg = w.wage_min
                elif w.wage_max is not None:
                    avg = w.wage_max
                if avg is not None:
                    if w.wage_period == "yearly" and avg > 100:
                        avg = avg / 2080
                    hourly_wages.append(avg)
            if hourly_wages:
                local_avg_wage = sum(hourly_wages) / len(hourly_wages)

        # ── Get chain avg wage ───────────────────────────────────────
        chain_wages = (
            session.query(WageIndex)
            .filter(WageIndex.is_chain.is_(True))
            .all()
        )
        chain_avg_wage = None
        if chain_wages:
            hourly_wages = []
            for w in chain_wages:
                avg = None
                if w.wage_min is not None and w.wage_max is not None:
                    avg = (w.wage_min + w.wage_max) / 2.0
                elif w.wage_min is not None:
                    avg = w.wage_min
                elif w.wage_max is not None:
                    avg = w.wage_max
                if avg is not None:
                    if w.wage_period == "yearly" and avg > 100:
                        avg = avg / 2080
                    hourly_wages.append(avg)
            if hourly_wages:
                chain_avg_wage = sum(hourly_wages) / len(hourly_wages)

        # ── Compute per-store targeting ──────────────────────────────
        results: list[TargetingResult] = []
        store_coords = {
            s.store_num: (s.lat, s.lng, s) for s in stores if s.lat and s.lng
        }

        for store in stores:
            sn = store.store_num

            # Component 1: Staffing stress (from composite score)
            staffing_stress = score_map.get(sn, 50.0)

            # Component 2: Wage gap
            wage_gap = wage_score_map.get(sn, 50.0)

            # Component 3: Isolation (distance to nearest same-chain store)
            isolation, nearest_dist = _compute_isolation(
                store, store_coords, store.chain
            )

            # Component 4: Local alternatives (density of non-chain hiring)
            local_alt = _compute_local_alternatives(
                store, store_coords, local_radius
            )

            # Weighted composite
            targeting_score = (
                weights.get("staffing_stress", 0.4) * staffing_stress
                + weights.get("wage_gap", 0.3) * wage_gap
                + weights.get("isolation", 0.2) * isolation
                + weights.get("local_alternatives", 0.1) * local_alt
            )

            # Determine tier
            targeting_tier = "moderate"
            if targeting_score >= tiers_cfg["prime"]["min_score"]:
                targeting_tier = "prime"
            elif targeting_score >= tiers_cfg["strong"]["min_score"]:
                targeting_tier = "strong"

            # Wage premium calculation
            wage_premium_pct = None
            if chain_avg_wage and local_avg_wage and chain_avg_wage > 0:
                wage_premium_pct = round(
                    ((local_avg_wage - chain_avg_wage) / chain_avg_wage) * 100, 1
                )

            # Recommended timing
            timing = _recommend_timing(staffing_stress, store.chain)

            result = TargetingResult(
                store_num=sn,
                chain=store.chain,
                industry=store.industry,
                address=store.address,
                lat=store.lat or 0.0,
                lng=store.lng or 0.0,
                staffing_stress=round(staffing_stress, 2),
                wage_gap=round(wage_gap, 2),
                isolation=round(isolation, 2),
                local_alternatives=round(local_alt, 2),
                targeting_score=round(targeting_score, 2),
                targeting_tier=targeting_tier,
                chain_avg_wage=round(chain_avg_wage, 2) if chain_avg_wage else None,
                local_avg_wage=round(local_avg_wage, 2) if local_avg_wage else None,
                wage_premium_pct=wage_premium_pct,
                nearest_same_chain_mi=round(nearest_dist, 2),
                recommended_timing=timing,
            )
            results.append(result)

        # Sort by targeting score, return top N
        results.sort(key=lambda r: r.targeting_score, reverse=True)
        results = results[:limit]

        logger.info(
            "[Targeting] Computed %d targets for region=%s (top %d returned)",
            len(results), region, limit,
        )
        return results

    except Exception as e:
        logger.error("[Targeting] Failed for region=%s: %s", region, e)
        return []
    finally:
        session.close()


def _compute_isolation(
    store: Store,
    store_coords: dict,
    chain: str,
) -> tuple[float, float]:
    """Compute isolation score and nearest same-chain distance.

    Returns (isolation_score 0-100, nearest_distance_mi).
    More isolated = higher score.
    """
    if not store.lat or not store.lng:
        return 50.0, 0.0

    nearest_dist = float("inf")
    for sn, (lat, lng, s) in store_coords.items():
        if sn == store.store_num:
            continue
        if s.chain != chain:
            continue
        dist = _haversine(store.lat, store.lng, lat, lng)
        if dist < nearest_dist:
            nearest_dist = dist

    if nearest_dist == float("inf"):
        return 100.0, 0.0  # Only store — maximum isolation

    # Convert to 0-100: 0 mi = 0 score, 5+ mi = 100 score
    score = min(100.0, (nearest_dist / 5.0) * 100)
    return score, nearest_dist


def _compute_local_alternatives(
    store: Store,
    store_coords: dict,
    radius_mi: float,
) -> float:
    """Compute local employer density score.

    Counts non-same-chain stores within radius.
    More local alternatives = higher score (better for job fair).
    """
    if not store.lat or not store.lng:
        return 50.0

    count = 0
    for sn, (lat, lng, s) in store_coords.items():
        if sn == store.store_num:
            continue
        if s.chain == store.chain:
            continue
        dist = _haversine(store.lat, store.lng, lat, lng)
        if dist <= radius_mi:
            count += 1

    # Normalize: 0 alternatives = 0, 10+ = 100
    return min(100.0, count * 10.0)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance in miles between two lat/lng points."""
    R = 3959  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def _recommend_timing(staffing_stress: float, chain: str) -> list[str]:
    """Suggest optimal timing for a job fair at this location."""
    timing: list[str] = []

    if staffing_stress >= 70:
        timing.append("Immediate — high staffing stress detected")
    elif staffing_stress >= 45:
        timing.append("Within 2 weeks — elevated stress window")
    else:
        timing.append("Monitor — schedule when stress rises")

    # Chain-specific timing
    timing.append("Weekday mornings (7-10am) — shift change overlap")
    timing.append("Weekend afternoons — high foot traffic")

    return timing
