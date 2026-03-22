"""
backend/endpoint_catalog.py — Dynamic API endpoint registry.

Three responsibilities:
  1. seed_from_route_index()     — upsert ApiEndpoint rows from ROUTES + INDUSTRY_REGISTRY
  2. verify_endpoint(id)         — lightweight HTTP probe; updates health columns
  3. get_healthy_endpoints()     — query used by the orchestrator prompt builder
  4. derive_available_capabilities() — what industries/brands/intents are actually usable

The orchestrator calls get_healthy_endpoints() + derive_available_capabilities()
before each session so the system prompt only advertises what is currently live
and healthy.  A broken source is silently excluded — the agent never learns about
intents it can't actually execute.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Optional

import requests

from backend.database import (
    ApiEndpoint,
    ENDPOINT_FAILURE_THRESHOLD,
    get_engine,
    get_session,
)

logger = logging.getLogger(__name__)

# ── Probe config ───────────────────────────────────────────────────────────────

_PROBE_TIMEOUT = 8          # seconds per health-check request
_INTER_PROBE_SLEEP = 0.4    # seconds between probes to avoid burst hammering

# Maps source_key → (probe_url, expected_status_codes)
# If a source_key is absent, the endpoint is verified by last_success_at staleness only.
_PROBE_MAP: dict[str, tuple[str, list[int]]] = {
    "atp_geojson":      ("https://data.alltheplaces.xyz/runs/latest/info.json", [200]),
    "overture_s3":      ("https://overturemaps.org", [200, 301, 302]),
    "overpass_api":     ("https://overpass-api.de/api/status", [200]),
    "bls_v1":           ("https://api.bls.gov/publicAPI/v2/timeseries/data/", [200]),
    "careers_workday":  ("https://www.indeed.com", [200, 301, 302]),   # careers pages vary; use indeed as proxy
    "jobspy":           ("https://www.indeed.com", [200, 301, 302]),
    "reddit_json":      ("https://www.reddit.com/r/starbucksbaristas/about.json", [200]),
    "reddit_oauth":     ("https://oauth.reddit.com", [200, 401]),       # 401 = reachable but needs auth
    "gmaps_scraper":    None,   # no probe — requires API key; use staleness only
}

# Adapters with no external source (DB-only) — always considered healthy
_DB_ONLY_ADAPTERS = {None, ""}

# ── Initial seed fixture ───────────────────────────────────────────────────────
# Defines the canonical set of (adapter, intent, metadata) rows.
# Derived from pipeline/route_index.py ROUTES + known adapter capabilities.
# industries/brands == None means the adapter covers all.

_SEED_FIXTURES: list[dict] = [
    # poi_chain_locations
    {
        "adapter_name": "AllThePlacesAdapter",
        "scraper_module": "scrapers.alltheplaces_adapter",
        "source_key": "atp_geojson",
        "intent": "poi_chain_locations",
        "data_type": "Store",
        "route_status": "live",
        "base_url": "https://data.alltheplaces.xyz",
        "url_pattern": "https://data.alltheplaces.xyz/runs/latest/output/{spider}.geojson",
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 6.0,
        "notes": "Primary chain-location source. ATP spider map keyed by Brand enum.",
    },
    {
        "adapter_name": "OvertureChainAdapter",
        "scraper_module": "scrapers.overture_adapter",
        "source_key": "overture_s3",
        "intent": "poi_chain_locations",
        "data_type": "Store",
        "route_status": "live",
        "base_url": "https://overturemaps.org",
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 24.0,
        "notes": "Secondary source. Overture Maps place dataset filtered by Wikidata ID.",
    },
    {
        "adapter_name": "OSMAdapter",
        "scraper_module": "scrapers.osm_adapter",
        "source_key": "overpass_api",
        "intent": "poi_chain_locations",
        "data_type": "Store",
        "route_status": "unwired",
        "base_url": "https://overpass-api.de",
        "url_pattern": "https://overpass-api.de/api/interpreter",
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 6.0,
        "notes": "Tertiary — adapter exists but executor does not call it for chain locations yet.",
    },
    # poi_local_density
    {
        "adapter_name": "OvertureLocalAdapter",
        "scraper_module": "scrapers.overture_adapter",
        "source_key": "overture_s3",
        "intent": "poi_local_density",
        "data_type": "Store",
        "route_status": "live",
        "base_url": "https://overturemaps.org",
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 24.0,
        "notes": "Fetches non-chain places from Overture filtered by industry category.",
    },
    {
        "adapter_name": "OSMAdapter",
        "scraper_module": "scrapers.osm_adapter",
        "source_key": "overpass_api",
        "intent": "poi_local_density",
        "data_type": "Store",
        "route_status": "unwired",
        "base_url": "https://overpass-api.de",
        "url_pattern": "https://overpass-api.de/api/interpreter",
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 6.0,
        "notes": "Can fetch local places by OSM amenity tag — not yet called from executor.",
    },
    # wage_baseline
    {
        "adapter_name": "BLSAdapter",
        "scraper_module": "scrapers.bls_adapter",
        "source_key": "bls_v1",
        "intent": "wage_baseline",
        "data_type": "WageIndex",
        "route_status": "live",
        "base_url": "https://api.bls.gov",
        "url_pattern": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 24.0,
        "notes": "BLS OEWS series by industry/region. Series IDs hardcoded in executor.py.",
    },
    # job_posting_volume
    {
        "adapter_name": "CareersAPIScraper",
        "scraper_module": "scrapers.careers_api",
        "source_key": "careers_workday",
        "intent": "job_posting_volume",
        "data_type": "Signal",
        "route_status": "live",
        "base_url": "https://jobs.lever.co",
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 4.0,
        "notes": "Scrapes Workday/Greenhouse/Lever career pages. Primary job source.",
    },
    {
        "adapter_name": "JobSpyAdapter",
        "scraper_module": "scrapers.jobspy_adapter",
        "source_key": "jobspy",
        "intent": "job_posting_volume",
        "data_type": "Signal",
        "route_status": "live",
        "base_url": "https://www.indeed.com",
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 4.0,
        "notes": "Indeed/LinkedIn/ZipRecruiter aggregator via JobSpy library.",
    },
    # sentiment_check
    {
        "adapter_name": "RedditAdapter",
        "scraper_module": "scrapers.reddit_adapter",
        "source_key": "reddit_json",
        "intent": "sentiment_check",
        "data_type": "Signal",
        "route_status": "live",
        "base_url": "https://www.reddit.com",
        "url_pattern": "https://www.reddit.com/r/{subreddit}/search.json",
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 2.0,
        "notes": "Public Reddit JSON API. No OAuth — limited to recent posts.",
    },
    {
        "adapter_name": "RedditAdapter",
        "scraper_module": "scrapers.reddit_adapter",
        "source_key": "reddit_oauth",
        "intent": "sentiment_check",
        "data_type": "Signal",
        "route_status": "suggested",
        "base_url": "https://oauth.reddit.com",
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 2.0,
        "notes": "Authenticated Reddit API — higher limits. Needs REDDIT_CLIENT_ID/SECRET.",
    },
    {
        "adapter_name": "ReviewsAdapter",
        "scraper_module": "scrapers.reviews_adapter",
        "source_key": "gmaps_scraper",
        "intent": "sentiment_check",
        "data_type": "Signal",
        "route_status": "unwired",
        "base_url": None,
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 24.0,
        "notes": "Google Maps / Glassdoor star ratings. Adapter exists; not called from executor.",
    },
    # economic_context
    {
        "adapter_name": "BLSAdapter",
        "scraper_module": "scrapers.bls_adapter",
        "source_key": "bls_v1",
        "intent": "economic_context",
        "data_type": "WageIndex",
        "route_status": "live",
        "base_url": "https://api.bls.gov",
        "url_pattern": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 24.0,
        "notes": "Reuses BLSAdapter for unemployment and CPI series.",
    },
    # DB-internal intents — always healthy, no external calls
    {
        "adapter_name": "_internal",
        "scraper_module": None,
        "source_key": "",
        "intent": "score_refresh",
        "data_type": "Score",
        "route_status": "live",
        "base_url": None,
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 999.0,
        "notes": "DB-internal compute — no external API. Always healthy.",
    },
    {
        "adapter_name": "_internal",
        "scraper_module": None,
        "source_key": "",
        "intent": "data_quality_audit",
        "data_type": "Store",
        "route_status": "live",
        "base_url": None,
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 999.0,
        "notes": "DB-internal read — queries Store/Signal/WageIndex/Score for staleness.",
    },
    {
        "adapter_name": "_internal",
        "scraper_module": None,
        "source_key": "",
        "intent": "campaign_status",
        "data_type": "RateBudget",
        "route_status": "live",
        "base_url": None,
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 999.0,
        "notes": "DB-internal read — returns queue + budget state.",
    },
    {
        "adapter_name": "_internal",
        "scraper_module": None,
        "source_key": "",
        "intent": "discovery_scan",
        "data_type": "Store",
        "route_status": "live",
        "base_url": None,
        "url_pattern": None,
        "industries": None,
        "brands": None,
        "health_check_freshness_hours": 999.0,
        "notes": "DB-internal analysis — ranks stores by staleness and score gap.",
    },
]


# ══════════════════════════════════════════════════════════════════════
# 1. Seeder
# ══════════════════════════════════════════════════════════════════════

def seed_from_route_index(
    overwrite_health: bool = False,
    db_session=None,
) -> dict:
    """Upsert ApiEndpoint rows from the canonical _SEED_FIXTURES list.

    Idempotent — re-running does not reset health columns unless
    overwrite_health=True.

    Args:
        overwrite_health: If True, reset consecutive_failures, last_verified_at,
                          etc. even for rows that already exist.
        db_session:       Inject for testing; creates and closes one if None.

    Returns:
        {"inserted": N, "updated": N, "skipped": N}
    """
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    counts = {"inserted": 0, "updated": 0, "skipped": 0}

    try:
        for fixture in _SEED_FIXTURES:
            existing = db_session.query(ApiEndpoint).filter(
                ApiEndpoint.adapter_name == fixture["adapter_name"],
                ApiEndpoint.source_key == (fixture.get("source_key") or ""),
                ApiEndpoint.intent == fixture["intent"],
            ).first()

            if existing:
                # Update non-health metadata columns
                existing.scraper_module  = fixture["scraper_module"]
                existing.source_key      = fixture["source_key"]
                existing.data_type       = fixture["data_type"]
                existing.route_status    = fixture["route_status"]
                existing.base_url        = fixture["base_url"]
                existing.url_pattern     = fixture["url_pattern"]
                existing.notes           = fixture.get("notes")
                existing.health_check_freshness_hours = fixture["health_check_freshness_hours"]

                # Only update coverage scope if not overriding (allow manual edits to persist)
                if overwrite_health or existing.industries_json is None:
                    existing.industries = fixture.get("industries")
                if overwrite_health or existing.brands_json is None:
                    existing.brands = fixture.get("brands")
                existing.regions = fixture.get("regions")

                if overwrite_health:
                    existing.consecutive_failures = 0
                    existing.last_verified_at     = None
                    existing.last_success_at      = None
                    existing.last_failure_reason  = None
                    existing.is_active            = True

                existing.updated_at = datetime.utcnow()
                counts["updated"] += 1
            else:
                ep = ApiEndpoint(
                    adapter_name=fixture["adapter_name"],
                    scraper_module=fixture["scraper_module"],
                    source_key=fixture["source_key"],
                    intent=fixture["intent"],
                    data_type=fixture["data_type"],
                    route_status=fixture["route_status"],
                    base_url=fixture["base_url"],
                    url_pattern=fixture["url_pattern"],
                    notes=fixture.get("notes"),
                    health_check_freshness_hours=fixture["health_check_freshness_hours"],
                    is_active=True,
                    consecutive_failures=0,
                    success_count=0,
                    failure_count=0,
                )
                ep.industries = fixture.get("industries")
                ep.brands     = fixture.get("brands")
                ep.regions    = fixture.get("regions")
                db_session.add(ep)
                counts["inserted"] += 1

        db_session.commit()
        logger.info(
            "[EndpointCatalog] Seed complete — inserted=%d updated=%d skipped=%d",
            counts["inserted"], counts["updated"], counts["skipped"],
        )
        return counts

    except Exception as e:
        db_session.rollback()
        logger.error("[EndpointCatalog] Seed failed: %s", e)
        raise
    finally:
        if close_session:
            db_session.close()


# ══════════════════════════════════════════════════════════════════════
# 2. Verifier
# ══════════════════════════════════════════════════════════════════════

def verify_endpoint(endpoint_id: int, db_session=None) -> dict:
    """Probe a single endpoint and update its health columns.

    Returns a summary dict describing what changed.
    """
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    try:
        ep = db_session.query(ApiEndpoint).filter(ApiEndpoint.id == endpoint_id).first()
        if not ep:
            return {"error": f"Endpoint {endpoint_id} not found"}

        # DB-internal adapters are always healthy
        if ep.adapter_name == "_internal" or ep.source_key == "":
            ep.last_verified_at = datetime.utcnow()
            ep.last_success_at  = datetime.utcnow()
            ep.is_active        = True
            ep.consecutive_failures = 0
            db_session.commit()
            return {
                "id": endpoint_id,
                "adapter_name": ep.adapter_name,
                "intent": ep.intent,
                "result": "healthy",
                "reason": "db-internal — no probe needed",
            }

        probe_cfg = _PROBE_MAP.get(ep.source_key)
        probe_succeeded = False
        failure_reason  = None

        if probe_cfg is None:
            # No probe defined — use staleness heuristic
            if ep.last_success_at:
                age_hours = (datetime.utcnow() - ep.last_success_at).total_seconds() / 3600
                probe_succeeded = age_hours < (ep.health_check_freshness_hours * 2)
                failure_reason = None if probe_succeeded else f"no probe available; last success {age_hours:.0f}h ago"
            else:
                # Never succeeded — leave is_active as-is, just stamp verified
                ep.last_verified_at = datetime.utcnow()
                db_session.commit()
                return {
                    "id": endpoint_id,
                    "adapter_name": ep.adapter_name,
                    "intent": ep.intent,
                    "result": "unknown",
                    "reason": "no probe defined and no prior success recorded",
                }
        else:
            probe_url, expected_codes = probe_cfg
            try:
                resp = requests.get(
                    probe_url,
                    timeout=_PROBE_TIMEOUT,
                    headers={"User-Agent": "first-helios-healthcheck/1.0"},
                    allow_redirects=True,
                )
                probe_succeeded = resp.status_code in expected_codes
                if not probe_succeeded:
                    failure_reason = f"HTTP {resp.status_code}"
            except requests.exceptions.ConnectionError:
                failure_reason = "connection refused"
            except requests.exceptions.Timeout:
                failure_reason = "probe timeout"
            except Exception as exc:
                failure_reason = str(exc)[:120]

        # Update health columns
        was_active = ep.is_active
        ep.last_verified_at = datetime.utcnow()

        if probe_succeeded:
            ep.last_success_at      = datetime.utcnow()
            ep.success_count        += 1
            ep.consecutive_failures = 0
            ep.last_failure_reason  = None
            ep.is_active            = True
        else:
            ep.failure_count        += 1
            ep.consecutive_failures += 1
            ep.last_failure_reason  = failure_reason
            if ep.consecutive_failures >= ENDPOINT_FAILURE_THRESHOLD:
                ep.is_active = False

        db_session.commit()

        became_inactive = was_active and not ep.is_active
        recovered       = not was_active and ep.is_active

        if became_inactive:
            logger.warning(
                "[EndpointCatalog] DEACTIVATED %s/%s after %d failures: %s",
                ep.adapter_name, ep.intent, ep.consecutive_failures, failure_reason,
            )
        if recovered:
            logger.info("[EndpointCatalog] RECOVERED %s/%s", ep.adapter_name, ep.intent)

        return {
            "id": endpoint_id,
            "adapter_name": ep.adapter_name,
            "intent": ep.intent,
            "result": "healthy" if probe_succeeded else "unhealthy",
            "reason": failure_reason,
            "is_active": ep.is_active,
            "consecutive_failures": ep.consecutive_failures,
            "became_inactive": became_inactive,
            "recovered": recovered,
        }

    except Exception as e:
        logger.error("[EndpointCatalog] verify_endpoint(%d) failed: %s", endpoint_id, e)
        if not close_session:
            db_session.rollback()
        raise
    finally:
        if close_session:
            db_session.close()


def verify_all_endpoints(
    skip_recently_verified_hours: float = 4.0,
    db_session=None,
) -> dict:
    """Probe all non-suggested endpoints, skipping recently verified ones.

    Returns:
        {
            "total": N, "checked": N, "skipped": N,
            "deactivated": [...], "recovered": [...],
        }
    """
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    try:
        rows = db_session.query(ApiEndpoint).filter(
            ApiEndpoint.route_status.in_(["live", "unwired"])
        ).all()

        results = {"total": len(rows), "checked": 0, "skipped": 0, "deactivated": [], "recovered": []}

        for ep in rows:
            # Skip if recently verified
            if ep.last_verified_at:
                age_hours = (datetime.utcnow() - ep.last_verified_at).total_seconds() / 3600
                if age_hours < skip_recently_verified_hours:
                    results["skipped"] += 1
                    continue

            outcome = verify_endpoint(ep.id, db_session=db_session)
            results["checked"] += 1

            if outcome.get("became_inactive"):
                results["deactivated"].append(outcome)
            if outcome.get("recovered"):
                results["recovered"].append(outcome)

            time.sleep(_INTER_PROBE_SLEEP)

        return results

    finally:
        if close_session:
            db_session.close()


# ══════════════════════════════════════════════════════════════════════
# 3. Query helpers
# ══════════════════════════════════════════════════════════════════════

def get_healthy_endpoints(
    intents: Optional[list[str]] = None,
    industries: Optional[list[str]] = None,
    include_unwired: bool = False,
    db_session=None,
) -> list[ApiEndpoint]:
    """Return active, healthy endpoint rows for the given filters.

    This is the primary query the orchestrator prompt builder calls.
    Falls back gracefully — if the table is empty the orchestrator's
    fallback path activates automatically.
    """
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    try:
        statuses = ["live", "unwired"] if include_unwired else ["live"]
        query = db_session.query(ApiEndpoint).filter(
            ApiEndpoint.is_active == True,
            ApiEndpoint.consecutive_failures < ENDPOINT_FAILURE_THRESHOLD,
            ApiEndpoint.route_status.in_(statuses),
        )

        if intents:
            query = query.filter(ApiEndpoint.intent.in_(intents))

        rows = query.order_by(ApiEndpoint.adapter_name, ApiEndpoint.intent).all()

        # Apply industries filter in Python (JSON column)
        if industries:
            rows = [
                ep for ep in rows
                if ep.industries is None  # NULL = covers all industries
                or any(ind in (ep.industries or []) for ind in industries)
            ]

        # Detach from session so they're safe to use after close
        for ep in rows:
            db_session.expunge(ep)

        return rows

    finally:
        if close_session:
            db_session.close()


def get_all_endpoints(db_session=None) -> list[ApiEndpoint]:
    """Return every endpoint row regardless of health — for the catalog UI."""
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    try:
        rows = db_session.query(ApiEndpoint).order_by(
            ApiEndpoint.intent, ApiEndpoint.adapter_name
        ).all()
        for ep in rows:
            db_session.expunge(ep)
        return rows
    finally:
        if close_session:
            db_session.close()


def get_endpoint_by_id(endpoint_id: int, db_session=None) -> Optional[ApiEndpoint]:
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    try:
        ep = db_session.query(ApiEndpoint).filter(ApiEndpoint.id == endpoint_id).first()
        if ep:
            db_session.expunge(ep)
        return ep
    finally:
        if close_session:
            db_session.close()


def set_endpoint_active(endpoint_id: int, active: bool, db_session=None) -> Optional[dict]:
    """Manually activate or deactivate an endpoint, overriding auto-deactivation."""
    close_session = db_session is None
    if db_session is None:
        db_session = get_session(get_engine())

    try:
        ep = db_session.query(ApiEndpoint).filter(ApiEndpoint.id == endpoint_id).first()
        if not ep:
            return None
        ep.is_active = active
        if active:
            ep.consecutive_failures = 0   # reset so it's not immediately re-deactivated
        ep.updated_at = datetime.utcnow()
        db_session.commit()
        db_session.refresh(ep)
        db_session.expunge(ep)
        return ep.to_dict()
    except Exception as e:
        db_session.rollback()
        logger.error("[EndpointCatalog] set_endpoint_active(%d) failed: %s", endpoint_id, e)
        raise
    finally:
        if close_session:
            db_session.close()


# ══════════════════════════════════════════════════════════════════════
# 4. Capability derivation
# ══════════════════════════════════════════════════════════════════════

def derive_available_capabilities(endpoints: list[ApiEndpoint]) -> dict:
    """From a set of healthy endpoints, derive what the agent can actually use.

    Returns:
        {
            "available_intents": [...],
            "available_industries": [...],   # None = all (no restriction)
            "available_brands": [...],       # None = all (no restriction)
            "coverage_by_intent": {
                intent: {"adapters": [...], "industries": [...] | None, "brands": [...] | None}
            }
        }
    """
    available_intents: set[str] = set()
    # Track per-intent whether any adapter covers ALL industries/brands (NULL)
    intent_all_industries: set[str] = set()
    intent_all_brands: set[str] = set()
    intent_industries: dict[str, set[str]] = {}
    intent_brands: dict[str, set[str]] = {}
    intent_adapters: dict[str, list[str]] = {}

    for ep in endpoints:
        intent = ep.intent
        available_intents.add(intent)

        intent_adapters.setdefault(intent, [])
        if ep.adapter_name not in intent_adapters[intent]:
            intent_adapters[intent].append(ep.adapter_name)

        if ep.industries is None:
            intent_all_industries.add(intent)
        else:
            intent_industries.setdefault(intent, set()).update(ep.industries)

        if ep.brands is None:
            intent_all_brands.add(intent)
        else:
            intent_brands.setdefault(intent, set()).update(ep.brands)

    # For the overall available_industries / available_brands:
    # If ANY intent has a NULL (covers all), the entire dimension is unrestricted.
    all_industries_unrestricted = bool(intent_all_industries)
    all_brands_unrestricted = bool(intent_all_brands)

    all_industries = None if all_industries_unrestricted else sorted(
        {ind for s in intent_industries.values() for ind in s}
    )
    all_brands = None if all_brands_unrestricted else sorted(
        {b for s in intent_brands.values() for b in s}
    )

    coverage: dict[str, dict] = {}
    for intent in available_intents:
        coverage[intent] = {
            "adapters": intent_adapters.get(intent, []),
            "industries": None if intent in intent_all_industries else sorted(intent_industries.get(intent, set())),
            "brands": None if intent in intent_all_brands else sorted(intent_brands.get(intent, set())),
        }

    return {
        "available_intents": sorted(available_intents),
        "available_industries": all_industries,
        "available_brands": all_brands,
        "coverage_by_intent": coverage,
    }
