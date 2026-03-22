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
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

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
