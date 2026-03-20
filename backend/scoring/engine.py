"""
Composite scoring engine for ChainStaffingTracker.

Pulls signals from tracker.db, delegates to sub-score modules
(careers, sentiment, wage), and writes final Score rows.

Weights are configurable in config/chains.yaml under scoring.weights:
  careers_api: 40%
  job_boards:  35%
  sentiment:   25%

If a source has no data for a store, its weight is redistributed
proportionally to available sources.

Depends on: backend.database, backend.scoring.{careers, sentiment, wage}, config.loader
Called by: backend/scheduler.py, server.py (after ingestion)
"""

import logging
from datetime import datetime

from backend.database import Score, Signal, Store, WageIndex, get_session, init_db
from backend.scoring.careers import compute_careers_score
from backend.scoring.sentiment import compute_sentiment_score
from backend.scoring.wage import compute_wage_score
from config.loader import get_score_tiers, get_scoring_weights

logger = logging.getLogger(__name__)


def compute_all_scores(region: str, chain: str | None = None) -> dict[str, dict]:
    """Compute composite scores for all stores in a region.

    1. Gather signals from tracker.db grouped by store and source.
    2. Compute sub-scores via careers, sentiment, and wage modules.
    3. Compute weighted composite score.
    4. Write Score rows to DB.

    Args:
        region: Region key, e.g. 'austin_tx'.
        chain: Optional chain filter, e.g. 'starbucks'.

    Returns:
        Mapping of store_num -> {
            'composite': float,
            'tier': str,
            'careers': dict|None,
            'sentiment': dict|None,
            'wage': dict|None,
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

        # ── Gather signals by store and type ─────────────────────────
        signals = (
            session.query(Signal)
            .filter(Signal.store_num.in_(store_nums))
            .order_by(Signal.observed_at.desc())
            .all()
        )

        # Group listings (careers_api + jobspy)
        store_listings: dict[str, list[dict]] = {sn: [] for sn in store_nums}
        # Group sentiment signals
        store_sentiment: dict[str, list[dict]] = {sn: [] for sn in store_nums}
        # Group wage data
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
                # Keep latest wage data per store
                if not store_wages[sn]:
                    store_wages[sn] = {
                        "wage_min": meta.get("wage_min"),
                        "wage_max": meta.get("wage_max"),
                        "wage_period": meta.get("wage_period", "hourly"),
                    }

        # ── Compute sub-scores ───────────────────────────────────────
        careers_scores = compute_careers_score(store_listings)

        sentiment_scores = compute_sentiment_score(store_sentiment)

        # Get local average wage for wage gap computation
        local_avg = _get_local_avg_wage(session, region, chain)
        wage_scores = compute_wage_score(store_wages, local_avg)

        # ── Compute composite ────────────────────────────────────────
        results: dict[str, dict] = {}

        for sn in store_nums:
            sub_scores: dict[str, float | None] = {}
            available_weights: dict[str, float] = {}

            # Careers (covers both careers_api and job_boards weight)
            c = careers_scores.get(sn)
            if c and store_listings.get(sn):
                # Split careers weight between careers_api and job_boards
                sub_scores["careers_api"] = c["value"]
                available_weights["careers_api"] = weights.get("careers_api", 0.4)
                available_weights["job_boards"] = weights.get("job_boards", 0.35)
                sub_scores["job_boards"] = c["value"]  # same source for now
            else:
                sub_scores["careers_api"] = None
                sub_scores["job_boards"] = None

            # Sentiment
            s = sentiment_scores.get(sn)
            if s and store_sentiment.get(sn):
                sub_scores["sentiment"] = s["value"]
                available_weights["sentiment"] = weights.get("sentiment", 0.25)
            else:
                sub_scores["sentiment"] = None

            # Compute weighted average with redistribution
            total_weight = sum(available_weights.values()) or 1.0
            composite = 0.0
            for key, w in available_weights.items():
                val = sub_scores.get(key)
                if val is not None:
                    composite += (w / total_weight) * val

            # Determine tier
            tier = "adequate"
            if composite >= tiers_cfg["critical"]["min_percentile"]:
                tier = "critical"
            elif composite >= tiers_cfg["elevated"]["min_percentile"]:
                tier = "elevated"

            results[sn] = {
                "composite": round(composite, 2),
                "tier": tier,
                "careers": careers_scores.get(sn),
                "sentiment": sentiment_scores.get(sn),
                "wage": wage_scores.get(sn),
            }

        # ── Write scores to DB ───────────────────────────────────────
        _write_scores(session, results)

        logger.info(
            "[ScoringEngine] Scored %d stores for region=%s: %s",
            len(results),
            region,
            _tier_distribution(results),
        )
        return results

    except Exception as e:
        session.rollback()
        logger.error("[ScoringEngine] Failed to compute scores: %s", e)
        return {}
    finally:
        session.close()


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

            # Sub-scores
            for sub_type in ("careers", "sentiment", "wage"):
                sub = data.get(sub_type)
                if sub is None:
                    continue
                existing_sub = (
                    session.query(Score)
                    .filter_by(store_num=store_num, score_type=sub_type)
                    .first()
                )
                if existing_sub:
                    existing_sub.value = sub["value"]
                    existing_sub.tier = sub.get("tier", "unknown")
                    existing_sub.computed_at = now
                else:
                    session.add(Score(
                        store_num=store_num,
                        score_type=sub_type,
                        value=sub["value"],
                        tier=sub.get("tier", "unknown"),
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
