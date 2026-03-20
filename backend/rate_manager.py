"""
backend/rate_manager.py

Centralized rate-limit tracking and request logging for every external API.

Every source gets a row in api_sources with a REQUIRED daily_limit (10000 default
for uncapped sources).  Every HTTP request is logged to api_request_log with success/
fail status, latency, and data yield.  Daily rollups in rate_budgets power the
/api/rate-budget dashboard.

Design goals:
  - Index ALL external sources, not just rate-limited ones
  - Track success/fail rates and latency per source
  - Predict daily budget exhaustion at current pace
  - Provide metrics for scalability planning

Usage:
    from backend.rate_manager import rate_manager  # singleton

    # Before making a request:
    if rate_manager.can_request("bls_v1"):
        t0 = time.time()
        resp = requests.get(url)
        rate_manager.log_request(
            source_key="bls_v1",
            request_type="series_fetch",
            url=url,
            method="GET",
            status_code=resp.status_code,
            success=resp.ok,
            latency_ms=int((time.time() - t0) * 1000),
            response_bytes=len(resp.content),
            data_items=5,
        )

Depends on: backend.database
Called by: all scrapers, server.py /api/rate-budget
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.database import (
    ApiRequestLog,
    ApiSource,
    RateBudget,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Master Source Registry
# Every external API the system touches.  daily_limit is required.
# Set to 10000 for sources with no known hard cap.
# ═══════════════════════════════════════════════════════════════════════

API_SOURCE_REGISTRY: list[dict] = [
    # ── BLS ──────────────────────────────────────────────────────
    {
        "source_key": "bls_v1",
        "display_name": "BLS Public Data API (v1, no key)",
        "base_url": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        "auth_type": "none",
        "daily_limit": 500,
        "min_delay_seconds": 1.0,
        "reset_hour_utc": 0,
        "notes": "25 req/day @ daily limit for unregistered. 500 w/ registration.",
    },
    {
        "source_key": "bls_v1_post",
        "display_name": "BLS V1 POST (populate_reference_data)",
        "base_url": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        "auth_type": "none",
        "daily_limit": 500,
        "min_delay_seconds": 1.0,
        "reset_hour_utc": 0,
        "notes": "Shared daily limit with bls_v1. POST batches multiple series.",
    },
    # ── Careers / Workday ────────────────────────────────────────
    {
        "source_key": "careers_workday",
        "display_name": "Starbucks Workday Careers API",
        "base_url": "https://starbucks.wd1.myworkdayjobs.com/wday/cxs/starbucks/",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 1.0,
        "reset_hour_utc": 0,
        "notes": "No published limit. Paginated JSON API with session cookies.",
    },
    {
        "source_key": "workday_playwright",
        "display_name": "Workday SPA (Playwright fallback)",
        "base_url": "https://starbucks.wd1.myworkdayjobs.com/StarbucksExternalCareerSite",
        "auth_type": "browser",
        "daily_limit": 10000,
        "min_delay_seconds": 2.0,
        "reset_hour_utc": 0,
        "notes": "Headless Chromium fallback when JSON API returns 422.",
    },
    # ── Geocoding ────────────────────────────────────────────────
    {
        "source_key": "nominatim",
        "display_name": "OSM Nominatim Geocoder",
        "base_url": "https://nominatim.openstreetmap.org",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 1.1,
        "reset_hour_utc": 0,
        "notes": "Hard limit 1 req/sec. ~86400 theoretical/day. Use 10k as planning cap.",
    },
    # ── Overpass (OSM) ───────────────────────────────────────────
    {
        "source_key": "overpass_api",
        "display_name": "OSM Overpass API",
        "base_url": "https://overpass-api.de/api/interpreter",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 1.0,
        "reset_hour_utc": 0,
        "notes": "Global fair-use ~10k/day. Heavy queries cost more.",
    },
    # ── AllThePlaces ─────────────────────────────────────────────
    {
        "source_key": "atp_geojson",
        "display_name": "AllThePlaces GeoJSON Download",
        "base_url": "https://data.alltheplaces.xyz/runs/latest/output/",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 0.0,
        "reset_hour_utc": 0,
        "notes": "Static file download. No rate limit. CC-0 licensed.",
    },
    {
        "source_key": "atp_parquet",
        "display_name": "AllThePlaces Parquet (DuckDB httpfs)",
        "base_url": "https://data.alltheplaces.xyz/",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 0.0,
        "reset_hour_utc": 0,
        "notes": "DuckDB range-request queries over HTTP. No explicit limit.",
    },
    # ── Overture Maps ────────────────────────────────────────────
    {
        "source_key": "overture_s3",
        "display_name": "Overture Maps S3 Parquet",
        "base_url": "s3://overturemaps-us-west-2/release/",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 0.0,
        "reset_hour_utc": 0,
        "notes": "Public S3 bucket. DuckDB httpfs + spatial. No limit.",
    },
    # ── Job boards ───────────────────────────────────────────────
    {
        "source_key": "jobspy",
        "display_name": "JobSpy (Indeed + Glassdoor)",
        "base_url": "https://www.indeed.com/",
        "auth_type": "none",
        "daily_limit": 50,
        "min_delay_seconds": 5.0,
        "reset_hour_utc": 0,
        "notes": "Aggressive rate limiting from job boards. python-jobspy handles internally.",
    },
    # ── Reddit ───────────────────────────────────────────────────
    {
        "source_key": "reddit_json",
        "display_name": "Reddit Public JSON API",
        "base_url": "https://www.reddit.com/",
        "auth_type": "none",
        "daily_limit": 100,
        "min_delay_seconds": 2.0,
        "reset_hour_utc": 0,
        "notes": "No-auth fallback. Conservative limit.",
    },
    {
        "source_key": "reddit_oauth",
        "display_name": "Reddit OAuth API (PRAW)",
        "base_url": "https://oauth.reddit.com/",
        "auth_type": "oauth",
        "daily_limit": 1000,
        "min_delay_seconds": 1.0,
        "reset_hour_utc": 0,
        "notes": "Requires REDDIT_CLIENT_ID + SECRET env vars. PRAW internal limiter.",
    },
    # ── Google Maps ──────────────────────────────────────────────
    {
        "source_key": "gmaps_scraper",
        "display_name": "Google Maps Scraper (library)",
        "base_url": "https://www.google.com/maps/",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 3.0,
        "reset_hour_utc": 0,
        "notes": "Via google-maps-scraper. Optional dep — graceful degradation.",
    },
    {
        "source_key": "gmaps_playwright",
        "display_name": "Google Maps (Playwright)",
        "base_url": "https://www.google.com/maps/search/",
        "auth_type": "browser",
        "daily_limit": 10000,
        "min_delay_seconds": 1.5,
        "reset_hour_utc": 0,
        "notes": "Headless Chromium search + scrape. No explicit limit.",
    },
    # ── Wikidata ─────────────────────────────────────────────────
    {
        "source_key": "wikidata_sparql",
        "display_name": "Wikidata SPARQL Endpoint",
        "base_url": "https://query.wikidata.org/sparql",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 1.0,
        "reset_hour_utc": 0,
        "notes": "CC-0. Soft limit ~60s query timeout. Single batch per brand refresh.",
    },
    # ── Map tiles (frontend, browser-side) ───────────────────────
    {
        "source_key": "carto_tiles",
        "display_name": "CARTO Dark Basemap Tiles",
        "base_url": "https://basemaps.cartocdn.com/",
        "auth_type": "none",
        "daily_limit": 10000,
        "min_delay_seconds": 0.0,
        "reset_hour_utc": 0,
        "is_active": True,
        "notes": "Browser-side tile loading. Not tracked server-side. Included for completeness.",
    },
]


class RateManager:
    """Centralized rate budget tracking and request logging.

    Singleton-style — use the module-level `rate_manager` instance.
    """

    def __init__(self) -> None:
        self._initialized = False

    def _ensure_init(self) -> None:
        """Lazy init: create tables + seed api_sources on first use."""
        if self._initialized:
            return
        init_db()
        self._seed_sources()
        self._initialized = True

    # ── Source registry seeding ───────────────────────────────────

    def _seed_sources(self) -> None:
        """Ensure all API_SOURCE_REGISTRY rows exist in api_sources."""
        session = get_session()
        try:
            for src in API_SOURCE_REGISTRY:
                existing = session.query(ApiSource).filter_by(
                    source_key=src["source_key"]
                ).first()
                if existing:
                    # Update mutable fields
                    existing.display_name = src["display_name"]
                    existing.base_url = src.get("base_url")
                    existing.daily_limit = src["daily_limit"]
                    existing.min_delay_seconds = src.get("min_delay_seconds", 1.0)
                    existing.reset_hour_utc = src.get("reset_hour_utc", 0)
                    existing.notes = src.get("notes")
                else:
                    session.add(ApiSource(
                        source_key=src["source_key"],
                        display_name=src["display_name"],
                        base_url=src.get("base_url"),
                        auth_type=src.get("auth_type", "none"),
                        daily_limit=src["daily_limit"],
                        min_delay_seconds=src.get("min_delay_seconds", 1.0),
                        reset_hour_utc=src.get("reset_hour_utc", 0),
                        is_active=src.get("is_active", True),
                        notes=src.get("notes"),
                    ))
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("[RateManager] Source seeding error: %s", e)
        finally:
            session.close()

    # ── Budget helpers ───────────────────────────────────────────

    def _today_str(self, source_key: str) -> str:
        """Today's date string accounting for the source's reset hour."""
        session = get_session()
        try:
            src = session.query(ApiSource).filter_by(source_key=source_key).first()
            reset_hour = src.reset_hour_utc if src else 0
        finally:
            session.close()

        now = datetime.now(timezone.utc)
        if now.hour < reset_hour:
            return (now - timedelta(days=1)).date().isoformat()
        return now.date().isoformat()

    def _get_or_create_budget(self, source_key: str, session) -> RateBudget:
        """Get or create today's RateBudget row."""
        today = self._today_str(source_key)

        budget = session.query(RateBudget).filter_by(
            source_key=source_key, date=today
        ).first()

        if not budget:
            # Pull daily_limit from api_sources
            src = session.query(ApiSource).filter_by(source_key=source_key).first()
            limit = src.daily_limit if src else 10000

            budget = RateBudget(
                source_key=source_key,
                date=today,
                daily_limit=limit,
                used=0,
                succeeded=0,
                failed=0,
                total_latency_ms=0,
                total_data_items=0,
                total_bytes=0,
            )
            session.add(budget)
            session.flush()

        return budget

    # ── Public API ───────────────────────────────────────────────

    def can_request(self, source_key: str, count: int = 1) -> bool:
        """Check if daily budget allows `count` more requests."""
        self._ensure_init()
        session = get_session()
        try:
            budget = self._get_or_create_budget(source_key, session)
            return budget.remaining >= count
        finally:
            session.close()

    def log_request(
        self,
        source_key: str,
        request_type: str,
        url: Optional[str] = None,
        method: str = "GET",
        status_code: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
        response_bytes: Optional[int] = None,
        data_items: Optional[int] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Log a completed request and update the daily budget rollup.

        Returns the updated budget stats dict.
        """
        self._ensure_init()
        session = get_session()
        try:
            now = datetime.now(timezone.utc)

            # 1. Insert request log row
            log = ApiRequestLog(
                source_key=source_key,
                request_type=request_type,
                url=url,
                method=method,
                status_code=status_code,
                success=success,
                error_message=error_message,
                latency_ms=latency_ms,
                response_bytes=response_bytes,
                data_items_returned=data_items,
                request_params_json=json.dumps(params) if params else None,
                requested_at=now,
            )
            session.add(log)

            # 2. Update daily budget rollup
            budget = self._get_or_create_budget(source_key, session)
            budget.used += 1
            if success:
                budget.succeeded += 1
            else:
                budget.failed += 1
                if error_message:
                    budget.last_error = error_message[:500]
            if latency_ms:
                budget.total_latency_ms += latency_ms
            if data_items:
                budget.total_data_items += data_items
            if response_bytes:
                budget.total_bytes += response_bytes
            budget.last_request_at = now

            session.commit()

            stats = budget.to_dict()
            return stats

        except Exception as e:
            session.rollback()
            logger.error("[RateManager] log_request failed: %s", e)
            return {"error": str(e)}
        finally:
            session.close()

    def get_source_status(self, source_key: str) -> dict:
        """Return current budget + source info for one API."""
        self._ensure_init()
        session = get_session()
        try:
            src = session.query(ApiSource).filter_by(source_key=source_key).first()
            if not src:
                return {"error": f"Unknown source: {source_key}"}

            budget = self._get_or_create_budget(source_key, session)

            # Predict exhaustion at current pace
            eta_exhaustion = None
            if budget.used > 0 and budget.remaining > 0:
                try:
                    budget_date = datetime.fromisoformat(budget.date).replace(
                        tzinfo=timezone.utc
                    )
                    elapsed = datetime.now(timezone.utc) - budget_date
                    elapsed_hours = max(elapsed.total_seconds() / 3600, 0.1)
                    rate_per_hour = budget.used / elapsed_hours
                    if rate_per_hour > 0:
                        hours_left = budget.remaining / rate_per_hour
                        eta_exhaustion = (
                            datetime.now(timezone.utc) + timedelta(hours=hours_left)
                        ).isoformat()
                except Exception:
                    pass

            return {
                "source": src.to_dict(),
                "budget": budget.to_dict(),
                "eta_exhaustion": eta_exhaustion,
            }
        finally:
            session.close()

    def get_all_status(self) -> list[dict]:
        """Return budget status for every registered source."""
        self._ensure_init()
        session = get_session()
        try:
            sources = session.query(ApiSource).filter_by(is_active=True).order_by(
                ApiSource.source_key
            ).all()
            results = []
            for src in sources:
                budget = self._get_or_create_budget(src.source_key, session)
                results.append({
                    "source_key": src.source_key,
                    "display_name": src.display_name,
                    "daily_limit": src.daily_limit,
                    "used": budget.used,
                    "remaining": budget.remaining,
                    "succeeded": budget.succeeded,
                    "failed": budget.failed,
                    "success_rate": budget.success_rate,
                    "avg_latency_ms": budget.avg_latency_ms,
                    "total_data_items": budget.total_data_items,
                    "utilization_pct": budget.to_dict()["utilization_pct"],
                    "last_request_at": budget.last_request_at.isoformat() if budget.last_request_at else None,
                })
            session.commit()
            return results
        finally:
            session.close()

    def get_source_history(
        self,
        source_key: str,
        days: int = 30,
    ) -> list[dict]:
        """Return daily budget rows for the last N days (scalability metrics)."""
        self._ensure_init()
        session = get_session()
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
            budgets = (
                session.query(RateBudget)
                .filter(
                    RateBudget.source_key == source_key,
                    RateBudget.date >= cutoff,
                )
                .order_by(RateBudget.date.desc())
                .all()
            )
            return [b.to_dict() for b in budgets]
        finally:
            session.close()

    def get_request_log(
        self,
        source_key: Optional[str] = None,
        limit: int = 100,
        success_only: Optional[bool] = None,
    ) -> list[dict]:
        """Return recent request log entries for debugging / metrics."""
        self._ensure_init()
        session = get_session()
        try:
            q = session.query(ApiRequestLog)
            if source_key:
                q = q.filter(ApiRequestLog.source_key == source_key)
            if success_only is not None:
                q = q.filter(ApiRequestLog.success == success_only)
            rows = q.order_by(ApiRequestLog.requested_at.desc()).limit(limit).all()
            return [r.to_dict() for r in rows]
        finally:
            session.close()

    def get_scalability_report(self) -> dict:
        """Return aggregate metrics across all sources for planning.

        Shows: which sources are near limits, which have headroom,
        success rates, avg latency, and data yield per request.
        """
        self._ensure_init()
        session = get_session()
        try:
            sources = session.query(ApiSource).filter_by(is_active=True).all()
            today = datetime.now(timezone.utc).date().isoformat()

            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "sources": [],
                "bottlenecks": [],      # sources > 80% utilization
                "expandable": [],       # sources < 20% utilization with data
                "failing": [],          # sources with < 80% success rate
            }

            for src in sources:
                budget = self._get_or_create_budget(src.source_key, session)

                entry = {
                    "source_key": src.source_key,
                    "display_name": src.display_name,
                    "daily_limit": src.daily_limit,
                    "used_today": budget.used,
                    "utilization_pct": round(budget.used / budget.daily_limit * 100, 1) if budget.daily_limit else 0,
                    "success_rate": budget.success_rate,
                    "avg_latency_ms": budget.avg_latency_ms,
                    "data_items_today": budget.total_data_items,
                    "data_per_request": (
                        round(budget.total_data_items / budget.used, 1) if budget.used else 0
                    ),
                }
                report["sources"].append(entry)

                if entry["utilization_pct"] > 80:
                    report["bottlenecks"].append(entry)
                elif budget.used > 0 and entry["utilization_pct"] < 20:
                    report["expandable"].append(entry)
                if budget.used > 0 and entry["success_rate"] < 80:
                    report["failing"].append(entry)

            session.commit()
            return report
        finally:
            session.close()


# Module-level singleton
rate_manager = RateManager()
