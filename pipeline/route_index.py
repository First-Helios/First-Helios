"""
pipeline/route_index.py — The single source of truth for every data route in Helios.

A route is the complete path from an agent intent to a database write:

    intent (enum) → source_key → scraper_adapter → signal_type → db_table

ROUTES is a dict[intent_value → list[RouteContract]].  Each intent can have
multiple routes (e.g. job_posting_volume uses both careers_workday and jobspy).

Statuses
--------
  live      — adapter is wired in executor.py and actively called
  unwired   — adapter class exists in scrapers/ but executor.py does not call it
  suggested — not yet implemented, documented here as a future data source

Usage by the agent pilot
------------------------
    from pipeline.route_index import ROUTES

    routes = ROUTES["poi_chain_locations"]
    live = [r for r in routes if r.status == "live"]
    print(live[0].scraper_adapter)  # "AllThePlacesAdapter"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agent_interface.schemas import FRESHNESS_THRESHOLDS


@dataclass
class RouteContract:
    """Describes one concrete path through the pipeline for a given intent.

    Fields
    ------
    intent                  intent enum value (str)
    source_key              rate-manager key used for budget tracking
                            (matches INTENT_SOURCE_MAP in validator.py);
                            None for DB-only intents
    scraper_adapter         class name of the BaseScraper subclass; None for
                            internal/DB-only intents
    scraper_module          dotted module path for the adapter class
    signal_type             value written to Signal.signal_type
                            (None for Store/WageIndex-only paths)
    db_table                primary table this route writes to
    freshness_threshold_days how many days before data is considered stale
    status                  "live" | "unwired" | "suggested"
    notes                   free-text for the agent pilot to read
    """

    intent: str
    db_table: str
    freshness_threshold_days: float
    status: str                             # "live" | "unwired" | "suggested"
    source_key: Optional[str] = None
    scraper_adapter: Optional[str] = None
    scraper_module: Optional[str] = None
    signal_type: Optional[str] = None
    notes: str = ""


# ── Route definitions ─────────────────────────────────────────────────────────
#
# Organized by intent.  Each list entry is one concrete source/adapter pair.
# Internal intents (score_refresh, data_quality_audit, campaign_status,
# discovery_scan) have a single entry with no scraper.

ROUTES: dict[str, list[RouteContract]] = {

    # ── poi_chain_locations ───────────────────────────────────────────────────
    # Find all locations for a chain brand in the region.
    # Primary: AllThePlaces GeoJSON (crowdsourced, most complete for chains)
    # Secondary: Overture Maps S3 (commercial, good coverage)
    # Tertiary: OpenStreetMap Overpass (open data, lower recall)

    "poi_chain_locations": [
        RouteContract(
            intent="poi_chain_locations",
            source_key="atp_geojson",
            scraper_adapter="AllThePlacesAdapter",
            scraper_module="scrapers.alltheplaces_adapter",
            signal_type="listing",
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["poi_chain_locations"],
            status="live",
            notes=(
                "Primary source. Uses ATP spider map keyed by Brand enum. "
                "Geocoding runs on addresses without coordinates."
            ),
        ),
        RouteContract(
            intent="poi_chain_locations",
            source_key="overture_s3",
            scraper_adapter="OvertureChainAdapter",
            scraper_module="scrapers.overture_adapter",
            signal_type="listing",
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["poi_chain_locations"],
            status="live",
            notes=(
                "Secondary source. Uses Overture Maps place dataset. "
                "Filtered by brand Wikidata ID and region bounding box."
            ),
        ),
        RouteContract(
            intent="poi_chain_locations",
            source_key="overpass_api",
            scraper_adapter="OSMAdapter",
            scraper_module="scrapers.osm_adapter",
            signal_type="listing",
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["poi_chain_locations"],
            status="unwired",
            notes=(
                "OSMAdapter exists and is functional but _execute_poi_chain() "
                "does not call it. Wire as tertiary fallback when ATP + Overture "
                "return < expected coverage."
            ),
        ),
    ],

    # ── poi_local_density ─────────────────────────────────────────────────────
    # Count local (non-chain) employers in an industry near chain stores.
    # Local density is the competitive context around a target chain location.

    "poi_local_density": [
        RouteContract(
            intent="poi_local_density",
            source_key="overture_s3",
            scraper_adapter="OvertureLocalAdapter",
            scraper_module="scrapers.overture_adapter",
            signal_type="listing",
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["poi_local_density"],
            status="live",
            notes=(
                "Fetches non-chain places from Overture Maps filtered by "
                "industry category and region bounding box."
            ),
        ),
        RouteContract(
            intent="poi_local_density",
            source_key="overpass_api",
            scraper_adapter="OSMAdapter",
            scraper_module="scrapers.osm_adapter",
            signal_type="listing",
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["poi_local_density"],
            status="unwired",
            notes=(
                "OSMAdapter can fetch local places by OSM amenity tag. "
                "Not yet called from _execute_poi_local()."
            ),
        ),
    ],

    # ── wage_baseline ─────────────────────────────────────────────────────────
    # Fetch BLS wage data for an industry/region.
    # Single source — BLS OEWS API is the authoritative wage dataset.

    "wage_baseline": [
        RouteContract(
            intent="wage_baseline",
            source_key="bls_v1",
            scraper_adapter="BLSAdapter",
            scraper_module="scrapers.bls_adapter",
            signal_type="wage",
            db_table="WageIndex",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["wage_baseline"],
            status="live",
            notes=(
                "Pulls BLS OEWS series for the matching industry and region. "
                "Austin TX series IDs are hardcoded in executor.py AUSTIN_BLS_SERIES."
            ),
        ),
    ],

    # ── job_posting_volume ────────────────────────────────────────────────────
    # Count open job postings for a brand in the region.
    # Two live sources: Workday (official careers pages) and JobSpy (aggregator).

    "job_posting_volume": [
        RouteContract(
            intent="job_posting_volume",
            source_key="careers_workday",
            scraper_adapter="CareersAPIScraper",
            scraper_module="scrapers.careers_api",
            signal_type="listing",
            db_table="Signal",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["job_posting_volume"],
            status="live",
            notes=(
                "Scrapes brand careers pages (Workday, Greenhouse, Lever). "
                "Primary source — reflects ground-truth posted positions."
            ),
        ),
        RouteContract(
            intent="job_posting_volume",
            source_key="jobspy",
            scraper_adapter="JobSpyAdapter",
            scraper_module="scrapers.jobspy_adapter",
            signal_type="listing",
            db_table="Signal",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["job_posting_volume"],
            status="live",
            notes=(
                "Aggregator (Indeed, LinkedIn, ZipRecruiter, Glassdoor). "
                "Used when careers page is not directly accessible."
            ),
        ),
    ],

    # ── sentiment_check ───────────────────────────────────────────────────────
    # Gather worker sentiment from Reddit and reviews for a brand.

    "sentiment_check": [
        RouteContract(
            intent="sentiment_check",
            source_key="reddit_json",
            scraper_adapter="RedditAdapter",
            scraper_module="scrapers.reddit_adapter",
            signal_type="sentiment",
            db_table="Signal",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["sentiment_check"],
            status="live",
            notes=(
                "Searches r/starbucksbaristas, r/Target, etc. via Reddit "
                "public JSON API. No OAuth — limited to recent posts."
            ),
        ),
        RouteContract(
            intent="sentiment_check",
            source_key="reddit_oauth",
            scraper_adapter="RedditAdapter",
            scraper_module="scrapers.reddit_adapter",
            signal_type="sentiment",
            db_table="Signal",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["sentiment_check"],
            status="suggested",
            notes=(
                "Authenticated Reddit API — higher rate limits and historical "
                "access. Requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars."
            ),
        ),
        RouteContract(
            intent="sentiment_check",
            source_key="gmaps_scraper",
            scraper_adapter="ReviewsAdapter",
            scraper_module="scrapers.reviews_adapter",
            signal_type="review_score",
            db_table="Signal",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["sentiment_check"],
            status="unwired",
            notes=(
                "ReviewsAdapter scrapes Google Maps / Glassdoor star ratings. "
                "Adapter is complete but _execute_sentiment_check() does not "
                "call it. Wire as secondary signal to complement Reddit text."
            ),
        ),
    ],

    # ── economic_context ──────────────────────────────────────────────────────
    # Fetch macro-economic indicators (unemployment, CPI) for the region.

    "economic_context": [
        RouteContract(
            intent="economic_context",
            source_key="bls_v1",
            scraper_adapter="BLSAdapter",
            scraper_module="scrapers.bls_adapter",
            signal_type="wage",
            db_table="WageIndex",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["economic_context"],
            status="live",
            notes=(
                "Reuses BLSAdapter for unemployment and CPI series. "
                "Series IDs for Austin TX are in AUSTIN_BLS_SERIES in executor.py."
            ),
        ),
    ],

    # ── score_refresh — internal compute, no external calls ───────────────────
    # Recompute composite staffing scores using latest Signal/WageIndex data.

    "score_refresh": [
        RouteContract(
            intent="score_refresh",
            source_key=None,
            scraper_adapter=None,
            scraper_module=None,
            signal_type=None,
            db_table="Score",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["score_refresh"],
            status="live",
            notes=(
                "Calls backend.scoring.engine.compute_all_scores(). "
                "No external API calls. Reads Signal + WageIndex, writes Score rows."
            ),
        ),
    ],

    # ── data_quality_audit — DB-only read ─────────────────────────────────────
    # Check for stale, missing, or conflicting data across all tables.

    "data_quality_audit": [
        RouteContract(
            intent="data_quality_audit",
            source_key=None,
            scraper_adapter=None,
            scraper_module=None,
            signal_type=None,
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["data_quality_audit"],
            status="live",
            notes=(
                "Queries Store, Signal, WageIndex, Score for staleness and gaps. "
                "No writes. Returns anomaly list in ConciseResult.anomalies."
            ),
        ),
    ],

    # ── campaign_status — queue + budget read ─────────────────────────────────
    # Report on queue state and rate-limit budget usage.

    "campaign_status": [
        RouteContract(
            intent="campaign_status",
            source_key=None,
            scraper_adapter=None,
            scraper_module=None,
            signal_type=None,
            db_table="RateBudget",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["campaign_status"],
            status="live",
            notes=(
                "Reads RateBudget and RateLimitEntry via rate_manager. "
                "Returns QueueStatus payload — no DB writes."
            ),
        ),
    ],

    # ── discovery_scan — DB analysis to find collection targets ───────────────
    # Analyze collected data to find coverage gaps, stale stores, and new targets.

    "discovery_scan": [
        RouteContract(
            intent="discovery_scan",
            source_key=None,
            scraper_adapter=None,
            scraper_module=None,
            signal_type=None,
            db_table="Store",
            freshness_threshold_days=FRESHNESS_THRESHOLDS["discovery_scan"],
            status="live",
            notes=(
                "Reads Store, Signal, Score. Ranks stores by staleness and score gap. "
                "Returns suggested_next list of AgentQuery dicts for the pilot."
            ),
        ),
    ],
}
