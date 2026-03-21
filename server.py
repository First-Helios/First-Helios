"""
Flask application for ChainStaffingTracker.

Serves the Leaflet map frontend and provides API endpoints for
scores, targeting, wage index, and scheduler status.

Port: 8765 (do not change)

Depends on: Flask, backend.*, config.loader
"""

import argparse
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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
from backend.models.reference import (
    BrandProfile,
    CategoryMapping,
    IndustryCategory,
    RegionProfile,
)
from backend.scheduler import get_scheduler_status, init_scheduler
from backend.scoring.engine import compute_all_scores
from backend.targeting import compute_targeting

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder="frontend",
    static_url_path="",
)
CORS(app)


# ── Frontend serving ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the Leaflet map frontend."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/openclaw")
def openclaw_dashboard():
    """Serve the OpenClaw monitoring dashboard."""
    return send_from_directory(app.static_folder, "openclaw.html")


@app.route("/openclaw/session")
def openclaw_session_view():
    """Serve the live OpenClaw session viewer."""
    return send_from_directory(app.static_folder, "openclaw_session.html")


@app.route("/metrics")
def metrics_dashboard():
    """Serve the data source metrics dashboard."""
    return send_from_directory(app.static_folder, "metrics.html")


@app.route("/<path:path>")
def static_files(path):
    """Serve static frontend files."""
    return send_from_directory(app.static_folder, path)


# ── Legacy SpiritPool endpoint ───────────────────────────────────────────────

@app.route("/api/spiritpool/stats")
def spiritpool_stats():
    """Legacy SpiritPool stats endpoint — returns basic status."""
    spiritpool_db = Path(__file__).parent / "data" / "spiritpool.db"
    if spiritpool_db.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(spiritpool_db))
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            stats = {}
            for (table_name,) in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
                stats[table_name] = count
            conn.close()
            return jsonify({"status": "ok", "tables": stats})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "no_database", "message": "spiritpool.db not found"})


# ── Scan endpoints ───────────────────────────────────────────────────────────

@app.route("/api/scan/status")
def scan_status():
    """Return metadata about the most recent scrape."""
    engine = init_db()
    session = get_session(engine)
    try:
        latest = (
            session.query(Snapshot)
            .order_by(Snapshot.scanned_at.desc())
            .first()
        )
        if latest:
            return jsonify({
                "status": "ok",
                "last_scan": latest.to_dict(),
            })
        return jsonify({"status": "ok", "last_scan": None, "message": "No scans yet"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


@app.route("/api/scan", methods=["POST"])
def trigger_scan():
    """Trigger a scrape for a chain/region.

    Body: {"chain": "starbucks", "region": "austin_tx", "force": false}
    """
    data = request.get_json(silent=True) or {}
    chain = data.get("chain", "starbucks")
    region = data.get("region", "austin_tx")

    try:
        from scrapers.careers_api import scrape_careers_api

        signals = scrape_careers_api(region=region, chain=chain, ingest=True)
        compute_all_scores(region=region, chain=chain)

        return jsonify({
            "status": "ok",
            "signals_scraped": len(signals),
            "chain": chain,
            "region": region,
        })
    except Exception as e:
        logger.error("[Server] Scan failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Scores endpoint ──────────────────────────────────────────────────────────

@app.route("/api/scores")
def get_scores():
    """Return all store scores for a region.

    Query params:
      - region (required): e.g. 'austin_tx'
      - chain (optional): e.g. 'starbucks'
    """
    region = request.args.get("region", "austin_tx")
    chain = request.args.get("chain")

    engine = init_db()
    session = get_session(engine)

    try:
        # Get stores
        query = session.query(Store).filter(
            Store.region == region, Store.is_active.is_(True)
        )
        if chain:
            query = query.filter(Store.chain == chain)
        stores = query.all()

        if not stores:
            return jsonify({"status": "ok", "stores": [], "count": 0})

        store_nums = [s.store_num for s in stores]
        store_map = {s.store_num: s for s in stores}

        # Get scores
        scores = (
            session.query(Score)
            .filter(Score.store_num.in_(store_nums))
            .all()
        )

        # Group scores by store
        score_data: dict = {}
        for score in scores:
            if score.store_num not in score_data:
                score_data[score.store_num] = {}
            score_data[score.store_num][score.score_type] = {
                "value": score.value,
                "tier": score.tier,
            }

        # Build response
        result = []
        for sn in store_nums:
            store = store_map[sn]
            store_scores = score_data.get(sn, {})
            composite = store_scores.get("composite", {})

            result.append({
                "store_num": sn,
                "chain": store.chain,
                "store_name": store.store_name,
                "address": store.address,
                "lat": store.lat,
                "lng": store.lng,
                "score": composite.get("value", 0),
                "tier": composite.get("tier", "unknown"),
                "sub_scores": store_scores,
            })

        # Sort by score descending
        result.sort(key=lambda x: x["score"], reverse=True)

        return jsonify({
            "status": "ok",
            "region": region,
            "chain": chain,
            "count": len(result),
            "stores": result,
        })

    except Exception as e:
        logger.error("[Server] Scores query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Targeting endpoint ───────────────────────────────────────────────────────

@app.route("/api/targeting")
def get_targeting():
    """Return ranked job fair targeting candidates.

    Query params:
      - industry (optional): e.g. 'coffee_cafe'
      - region (default: austin_tx)
      - chain (optional): e.g. 'starbucks'
      - limit (default: 10)
    """
    region = request.args.get("region", "austin_tx")
    industry = request.args.get("industry")
    chain = request.args.get("chain")
    limit = request.args.get("limit", 10, type=int)

    try:
        results = compute_targeting(
            region=region,
            industry=industry,
            chain=chain,
            limit=limit,
        )

        return jsonify({
            "status": "ok",
            "region": region,
            "industry": industry,
            "count": len(results),
            "targets": [r.to_dict() for r in results],
        })

    except Exception as e:
        logger.error("[Server] Targeting query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Wage Index endpoint ──────────────────────────────────────────────────────

@app.route("/api/wage-index")
def get_wage_index():
    """Return local vs chain pay comparison.

    Query params:
      - industry (optional): e.g. 'coffee_cafe'
      - region (default: austin_tx)
    """
    region = request.args.get("region", "austin_tx")
    industry = request.args.get("industry")

    engine = init_db()
    session = get_session(engine)

    try:
        query = session.query(WageIndex)
        if industry:
            query = query.filter(WageIndex.industry == industry)

        wages = query.order_by(WageIndex.observed_at.desc()).all()

        chain_wages = [w.to_dict() for w in wages if w.is_chain]
        local_wages = [w.to_dict() for w in wages if not w.is_chain]

        # Compute averages
        def _avg_hourly(items):
            vals = []
            for w in items:
                avg = None
                if w.get("wage_min") and w.get("wage_max"):
                    avg = (w["wage_min"] + w["wage_max"]) / 2.0
                elif w.get("wage_min"):
                    avg = w["wage_min"]
                elif w.get("wage_max"):
                    avg = w["wage_max"]
                if avg:
                    if w.get("wage_period") == "yearly" and avg > 100:
                        avg = avg / 2080
                    vals.append(avg)
            return round(sum(vals) / len(vals), 2) if vals else None

        chain_avg = _avg_hourly(chain_wages)
        local_avg = _avg_hourly(local_wages)

        gap_pct = None
        if chain_avg and local_avg and chain_avg > 0:
            gap_pct = round(((local_avg - chain_avg) / chain_avg) * 100, 1)

        return jsonify({
            "status": "ok",
            "region": region,
            "industry": industry,
            "chain_avg_hourly": chain_avg,
            "local_avg_hourly": local_avg,
            "gap_pct": gap_pct,
            "chain_entries": len(chain_wages),
            "local_entries": len(local_wages),
            "chain_wages": chain_wages[:20],
            "local_wages": local_wages[:20],
        })

    except Exception as e:
        logger.error("[Server] Wage index query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Stores endpoint ──────────────────────────────────────────────────────────

@app.route("/api/stores")
def get_stores():
    """Return all stores with coordinates and scores.

    Query params:
      - region (default: austin_tx)
      - chain (optional): filter to one chain
      - industry (optional): filter to one industry
    """
    region = request.args.get("region", "austin_tx")
    chain = request.args.get("chain")
    industry = request.args.get("industry")

    engine = init_db()
    session = get_session(engine)

    try:
        q = session.query(Store).filter(
            Store.region == region,
            Store.is_active.is_(True),
            Store.lat.isnot(None),
        )
        if chain:
            q = q.filter(Store.chain == chain)
        if industry:
            q = q.filter(Store.industry == industry)
        stores = q.all()

        result = []
        for s in stores:
            score_row = (
                session.query(Score)
                .filter_by(store_num=s.store_num, score_type="composite")
                .first()
            )
            result.append({
                "store_num": s.store_num,
                "chain": s.chain,
                "name": s.store_name,
                "address": s.address,
                "lat": s.lat,
                "lng": s.lng,
                "industry": s.industry,
                "score": score_row.value if score_row else None,
                "tier": score_row.tier if score_row else "unknown",
            })

        return jsonify({"status": "ok", "stores": result, "count": len(result)})

    except Exception as e:
        logger.error("[Server] Stores query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Local Employers endpoint ─────────────────────────────────────────────────

@app.route("/api/local-employers")
def get_local_employers():
    """Return local (non-chain) employer POIs.

    Query params:
      - region (default: austin_tx)
      - industry (optional): filter to one industry
    """
    region = request.args.get("region", "austin_tx")
    industry = request.args.get("industry")

    engine = init_db()
    session = get_session(engine)

    try:
        q = session.query(LocalEmployer).filter_by(
            region=region, is_active=True
        )
        if industry:
            q = q.filter_by(industry=industry)
        employers = q.all()

        return jsonify({
            "status": "ok",
            "employers": [
                {
                    "name": e.name,
                    "category": e.category,
                    "industry": e.industry,
                    "address": e.address,
                    "lat": e.lat,
                    "lng": e.lng,
                }
                for e in employers
                if e.lat and e.lng
            ],
            "count": len(employers),
        })

    except Exception as e:
        logger.error("[Server] Local employers query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Meta endpoint — single source of truth for all frontends ─────────────────

@app.route("/api/meta")
def api_meta():
    """Single source of truth for frontend filter population.

    Merges the authoritative INDUSTRY_REGISTRY (display names, brands,
    search terms) with live DB counts (stores per chain, local employers).
    Every frontend page should call this once on load to populate dropdowns,
    nav links, and industry/brand selectors.

    Returns:
      - industries: [{key, display_name, brand_count, brands: [{key, display_name}]}]
      - brands: [{key, display_name, industry}]  (flat list, all brands)
      - regions: [{key, display_name}]
      - pages: [{path, label, description}]
      - store_total, local_employer_total
      - store_counts: {chain_key: count}
    """
    try:
        from openclaw.industries import INDUSTRY_REGISTRY
        from agent_interface.schemas import Region

        engine = init_db()
        session = get_session(engine)

        # Live store counts per chain key
        from sqlalchemy import func as sqlfunc
        chain_counts = dict(
            session.query(Store.chain, sqlfunc.count(Store.store_num))
            .filter(Store.is_active.is_(True))
            .group_by(Store.chain)
            .all()
        )
        local_count = session.query(LocalEmployer).filter(
            LocalEmployer.is_active.is_(True)
        ).count()

        # Build industry list with nested brands
        industries = []
        all_brands = []
        for key, dim in INDUSTRY_REGISTRY.items():
            brands = []
            for mc in dim.mega_corps:
                b = {
                    "key": mc.key,
                    "display_name": mc.display_name,
                    "industry": key,
                    "store_count": chain_counts.get(mc.key, 0),
                }
                brands.append(b)
                all_brands.append(b)
            industries.append({
                "key": key,
                "display_name": dim.display_name,
                "description": dim.description,
                "brand_count": len(brands),
                "brands": brands,
            })

        # Regions
        regions = [{"key": r.value, "display_name": r.value.replace("_", " ").title()} for r in Region]

        # Pages — so nav can be built dynamically
        pages = [
            {"path": "/", "label": "Map", "icon": "🗺️", "description": "Leaflet store map with targeting"},
            {"path": "/openclaw", "label": "OpenClaw", "icon": "🦀", "description": "Agent query monitor"},
            {"path": "/openclaw/session", "label": "Session", "icon": "⚡", "description": "Live agent session viewer"},
            {"path": "/metrics", "label": "Metrics", "icon": "📊", "description": "Data source effectiveness"},
        ]

        session.close()

        return jsonify({
            "status": "ok",
            "industries": industries,
            "brands": all_brands,
            "regions": regions,
            "pages": pages,
            "store_total": sum(chain_counts.values()),
            "local_employer_total": local_count,
            "store_counts": chain_counts,
        })
    except Exception as e:
        logger.error("[Server] Meta endpoint failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Reference Data endpoints ──────────────────────────────────────────────────

@app.route("/api/ref/brands")
def ref_brands():
    """Return all known brand profiles.

    Query params:
      - industry (optional): filter to one internal_industry key
      - chain_only (optional): if 'true', only return is_chain=True
    """
    industry = request.args.get("industry")
    chain_only = request.args.get("chain_only", "false").lower() == "true"

    engine = init_db()
    session = get_session(engine)
    try:
        q = session.query(BrandProfile)
        if industry:
            q = q.filter(BrandProfile.internal_industry == industry)
        if chain_only:
            q = q.filter(BrandProfile.is_chain.is_(True))
        brands = q.order_by(BrandProfile.display_name).all()
        return jsonify({
            "status": "ok",
            "count": len(brands),
            "brands": [b.to_dict() for b in brands],
        })
    except Exception as e:
        logger.error("[Server] Ref brands query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


@app.route("/api/ref/industries")
def ref_industries():
    """Return the NAICS-based industry hierarchy.

    Query params:
      - leaf_only (optional): if 'true', only return deepest-level codes
    """
    leaf_only = request.args.get("leaf_only", "false").lower() == "true"

    engine = init_db()
    session = get_session(engine)
    try:
        cats = session.query(IndustryCategory).order_by(IndustryCategory.naics_code).all()
        if leaf_only:
            # A leaf node is one whose naics_code is not the parent_naics of another
            parent_codes = {c.parent_naics for c in cats if c.parent_naics}
            cats = [c for c in cats if c.naics_code not in parent_codes]
        return jsonify({
            "status": "ok",
            "count": len(cats),
            "industries": [c.to_dict() for c in cats],
        })
    except Exception as e:
        logger.error("[Server] Ref industries query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


@app.route("/api/ref/regions")
def ref_regions():
    """Return regional economic profiles."""
    engine = init_db()
    session = get_session(engine)
    try:
        regions = session.query(RegionProfile).order_by(RegionProfile.region_key).all()
        return jsonify({
            "status": "ok",
            "count": len(regions),
            "regions": [r.to_dict() for r in regions],
        })
    except Exception as e:
        logger.error("[Server] Ref regions query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


@app.route("/api/ref/categories")
def ref_categories():
    """Return category crosswalk mappings.

    Query params:
      - source (optional): filter to one source_system (overture, osm, indeed, etc.)
    """
    source = request.args.get("source")

    engine = init_db()
    session = get_session(engine)
    try:
        q = session.query(CategoryMapping)
        if source:
            q = q.filter(CategoryMapping.source_system == source)
        mappings = q.order_by(CategoryMapping.source_system, CategoryMapping.source_value).all()
        return jsonify({
            "status": "ok",
            "count": len(mappings),
            "categories": [m.to_dict() for m in mappings],
        })
    except Exception as e:
        logger.error("[Server] Ref categories query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


@app.route("/api/ref/summary")
def ref_summary():
    """Return a combined summary: brands + industries + region + store counts.

    Used by the frontend to populate all filter dropdowns in a single request.
    """
    engine = init_db()
    session = get_session(engine)
    try:
        brands = session.query(BrandProfile).filter(
            BrandProfile.is_chain.is_(True)
        ).order_by(BrandProfile.display_name).all()

        industries = session.query(IndustryCategory).order_by(
            IndustryCategory.naics_code
        ).all()
        # Only leaf industries
        parent_codes = {c.parent_naics for c in industries if c.parent_naics}
        leaf_industries = [c for c in industries if c.naics_code not in parent_codes]

        regions = session.query(RegionProfile).all()

        # Store count per chain
        from sqlalchemy import func
        chain_counts = dict(
            session.query(Store.chain, func.count(Store.store_num))
            .filter(Store.is_active.is_(True))
            .group_by(Store.chain)
            .all()
        )

        # Local employer count
        local_count = session.query(LocalEmployer).filter(
            LocalEmployer.is_active.is_(True)
        ).count()

        return jsonify({
            "status": "ok",
            "brands": [
                {
                    "brand_key": b.brand_key,
                    "display_name": b.display_name,
                    "internal_industry": b.internal_industry,
                    "store_count": chain_counts.get(b.brand_key, 0),
                }
                for b in brands
            ],
            "industries": [
                {
                    "internal_key": c.internal_key,
                    "naics_title": c.naics_title,
                    "naics_code": c.naics_code,
                }
                for c in leaf_industries
            ],
            "regions": [
                {
                    "region_key": r.region_key,
                    "display_name": r.display_name,
                }
                for r in regions
            ],
            "store_total": sum(chain_counts.values()),
            "local_employer_total": local_count,
        })
    except Exception as e:
        logger.error("[Server] Ref summary query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Scheduler endpoint ───────────────────────────────────────────────────────

@app.route("/api/scheduler/status")
def scheduler_status():
    """Return scheduler job status and next run times."""
    try:
        status = get_scheduler_status()
        return jsonify({"status": "ok", **status})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Rate Budget / Metrics endpoints ──────────────────────────────────────────

@app.route("/api/rate-budget")
def rate_budget_status():
    """Return rate-limit budget status for all API sources.

    Query params:
      - source (optional): one source_key for detailed view
    """
    try:
        from backend.rate_manager import rate_manager

        source = request.args.get("source")
        if source:
            status = rate_manager.get_source_status(source)
            return jsonify({"status": "ok", **status})

        all_status = rate_manager.get_all_status()
        return jsonify({
            "status": "ok",
            "count": len(all_status),
            "budgets": all_status,
        })
    except Exception as e:
        logger.error("[Server] Rate budget query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/rate-budget/history")
def rate_budget_history():
    """Return daily budget history for a source (scalability metrics).

    Query params:
      - source (required): source_key
      - days (optional, default 30): how far back
    """
    source = request.args.get("source")
    if not source:
        return jsonify({"status": "error", "message": "source param required"}), 400

    days = request.args.get("days", 30, type=int)

    try:
        from backend.rate_manager import rate_manager
        history = rate_manager.get_source_history(source, days=days)
        return jsonify({
            "status": "ok",
            "source": source,
            "days": days,
            "history": history,
        })
    except Exception as e:
        logger.error("[Server] Rate history query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/rate-budget/log")
def rate_budget_log():
    """Return recent individual request log entries.

    Query params:
      - source (optional): filter to one source_key
      - limit (optional, default 100)
      - failures_only (optional): if 'true', only failed requests
    """
    source = request.args.get("source")
    limit = request.args.get("limit", 100, type=int)
    failures_only = request.args.get("failures_only", "false").lower() == "true"

    try:
        from backend.rate_manager import rate_manager
        success_filter = False if failures_only else None
        logs = rate_manager.get_request_log(
            source_key=source, limit=limit, success_only=success_filter
        )
        return jsonify({
            "status": "ok",
            "count": len(logs),
            "requests": logs,
        })
    except Exception as e:
        logger.error("[Server] Rate log query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/rate-budget/scalability")
def rate_budget_scalability():
    """Return scalability planning report.

    Shows bottlenecks (>80% utilization), expandable sources (<20%),
    and failing sources (<80% success rate).
    """
    try:
        from backend.rate_manager import rate_manager
        report = rate_manager.get_scalability_report()
        return jsonify({"status": "ok", **report})
    except Exception as e:
        logger.error("[Server] Scalability report failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Agent Interface endpoints ────────────────────────────────────────────────

@app.route("/api/agent/options")
def agent_options():
    """Return all valid enum values the agent can use.

    This is the first thing an LLM agent should call to learn
    the valid intents, regions, brands, industries, priorities, and modes.
    """
    try:
        from agent_interface.schemas import get_all_options
        return jsonify({"status": "ok", **get_all_options()})
    except Exception as e:
        logger.error("[Server] Agent options failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/modes")
def agent_modes():
    """Return all operational modes with their configurations.

    Each mode controls freshness bypass, DB fallback, success criteria,
    and allowed intents. Use this to choose the right mode for a session.
    """
    try:
        from agent_interface.schemas import MODE_CONFIG, AgentMode
        modes = {}
        for key, cfg in MODE_CONFIG.items():
            modes[key] = cfg.to_dict()
        return jsonify({
            "status": "ok",
            "modes": modes,
            "default": AgentMode.MIXED.value,
        })
    except Exception as e:
        logger.error("[Server] Agent modes failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/query", methods=["POST"])
def agent_query():
    """Submit one structured query from the agent.

    Body: {
        "intent": "data_quality_audit",
        "region": "austin_tx",
        "brand": "starbucks",          // optional, depends on intent
        "industry": "coffee_cafe",     // optional, depends on intent
        "priority": "normal",          // optional
        "source_preference": "auto",   // optional
        "max_results": 500,            // optional, cap 5000
        "max_budget_spend": 5,         // optional, cap 50
        "known_count": null,           // optional
        "reason": "Initial audit"      // optional logging note
    }

    Returns ConciseResult JSON with status, records found/new, anomalies,
    and suggested_next actions.

    On invalid enum values, returns HTTP 422 with valid_options dict
    so the agent can self-correct.
    """
    data = request.get_json(silent=True) or {}

    try:
        from agent_interface.schemas import parse_agent_query, get_all_options
        from agent_interface.queue_manager import agent_queue

        query, errors = parse_agent_query(data)
        if errors:
            return jsonify({
                "status": "rejected",
                "errors": errors,
                "valid_options": get_all_options(),
            }), 422

        result = agent_queue.submit(query)
        return jsonify({"status": "ok", **result.to_dict()})

    except Exception as e:
        logger.error("[Server] Agent query failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/batch", methods=["POST"])
def agent_batch():
    """Submit multiple structured queries in one request.

    Body: {
        "queries": [
            {"intent": "poi_chain_locations", "brand": "starbucks", "region": "austin_tx"},
            {"intent": "wage_baseline", "industry": "coffee_cafe", "region": "austin_tx"}
        ]
    }

    Later queries benefit from earlier ones (freshness dedup).
    Returns a list of ConciseResult objects.
    """
    data = request.get_json(silent=True) or {}
    raw_queries = data.get("queries", [])

    if not raw_queries:
        return jsonify({"status": "error", "message": "No queries provided"}), 400
    if len(raw_queries) > 20:
        return jsonify({"status": "error", "message": "Max 20 queries per batch"}), 400

    try:
        from agent_interface.schemas import parse_agent_query, get_all_options
        from agent_interface.queue_manager import agent_queue

        parsed_queries = []
        all_errors = []

        for i, raw in enumerate(raw_queries):
            query, errors = parse_agent_query(raw)
            if errors:
                all_errors.append({"index": i, "errors": errors})
            else:
                parsed_queries.append(query)

        if all_errors and not parsed_queries:
            return jsonify({
                "status": "rejected",
                "errors": all_errors,
                "valid_options": get_all_options(),
            }), 422

        results = agent_queue.submit_batch(parsed_queries)

        return jsonify({
            "status": "ok",
            "count": len(results),
            "results": [r.to_dict() for r in results],
            "parse_errors": all_errors if all_errors else None,
        })

    except Exception as e:
        logger.error("[Server] Agent batch failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/queue/status")
def agent_queue_status():
    """Return current queue state + budget summary."""
    try:
        from agent_interface.queue_manager import agent_queue
        status = agent_queue.status()
        return jsonify({"status": "ok", **status.to_dict()})
    except Exception as e:
        logger.error("[Server] Agent queue status failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/queue/pause", methods=["POST"])
def agent_queue_pause():
    """Pause the agent execution queue.

    Body: {"reason": "BLS budget exhausted"}
    """
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "")

    try:
        from agent_interface.queue_manager import agent_queue
        result = agent_queue.pause(reason)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error("[Server] Agent queue pause failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/queue/resume", methods=["POST"])
def agent_queue_resume():
    """Resume the agent execution queue."""
    try:
        from agent_interface.queue_manager import agent_queue
        result = agent_queue.resume()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error("[Server] Agent queue resume failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/history")
def agent_history():
    """Return recent agent query results.

    Query params:
      - limit (optional, default 20, max 100)
    """
    limit = request.args.get("limit", 20, type=int)
    limit = min(limit, 100)

    try:
        from agent_interface.queue_manager import agent_queue
        history = agent_queue.get_recent_history(limit=limit)
        return jsonify({"status": "ok", "count": len(history), "results": history})
    except Exception as e:
        logger.error("[Server] Agent history failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Discovery endpoints ──────────────────────────────────────────────────────

@app.route("/api/discovery/scan")
def discovery_scan():
    """Run a full discovery scan and return prioritised leads.

    Query params:
      - region (optional, default: austin_tx)
      - max_leads (optional, default: 25, max 100)
      - types (optional, comma-separated: coverage_gaps,data_dimension_gaps,
               stale_leads,geographic_clusters,local_opportunities)
    """
    region = request.args.get("region", "austin_tx")
    max_leads = min(request.args.get("max_leads", 25, type=int), 100)
    types_raw = request.args.get("types", "")
    include_types = [t.strip() for t in types_raw.split(",") if t.strip()] or None

    try:
        from backend.discovery import run_discovery
        scan = run_discovery(region=region, max_leads=max_leads, include_types=include_types)
        return jsonify({"status": "ok", **scan.to_dict()})
    except Exception as e:
        logger.error("[Server] Discovery scan failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/discovery/summary")
def discovery_summary():
    """Quick discovery dashboard — coverage stats without full scan.

    Query params:
      - region (optional, default: austin_tx)
    """
    region = request.args.get("region", "austin_tx")

    try:
        from backend.discovery import get_discovery_summary
        summary = get_discovery_summary(region=region)
        return jsonify({"status": "ok", **summary})
    except Exception as e:
        logger.error("[Server] Discovery summary failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/discovery/leads")
def discovery_leads():
    """Return leads from the most recent scan as agent proposals.

    Query params:
      - region (optional, default: austin_tx)
      - min_priority (optional, default: 0, range 0-100)
      - limit (optional, default: 10, max 50)
    """
    region = request.args.get("region", "austin_tx")
    min_priority = request.args.get("min_priority", 0, type=int)
    limit = min(request.args.get("limit", 10, type=int), 50)

    try:
        from backend.discovery import run_discovery
        scan = run_discovery(region=region, max_leads=limit)
        leads = [l.to_dict() for l in scan.leads if l.priority >= min_priority]
        proposals = [l.to_agent_proposal() for l in scan.leads if l.priority >= min_priority]
        return jsonify({
            "status": "ok",
            "count": len(leads),
            "leads": leads[:limit],
            "agent_proposals": proposals[:limit],
        })
    except Exception as e:
        logger.error("[Server] Discovery leads failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Dedup endpoints ──────────────────────────────────────────────────────────

@app.route("/api/dedup/summary")
def dedup_summary():
    """Return dedup status for a region.

    Query params:
      - region (optional, default: austin_tx)
    """
    region = request.args.get("region", "austin_tx")
    try:
        from backend.dedup import get_dedup_summary
        summary = get_dedup_summary(region=region)
        return jsonify({"status": "ok", **summary})
    except Exception as e:
        logger.error("[Server] Dedup summary failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/dedup/run", methods=["POST"])
def dedup_run():
    """Run bulk store deduplication.

    JSON body:
      - region (optional, default: austin_tx)
      - dry_run (optional, default: true)
    """
    data = request.get_json(silent=True) or {}
    region = data.get("region", "austin_tx")
    dry_run = data.get("dry_run", True)

    try:
        from backend.dedup import deduplicate_stores
        report = deduplicate_stores(region=region, dry_run=dry_run)
        return jsonify({"status": "ok", **report.to_dict()})
    except Exception as e:
        logger.error("[Server] Dedup run failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Source Metrics endpoints ─────────────────────────────────────────────────

@app.route("/api/metrics/sources")
def metrics_sources():
    """Per-source effectiveness metrics — queries, records, yield, trends.

    Query params:
      - days (optional, default: 30): lookback period
    """
    days = request.args.get("days", 30, type=int)

    try:
        from backend.source_metrics import get_source_effectiveness
        data = get_source_effectiveness(days=days)
        return jsonify({"status": "ok", **data})
    except Exception as e:
        logger.error("[Server] Source metrics failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/metrics/sources/<source_key>")
def metrics_source_detail(source_key):
    """Detail view for one data source — daily breakdown + recent requests.

    Query params:
      - days (optional, default: 30)
      - log_limit (optional, default: 50)
    """
    days = request.args.get("days", 30, type=int)
    log_limit = request.args.get("log_limit", 50, type=int)

    try:
        from backend.source_metrics import get_source_detail
        data = get_source_detail(source_key, days=days, log_limit=log_limit)
        return jsonify({"status": "ok", **data})
    except Exception as e:
        logger.error("[Server] Source detail failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/metrics/effectiveness")
def metrics_effectiveness():
    """Cross-source comparison — ranked by data yield per query.

    Query params:
      - days (optional, default: 7): lookback window
    """
    days = request.args.get("days", 7, type=int)

    try:
        from backend.source_metrics import get_effectiveness_ranking
        data = get_effectiveness_ranking(days=days)
        return jsonify({"status": "ok", **data})
    except Exception as e:
        logger.error("[Server] Effectiveness ranking failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Ollama Agent endpoints ───────────────────────────────────────────────────

@app.route("/api/agent/ollama/status")
def ollama_status():
    """Check Ollama availability, listed models, and session state.

    Returns setup instructions if Ollama is not available.
    """
    try:
        from agent_interface.ollama_agent import get_agent_status
        status = get_agent_status()
        return jsonify({"status": "ok", **status})
    except Exception as e:
        logger.error("[Server] Ollama status failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/ollama/models")
def ollama_models():
    """List available Ollama models."""
    try:
        from agent_interface.ollama_agent import get_or_create_agent
        agent = get_or_create_agent()
        models = agent.list_models()
        return jsonify({"status": "ok", "models": models, "count": len(models)})
    except Exception as e:
        logger.error("[Server] Ollama models failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/ollama/pull", methods=["POST"])
def ollama_pull():
    """Pull a model from the Ollama registry.

    Body: {"model": "llama3.2"}
    """
    data = request.get_json(silent=True) or {}
    model = data.get("model", "llama3.2")

    try:
        from agent_interface.ollama_agent import get_or_create_agent
        agent = get_or_create_agent()
        result = agent.pull_model(model)
        return jsonify({"status": "ok", "model": model, **result})
    except Exception as e:
        logger.error("[Server] Ollama pull failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/agent/ollama/research", methods=["POST"])
def ollama_research():
    """Start an autonomous research session with the Ollama agent.

    Body: {
        "model": "llama3.2",           // optional, default: openclaw
        "region": "austin_tx",         // optional, default: austin_tx
        "goal": "Analyze coffee labor" // optional research goal
    }

    Returns the session results after completion.
    WARNING: This is a blocking call — may take minutes depending on model.
    """
    data = request.get_json(silent=True) or {}
    model = data.get("model", "openclaw")
    region = data.get("region", "austin_tx")
    goal = data.get("goal")

    try:
        from agent_interface.ollama_agent import OllamaAgent

        agent = OllamaAgent(model=model)
        if not agent.is_available():
            return jsonify({
                "status": "error",
                "message": f"Model '{model}' not available. "
                f"Pull it first: ollama pull {model}",
                "available_models": agent.list_models(),
            }), 503

        session = agent.run_research_session(region=region, goal=goal)

        return jsonify({
            "status": "ok",
            "model": model,
            "region": region,
            "iterations": session.iterations,
            "queries_submitted": session.queries_submitted,
            "is_complete": session.is_complete,
            "summary": session.final_summary,
            "results": session.results,
        })

    except Exception as e:
        logger.error("[Server] Ollama research failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── OpenClaw endpoints ───────────────────────────────────────────────────────

@app.route("/api/openclaw/status")
def openclaw_status():
    """OpenClaw orchestrator status, model availability, and industry registry."""
    try:
        from openclaw.orchestrator import get_claw_status
        return jsonify({"status": "ok", **get_claw_status()})
    except Exception as e:
        logger.error("[Server] OpenClaw status failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/industries")
def openclaw_industries():
    """List all industry dimensions the agent can explore."""
    try:
        from openclaw.industries import get_all_industries, get_all_mega_corps
        industries = get_all_industries()
        corps = get_all_mega_corps()
        return jsonify({
            "status": "ok",
            "industries": industries,
            "mega_corps": corps,
            "industry_count": len(industries),
            "mega_corp_count": len(corps),
        })
    except Exception as e:
        logger.error("[Server] OpenClaw industries failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/prevalidate", methods=["POST"])
def openclaw_prevalidate():
    """Pre-validate proposed queries without executing them.

    Body: {"queries": [{"intent": "...", "brand": "...", ...}]}
    """
    data = request.get_json(silent=True) or {}
    queries = data.get("queries", [])
    if not queries:
        return jsonify({"status": "error", "message": "Provide 'queries' list"}), 400
    try:
        from openclaw.prevalidate import prevalidate_agent_plan
        result = prevalidate_agent_plan(queries)
        return jsonify({"status": "ok", **result.to_dict()})
    except Exception as e:
        logger.error("[Server] OpenClaw prevalidate failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/tracker")
def openclaw_tracker():
    """Today's request success/fail rollup."""
    try:
        from openclaw.tracker import request_tracker
        limit = request.args.get("limit", 50, type=int)
        rollup = request_tracker.get_today_rollup()
        recent = request_tracker.get_recent_records(limit=limit)
        return jsonify({
            "status": "ok",
            "rollup": rollup.to_dict(),
            "recent_requests": recent,
        })
    except Exception as e:
        logger.error("[Server] OpenClaw tracker failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/freshness")
def openclaw_freshness():
    """Source freshness overview — how old each data source is.

    Returns all freshness records sorted by staleness (most stale first),
    plus summary stats for the agent and dashboard.
    """
    try:
        from backend.database import get_all_freshness
        from agent_interface.schemas import FRESHNESS_THRESHOLDS

        records = get_all_freshness()
        stale_count = sum(1 for r in records if r.get("is_stale", True))
        fresh_count = len(records) - stale_count

        return jsonify({
            "status": "ok",
            "total_tracked": len(records),
            "stale": stale_count,
            "fresh": fresh_count,
            "thresholds": FRESHNESS_THRESHOLDS,
            "records": records,
        })
    except Exception as e:
        logger.error("[Server] OpenClaw freshness failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/freshness/check", methods=["POST"])
def openclaw_freshness_check():
    """Check freshness for a specific intent/region/brand/industry combo.

    POST JSON: { "intent": "...", "region": "...", "brand": "...", "industry": "..." }
    """
    try:
        from backend.database import check_freshness
        from agent_interface.schemas import FRESHNESS_THRESHOLDS

        data = request.get_json(force=True)
        intent = data.get("intent", "")
        region = data.get("region", "austin_tx")
        brand = data.get("brand") or None
        industry = data.get("industry") or None

        result = check_freshness(
            intent=intent,
            region=region,
            brand=brand,
            industry=industry,
        )
        result["threshold_days"] = FRESHNESS_THRESHOLDS.get(intent, 14.0)
        if result.get("age_days") is not None:
            result["is_stale"] = result["age_days"] > result["threshold_days"]

        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error("[Server] Freshness check failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/wishlist")
def openclaw_wishlist():
    """Today's agent wishlist."""
    try:
        from openclaw.wishlist import wishlist_manager
        wl = wishlist_manager.get_today()
        return jsonify({"status": "ok", **wl.to_dict()})
    except Exception as e:
        logger.error("[Server] OpenClaw wishlist failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/wishlist/review", methods=["POST"])
def openclaw_wishlist_review():
    """Approve or reject a wish item.

    Body: {"wish_id": "wish-2026-03-20-001", "approved": true, "note": "Looks good"}
    """
    data = request.get_json(silent=True) or {}
    wish_id = data.get("wish_id", "")
    approved = data.get("approved", False)
    note = data.get("note", "")

    if not wish_id:
        return jsonify({"status": "error", "message": "Provide 'wish_id'"}), 400

    try:
        from openclaw.wishlist import wishlist_manager
        result = wishlist_manager.review_wish(wish_id, approved, note)
        if result:
            return jsonify({"status": "ok", "wish": result})
        return jsonify({"status": "error", "message": f"Wish '{wish_id}' not found"}), 404
    except Exception as e:
        logger.error("[Server] OpenClaw wishlist review failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/run", methods=["POST"])
def openclaw_run():
    """Start an OpenClaw research session (non-blocking).

    Body: {
        "model": "qwen2.5:7b-instruct",
        "region": "austin_tx",
        "mode": "collect",
        "goal": "Survey coffee and healthcare labor markets",
        "industries": ["coffee_cafe", "healthcare_clinic"]
    }

    Mode options:
      - collect  — Fresh data from external APIs. Bypasses freshness. No DB fallback.
      - analyze  — Compute insights from existing data. No external API calls.
      - monitor  — Lightweight health checks. Read-only.
      - mixed    — Smart default — freshness-aware with DB fallback.

    Returns immediately.  Poll /api/openclaw/session/live to watch progress.
    """
    data = request.get_json(silent=True) or {}
    model = data.get("model", "qwen2.5:7b-instruct")
    region = data.get("region", "austin_tx")
    mode = data.get("mode", "mixed")
    goal = data.get("goal", "")
    industries = data.get("industries")

    # Validate mode
    valid_modes = ["collect", "analyze", "monitor", "mixed"]
    if mode not in valid_modes:
        return jsonify({
            "status": "error",
            "message": f"Invalid mode '{mode}'. Valid: {valid_modes}",
        }), 400

    try:
        from openclaw.orchestrator import OpenClawOrchestrator, session_log
        orch = OpenClawOrchestrator(model=model)
        if not orch.is_available():
            return jsonify({
                "status": "error",
                "message": f"Model '{model}' not available. Pull it: ollama pull {model}",
                "available_models": orch.list_models(),
            }), 503

        # If session already running, reject
        if session_log.state == "running":
            return jsonify({
                "status": "error",
                "message": "A session is already running. Wait for it to finish or view it at /openclaw/session",
                "session": session_log.snapshot(),
            }), 409

        # Run in background thread
        def _run():
            try:
                orch.run(region=region, goal=goal, industries=industries, mode=mode)
            except Exception as exc:
                logger.error("[Server] Background OpenClaw run failed: %s", exc)
                session_log.append("error", f"Session crashed: {exc}")
                session_log.finish("error")

        t = threading.Thread(target=_run, daemon=True, name="openclaw-session")
        t.start()

        return jsonify({
            "status": "ok",
            "mode": mode,
            "message": f"Session started in {mode.upper()} mode.  Poll /api/openclaw/session/live to follow progress.",
            "session": session_log.snapshot(),
        })
    except Exception as e:
        logger.error("[Server] OpenClaw run failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/openclaw/session/live")
def openclaw_session_live():
    """Poll the live session thought log.

    Query params:
        after: int — only return entries with seq > after (for incremental polling)
    """
    try:
        from openclaw.orchestrator import session_log
        after = request.args.get("after", 0, type=int)
        entries = session_log.get_since(after)
        snap = session_log.snapshot()
        return jsonify({
            "status": "ok",
            **snap,
            "entries": entries,
        })
    except Exception as e:
        logger.error("[Server] Session live failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Server startup ───────────────────────────────────────────────────────────

def create_app() -> Flask:
    """Application factory for Flask."""
    # Initialize database
    init_db()

    # Start scheduler
    try:
        init_scheduler()
    except Exception as e:
        logger.warning("[Server] Scheduler init failed (non-fatal): %s", e)

    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="ChainStaffingTracker Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    args = parser.parse_args()

    create_app()
    app.run(host="0.0.0.0", port=args.port, debug=args.debug, use_reloader=False)
