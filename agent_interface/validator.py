"""
agent_interface/validator.py — Pre-flight validation before query execution.

Checks:
  1. Schema validation (intent-specific required fields)
  2. Freshness check (is there already recent-enough data?)
  3. Budget check (can we afford the API calls?)
  4. Dedup check (has this exact query been run recently?)

Returns REJECTED, DUPLICATE, NO_BUDGET, or allows execution to proceed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.database import (
    LocalEmployer,
    Score,
    Signal,
    Snapshot,
    Store,
    WageIndex,
    get_session,
    init_db,
)
from backend.rate_manager import rate_manager

from agent_interface.schemas import (
    AgentMode,
    AgentQuery,
    ConciseResult,
    DataSource,
    FRESHNESS_THRESHOLDS,
    Intent,
    ResultStatus,
    get_mode_config,
)

logger = logging.getLogger(__name__)

# Map intent → list of API source keys that would be used
INTENT_SOURCE_MAP: dict[str, list[str]] = {
    Intent.POI_CHAIN_LOCATIONS.value: ["atp_geojson", "overture_s3", "overpass_api"],
    Intent.POI_LOCAL_DENSITY.value: ["overture_s3", "overpass_api"],
    Intent.WAGE_BASELINE.value: ["bls_v1"],
    Intent.JOB_POSTING_VOLUME.value: ["jobspy", "careers_workday"],
    Intent.SENTIMENT_CHECK.value: ["reddit_json", "reddit_oauth"],
    Intent.ECONOMIC_CONTEXT.value: ["bls_v1"],
    Intent.SCORE_REFRESH.value: [],         # internal only
    Intent.DATA_QUALITY_AUDIT.value: [],    # DB queries only
    Intent.CAMPAIGN_STATUS.value: [],       # DB queries only
}


def validate_and_check(query: AgentQuery) -> Optional[ConciseResult]:
    """Run pre-flight checks on an AgentQuery.

    Mode-aware:
      COLLECT  — freshness check SKIPPED (always collect fresh data)
      ANALYZE  — freshness check skipped (no external calls anyway)
      MONITOR  — freshness check skipped (read-only)
      MIXED    — freshness check ACTIVE (original behavior)

    Returns:
        ConciseResult with status REJECTED/DUPLICATE/NO_BUDGET if blocked.
        None if the query should proceed to execution.
    """
    mode_cfg = get_mode_config(query.mode)

    # 1. Schema validation (already done at parse time, but double-check)
    errors = query.validate()
    if errors:
        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.REJECTED,
            intent=query.intent,
            errors=errors,
            valid_options=_get_valid_options_for_intent(query.intent),
        )

    # 2. Freshness check — SKIP if mode bypasses freshness
    if not mode_cfg.bypass_freshness:
        freshness = _check_freshness(query)
        if freshness is not None:
            return freshness
    else:
        logger.info(
            "[Validator] Freshness check BYPASSED for %s (mode=%s)",
            query.intent.value, query.mode.value,
        )

    # 3. Budget check — can we afford the API calls?
    #    Skip for modes that don't make external calls
    if mode_cfg.allow_collection:
        budget_check = _check_budget(query)
        if budget_check is not None:
            return budget_check

    # All checks passed — proceed to execution
    return None


def _check_freshness(query: AgentQuery) -> Optional[ConciseResult]:
    """Check if existing data is fresh enough to skip re-collection."""
    threshold_days = FRESHNESS_THRESHOLDS.get(query.intent.value, 0.0)

    # Intents with 0 threshold always run
    if threshold_days == 0.0:
        return None

    engine = init_db()
    session = get_session(engine)

    try:
        staleness_days = None
        existing_count = 0

        if query.intent in (Intent.POI_CHAIN_LOCATIONS,):
            staleness_days, existing_count = _poi_chain_freshness(
                session, query
            )

        elif query.intent in (Intent.POI_LOCAL_DENSITY,):
            staleness_days, existing_count = _poi_local_freshness(
                session, query
            )

        elif query.intent in (Intent.WAGE_BASELINE, Intent.ECONOMIC_CONTEXT):
            staleness_days, existing_count = _wage_freshness(
                session, query
            )

        elif query.intent in (Intent.JOB_POSTING_VOLUME,):
            staleness_days, existing_count = _signal_freshness(
                session, query, "listing"
            )

        elif query.intent in (Intent.SENTIMENT_CHECK,):
            staleness_days, existing_count = _signal_freshness(
                session, query, "sentiment"
            )

        elif query.intent in (Intent.SCORE_REFRESH,):
            staleness_days, existing_count = _score_freshness(
                session, query
            )

        # If data is fresh enough, return DUPLICATE
        if staleness_days is not None and staleness_days < threshold_days:
            # But if the agent reported a known_count and we have more, still skip
            agent_knows = query.known_count or 0
            if existing_count > 0 and existing_count >= agent_knows:
                return ConciseResult(
                    query_id=query.query_id,
                    status=ResultStatus.DUPLICATE,
                    intent=query.intent,
                    records_found=existing_count,
                    staleness_days=round(staleness_days, 2),
                    anomalies=[
                        f"Data is {staleness_days:.1f} days old "
                        f"(threshold: {threshold_days:.0f} days). "
                        f"Already have {existing_count} records."
                    ],
                    suggested_next=_suggest_next_after_duplicate(query),
                )

        return None

    except Exception as e:
        logger.warning("[Validator] Freshness check error: %s", e)
        return None  # Don't block on errors — let execution proceed
    finally:
        session.close()


def _check_budget(query: AgentQuery) -> Optional[ConciseResult]:
    """Check if the rate budget allows the requested API calls."""
    sources = INTENT_SOURCE_MAP.get(query.intent.value, [])

    if not sources:
        return None  # No external API calls needed

    # If source_preference is set, only check that source
    if query.source_preference != DataSource.AUTO:
        source_key = _datasource_to_api_key(query.source_preference)
        if source_key:
            sources = [source_key]

    # Check if ANY source has budget
    available_sources: list[str] = []
    exhausted_sources: list[str] = []

    for source_key in sources:
        if rate_manager.can_request(source_key, count=query.max_budget_spend):
            available_sources.append(source_key)
        else:
            exhausted_sources.append(source_key)

    if not available_sources:
        # All sources exhausted
        budget_info = {}
        for sk in exhausted_sources:
            status = rate_manager.get_source_status(sk)
            budget = status.get("budget", {})
            budget_info[sk] = {
                "used": budget.get("used", 0),
                "remaining": budget.get("remaining", 0),
                "daily_limit": budget.get("daily_limit", 0),
            }

        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.NO_BUDGET,
            intent=query.intent,
            api_calls_remaining_today=0,
            errors=[
                f"All data sources exhausted for intent '{query.intent.value}': "
                f"{', '.join(exhausted_sources)}"
            ],
            anomalies=[
                f"Budget resets at midnight UTC. "
                f"Exhausted: {budget_info}"
            ],
            suggested_next=[
                {
                    "action": "wait_for_reset",
                    "description": "Budget resets at midnight UTC",
                },
                {
                    "action": "pause_queue",
                    "description": "Pause execution to conserve remaining budget",
                },
            ],
        )

    return None


# ── Freshness helpers ────────────────────────────────────────────────


def _poi_chain_freshness(session, query: AgentQuery) -> tuple[Optional[float], int]:
    """Check freshness of chain store data."""
    q = session.query(Store).filter(
        Store.region == query.region.value,
        Store.is_active.is_(True),
    )
    if query.brand:
        q = q.filter(Store.chain == query.brand.value)

    stores = q.all()
    if not stores:
        return None, 0

    # Find the most recent last_seen
    latest = max(s.last_seen for s in stores if s.last_seen)
    if latest:
        now = datetime.utcnow()
        staleness = (now - latest).total_seconds() / 86400.0
        return staleness, len(stores)

    return None, len(stores)


def _poi_local_freshness(session, query: AgentQuery) -> tuple[Optional[float], int]:
    """Check freshness of local employer data."""
    q = session.query(LocalEmployer).filter(
        LocalEmployer.region == query.region.value,
        LocalEmployer.is_active.is_(True),
    )
    if query.industry:
        q = q.filter(LocalEmployer.industry == query.industry.value)

    employers = q.all()
    if not employers:
        return None, 0

    latest = max(
        (e.last_seen for e in employers if e.last_seen),
        default=None,
    )
    if latest:
        now = datetime.utcnow()
        staleness = (now - latest).total_seconds() / 86400.0
        return staleness, len(employers)

    return None, len(employers)


def _wage_freshness(session, query: AgentQuery) -> tuple[Optional[float], int]:
    """Check freshness of wage data."""
    q = session.query(WageIndex)
    if query.industry:
        q = q.filter(WageIndex.industry == query.industry.value)

    wages = q.order_by(WageIndex.observed_at.desc()).all()
    if not wages:
        return None, 0

    latest = wages[0].observed_at
    if latest:
        now = datetime.utcnow()
        staleness = (now - latest).total_seconds() / 86400.0
        return staleness, len(wages)

    return None, len(wages)


def _signal_freshness(
    session, query: AgentQuery, signal_type: str
) -> tuple[Optional[float], int]:
    """Check freshness of signal data (listings, sentiment, etc.)."""
    q = session.query(Signal).filter(
        Signal.signal_type == signal_type,
    )

    if query.brand:
        # Find store nums for this brand
        store_nums = [
            s.store_num
            for s in session.query(Store.store_num).filter(
                Store.chain == query.brand.value,
                Store.region == query.region.value,
            ).all()
        ]
        if store_nums:
            q = q.filter(Signal.store_num.in_(store_nums))
        else:
            return None, 0

    signals = q.order_by(Signal.observed_at.desc()).limit(100).all()
    if not signals:
        return None, 0

    latest = signals[0].observed_at
    if latest:
        now = datetime.utcnow()
        staleness = (now - latest).total_seconds() / 86400.0
        return staleness, len(signals)

    return None, len(signals)


def _score_freshness(session, query: AgentQuery) -> tuple[Optional[float], int]:
    """Check freshness of computed scores."""
    q = session.query(Score).filter(Score.score_type == "composite")

    if query.brand:
        store_nums = [
            s.store_num
            for s in session.query(Store.store_num).filter(
                Store.chain == query.brand.value,
                Store.region == query.region.value,
            ).all()
        ]
        if store_nums:
            q = q.filter(Score.store_num.in_(store_nums))
        else:
            return None, 0

    scores = q.order_by(Score.computed_at.desc()).all()
    if not scores:
        return None, 0

    latest = scores[0].computed_at
    if latest:
        now = datetime.utcnow()
        staleness = (now - latest).total_seconds() / 86400.0
        return staleness, len(scores)

    return None, len(scores)


# ── Helpers ──────────────────────────────────────────────────────────


def _datasource_to_api_key(source: DataSource) -> Optional[str]:
    """Map DataSource enum to primary API source_key."""
    return {
        DataSource.ALLTHEPLACES: "atp_geojson",
        DataSource.OVERTURE: "overture_s3",
        DataSource.OSM: "overpass_api",
        DataSource.BLS: "bls_v1",
        DataSource.JOBSPY: "jobspy",
        DataSource.REDDIT: "reddit_json",
        DataSource.WORKDAY: "careers_workday",
    }.get(source)


def _get_valid_options_for_intent(intent: Intent) -> dict:
    """Return valid options dict for self-correction on rejection."""
    return {
        "brands": [e.value for e in from_module("Brand")],
        "industries": [e.value for e in from_module("Industry")],
        "regions": [e.value for e in from_module("Region")],
    }


def from_module(enum_name: str):
    """Lazy import to avoid circular references."""
    from agent_interface.schemas import Brand, Industry, Region
    return {"Brand": Brand, "Industry": Industry, "Region": Region}[enum_name]


def _suggest_next_after_duplicate(query: AgentQuery) -> list[dict]:
    """Suggest what the agent should do when data is already fresh."""
    suggestions: list[dict] = []

    if query.intent == Intent.POI_CHAIN_LOCATIONS:
        suggestions.append({
            "action": "score_refresh",
            "query": {"intent": "score_refresh", "region": query.region.value},
            "description": "Scores may be stale — refresh with existing data",
        })
        suggestions.append({
            "action": "poi_local_density",
            "query": {
                "intent": "poi_local_density",
                "region": query.region.value,
                "industry": "coffee_cafe",
            },
            "description": "Check local employer density around chain stores",
        })

    elif query.intent == Intent.POI_LOCAL_DENSITY:
        suggestions.append({
            "action": "wage_baseline",
            "query": {
                "intent": "wage_baseline",
                "region": query.region.value,
                "industry": query.industry.value if query.industry else "coffee_cafe",
            },
            "description": "Compare wages between chain and local employers",
        })

    elif query.intent == Intent.WAGE_BASELINE:
        suggestions.append({
            "action": "score_refresh",
            "query": {"intent": "score_refresh", "region": query.region.value},
            "description": "Recompute scores with updated wage data",
        })

    return suggestions
