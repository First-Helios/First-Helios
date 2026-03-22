"""backend/freshness.py

Freshness checking for the collection scheduler.

Checks whether collected data is stale by consulting:
  1. SourceFreshness tracking table (populated after each collection run)
  2. Fallback: actual data tables (Store, LocalEmployer, Signal, etc.)
"""

from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


FRESHNESS_THRESHOLDS: dict[str, float] = {
    "poi_chain_locations": 60.0,
    "poi_local_density": 60.0,
    "wage_baseline": 90.0,
    "job_posting_volume": 14.0,
    "sentiment_check": 14.0,
    "economic_context": 90.0,
    "score_refresh": 1.0,
    "data_quality_audit": 0.0,
    "discovery_scan": 0.0,
}


def _check_data_table_freshness(
    intent: str,
    region: str,
    brand: str | None = None,
    industry: str | None = None,
) -> dict | None:
    """Fallback freshness check against actual data tables.

    Used when the SourceFreshness tracking table has no record for a query
    (e.g. data was ingested before tracking was implemented).
    """
    from datetime import datetime
    from backend.database import (
        LocalEmployer, Score, Signal, Store, WageIndex,
        get_session, init_db,
    )

    engine = init_db()
    session = get_session(engine)

    try:
        staleness_days = None
        count = 0

        if intent == "poi_chain_locations":
            q = session.query(Store).filter(
                Store.region == region, Store.is_active.is_(True),
            )
            if brand:
                q = q.filter(Store.chain == brand)
            stores = q.all()
            if stores:
                count = len(stores)
                latest = max((s.last_seen for s in stores if s.last_seen), default=None)
                if latest:
                    staleness_days = (datetime.utcnow() - latest).total_seconds() / 86400.0

        elif intent == "poi_local_density":
            q = session.query(LocalEmployer).filter(
                LocalEmployer.region == region, LocalEmployer.is_active.is_(True),
            )
            if industry:
                q = q.filter(LocalEmployer.industry == industry)
            employers = q.all()
            if employers:
                count = len(employers)
                latest = max((e.last_seen for e in employers if e.last_seen), default=None)
                if latest:
                    staleness_days = (datetime.utcnow() - latest).total_seconds() / 86400.0

        elif intent in ("wage_baseline", "economic_context"):
            # Check QCEW signals first (newer, authoritative source)
            qcew_q = session.query(Signal).filter(
                Signal.source == "qcew",
                Signal.signal_type == "wage",
            )
            if industry:
                qcew_q = qcew_q.filter(
                    Signal.store_num.like(f"QCEW-{region}-%{industry}%")
                )
            qcew_sigs = qcew_q.order_by(Signal.observed_at.desc()).all()
            if qcew_sigs:
                count = len(qcew_sigs)
                if qcew_sigs[0].observed_at:
                    staleness_days = (datetime.utcnow() - qcew_sigs[0].observed_at).total_seconds() / 86400.0
            else:
                # Fallback: check WageIndex (legacy BLS data)
                q = session.query(WageIndex)
                if industry:
                    q = q.filter(WageIndex.industry == industry)
                wages = q.order_by(WageIndex.observed_at.desc()).all()
                if wages:
                    count = len(wages)
                    if wages[0].observed_at:
                        staleness_days = (datetime.utcnow() - wages[0].observed_at).total_seconds() / 86400.0

        elif intent == "job_posting_volume":
            q = session.query(Signal).filter(Signal.signal_type == "listing")
            if brand:
                store_nums = [
                    s.store_num for s in session.query(Store.store_num).filter(
                        Store.chain == brand, Store.region == region,
                    ).all()
                ]
                if store_nums:
                    q = q.filter(Signal.store_num.in_(store_nums))
                else:
                    return None
            signals = q.order_by(Signal.observed_at.desc()).limit(100).all()
            if signals:
                count = len(signals)
                if signals[0].observed_at:
                    staleness_days = (datetime.utcnow() - signals[0].observed_at).total_seconds() / 86400.0

        elif intent == "sentiment_check":
            q = session.query(Signal).filter(Signal.signal_type == "sentiment")
            if brand:
                store_nums = [
                    s.store_num for s in session.query(Store.store_num).filter(
                        Store.chain == brand, Store.region == region,
                    ).all()
                ]
                if store_nums:
                    q = q.filter(Signal.store_num.in_(store_nums))
                else:
                    return None
            signals = q.order_by(Signal.observed_at.desc()).limit(100).all()
            if signals:
                count = len(signals)
                if signals[0].observed_at:
                    staleness_days = (datetime.utcnow() - signals[0].observed_at).total_seconds() / 86400.0

        elif intent == "score_refresh":
            q = session.query(Score).filter(Score.score_type == "composite")
            if brand:
                store_nums = [
                    s.store_num for s in session.query(Store.store_num).filter(
                        Store.chain == brand, Store.region == region,
                    ).all()
                ]
                if store_nums:
                    q = q.filter(Score.store_num.in_(store_nums))
                else:
                    return None
            scores = q.order_by(Score.computed_at.desc()).all()
            if scores:
                count = len(scores)
                if scores[0].computed_at:
                    staleness_days = (datetime.utcnow() - scores[0].computed_at).total_seconds() / 86400.0

        if count == 0:
            return None  # No data at all — let it through

        return {
            "is_stale": True,  # re-evaluated by caller
            "age_days": round(staleness_days, 1) if staleness_days is not None else None,
            "last_collected_at": None,
            "records_collected": count,
            "next_due_at": None,
            "never_collected": False,
            "source": "data_table_fallback",
        }

    except Exception as e:
        logger.warning("[Freshness] Data table freshness fallback error: %s", e)
        return None
    finally:
        session.close()


def check_freshness_for_intent(
    intent: str,
    region: str,
    brand: str | None = None,
    industry: str | None = None,
) -> dict | None:
    """Check if data for this query combo is still fresh.

    Two-tier check:
      1. SourceFreshness tracking table (populated by executor after runs)
      2. Fallback: actual data tables (Store, LocalEmployer, etc.) when
         the tracking table has no record (data predates tracking)

    Returns a dict with is_stale, age_days, threshold_days, etc.
    Returns None if freshness tracking is unavailable (import error, etc).
    """
    try:
        from backend.database import check_freshness

        threshold = FRESHNESS_THRESHOLDS.get(intent, 14.0)

        # Intents with threshold 0 always run — skip freshness gate
        if threshold <= 0:
            return None

        result = check_freshness(
            intent=intent,
            region=region,
            brand=brand,
            industry=industry,
        )
        # Inject the configured threshold so caller can compare
        result["threshold_days"] = threshold

        # Re-evaluate staleness against the configured threshold
        if result.get("age_days") is not None:
            result["is_stale"] = result["age_days"] > threshold
            return result

        # ── Fallback: check actual data tables ──────────────────────
        # If the tracking table has no record (never_collected), OR if it
        # recorded 0 results (a failed/empty run), data may still exist from
        # a more recent ingest. Query real tables to avoid re-collecting.
        if result.get("never_collected") or result.get("records_collected", 1) == 0:
            fallback = _check_data_table_freshness(intent, region, brand, industry)
            if fallback is not None:
                fallback["threshold_days"] = threshold
                fallback["is_stale"] = (
                    fallback["age_days"] > threshold
                    if fallback.get("age_days") is not None
                    else True
                )
                logger.info(
                    "[Freshness] Freshness fallback from data tables: "
                    "intent=%s age=%.1f days, records=%d, stale=%s",
                    intent,
                    fallback.get("age_days", -1),
                    fallback.get("records_collected", 0),
                    fallback.get("is_stale"),
                )
                return fallback

        return result

    except Exception as e:
        logger.warning("[Freshness] Freshness check error: %s — allowing query", e)
        return None
