"""
Composite scoring engine for ChainStaffingTracker.

Economically grounded scoring that uses government labor market data
as denominators and benchmarks, not arbitrary weighted averages.

Score formula:
  Composite = w₁·demand_pressure + w₂·wage_competitiveness + w₃·churn_signal + w₄·qualitative

Where:
  demand_pressure     = (postings per establishment) / regional baseline
  wage_competitiveness = (market median - chain wage) / market median
  churn_signal         = posting velocity / expected turnover (from JOLTS)
  qualitative          = sentiment score (Reddit + Google Reviews)

Each component has an economic interpretation.  If ground-truth data
(QCEW, JOLTS) is not yet available, falls back to the previous
percentile-based approach.

Weights are in config/chains.yaml under scoring.weights:
  demand_pressure:      35%
  wage_competitiveness: 25%
  churn_signal:         25%
  qualitative:          15%

Depends on: backend.database, backend.baseline, backend.scoring.{careers, sentiment, wage}
Called by: backend/scheduler.py, server.py (after ingestion)
"""

import logging
from datetime import datetime

from backend.database import (
    Score,
    Signal,
    Store,
    WageIndex,
    get_session,
    init_db,
)
from backend.scoring.careers import compute_careers_score, weighted_listing_count
from backend.scoring.sentiment import compute_sentiment_score
from backend.scoring.wage import compute_wage_score
from config.loader import get_score_tiers, get_scoring_weights, get_seasonal_config

logger = logging.getLogger(__name__)


def compute_all_scores(region: str, chain: str | None = None) -> dict[str, dict]:
    """Compute economically-grounded composite scores for all stores.

    Uses ground-truth baselines (QCEW establishment counts, JOLTS turnover,
    OEWS wages) when available, with percentile fallback when not.

    Args:
        region: Region key, e.g. 'austin_tx'.
        chain: Optional chain filter, e.g. 'starbucks'.

    Returns:
        Mapping of store_num -> {
            'composite': float,
            'tier': str,
            'demand_pressure': dict|None,
            'wage_competitiveness': dict|None,
            'churn_signal': dict|None,
            'qualitative': dict|None,
        }
    """
    engine = init_db()
    session = get_session(engine)
    weights = get_scoring_weights()
    tiers_cfg = get_score_tiers()

    try:
        # ── Fetch stores ─────────────────────────────────────────────
        query = session.query(Store).filter(Store.region == region, Store.is_active.is_(True))
        if chain:
            query = query.filter(Store.chain == chain)
        stores = query.all()

        if not stores:
            logger.info("[ScoringEngine] No stores found for region=%s chain=%s", region, chain)
            return {}

        store_nums = [s.store_num for s in stores]
        store_map = {s.store_num: s for s in stores}

        # ── Load ground-truth baseline ───────────────────────────────
        baseline = _load_baseline(region, chain)

        # ── Gather signals by store and type ─────────────────────────
        signals = (
            session.query(Signal)
            .filter(Signal.store_num.in_(store_nums))
            .order_by(Signal.observed_at.desc())
            .all()
        )

        store_listings: dict[str, list[dict]] = {sn: [] for sn in store_nums}
        store_sentiment: dict[str, list[dict]] = {sn: [] for sn in store_nums}
        store_wages: dict[str, dict] = {sn: {} for sn in store_nums}

        for sig in signals:
            sn = sig.store_num
            if sn not in store_listings:
                continue

            meta = sig.get_metadata()

            if sig.source in ("careers_api", "jobspy") and sig.signal_type == "listing":
                store_listings[sn].append({
                    "observed_at": sig.observed_at,
                    "posted_date": meta.get("posted_date") or meta.get("date_posted"),
                    "value": sig.value,
                })
            elif sig.signal_type in ("sentiment", "review_score"):
                store_sentiment[sn].append({
                    "signal_type": sig.signal_type,
                    "value": sig.value,
                    "source": sig.source,
                })
            elif sig.signal_type == "wage":
                if not store_wages[sn]:
                    store_wages[sn] = {
                        "wage_min": meta.get("wage_min"),
                        "wage_max": meta.get("wage_max"),
                        "wage_period": meta.get("wage_period", "hourly"),
                    }

        # ── Compute sub-scores ───────────────────────────────────────
        # 1. Demand pressure (postings-per-establishment based)
        demand_scores = _compute_demand_pressure(store_listings, baseline)

        # 2. Wage competitiveness
        local_avg = _get_local_avg_wage(session, region, chain)
        market_median = baseline.get("occupation_median_wage") if baseline else None
        wage_scores = _compute_wage_competitiveness(store_wages, local_avg, market_median)

        # 3. Churn signal (posting velocity vs expected turnover)
        churn_scores = _compute_churn_signal(store_listings, baseline)

        # 4. Qualitative (sentiment — unchanged methodology)
        qualitative_scores = compute_sentiment_score(store_sentiment)

        # ── Compute composite ────────────────────────────────────────
        results: dict[str, dict] = {}

        for sn in store_nums:
            sub_scores: dict[str, float | None] = {}
            available_weights: dict[str, float] = {}

            # Demand pressure
            dp = demand_scores.get(sn)
            if dp is not None:
                sub_scores["demand_pressure"] = dp["value"]
                available_weights["demand_pressure"] = weights.get("demand_pressure", 0.35)

            # Wage competitiveness
            wc = wage_scores.get(sn)
            if wc is not None:
                sub_scores["wage_competitiveness"] = wc["value"]
                available_weights["wage_competitiveness"] = weights.get("wage_competitiveness", 0.25)

            # Churn signal
            cs = churn_scores.get(sn)
            if cs is not None:
                sub_scores["churn_signal"] = cs["value"]
                available_weights["churn_signal"] = weights.get("churn_signal", 0.25)

            # Qualitative
            qs = qualitative_scores.get(sn)
            if qs and store_sentiment.get(sn):
                sub_scores["qualitative"] = qs["value"]
                available_weights["qualitative"] = weights.get("qualitative", 0.15)

            # Weighted average with redistribution
            total_weight = sum(available_weights.values()) or 1.0
            composite = 0.0
            for key, w in available_weights.items():
                val = sub_scores.get(key)
                if val is not None:
                    composite += (w / total_weight) * val

            # Apply seasonal adjustment if available
            seasonal_cfg = get_seasonal_config()
            if seasonal_cfg.get("enabled") and baseline:
                seasonal_idx = baseline.get("seasonal_index")
                if seasonal_idx and seasonal_idx != 0:
                    # Adjust composite: divide by seasonal index to normalize
                    # During peak hiring months, raw scores are inflated
                    composite = composite / seasonal_idx

            composite = max(0.0, min(100.0, composite))

            # Determine tier
            tier = "adequate"
            if composite >= tiers_cfg["critical"]["min_percentile"]:
                tier = "critical"
            elif composite >= tiers_cfg["elevated"]["min_percentile"]:
                tier = "elevated"

            results[sn] = {
                "composite": round(composite, 2),
                "tier": tier,
                "demand_pressure": demand_scores.get(sn),
                "wage_competitiveness": wage_scores.get(sn),
                "churn_signal": churn_scores.get(sn),
                "qualitative": qualitative_scores.get(sn),
                "baseline_available": baseline is not None,
            }

        # ── Write scores to DB ───────────────────────────────────────
        _write_scores(session, results)

        logger.info(
            "[ScoringEngine] Scored %d stores for region=%s (baseline=%s): %s",
            len(results), region,
            "yes" if baseline else "no",
            _tier_distribution(results),
        )
        return results

    except Exception as e:
        session.rollback()
        logger.error("[ScoringEngine] Failed to compute scores: %s", e)
        return {}
    finally:
        session.close()


# ── Sub-score computation ────────────────────────────────────────────────────

def _load_baseline(region: str, chain: str | None) -> dict | None:
    """Load the latest labor market baseline for the region.

    Maps chain → NAICS code and fetches the corresponding baseline.
    """
    try:
        from backend.baseline import get_latest_baseline
        from config.loader import get_chain

        # Determine NAICS from chain config
        naics = "7225"  # default: food services
        if chain:
            try:
                chain_cfg = get_chain(chain)
                industry = chain_cfg.get("industry", "")
                # Map industry → NAICS
                industry_naics = {
                    "coffee_cafe": "722515",
                    "fast_food": "722513",
                    "full_service_restaurant": "722511",
                    "food_service": "7225",
                }
                naics = industry_naics.get(industry, "7225")
            except (KeyError, TypeError):
                pass

        baseline = get_latest_baseline(region, naics)
        if baseline:
            logger.info(
                "[ScoringEngine] Loaded baseline: NAICS=%s, est=%s, emp=%s, quits=%.1f%%",
                naics,
                baseline.get("establishment_count", "?"),
                baseline.get("total_employment", "?"),
                baseline.get("expected_quits_rate", 0) or 0,
            )
        return baseline

    except ImportError:
        logger.debug("[ScoringEngine] baseline module not available — using fallback")
        return None
    except Exception as e:
        logger.warning("[ScoringEngine] Failed to load baseline: %s", e)
        return None


def _compute_demand_pressure(
    store_listings: dict[str, list[dict]],
    baseline: dict | None,
) -> dict[str, dict]:
    """Compute demand pressure: postings per establishment / regional norm.

    If baseline is available:
      score = (weighted_listings / establishment_count) / regional_norm × 50
      Capped at 100.  50 = exactly at norm.  100 = 2× norm.

    Fallback: percentile rank within region (old behavior).
    """
    # Compute weighted listing counts
    listing_counts: dict[str, float] = {}
    for sn, listings in store_listings.items():
        listing_counts[sn] = weighted_listing_count(listings)

    establishment_count = None
    if baseline:
        establishment_count = baseline.get("establishment_count")

    if establishment_count and establishment_count > 0:
        # Ground-truth scoring: normalize by establishment count
        total_listings = sum(listing_counts.values())
        regional_per_est = total_listings / establishment_count if establishment_count else 0

        scores: dict[str, dict] = {}
        for sn, count in listing_counts.items():
            if regional_per_est > 0:
                # How many times above/below the regional per-establishment rate
                ratio = count / regional_per_est
                value = min(100.0, ratio * 50.0)  # 1× = 50, 2× = 100
            else:
                value = 50.0 if count > 0 else 0.0

            scores[sn] = {
                "value": round(value, 2),
                "weighted_listings": round(count, 2),
                "regional_per_establishment": round(regional_per_est, 3),
                "establishment_count": establishment_count,
                "method": "ground_truth",
            }
        return scores
    else:
        # Fallback: percentile rank
        careers_scores = compute_careers_score(store_listings)
        for sn in careers_scores:
            careers_scores[sn]["method"] = "percentile_fallback"
        return careers_scores


def _compute_wage_competitiveness(
    store_wages: dict[str, dict],
    local_avg: float | None,
    market_median: float | None,
) -> dict[str, dict]:
    """Compute wage competitiveness score.

    Formula: gap_pct = (market_wage - chain_wage) / market_wage × 100
    Score: 50 + gap_pct (so 50 = at market, 100 = 50% below market)
    """
    reference_wage = market_median or local_avg

    scores: dict[str, dict] = {}
    for sn, wages in store_wages.items():
        if not wages:
            continue

        chain_wage = None
        wmin = wages.get("wage_min")
        wmax = wages.get("wage_max")
        if wmin and wmax:
            chain_wage = (wmin + wmax) / 2.0
        elif wmin:
            chain_wage = wmin
        elif wmax:
            chain_wage = wmax

        if chain_wage is None:
            continue

        # Convert yearly to hourly if needed
        if wages.get("wage_period") == "yearly" and chain_wage > 100:
            chain_wage = chain_wage / 2080.0

        if reference_wage and reference_wage > 0:
            gap_pct = ((reference_wage - chain_wage) / reference_wage) * 100.0
            value = max(0.0, min(100.0, 50.0 + gap_pct))
        else:
            value = 50.0  # no reference — neutral

        scores[sn] = {
            "value": round(value, 2),
            "chain_wage": round(chain_wage, 2),
            "market_reference": round(reference_wage, 2) if reference_wage else None,
            "gap_pct": round(gap_pct, 2) if reference_wage else None,
            "method": "oews_median" if market_median else ("local_avg" if local_avg else "none"),
        }

    return scores


def _compute_churn_signal(
    store_listings: dict[str, list[dict]],
    baseline: dict | None,
) -> dict[str, dict]:
    """Compute churn signal: posting velocity vs expected turnover.

    If JOLTS expected separations are available:
      ratio = active_postings / expected_monthly_separations
      score = ratio × 50  (1× = 50 = normal, 2× = 100 = 2× expected churn)

    Fallback: just use weighted listing counts as a proxy.
    """
    expected_seps = None
    quits_rate = None
    if baseline:
        expected_seps = baseline.get("expected_monthly_separations")
        quits_rate = baseline.get("expected_quits_rate")

    listing_counts: dict[str, float] = {}
    for sn, listings in store_listings.items():
        listing_counts[sn] = weighted_listing_count(listings)

    scores: dict[str, dict] = {}

    if expected_seps and expected_seps > 0:
        total_listings = sum(listing_counts.values())
        n_stores = len([c for c in listing_counts.values() if c > 0])

        for sn, count in listing_counts.items():
            if count == 0:
                value = 0.0
            else:
                # Per-store expected = total separations / total stores
                per_store_expected = expected_seps / max(n_stores, 1)
                ratio = count / per_store_expected if per_store_expected > 0 else 1.0
                value = min(100.0, ratio * 50.0)

            scores[sn] = {
                "value": round(value, 2),
                "weighted_listings": round(count, 2),
                "expected_monthly_separations": expected_seps,
                "quits_rate": quits_rate,
                "method": "jolts_benchmark",
            }
    else:
        # Fallback: relative listing count (higher = more churn signal)
        all_counts = list(listing_counts.values())
        max_count = max(all_counts) if all_counts else 1.0

        for sn, count in listing_counts.items():
            if max_count > 0:
                value = (count / max_count) * 100.0
            else:
                value = 0.0

            scores[sn] = {
                "value": round(value, 2),
                "weighted_listings": round(count, 2),
                "method": "relative_fallback",
            }

    return scores


def _get_local_avg_wage(session, region: str, chain: str | None) -> float | None:
    """Compute average local (non-chain) wage for the region."""
    try:
        # Extract city/state from region key for location matching
        # e.g. "austin_tx" → search for "austin" or state "TX"
        # Include the wider MSA (Round Rock, Cedar Park, etc.)
        parts = region.split("_")
        city = parts[0] if parts else region
        state = parts[1].upper() if len(parts) > 1 else ""

        query = session.query(WageIndex).filter(
            WageIndex.is_chain.is_(False),
        )
        # Filter by state if available (broad MSA match)
        if state:
            query = query.filter(WageIndex.location.ilike(f"%{state}%"))
        else:
            query = query.filter(WageIndex.location.ilike(f"%{city}%"))

        rows = query.all()
        if not rows:
            return None

        hourly_wages: list[float] = []
        for r in rows:
            avg = None
            if r.wage_min is not None and r.wage_max is not None:
                avg = (r.wage_min + r.wage_max) / 2.0
            elif r.wage_min is not None:
                avg = r.wage_min
            elif r.wage_max is not None:
                avg = r.wage_max

            if avg is not None:
                if r.wage_period == "yearly" and avg > 100:
                    avg = avg / 2080
                hourly_wages.append(avg)

        if hourly_wages:
            return sum(hourly_wages) / len(hourly_wages)
        return None

    except Exception as e:
        logger.error("[ScoringEngine] Failed to get local avg wage: %s", e)
        return None


def _write_scores(session, results: dict[str, dict]) -> None:
    """Upsert Score rows for computed results."""
    now = datetime.utcnow()
    try:
        for store_num, data in results.items():
            # Composite score
            existing = (
                session.query(Score)
                .filter_by(store_num=store_num, score_type="composite")
                .first()
            )
            if existing:
                existing.value = data["composite"]
                existing.tier = data["tier"]
                existing.computed_at = now
            else:
                session.add(Score(
                    store_num=store_num,
                    score_type="composite",
                    value=data["composite"],
                    tier=data["tier"],
                    computed_at=now,
                ))

            # Sub-scores (new economically-grounded names)
            for sub_type in ("demand_pressure", "wage_competitiveness", "churn_signal", "qualitative"):
                sub = data.get(sub_type)
                if sub is None:
                    continue
                existing_sub = (
                    session.query(Score)
                    .filter_by(store_num=store_num, score_type=sub_type)
                    .first()
                )
                val = sub["value"] if isinstance(sub, dict) else sub
                if existing_sub:
                    existing_sub.value = val
                    existing_sub.tier = sub.get("tier", "unknown") if isinstance(sub, dict) else "unknown"
                    existing_sub.computed_at = now
                else:
                    session.add(Score(
                        store_num=store_num,
                        score_type=sub_type,
                        value=val,
                        tier=sub.get("tier", "unknown") if isinstance(sub, dict) else "unknown",
                        computed_at=now,
                    ))

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("[ScoringEngine] Failed to write scores: %s", e)


def _tier_distribution(results: dict[str, dict]) -> dict[str, int]:
    """Count stores per tier for logging."""
    dist: dict[str, int] = {"critical": 0, "elevated": 0, "adequate": 0}
    for r in results.values():
        tier = r.get("tier", "unknown")
        dist[tier] = dist.get(tier, 0) + 1
    return dist
