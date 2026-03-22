"""
agent_interface/executor.py — Translates validated queries into collector calls.

Routes each Intent to the appropriate collector(s) and storage handler.
Handles multi-source execution with budget tracking and source agreement.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import func

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
from backend.scoring.engine import compute_all_scores

from agent_interface.schemas import (
    AgentMode,
    AgentQuery,
    Brand,
    ConciseResult,
    DataSource,
    FRESHNESS_THRESHOLDS,
    Intent,
    ModeConfig,
    ResultStatus,
    get_mode_config,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# Austin TX bounding box (default region)
# ══════════════════════════════════════════════════════════════════════

REGION_BBOX = {
    "austin_tx": {
        "west": -97.9383,
        "east": -97.4104,
        "south": 30.0986,
        "north": 30.5168,
    },
}

# Brand → AllThePlaces spider mapping
# ATP_SPIDER_MAP removed — ATP_BRAND_MAP in scrapers/alltheplaces_adapter.py is the single source of truth

# Brand → OSM Wikidata ID mapping
BRAND_WIKIDATA = {
    "starbucks": "Q37158",
    "dutch_bros": "Q5765571",
    "mcdonalds": "Q38076",
    "whataburger": "Q376525",
    "chipotle": "Q465751",
    "target": "Q137078",
}

# BLS series IDs for Austin MSA
AUSTIN_BLS_SERIES = {
    "food_service_employment": "SMU48124207072200001",
    "leisure_hospitality": "SMU48124207000000001",
    "accommodation_food": "SMU48124207072000001",
    "national_food_hourly": "CEU7072200003",
    "national_food_employment": "CEU7072200001",
}


def execute(query: AgentQuery) -> ConciseResult:
    """Execute a validated AgentQuery and return a ConciseResult.

    Dispatches to the appropriate intent handler based on query.intent.
    Mode-aware: the query.mode controls freshness bypass, DB fallback,
    and success criteria (see ModeConfig in schemas.py).
    """
    t0 = time.time()
    mode_cfg = get_mode_config(query.mode)

    try:
        handler = _INTENT_HANDLERS.get(query.intent)
        if handler is None:
            return ConciseResult(
                query_id=query.query_id,
                status=ResultStatus.FAILED,
                intent=query.intent,
                errors=[f"No executor handler for intent '{query.intent.value}'"],
            )

        result = handler(query)
        result.estimated_seconds = round(time.time() - t0, 2)

        # ── Mode-aware success re-evaluation ────────────────────────
        # In COLLECT mode: must have actually fetched new data
        if mode_cfg.require_new_data and result.records_new == 0:
            if result.status in (ResultStatus.COMPLETED, ResultStatus.PARTIAL):
                result.status = ResultStatus.FAILED
                result.anomalies.append(
                    f"MODE={query.mode.value}: no new records collected from "
                    f"external sources — treating as failure"
                )

        # In ANALYZE/MONITOR mode: PARTIAL is fine
        if mode_cfg.success_on_partial and result.status == ResultStatus.PARTIAL:
            result.status = ResultStatus.COMPLETED
            result.anomalies.append(
                f"MODE={query.mode.value}: promoted PARTIAL → COMPLETED (cached data is acceptable)"
            )

        # Add remaining budget info
        result.api_calls_remaining_today = _get_total_remaining_budget(query)

        # ── Record freshness stamp ──────────────────────────────────
        # After successful or partial execution, update the freshness table
        # so future queries know when data was last collected.
        if result.status in (ResultStatus.COMPLETED, ResultStatus.PARTIAL):
            try:
                from backend.database import upsert_freshness
                threshold = FRESHNESS_THRESHOLDS.get(query.intent.value, 14.0)
                upsert_freshness(
                    intent=query.intent.value,
                    region=query.region.value,
                    brand=query.brand.value if query.brand else None,
                    industry=query.industry.value if query.industry else None,
                    records_collected=result.records_found,
                    status=result.status.value,
                    source_key=None,  # populated if specific source known
                    threshold_days=threshold,
                    notes=f"query_id={query.query_id}, mode={query.mode.value}, api_calls={result.api_calls_used}",
                )
                logger.info(
                    "[Executor] Freshness stamped: %s/%s brand=%s industry=%s (%d records) mode=%s",
                    query.intent.value, query.region.value,
                    query.brand.value if query.brand else "-",
                    query.industry.value if query.industry else "-",
                    result.records_found,
                    query.mode.value,
                )
            except Exception as e:
                logger.warning("[Executor] Freshness upsert failed (non-fatal): %s", e)

        return result

    except Exception as e:
        logger.error("[Executor] Failed for %s: %s", query.query_id, e, exc_info=True)
        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.FAILED,
            intent=query.intent,
            errors=[f"Execution error: {str(e)}"],
            estimated_seconds=round(time.time() - t0, 2),
        )


# ══════════════════════════════════════════════════════════════════════
# Intent Handlers
# ══════════════════════════════════════════════════════════════════════


def _execute_poi_chain(query: AgentQuery) -> ConciseResult:
    """POI_CHAIN_LOCATIONS — Find all chain store locations.

    Tries collectors in priority order: AllThePlaces → Overture → OSM.
    Mode-aware:
      COLLECT  — must hit external APIs, no DB fallback
      ANALYZE  — report DB counts only, no API calls
      MONITOR  — read-only DB summary
      MIXED    — try APIs, fall back to DB
    """
    brand_key = query.brand.value if query.brand else "starbucks"
    bbox = REGION_BBOX.get(query.region.value, REGION_BBOX["austin_tx"])
    mode_cfg = get_mode_config(query.mode)
    api_calls = 0
    records_found = 0
    records_new = 0
    records_updated = 0
    anomalies: list[str] = []
    sources_used: list[str] = []

    # ── External collection (skip in ANALYZE/MONITOR modes) ─────────
    if mode_cfg.allow_collection:
        try:
            from scrapers.alltheplaces_adapter import AllThePlacesAdapter

            if rate_manager.can_request("atp_geojson", count=1):
                from scrapers.alltheplaces_adapter import ATP_BRAND_MAP as _ATP_MAP
                if brand_key in _ATP_MAP:
                    adapter = AllThePlacesAdapter()
                    adapter.chain = brand_key
                    try:
                        signals = adapter.scrape(region=query.region.value)
                        api_calls += 1
                        records_new = len(signals)
                        records_found += records_new
                        sources_used.append("alltheplaces")
                        logger.info("[Executor] ATP returned %d stores for %s", records_new, brand_key)
                    except Exception as e:
                        anomalies.append(f"AllThePlaces failed: {e}")
                        logger.warning("[Executor] ATP error: %s", e)
                # else: brand not in ATP map — silently fall through to Overture
            else:
                anomalies.append("AllThePlaces budget exhausted")
        except ImportError:
            anomalies.append("AllThePlaces adapter not available")

        # ── Overture fallback (if ATP had no spider or failed) ──────
        if not sources_used:
            try:
                from scrapers.overture_adapter import OvertureChainAdapter

                if rate_manager.can_request("overture_s3", count=1):
                    adapter = OvertureChainAdapter()
                    adapter.chain = brand_key
                    try:
                        signals = adapter.scrape(region=query.region.value)
                        if signals:
                            api_calls += 1
                            records_new += len(signals)
                            records_found += len(signals)
                            sources_used.append("overture")
                            logger.info(
                                "[Executor] Overture returned %d stores for %s",
                                len(signals), brand_key,
                            )
                        else:
                            anomalies.append(f"Overture: no name filter for brand '{brand_key}' — chain not in Overture map")
                    except Exception as e:
                        anomalies.append(f"Overture chain lookup failed: {e}")
                else:
                    anomalies.append("Overture budget exhausted")
            except ImportError:
                anomalies.append("Overture adapter not available")

    # ── DB fallback (disabled in COLLECT mode) ──────────────────────
    if not sources_used and mode_cfg.allow_db_fallback:
        engine = init_db()
        session = get_session(engine)
        try:
            existing = session.query(Store).filter(
                Store.chain == brand_key,
                Store.region == query.region.value,
                Store.is_active.is_(True),
            ).count()
            records_found = existing
            anomalies.append(
                f"No collector executed — reporting {existing} existing stores from DB"
            )
        finally:
            session.close()
    elif not sources_used and not mode_cfg.allow_db_fallback:
        anomalies.append(
            f"MODE={query.mode.value}: no collector executed and DB fallback disabled"
        )

    # Build suggested next steps
    suggested_next: list[dict] = []
    if records_found > 0:
        suggested_next.append({
            "suggested_intent": "poi_local_density",
            "query": {
                "intent": "poi_local_density",
                "region": query.region.value,
                "industry": "coffee_cafe",
            },
            "description": f"Find local competitors near {records_found} {brand_key} stores",
        })
        suggested_next.append({
            "suggested_intent": "score_refresh",
            "query": {"intent": "score_refresh", "region": query.region.value},
            "description": "Recompute staffing scores with updated location data",
        })

    return ConciseResult(
        query_id=query.query_id,
        status=ResultStatus.COMPLETED if sources_used else ResultStatus.PARTIAL,
        intent=query.intent,
        records_found=records_found,
        records_new=records_new,
        records_updated=records_updated,
        api_calls_used=api_calls,
        anomalies=anomalies,
        suggested_next=suggested_next,
    )


def _execute_poi_local(query: AgentQuery) -> ConciseResult:
    """POI_LOCAL_DENSITY — Count local employers in an industry.

    Mode-aware: COLLECT requires external API hit, ANALYZE/MONITOR DB-only.
    """
    industry_key = query.industry.value if query.industry else "coffee_cafe"
    mode_cfg = get_mode_config(query.mode)
    api_calls = 0
    anomalies: list[str] = []
    sources_used: list[str] = []
    records_new = 0

    # ── External collection (skip in ANALYZE/MONITOR modes) ─────────
    if mode_cfg.allow_collection:
        try:
            from scrapers.overture_adapter import OvertureLocalAdapter

            if rate_manager.can_request("overture_s3", count=1):
                adapter = OvertureLocalAdapter()
                try:
                    signals = adapter.scrape(region=query.region.value)
                    api_calls += 1
                    records_new = len(signals)
                    sources_used.append("overture")
                    logger.info("[Executor] Overture returned %d local employer signals", records_new)
                except Exception as e:
                    anomalies.append(f"Overture query failed: {e}")
            else:
                anomalies.append("Overture budget exhausted")
        except ImportError:
            anomalies.append("Overture adapter not available")

    # ── DB report — total local employers in region (all industries) ─
    total = 0
    if mode_cfg.allow_db_fallback or sources_used:
        engine = init_db()
        session = get_session(engine)
        try:
            # Count ALL local employers in region (not filtered by industry)
            # so records_found reflects actual DB coverage, not classification gaps
            total_all = session.query(LocalEmployer).filter(
                LocalEmployer.region == query.region.value,
                LocalEmployer.is_active.is_(True),
            ).count()
            # Count industry-specific for context
            total_industry = 0
            if industry_key:
                total_industry = session.query(LocalEmployer).filter(
                    LocalEmployer.region == query.region.value,
                    LocalEmployer.is_active.is_(True),
                    LocalEmployer.industry == industry_key,
                ).count()

            total = total_all
            if total_all == 0:
                anomalies.append(
                    "0 local employers indexed — run poi_local_density in collect mode to populate"
                )
            elif total_industry == 0 and industry_key:
                anomalies.append(
                    f"0 {industry_key} employers classified (of {total_all} total) — "
                    f"category mappings may be pending; run POST /api/categories/discover"
                )
            else:
                anomalies.append(
                    f"{total_industry} {industry_key} employers of {total_all} total in region"
                )
        finally:
            session.close()
    elif not sources_used:
        anomalies.append(
            f"MODE={query.mode.value}: no collector executed and DB fallback disabled"
        )

    suggested_next: list[dict] = []
    if total > 0 or records_new > 0:
        suggested_next.append({
            "suggested_intent": "wage_baseline",
            "query": {
                "intent": "wage_baseline",
                "region": query.region.value,
                "industry": industry_key,
            },
            "description": f"Collect wage baseline for {industry_key} after indexing local employers",
        })

    return ConciseResult(
        query_id=query.query_id,
        status=ResultStatus.COMPLETED if sources_used else ResultStatus.PARTIAL,
        intent=query.intent,
        records_found=total,
        records_new=records_new,
        api_calls_used=api_calls,
        anomalies=anomalies,
        suggested_next=suggested_next,
    )


def _execute_wage_baseline(query: AgentQuery) -> ConciseResult:
    """WAGE_BASELINE — Fetch BLS wage data for industry/region.

    Mode-aware: COLLECT requires BLS API hit, ANALYZE/MONITOR DB-only.
    """
    industry_key = query.industry.value if query.industry else "coffee_cafe"
    mode_cfg = get_mode_config(query.mode)
    api_calls = 0
    anomalies: list[str] = []
    sources_used: list[str] = []
    records_new = 0

    # ── External collection ─────────────────────────────────────────
    if mode_cfg.allow_collection:
        try:
            from scrapers.bls_adapter import BLSAdapter

            if rate_manager.can_request("bls_v1", count=1):
                adapter = BLSAdapter()
                try:
                    signals = adapter.scrape(region=query.region.value)
                    api_calls += 1
                    records_new = len(signals)
                    sources_used.append("bls")
                    logger.info("[Executor] BLS returned %d wage signals", records_new)
                except Exception as e:
                    anomalies.append(f"BLS fetch failed: {e}")
            else:
                anomalies.append("BLS budget exhausted for today")
        except ImportError:
            anomalies.append("BLS adapter not available")

    # ── DB report ───────────────────────────────────────────────────
    wages = []
    if mode_cfg.allow_db_fallback or sources_used:
        engine = init_db()
        session = get_session(engine)
        try:
            q = session.query(WageIndex)
            if industry_key:
                q = q.filter(WageIndex.industry == industry_key)
            wages = q.all()

            chain_wages = [w for w in wages if w.is_chain]
            local_wages = [w for w in wages if not w.is_chain]

            if not wages:
                anomalies.append("No wage data in DB — need BLS collection first")
            else:
                def _avg(items):
                    vals = []
                    for w in items:
                        if w.wage_min and w.wage_max:
                            vals.append((w.wage_min + w.wage_max) / 2)
                    return round(sum(vals) / len(vals), 2) if vals else None

                chain_avg = _avg(chain_wages)
                local_avg = _avg(local_wages)
                if chain_avg and local_avg:
                    gap = round(((local_avg - chain_avg) / chain_avg) * 100, 1)
                    anomalies.append(
                        f"Wage gap: local avg ${local_avg}/hr vs chain avg ${chain_avg}/hr ({gap:+.1f}%)"
                    )
        finally:
            session.close()
    elif not sources_used:
        anomalies.append(
            f"MODE={query.mode.value}: no collector executed and DB fallback disabled"
        )

    suggested_next: list[dict] = []
    suggested_next.append({
        "suggested_intent": "score_refresh",
        "query": {"intent": "score_refresh", "region": query.region.value},
        "description": "Recompute scores with updated wage data",
    })

    return ConciseResult(
        query_id=query.query_id,
        status=ResultStatus.COMPLETED if sources_used else ResultStatus.PARTIAL,
        intent=query.intent,
        records_found=len(wages),
        records_new=records_new,
        api_calls_used=api_calls,
        anomalies=anomalies,
        suggested_next=suggested_next,
    )


def _execute_job_posting_volume(query: AgentQuery) -> ConciseResult:
    """JOB_POSTING_VOLUME — Count open job postings for a brand.

    Mode-aware: COLLECT requires Workday API hit, ANALYZE/MONITOR DB-only.
    """
    brand_key = query.brand.value if query.brand else "starbucks"
    mode_cfg = get_mode_config(query.mode)
    api_calls = 0
    anomalies: list[str] = []
    sources_used: list[str] = []
    records_found = 0
    records_new = 0

    # ── External collection ─────────────────────────────────────────
    if mode_cfg.allow_collection:
        try:
            from scrapers.careers_api import scrape_careers_api

            if rate_manager.can_request("careers_workday", count=1):
                try:
                    signals = scrape_careers_api(
                        region=query.region.value,
                        chain=brand_key,
                        ingest=True,
                    )
                    api_calls += 1
                    records_found = len(signals)
                    records_new = len(signals)
                    sources_used.append("workday")
                    logger.info("[Executor] Careers API returned %d signals", len(signals))
                except Exception as e:
                    anomalies.append(f"Careers API failed: {e}")
            else:
                anomalies.append("Careers API budget exhausted")
        except ImportError:
            anomalies.append("Careers API adapter not available")

    # ── DB fallback ─────────────────────────────────────────────────
    if not sources_used and mode_cfg.allow_db_fallback:
        engine = init_db()
        session = get_session(engine)
        try:
            store_nums = [
                s.store_num
                for s in session.query(Store.store_num).filter(
                    Store.chain == brand_key,
                    Store.region == query.region.value,
                ).all()
            ]
            if store_nums:
                listing_count = session.query(Signal).filter(
                    Signal.store_num.in_(store_nums),
                    Signal.signal_type == "listing",
                ).count()
                records_found = listing_count
                anomalies.append(f"Total listing signals in DB: {listing_count}")
        finally:
            session.close()
    elif not sources_used:
        anomalies.append(
            f"MODE={query.mode.value}: no collector executed and DB fallback disabled"
        )

    suggested_next: list[dict] = [
        {
            "suggested_intent": "score_refresh",
            "query": {"intent": "score_refresh", "region": query.region.value},
            "description": "Update staffing stress scores with new posting data",
        }
    ]

    return ConciseResult(
        query_id=query.query_id,
        status=ResultStatus.COMPLETED if sources_used else ResultStatus.PARTIAL,
        intent=query.intent,
        records_found=records_found,
        api_calls_used=api_calls,
        anomalies=anomalies,
        suggested_next=suggested_next,
    )


def _execute_sentiment_check(query: AgentQuery) -> ConciseResult:
    """SENTIMENT_CHECK — Gather worker sentiment for a brand.

    Mode-aware: COLLECT requires Reddit API hit, ANALYZE/MONITOR DB-only.
    """
    brand_key = query.brand.value if query.brand else "starbucks"
    mode_cfg = get_mode_config(query.mode)
    api_calls = 0
    anomalies: list[str] = []
    sources_used: list[str] = []
    records_found = 0
    records_new = 0

    # ── External collection ─────────────────────────────────────────
    if mode_cfg.allow_collection:
        try:
            from scrapers.reddit_adapter import RedditAdapter

            source_key = "reddit_oauth" if rate_manager.can_request("reddit_oauth") else "reddit_json"
            if rate_manager.can_request(source_key, count=1):
                try:
                    adapter = RedditAdapter()
                    posts = adapter.fetch_sentiment(brand=brand_key)
                    api_calls += 1
                    records_found = len(posts) if posts else 0
                    records_new = records_found
                    sources_used.append("reddit")
                except Exception as e:
                    anomalies.append(f"Reddit fetch failed: {e}")
            else:
                anomalies.append("Reddit budget exhausted")
        except ImportError:
            anomalies.append("Reddit adapter not available")

    # ── DB fallback ─────────────────────────────────────────────────
    if not sources_used and mode_cfg.allow_db_fallback:
        engine = init_db()
        session = get_session(engine)
        try:
            sentiment_count = session.query(Signal).filter(
                Signal.signal_type.in_(["sentiment", "review_score"]),
            ).count()
            records_found = sentiment_count
            anomalies.append(f"Total sentiment signals in DB: {sentiment_count}")
        finally:
            session.close()
    elif not sources_used:
        anomalies.append(
            f"MODE={query.mode.value}: no collector executed and DB fallback disabled"
        )

    return ConciseResult(
        query_id=query.query_id,
        status=ResultStatus.COMPLETED if sources_used else ResultStatus.PARTIAL,
        intent=query.intent,
        records_found=records_found,
        api_calls_used=api_calls,
        anomalies=anomalies,
        suggested_next=[{
            "suggested_intent": "score_refresh",
            "query": {"intent": "score_refresh", "region": query.region.value},
            "description": "Update scores with new sentiment data",
        }],
    )


def _execute_economic_context(query: AgentQuery) -> ConciseResult:
    """ECONOMIC_CONTEXT — Fetch macro indicators for the region."""
    anomalies: list[str] = []

    # Report what's available — BLS data from existing wage_index and signals
    engine = init_db()
    session = get_session(engine)
    try:
        wage_count = session.query(WageIndex).count()
        snapshot_count = session.query(Snapshot).count()

        anomalies.append(f"Wage observations: {wage_count}")
        anomalies.append(f"Scan snapshots: {snapshot_count}")

        if wage_count == 0:
            anomalies.append("No economic data — need BLS collection via wage_baseline intent")
    finally:
        session.close()

    return ConciseResult(
        query_id=query.query_id,
        status=ResultStatus.COMPLETED,
        intent=query.intent,
        records_found=wage_count if 'wage_count' in dir() else 0,
        anomalies=anomalies,
        suggested_next=[{
            "suggested_intent": "wage_baseline",
            "query": {
                "intent": "wage_baseline",
                "region": query.region.value,
                "industry": "coffee_cafe",
            },
            "description": "Collect BLS wage data for the region",
        }],
    )


def _execute_score_refresh(query: AgentQuery) -> ConciseResult:
    """SCORE_REFRESH — Recompute composite staffing scores."""
    anomalies: list[str] = []

    try:
        brand_filter = query.brand.value if query.brand else None
        results = compute_all_scores(
            region=query.region.value,
            chain=brand_filter,
        )

        tier_dist = {}
        for sn, data in results.items():
            tier = data.get("tier", "unknown")
            tier_dist[tier] = tier_dist.get(tier, 0) + 1

        if tier_dist:
            anomalies.append(f"Tier distribution: {tier_dist}")
        else:
            anomalies.append("No stores to score — need POI data first")

        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.COMPLETED,
            intent=query.intent,
            records_found=len(results),
            records_updated=len(results),
            anomalies=anomalies,
            suggested_next=[{
                "suggested_intent": "data_quality_audit",
                "query": {
                    "intent": "data_quality_audit",
                    "region": query.region.value,
                },
                "description": "Check for stale or missing data after scoring",
            }],
        )

    except Exception as e:
        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.FAILED,
            intent=query.intent,
            errors=[f"Score computation failed: {str(e)}"],
        )


def _execute_data_quality_audit(query: AgentQuery) -> ConciseResult:
    """DATA_QUALITY_AUDIT — Check for stale, missing, or conflicting data."""
    anomalies: list[str] = []
    suggested_next: list[dict] = []

    engine = init_db()
    session = get_session(engine)

    try:
        region = query.region.value

        # 1. Chain store counts (exclude 'local' — those are local employers, not chains)
        chain_counts = dict(
            session.query(Store.chain, func.count(Store.store_num))
            .filter(Store.region == region, Store.is_active.is_(True), Store.chain != "local")
            .group_by(Store.chain)
            .all()
        )
        total_stores = sum(chain_counts.values())
        anomalies.append(f"Chain stores: {total_stores} total — {dict(chain_counts)}")

        # Check for surprisingly low counts
        for brand_key in ["starbucks", "dutch_bros", "mcdonalds"]:
            count = chain_counts.get(brand_key, 0)
            if count < 50 and brand_key == "starbucks":
                anomalies.append(
                    f"WARNING: Only {count} {brand_key} stores — "
                    f"expected ~300+ for Austin metro"
                )
                suggested_next.append({
                    "suggested_intent": "poi_chain_locations",
                    "query": {
                        "intent": "poi_chain_locations",
                        "brand": brand_key,
                        "region": region,
                    },
                    "description": f"Re-collect {brand_key} locations — count seems low",
                })

        # 2. Local employer count
        local_count = session.query(LocalEmployer).filter(
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
        ).count()
        anomalies.append(f"Local employers: {local_count}")

        if local_count == 0:
            anomalies.append("WARNING: 0 local employers indexed")
            suggested_next.append({
                "suggested_intent": "poi_local_density",
                "query": {
                    "intent": "poi_local_density",
                    "region": region,
                    "industry": "coffee_cafe",
                },
                "description": "Index local employers for the region",
            })

        # 3. Score coverage
        scored_stores = session.query(Score).filter(
            Score.score_type == "composite"
        ).count()
        if total_stores > 0:
            coverage = round(scored_stores / total_stores * 100, 1)
            anomalies.append(f"Score coverage: {scored_stores}/{total_stores} ({coverage}%)")
            if coverage < 80:
                suggested_next.append({
                    "suggested_intent": "score_refresh",
                    "query": {"intent": "score_refresh", "region": region},
                    "description": f"Only {coverage}% of stores scored — refresh needed",
                })

        # 4. Wage data
        wage_count = session.query(WageIndex).count()
        anomalies.append(f"Wage observations: {wage_count}")
        if wage_count == 0:
            anomalies.append("WARNING: No wage data — scoring will be incomplete")
            suggested_next.append({
                "suggested_intent": "wage_baseline",
                "query": {
                    "intent": "wage_baseline",
                    "region": region,
                    "industry": "coffee_cafe",
                },
                "description": "Collect BLS wage data",
            })

        # 5. Signal freshness
        latest_signal = session.query(Signal).order_by(
            Signal.observed_at.desc()
        ).first()
        if latest_signal and latest_signal.observed_at:
            age_days = (datetime.utcnow() - latest_signal.observed_at).total_seconds() / 86400
            anomalies.append(f"Freshest signal: {age_days:.1f} days old")
            if age_days > 7:
                anomalies.append("WARNING: All signals are >7 days old")
                suggested_next.append({
                    "suggested_intent": "job_posting_volume",
                    "query": {
                        "intent": "job_posting_volume",
                        "brand": "starbucks",
                        "region": region,
                    },
                    "description": "Refresh job posting signals",
                })
        else:
            anomalies.append("No signals found — system needs initial data collection")

        # 6. Snapshot history
        snapshot_count = session.query(Snapshot).count()
        anomalies.append(f"Scan snapshots: {snapshot_count}")

        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.COMPLETED,
            intent=query.intent,
            records_found=total_stores + local_count,
            coverage_pct=coverage if total_stores > 0 else 0.0,
            anomalies=anomalies,
            suggested_next=suggested_next,
        )

    except Exception as e:
        logger.error("[Executor] Data quality audit failed: %s", e)
        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.FAILED,
            intent=query.intent,
            errors=[f"Audit failed: {str(e)}"],
        )
    finally:
        session.close()


def _execute_campaign_status(query: AgentQuery) -> ConciseResult:
    """CAMPAIGN_STATUS — Report queue state and budget usage."""
    anomalies: list[str] = []

    try:
        all_status = rate_manager.get_all_status()

        total_used = sum(s.get("used", 0) for s in all_status)
        total_remaining = sum(s.get("remaining", 0) for s in all_status)
        bottlenecks = [
            s["source_key"]
            for s in all_status
            if s.get("utilization_pct", 0) > 80
        ]

        anomalies.append(f"API calls today: {total_used} used, {total_remaining} remaining")

        if bottlenecks:
            anomalies.append(f"Bottleneck sources (>80% used): {bottlenecks}")

        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.COMPLETED,
            intent=query.intent,
            api_calls_remaining_today=total_remaining,
            anomalies=anomalies,
            suggested_next=[{
                "suggested_intent": "data_quality_audit",
                "query": {
                    "intent": "data_quality_audit",
                    "region": query.region.value,
                },
                "description": "Audit data quality to decide what to collect next",
            }],
        )

    except Exception as e:
        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.FAILED,
            intent=query.intent,
            errors=[f"Campaign status failed: {str(e)}"],
        )


def _execute_discovery_scan(query: AgentQuery) -> ConciseResult:
    """DISCOVERY_SCAN — Analyze collected data to find what to collect next.

    Runs all five discovery strategies against the current DB state and
    returns ranked leads. No API calls — purely analytical.
    """
    anomalies: list[str] = []
    suggested_next: list[dict] = []

    try:
        from backend.discovery import run_discovery, get_discovery_summary

        # Run full discovery scan
        scan = run_discovery(
            region=query.region.value,
            max_leads=25,
        )

        # Build anomalies from summary
        summary = scan.summary
        anomalies.append(
            f"Industries: {summary.get('industries_with_data', 0)}/{summary.get('industries_registered', 0)} have data"
        )
        missing = summary.get("industries_missing", [])
        if missing:
            anomalies.append(f"Industries with ZERO data: {missing}")

        anomalies.append(
            f"Discovery found {scan.total_leads} leads: {scan.leads_by_type}"
        )

        # Convert top leads into suggested_next for the agent
        for lead in scan.leads[:10]:  # top 10
            proposal = lead.to_agent_proposal()
            suggested_next.append({
                "suggested_intent": lead.suggested_intent,
                "query": proposal,
                "description": lead.description,
            })

        # Add coverage summary to anomalies
        disc_summary = get_discovery_summary(query.region.value)
        brand_cov = disc_summary.get("brand_coverage", {})
        anomalies.append(
            f"Brand coverage: {brand_cov.get('with_data', 0)}/{brand_cov.get('registered', 0)} "
            f"({brand_cov.get('coverage_pct', 0)}%)"
        )
        freshness = disc_summary.get("freshness", {})
        if freshness.get("stale", 0) > 0:
            anomalies.append(
                f"Stale data: {freshness['stale']} intent/brand combos need re-collection"
            )

        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.COMPLETED,
            intent=query.intent,
            records_found=scan.total_leads,
            anomalies=anomalies,
            suggested_next=suggested_next,
        )

    except Exception as e:
        logger.error("[Executor] Discovery scan failed: %s", e, exc_info=True)
        return ConciseResult(
            query_id=query.query_id,
            status=ResultStatus.FAILED,
            intent=query.intent,
            errors=[f"Discovery scan failed: {str(e)}"],
        )


# ══════════════════════════════════════════════════════════════════════
# Intent → Handler dispatch table
# ══════════════════════════════════════════════════════════════════════

_INTENT_HANDLERS = {
    Intent.POI_CHAIN_LOCATIONS: _execute_poi_chain,
    Intent.POI_LOCAL_DENSITY: _execute_poi_local,
    Intent.WAGE_BASELINE: _execute_wage_baseline,
    Intent.JOB_POSTING_VOLUME: _execute_job_posting_volume,
    Intent.SENTIMENT_CHECK: _execute_sentiment_check,
    Intent.ECONOMIC_CONTEXT: _execute_economic_context,
    Intent.SCORE_REFRESH: _execute_score_refresh,
    Intent.DATA_QUALITY_AUDIT: _execute_data_quality_audit,
    Intent.CAMPAIGN_STATUS: _execute_campaign_status,
    Intent.DISCOVERY_SCAN: _execute_discovery_scan,
}


def _get_total_remaining_budget(query: AgentQuery) -> int:
    """Sum remaining budget across all sources relevant to this intent."""
    try:
        all_status = rate_manager.get_all_status()
        return sum(s.get("remaining", 0) for s in all_status)
    except Exception:
        return -1
