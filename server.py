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

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.database import (
    Score,
    Signal,
    Snapshot,
    Store,
    WageIndex,
    get_session,
    init_db,
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


# ── Scheduler endpoint ───────────────────────────────────────────────────────

@app.route("/api/scheduler/status")
def scheduler_status():
    """Return scheduler job status and next run times."""
    try:
        status = get_scheduler_status()
        return jsonify({"status": "ok", **status})
    except Exception as e:
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
