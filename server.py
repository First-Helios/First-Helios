"""
Flask application for First-Helios.

Broad-scope data intelligence platform serving dashboards for jobs,
events, businesses, wages, economic indicators, and career mobility
across the Austin regional labor market.

Port: 8765 (do not change)

Depends on: Flask, core.*, postings.*, events.*, config.loader
"""

import argparse
import functools
import json
import logging
import sys
from datetime import datetime, timedelta
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

from core.database import (
    LocalEmployer,
    MealDeal,
    RestaurantURL,
    Score,
    Signal,
    Snapshot,
    Store,
    WageIndex,
    get_session,
    init_db,
)
from core.models.reference import (
    BrandProfile,
    CategoryMapping,
    IndustryCategory,
    IndustryTaxonomy,
    MobOccupation,
    MobTransition,
    OccupationAlias,
    RegionProfile,
)
from core.scheduler import get_scheduler_status
from core.scoring.engine import compute_all_scores
from core.targeting import compute_targeting

logger = logging.getLogger(__name__)

# ── H3 cell-to-latlng cache (stable geometric centers, never change) ─────────
_h3_latlng_cache: dict[str, tuple[float, float]] = {}

def _cached_cell_to_latlng(cell_id: str) -> tuple[float, float]:
    """Return (lat, lng) for an H3 cell, caching results in-process."""
    result = _h3_latlng_cache.get(cell_id)
    if result is None:
        import h3 as h3lib_cache
        result = h3lib_cache.cell_to_latlng(cell_id)
        _h3_latlng_cache[cell_id] = result
    return result

# ── Reference data caches (read-only tables, loaded once) ────────────────────

@functools.lru_cache(maxsize=1)
def _get_taxonomy_map() -> dict:
    """Load IndustryTaxonomy into a dict once, keyed by industry_key."""
    engine = init_db()
    session = get_session(engine)
    try:
        from core.models.reference import IndustryTaxonomy as IT
        return {
            t.industry_key: {"display_name": t.display_name, "worker_tier": t.worker_tier}
            for t in session.query(IT).all()
        }
    finally:
        session.close()

@functools.lru_cache(maxsize=1)
def _get_occupation_data() -> tuple[list, dict]:
    """Load MobOccupation rows + OccupationAlias map once.

    Returns (occupation_dicts, alias_map) where alias_map is soc_code → [alias, ...].
    """
    engine = init_db()
    session = get_session(engine)
    try:
        from core.models.reference import MobOccupation, MobTransition, OccupationAlias
        occs = session.query(MobOccupation).order_by(MobOccupation.title).all()
        origin_socs = {r[0] for r in session.query(MobTransition.origin_soc).distinct().all()}

        alias_rows = session.query(OccupationAlias.soc_code, OccupationAlias.alias).all()
        alias_map: dict[str, list[str]] = {}
        for soc, alias in alias_rows:
            if soc not in alias_map:
                alias_map[soc] = []
            if len(alias_map[soc]) < 15:
                alias_map[soc].append(alias)

        occ_dicts = []
        for o in occs:
            occ_dicts.append({
                "soc_code": o.soc_code,
                "title": o.title,
                "median_hourly_wage": o.median_hourly_wage,
                "annual_employment": o.annual_employment,
                "industry_cluster": o.industry_cluster,
                "has_transitions": o.soc_code in origin_socs,
                "aliases": alias_map.get(o.soc_code, []),
            })
        return occ_dicts, alias_map
    finally:
        session.close()

app = Flask(
    __name__,
    # NOTE: This repo is backend-only. The frontend lives in the sibling repo
    # at /home/fortune/CodeProjects/First-Helios_Frontend/ (see README §Related Repos).
    # The `static_folder="frontend"` below is legacy — the folder does not exist
    # here and the static routes below will 404. Kept only to avoid breaking
    # imports that reference `app.static_folder`. Do NOT conclude from this that
    # there is an in-repo frontend to edit.
    static_folder="frontend",
    static_url_path="",
)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB POST body cap
CORS(app, origins=[
    "moz-extension://*",       # Firefox extension
    "chrome-extension://*",    # Chrome/Edge extension
    "http://localhost:8765",   # Local frontend
    "http://192.168.1.191",    # Orange Pi LAN frontend
])

# ── Privacy: IP Suppression Middleware (FH-1 §1 — Critical Priority 1) ────────
# Strip client IP from request context before ANY handler runs.
# Override Werkzeug / Flask logging to never emit IP addresses.

class _IPSuppressedRequest(Flask.request_class):
    """Custom request class that always returns a redacted remote address."""

    @property  # type: ignore[override]
    def remote_addr(self):  # type: ignore[override]
        return "0.0.0.0"

    @remote_addr.setter
    def remote_addr(self, value):
        pass  # discard — never store the real IP

app.request_class = _IPSuppressedRequest

class _IPFreeFormatter(logging.Formatter):
    """Log formatter that strips any IPv4/IPv6-like patterns from messages."""

    import re as _re
    _IPV4_RE = _re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    _IPV6_RE = _re.compile(r'[0-9a-fA-F]{1,4}(:[0-9a-fA-F]{1,4}){2,7}')

    def format(self, record):
        msg = super().format(record)
        msg = self._IPV4_RE.sub('[REDACTED]', msg)
        msg = self._IPV6_RE.sub('[REDACTED]', msg)
        return msg

# Apply IP-free formatter to werkzeug logger (Flask's default access log)
_werkzeug_logger = logging.getLogger('werkzeug')
for _handler in _werkzeug_logger.handlers[:]:
    _handler.setFormatter(_IPFreeFormatter('%(message)s'))
if not _werkzeug_logger.handlers:
    _wh = logging.StreamHandler()
    _wh.setFormatter(_IPFreeFormatter('%(message)s'))
    _werkzeug_logger.addHandler(_wh)

# ── Spirit Pool Blueprint ─────────────────────────────────────────────────────
try:
    from postings.spiritpool_routes import spiritpool_bp
    app.register_blueprint(spiritpool_bp)
    logger.info("Spirit Pool blueprint registered at /api/spiritpool")
except Exception as exc:
    logger.warning("Spirit Pool blueprint NOT registered: %s: %s", type(exc).__name__, exc)

# ── Events Blueprint ──────────────────────────────────────────────────────────
try:
    from events.routes import events_bp
    app.register_blueprint(events_bp)
    logger.info("Events blueprint registered at /api/events")
except Exception as exc:
    logger.warning("Events blueprint NOT registered: %s: %s", type(exc).__name__, exc)

# ── Contributor Intake Blueprint (FH-0) ───────────────────────────────────────
try:
    from core.contribute_routes import contribute_bp
    app.register_blueprint(contribute_bp)
    logger.info("Contributor blueprint registered (/api/contribute, /api/burn)")
except Exception as exc:
    logger.warning("Contributor blueprint NOT registered: %s: %s", type(exc).__name__, exc)

# ── Meal Deals Blueprint ──────────────────────────────────────────────────────
try:
    from collectors.meal_deals.routes import deals_bp
    app.register_blueprint(deals_bp)
    logger.info("Meal Deals blueprint registered at /api/deals")
except Exception as exc:
    logger.warning("Meal Deals blueprint NOT registered: %s: %s", type(exc).__name__, exc)

# ── Food Price Index Blueprint (FPI-1) ────────────────────────────────────────
try:
    from collectors.meal_deals.price_index_routes import price_index_bp
    app.register_blueprint(price_index_bp)
    logger.info("Price Index blueprint registered at /api/price-index")
except Exception as exc:
    logger.warning("Price Index blueprint NOT registered: %s: %s", type(exc).__name__, exc)


# ── Security: suppress exception details from API responses ──────────────────

def _err(e: Exception, status: int = 500):
    """Log the full exception, return a generic JSON error with no internal details."""
    logger.error("Request error [%s %s]: %s", request.method, request.path, e, exc_info=True)
    return jsonify({"status": "error", "message": "An internal error occurred"}), status

@app.errorhandler(Exception)
def handle_unhandled(e: Exception):
    return _err(e)

# ── Security: add hardening headers to every response ────────────────────────

@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response

# ── Frontend serving (LEGACY — frontend moved) ───────────────────────────────
# These routes served the in-repo frontend before it was split into
# `/home/fortune/CodeProjects/First-Helios_Frontend/` (sibling repo).
# They will 404 in this repo because the `frontend/` directory no longer exists
# here. They are kept as harmless stubs — do not rely on them, and do not edit
# files under `frontend/` in this repo expecting them to render.

@app.route("/")
def index():
    """Legacy route — frontend is served from the First-Helios_Frontend repo."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path):
    """Legacy route — frontend is served from the First-Helios_Frontend repo."""
    return send_from_directory(app.static_folder, path)


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
        return _err(e)
    finally:
        session.close()


@app.route("/api/scan", methods=["POST"])
def trigger_scan():
    """Trigger a scrape for a chain/region using public data sources.

    Body: {"chain": "starbucks", "region": "austin_tx"}

    NOTE: Direct website scraping (careers_api) has been moved to
    future_plans/web_scraping/. This endpoint now uses JobSpy.
    """
    data = request.get_json(silent=True) or {}
    chain = data.get("chain", "starbucks")
    region = data.get("region", "austin_tx")

    try:
        from collectors.job_boards.jobspy_adapter import scrape_jobspy

        signals = scrape_jobspy(chain=chain, region=region, mode="chain")
        compute_all_scores(region=region, chain=chain)

        return jsonify({
            "status": "ok",
            "signals_scraped": len(signals),
            "chain": chain,
            "region": region,
            "source": "jobspy",
        })
    except Exception as e:
        logger.error("[Server] Scan failed: %s", e)
        return _err(e)


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
        return _err(e)
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
        return _err(e)


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
        return _err(e)
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
            q = q.filter(Store.brand_key == chain)
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
        return _err(e)
    finally:
        session.close()


# ── Local Employers endpoint ─────────────────────────────────────────────────

CHAIN_THRESHOLD = 5  # location_count >= this → chain-like, exclude from local view

@app.route("/api/local-employers")
def get_local_employers():
    """Return local employer POIs.

    Chain-like records (location_count >= CHAIN_THRESHOLD) have been purged
    from the table by classify_local_employers.py, so no local_only filter
    is needed here.

    Query params:
      - region (default: austin_tx)
      - industry (optional): filter to one industry key.  When set, ALL
            matching records are returned (per-industry counts are small).
            When omitted, a random geographic sample is returned.
      - sample (default: 3000): max records when no industry filter is set.
            Pass sample=0 to return everything (may be slow for large regions).
    """
    region   = request.args.get("region", "austin_tx")
    industry = request.args.get("industry")
    sample   = min(max(1, request.args.get("sample", 3000, type=int)), 5000)

    engine = init_db()
    session = get_session(engine)

    try:
        from sqlalchemy import func as sqlfunc

        q = session.query(LocalEmployer).filter(
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
            LocalEmployer.lat.isnot(None),
            LocalEmployer.lng.isnot(None),
        )
        if industry:
            q = q.filter(LocalEmployer.industry == industry)

        if industry:
            # Specific industry: return all matches (per-industry counts are small)
            employers = q.all()
        elif sample == 0:
            employers = q.all()
        else:
            # No filter: random sample for geographic coverage
            employers = q.order_by(sqlfunc.random()).limit(sample).all()

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
                    "location_count": e.location_count,
                }
                for e in employers
            ],
            "count": len(employers),
        })

    except Exception as e:
        logger.error("[Server] Local employers query failed: %s", e)
        return _err(e)
    finally:
        session.close()


# ── Unified map endpoint ─────────────────────────────────────────────────────

@app.route("/api/map-employers")
def get_map_employers():
    """Map data sourced entirely from local_employers (Overture POI data).

    Records with location_count >= CHAIN_THRESHOLD are classified as 'brand'
    (multi-location area employer, e.g. H-E-B, CVS).
    Records below threshold are classified as 'local' (truly independent).

    The brand filter matches on LocalEmployer.name.
    The industry filter matches on LocalEmployer.industry.

    Query params:
      - region (default: austin_tx)
      - chain (optional): employer name to filter to (exact match on LocalEmployer.name)
      - industry (optional): industry key filter
      - sample (default: 3000): random sample size when no filters set; 0 = all
    """
    region   = request.args.get("region", "austin_tx")
    chain    = request.args.get("chain")
    industry = request.args.get("industry")
    sample   = min(max(1, request.args.get("sample", 3000, type=int)), 5000)

    engine = init_db()
    session = get_session(engine)

    try:
        from sqlalchemy import func as sqlfunc

        q = session.query(LocalEmployer).filter(
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
            LocalEmployer.lat.isnot(None),
            LocalEmployer.lng.isnot(None),
        )
        if chain:
            q = q.filter(LocalEmployer.name == chain)
        if industry:
            q = q.filter(LocalEmployer.industry == industry)

        # h3_cell: return only employers inside a specific H3 cell (for sidebar listings)
        h3_cell    = request.args.get("h3_cell")
        h3_res_arg = request.args.get("resolution", 7, type=int)
        if h3_cell and h3_res_arg in (6, 7, 8, 9):
            h3_col = f"h3_r{h3_res_arg}"
            q = q.filter(getattr(LocalEmployer, h3_col) == h3_cell)

        if chain or industry or h3_cell or sample == 0:
            employers = q.all()
        else:
            employers = q.order_by(sqlfunc.random()).limit(sample).all()

        results = []
        for e in employers:
            is_brand = (e.location_count or 0) >= CHAIN_THRESHOLD
            results.append({
                "source_type": "brand" if is_brand else "local",
                "name": e.name,
                "address": e.address,
                "lat": e.lat,
                "lng": e.lng,
                "industry": e.industry,
                "category": e.category,
                "location_count": e.location_count,
                "mobility_score": e.mobility_score,
            })

        brand_count = sum(1 for r in results if r["source_type"] == "brand")
        local_count = len(results) - brand_count
        return jsonify({
            "status": "ok",
            "employers": results,
            "count": len(results),
            "brand_count": brand_count,
            "local_count": local_count,
        })

    except Exception as e:
        logger.error("[Server] Map employers query failed: %s", e)
        return _err(e)
    finally:
        session.close()


@app.route("/api/h3-map")
def get_h3_map():
    """Aggregated H3 hex map data for zoom-adaptive rendering.

    Returns one record per occupied H3 cell instead of raw lat/lng points.
    At resolution 7 (default zoom 11), 45K employers collapse to ~453 cells.

    Query params:
      resolution  (int, default 7)  — H3 resolution 6-9
      region      (default: austin_tx)
      industry    (optional)        — filter by industry key
      chain       (optional)        — filter by employer name (brand)
    """
    import h3 as h3lib
    from sqlalchemy import case, func as sqlfunc

    resolution = request.args.get("resolution", 7, type=int)
    region     = request.args.get("region", "austin_tx")
    industry   = request.args.get("industry")
    chain      = request.args.get("chain")

    if resolution not in (6, 7, 8, 9):
        return jsonify({"status": "error", "message": "resolution must be 6, 7, 8, or 9"}), 400

    col     = f"h3_r{resolution}"
    h3_col  = getattr(LocalEmployer, col)
    is_brand = case((LocalEmployer.location_count >= CHAIN_THRESHOLD, 1), else_=0)

    engine = init_db()
    session = get_session(engine)
    try:
        q = session.query(
            h3_col.label("cell_id"),
            sqlfunc.count().label("count"),
            sqlfunc.sum(is_brand).label("brand_count"),
            sqlfunc.avg(LocalEmployer.mobility_score).label("avg_score"),
        ).filter(
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
            h3_col.isnot(None),
        )

        if industry:
            q = q.filter(LocalEmployer.industry == industry)
        if chain:
            q = q.filter(LocalEmployer.name == chain)

        q = q.group_by(h3_col)
        rows = q.all()

        cells = []
        for row in rows:
            cell_id = row.cell_id
            lat, lng = _cached_cell_to_latlng(cell_id)
            cells.append({
                "cell_id":     cell_id,
                "count":       row.count,
                "brand_count": row.brand_count or 0,
                "avg_score":   round(row.avg_score, 1) if row.avg_score else None,
                "lat":         lat,
                "lng":         lng,
            })

        return jsonify({
            "status":     "ok",
            "resolution": resolution,
            "cell_count": len(cells),
            "cells":      cells,
        })

    except Exception as e:
        logger.error("[Server] H3 map query failed: %s", e)
        return _err(e)
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
        return _err(e)
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
        return _err(e)
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
        return _err(e)
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
        return _err(e)
    finally:
        session.close()


@app.route("/api/ref/summary")
def ref_summary():
    """Return a combined summary: chains + industries + store counts.

    Chains and industries are derived entirely from what is actually ingested
    in the Store and LocalEmployer tables.  Reference tables (BrandProfile,
    IndustryTaxonomy) supply display names / metadata only — they never gate
    what appears in the dropdowns.
    """
    engine = init_db()
    session = get_session(engine)
    try:
        from sqlalchemy import func

        # ── Brands: multi-location employers from local_employers.
        # Any business appearing >= CHAIN_THRESHOLD times in Austin data
        # is treated as a brand (area chain) and shown in the filter dropdown.
        # Sorted by location count descending so biggest employers appear first.
        brand_rows = (
            session.query(LocalEmployer.name, func.count(LocalEmployer.id))
            .filter(
                LocalEmployer.is_active.is_(True),
                LocalEmployer.location_count >= CHAIN_THRESHOLD,
            )
            .group_by(LocalEmployer.name)
            .order_by(func.count(LocalEmployer.id).desc())
            .all()
        )

        chain_list = [
            {
                "chain_key": name,
                "chain_name": name,
                "location_count": cnt,
                "has_scores": False,
            }
            for name, cnt in brand_rows
        ]

        # ── Industries: built from local_employers (single source).
        #    Display name resolved from IndustryTaxonomy.
        local_counts_by_ind = dict(
            session.query(LocalEmployer.industry, func.count(LocalEmployer.id))
            .filter(LocalEmployer.is_active.is_(True), LocalEmployer.industry.isnot(None))
            .group_by(LocalEmployer.industry)
            .all()
        )
        taxonomy_map = _get_taxonomy_map()
        industry_list = sorted(
            [
                {
                    "industry_key": key,
                    "display_name": taxonomy_map.get(key, {}).get("display_name") or key.replace("_", " ").title(),
                    "worker_tier": taxonomy_map.get(key, {}).get("worker_tier"),
                    "local_count": cnt,
                }
                for key, cnt in local_counts_by_ind.items()
            ],
            key=lambda x: x["display_name"],
        )

        brand_total = sum(cnt for _, cnt in brand_rows)
        local_total = sum(local_counts_by_ind.values())

        return jsonify({
            "status": "ok",
            "chains": chain_list,
            "industries": industry_list,
            "brand_total": brand_total,
            "local_employer_total": local_total,
        })
    except Exception as e:
        logger.error("[Server] Ref summary query failed: %s", e)
        return _err(e)
    finally:
        session.close()


# ── Scheduler endpoint ───────────────────────────────────────────────────────

@app.route("/api/scheduler/status")
def scheduler_status():
    """Return scheduler job status.

    The scheduler now runs in collector_main.py (separate process).
    This endpoint reflects that process's state only if it happens to share
    this Python interpreter (dev mode); in production it will show running=false.
    """
    try:
        status = get_scheduler_status()
        status["note"] = "scheduler runs as collector_main.py — start that process separately"
        return jsonify({"status": "ok", **status})
    except Exception as e:
        return _err(e)


# ── Rate Budget / Metrics endpoints ──────────────────────────────────────────

@app.route("/api/rate-budget")
def rate_budget_status():
    """Return rate-limit budget status for all API sources.

    Query params:
      - source (optional): one source_key for detailed view
    """
    try:
        from core.rate_manager import rate_manager

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
        return _err(e)


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
        from core.rate_manager import rate_manager
        history = rate_manager.get_source_history(source, days=days)
        return jsonify({
            "status": "ok",
            "source": source,
            "days": days,
            "history": history,
        })
    except Exception as e:
        logger.error("[Server] Rate history query failed: %s", e)
        return _err(e)


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
        from core.rate_manager import rate_manager
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
        return _err(e)


@app.route("/api/rate-budget/scalability")
def rate_budget_scalability():
    """Return scalability planning report.

    Shows bottlenecks (>80% utilization), expandable sources (<20%),
    and failing sources (<80% success rate).
    """
    try:
        from core.rate_manager import rate_manager
        report = rate_manager.get_scalability_report()
        return jsonify({"status": "ok", **report})
    except Exception as e:
        logger.error("[Server] Scalability report failed: %s", e)
        return _err(e)


@app.route("/api/collector/runs")
def collector_runs():
    """Per-source, per-industry-key pull stats for tracking search term success."""
    from core.database import CollectorRun
    from sqlalchemy import func
    from datetime import timedelta

    source = request.args.get("source")
    days   = max(1, request.args.get("days", 30, type=int))
    limit  = min(500, request.args.get("limit", 100, type=int))

    engine  = init_db()
    session = get_session(engine)
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = session.query(
            CollectorRun.source,
            CollectorRun.industry_key,
            CollectorRun.search_term,
            func.count().label("runs"),
            func.sum(CollectorRun.fetched).label("total_fetched"),
            func.sum(CollectorRun.new).label("total_new"),
            func.sum(CollectorRun.updated).label("total_updated"),
            func.max(CollectorRun.run_at).label("last_run"),
        ).filter(CollectorRun.run_at >= cutoff)

        if source:
            q = q.filter(CollectorRun.source == source)

        rows = (
            q.group_by(CollectorRun.source, CollectorRun.industry_key, CollectorRun.search_term)
             .order_by(func.sum(CollectorRun.new).desc())
             .limit(limit)
             .all()
        )

        return jsonify({
            "status": "ok",
            "days":   days,
            "rows": [
                {
                    "source":        r.source,
                    "industry_key":  r.industry_key,
                    "search_term":   r.search_term,
                    "runs":          r.runs,
                    "total_fetched": int(r.total_fetched or 0),
                    "total_new":     int(r.total_new or 0),
                    "total_updated": int(r.total_updated or 0),
                    "last_run":      r.last_run.isoformat() if r.last_run else None,
                }
                for r in rows
            ],
        })
    except Exception as exc:
        logger.error("/api/collector/runs error: %s", exc)
        return _err(exc)
    finally:
        session.close()


# ── Career Pathfinder — Mobility API ─────────────────────────────────────────

@app.route("/api/mobility/occupations")
def mobility_occupations():
    """Return all occupations in the mobility graph for client-side filtering.

    Returns all 781 mob_occupation rows with a compact set of alias keywords
    per occupation (up to 15 per SOC), so the frontend can match common job
    titles like 'barista' or 'personal trainer' without an extra API call.
    """
    try:
        occ_dicts, _ = _get_occupation_data()
        return jsonify({
            "status": "ok",
            "occupations": occ_dicts,
        })
    except Exception as e:
        logger.error("[mobility/occupations] %s", e)
        return _err(e)


@app.route("/api/mobility/search")
def mobility_search():
    """Fuzzy-match a job title to SOC codes — searches titles AND Census aliases.

    Query params:
      q (alias: job_title) — job title string (required)
      limit                — max results (default 10)

    Searches mob_occupation.title first (official titles), then
    ref_occupation_aliases.alias (28k Census job-title variants) so that
    common terms like 'barista', 'cashier', 'CDL driver' resolve correctly.
    """
    q = (request.args.get("q") or request.args.get("job_title") or "").strip()
    if not q:
        return jsonify({"status": "error", "message": "q or job_title is required"}), 400
    limit = min(int(request.args.get("limit", 10)), 50)

    try:
        db = get_session(init_db())

        origin_socs = {
            r[0] for r in db.query(MobTransition.origin_soc).distinct().all()
        }

        # 1. Title matches (official SOC titles)
        title_matches = (
            db.query(MobOccupation)
            .filter(MobOccupation.title.ilike(f"%{q}%"))
            .order_by(MobOccupation.median_hourly_wage.asc().nulls_last())
            .limit(limit)
            .all()
        )
        seen_socs = {o.soc_code for o in title_matches}

        # 2. Alias matches — find SOC codes where an alias contains the query
        alias_socs = (
            db.query(OccupationAlias.soc_code)
            .filter(OccupationAlias.alias.ilike(f"%{q}%"))
            .distinct()
            .limit(limit)
            .all()
        )
        alias_soc_set = {r[0] for r in alias_socs} - seen_socs

        alias_occs = []
        if alias_soc_set:
            alias_occs = (
                db.query(MobOccupation)
                .filter(MobOccupation.soc_code.in_(alias_soc_set))
                .order_by(MobOccupation.median_hourly_wage.asc().nulls_last())
                .limit(limit - len(title_matches))
                .all()
            )

        all_matches = title_matches + alias_occs

        return jsonify({
            "status": "ok",
            "query": q,
            "matches": [
                {
                    **o.to_dict(),
                    "has_transitions": o.soc_code in origin_socs,
                }
                for o in all_matches
            ],
        })
    except Exception as e:
        logger.error("[mobility/search] %s", e)
        return _err(e)
    finally:
        db.close()


@app.route("/api/mobility/paths")
def mobility_paths():
    """Return ranked career transition paths from an origin SOC code.

    Query params:
      soc            — origin SOC code (required), e.g. "41-2011"
      wage_filter    — "up" | "lateral_or_up" | "any"  (default: "lateral_or_up")
      same_cluster   — "true" | "false" | "any"  (default: "any")
      max_skill_gap  — float ceiling on avg_skill_gap (default: none)
      limit          — max results (default: 15)

    Returns list of destination occupations with transition metadata and
    trajectory outcomes, ordered by frequency then skill gap.
    """
    soc = request.args.get("soc", "").strip()
    if not soc:
        return jsonify({"status": "error", "message": "soc is required"}), 400

    wage_filter    = request.args.get("wage_filter", "")   # "up" | "lateral" | "" (any)
    cluster_filter = request.args.get("same_cluster", "")  # "1"/"true" | ""
    max_gap        = request.args.get("max_skill_gap")
    limit          = min(int(request.args.get("limit", 15)), 50)

    try:
        db = get_session(init_db())

        # Check if we have a direct origin or need to use fallback SOC
        origin_occ = db.query(MobOccupation).filter_by(soc_code=soc).first()

        # Find the effective origin SOC (may differ from requested if not in Emsi origins)
        origin_count = db.query(MobTransition).filter_by(origin_soc=soc).count()
        effective_soc = soc

        if origin_count == 0:
            # Attempt minor-group fallback (first 5 chars, e.g. "35-30")
            fallback = (
                db.query(MobTransition.origin_soc)
                .filter(MobTransition.origin_soc.like(f"{soc[:5]}%"))
                .join(MobOccupation, MobTransition.origin_soc == MobOccupation.soc_code)
                .order_by(MobOccupation.median_hourly_wage.asc().nulls_last())
                .first()
            )
            if not fallback:
                # Major-group fallback (first 2 chars, e.g. "35")
                fallback = (
                    db.query(MobTransition.origin_soc)
                    .filter(MobTransition.origin_soc.like(f"{soc[:2]}%"))
                    .join(MobOccupation, MobTransition.origin_soc == MobOccupation.soc_code)
                    .order_by(MobOccupation.median_hourly_wage.asc().nulls_last())
                    .first()
                )
            effective_soc = fallback[0] if fallback else soc

        # Build query
        q = (
            db.query(MobTransition, MobOccupation)
            .join(MobOccupation, MobTransition.dest_soc == MobOccupation.soc_code)
            .filter(MobTransition.origin_soc == effective_soc)
        )

        if wage_filter == "up":
            q = q.filter(MobTransition.wage_direction == 1)
        elif wage_filter == "lateral":
            q = q.filter(MobTransition.wage_direction == 0)
        elif wage_filter == "lateral_or_up":
            q = q.filter(MobTransition.wage_direction >= 0)
        elif wage_filter == "down":
            q = q.filter(MobTransition.wage_direction == -1)
        elif wage_filter == "lateral_or_down":
            q = q.filter(MobTransition.wage_direction <= 0)
        # "" / "any" → no wage filter

        if cluster_filter in ("1", "true"):
            q = q.filter(MobTransition.same_cluster == True)   # noqa: E712
        elif cluster_filter in ("0", "false"):
            q = q.filter(MobTransition.same_cluster == False)  # noqa: E712

        if max_gap:
            q = q.filter(MobTransition.avg_skill_gap <= float(max_gap))

        # Fetch a larger pool then re-rank with composite score so the final
        # ordering reflects more than just raw transition frequency.
        rows = (
            q.order_by(
                MobTransition.transition_order.asc().nulls_last(),
                MobTransition.avg_skill_gap.asc(),
            )
            .limit(min(limit * 3, 50))
            .all()
        )

        import json as _json
        import math as _math

        def _path_score(t, dest):
            """Composite career-path score.  Higher = better recommendation.

            Components
            ----------
            accessibility  (40 %) — skill gap + how often workers make this move
            wage_value     (35 %) — immediate pay outcome; lateral gets a bonus
                                    because it opens future paths without friction
            trajectory     (25 %) — 3-yr wage growth at the destination
            """
            gap   = t.avg_skill_gap or 0.5
            order = t.transition_order or 99

            # Piecewise gap score:
            #   ≤ 0.30  → boost  (1.0–1.5)   easy to cross, prioritise heavily
            #   0.30–0.40 → transition (1.0–0.7)
            #   > 0.40  → steep penalty (0.7→0)  hard to break in
            if gap <= 0.30:
                gap_score = 1.0 + (0.30 - gap) / 0.30 * 0.50   # 0→1.50, 0.15→1.25, 0.30→1.0
            elif gap <= 0.40:
                gap_score = 1.0 - (gap - 0.30) * 3.0            # 0.30→1.0, 0.40→0.70
            else:
                gap_score = max(0.0, 0.70 - (gap - 0.40) * 1.75) # 0.40→0.70, 0.80→0.0

            order_score = 1.0 / _math.log1p(order)          # 1→1.0, 2→0.63, 10→0.42
            access      = 0.6 * gap_score + 0.4 * order_score
            if t.requires_new_license:
                access *= 0.80

            if t.wage_direction == 1:
                change = t.wage_change_dollars or 0
                wage_val = 0.50 + min(change / 40.0, 0.50)  # 0.50–1.00
            elif t.wage_direction == 0:
                wage_val = 0.65                              # lateral bonus
            else:
                change   = abs(t.wage_change_dollars or 0)
                wage_val = max(0.0, 0.35 - change / 25.0)   # 0–0.35

            traj_3yr = dest.traj_med_wage_growth_3yr or 0
            traj     = min(traj_3yr / 15.0, 1.0)

            return 0.40 * access + 0.35 * wage_val + 0.25 * traj

        scored = sorted(rows, key=lambda r: _path_score(r[0], r[1]), reverse=True)
        rows   = scored[:limit]

        paths = []
        for t, dest in rows:
            dest_keys = _json.loads(dest.dest_industry_keys_json) if dest.dest_industry_keys_json else []
            paths.append({
                "dest_soc":             t.dest_soc,
                "dest_title":           dest.title,
                "dest_median_wage":     dest.median_hourly_wage,
                "dest_cluster":         dest.cluster_name,
                "dest_traj_3yr":        dest.traj_med_wage_growth_3yr,
                "transition_order":     t.transition_order,
                "wage_direction":       t.wage_direction,
                "wage_change_dollars":  t.wage_change_dollars,
                "avg_skill_gap":        t.avg_skill_gap,
                "requires_license":     t.requires_new_license,
                "same_cluster":         t.same_cluster,
                "ranking_score":        round(_path_score(t, dest), 3),
                "dest_industry_keys":   dest_keys,
            })

        return jsonify({
            "status": "ok",
            "origin_soc":      soc,
            "origin_soc_used": effective_soc,
            "origin":          origin_occ.to_dict() if origin_occ else None,
            "paths":           paths,
        })
    except Exception as e:
        logger.error("[mobility/paths] %s", e)
        return _err(e)
    finally:
        db.close()


@app.route("/api/mobility/employers")
def mobility_employers():
    """Return nearby employers for a destination SOC code.

    Query params:
      soc      — destination SOC code (required)
      lat      — center latitude  (required)
      lng      — center longitude (required)
      radius   — search radius in miles (default: 10)
      limit    — max results (default: 50)

    Returns chain_locations and local_employers whose industry matches
    the destination SOC's dest_industry_keys, ordered by distance.
    Includes a direct job search URL for prototyping (before live scraping).
    """
    soc    = request.args.get("soc", "").strip()
    lat    = request.args.get("lat")
    lng    = request.args.get("lng")
    if not soc or not lat or not lng:
        return jsonify({"status": "error", "message": "soc, lat, lng are required"}), 400

    lat    = float(lat)
    lng    = float(lng)
    radius = float(request.args.get("radius", 10))
    limit  = min(int(request.args.get("limit", 50)), 200)

    try:
        import json as _json
        import math
        from sqlalchemy import func as sqlfunc

        db = get_session(init_db())

        occ = db.query(MobOccupation).filter_by(soc_code=soc).first()
        if not occ or not occ.dest_industry_keys_json:
            return jsonify({"status": "ok", "soc": soc, "employers": [], "industry_keys": []})

        dest_keys = _json.loads(occ.dest_industry_keys_json)

        # Approx degree-to-miles: 1 deg lat ≈ 69 miles, 1 deg lng ≈ 69*cos(lat) miles
        lat_delta = radius / 69.0
        lng_delta = radius / (69.0 * math.cos(math.radians(lat)))

        employers = []

        # Chain locations — random sample so results are geographically distributed
        chains = (
            db.query(Store)
            .filter(
                Store.industry.in_(dest_keys),
                Store.lat.between(lat - lat_delta, lat + lat_delta),
                Store.lng.between(lng - lng_delta, lng + lng_delta),
                Store.is_active == True,  # noqa: E712
            )
            .order_by(sqlfunc.random())
            .limit(limit)
            .all()
        )
        for c in chains:
            d = c.to_dict()
            d["employer_type"] = "chain"
            d["job_search_url"] = (
                f"https://www.indeed.com/jobs?q={occ.title.replace(' ', '+')}"
                f"&l={c.address.replace(' ', '+')}"
            )
            employers.append(d)

        # Local employers — random sample so results are geographically distributed
        remaining = limit - len(chains)
        if remaining > 0:
            locals_ = (
                db.query(LocalEmployer)
                .filter(
                    LocalEmployer.industry.in_(dest_keys),
                    LocalEmployer.lat.between(lat - lat_delta, lat + lat_delta),
                    LocalEmployer.lng.between(lng - lng_delta, lng + lng_delta),
                    LocalEmployer.is_active == True,  # noqa: E712
                )
                .order_by(sqlfunc.random())
                .limit(remaining)
                .all()
            )
            for loc in locals_:
                d = loc.to_dict()
                d["employer_type"] = "local"
                d["job_search_url"] = (
                    f"https://www.indeed.com/jobs?q={occ.title.replace(' ', '+')}"
                    f"+{loc.name.replace(' ', '+')}&l=Austin+TX"
                )
                employers.append(d)

        return jsonify({
            "status": "ok",
            "soc": soc,
            "occupation": occ.title,
            "industry_keys": dest_keys,
            "employer_count": len(employers),
            "employers": employers,
        })
    except Exception as e:
        logger.error("[mobility/employers] %s", e)
        return _err(e)
    finally:
        db.close()


# ── Job Finder endpoints ─────────────────────────────────────────────────────

@app.route("/api/jobs/h3-map")
def jobs_h3_map():
    """H3 hex aggregation of active job_postings that have coordinates.

    JobPosting only stores h3_r7 and h3_r8, so resolution is clamped to 7–8.

    Query params:
      resolution  (int, default 7)  — 7 or 8
      region      (default: austin_tx)
      category    (optional)        — industry string filter
      mode        local | remote | all  (default: local)
                  local  = jobs where is_remote is not True
                  remote = jobs where is_remote is True
                  all    = no is_remote filter
    """
    import h3 as h3lib
    from sqlalchemy import func as sqlfunc
    from postings.models import JobPosting

    resolution = request.args.get("resolution", 7, type=int)
    region     = request.args.get("region", "austin_tx")
    category   = request.args.get("category")
    mode       = request.args.get("mode", "local")

    # h3_r6: aggregate r7 cells server-side; clamp to 6–8
    resolution = max(6, min(8, resolution))
    agg_to_r6  = resolution <= 6
    h3_col     = JobPosting.h3_r7 if agg_to_r6 else getattr(JobPosting, f"h3_r{resolution}")

    engine  = init_db()
    session = get_session(engine)
    try:
        q = session.query(
            h3_col.label("cell_id"),
            sqlfunc.count().label("count"),
        ).filter(
            JobPosting.region   == region,
            JobPosting.is_active.is_(True),
            h3_col.isnot(None),
        )

        if mode == "local":
            q = q.filter(JobPosting.is_remote.isnot(True))
        elif mode == "remote":
            q = q.filter(JobPosting.is_remote.is_(True))

        if category:
            q = q.filter(JobPosting.industry == category)

        rows = q.group_by(h3_col).all()

        cells = []
        if agg_to_r6:
            from collections import defaultdict
            r6_counts: dict = defaultdict(int)
            for row in rows:
                if row.cell_id:
                    parent = h3lib.cell_to_parent(row.cell_id, 6)
                    r6_counts[parent] += row.count
            for cell_id, count in r6_counts.items():
                lat, lng = _cached_cell_to_latlng(cell_id)
                cells.append({"cell_id": cell_id, "count": count, "lat": lat, "lng": lng})
        else:
            for row in rows:
                lat, lng = _cached_cell_to_latlng(row.cell_id)
                cells.append({"cell_id": row.cell_id, "count": row.count, "lat": lat, "lng": lng})

        return jsonify({"status": "ok", "resolution": resolution, "cell_count": len(cells), "cells": cells})

    except Exception as e:
        logger.error("[jobs/h3-map] %s", e)
        return _err(e)
    finally:
        session.close()


@app.route("/api/jobs/listings")
def jobs_listings():
    """Paginated job postings, optionally filtered to a single H3 cell.

    Query params:
      region      (default: austin_tx)
      h3_cell     (optional) — restrict to one H3 cell (ignores mode filter)
      resolution  (int, default 7) — which h3 column to use when h3_cell given
      mode        local | remote | all  (default: all)
      category    (optional) — industry string filter
      page        (int, default 1)
      limit       (int, default 20, max 100)
      wage_min_filter  (float, optional) — min hourly wage (yearly auto-converted)
      wage_max_filter  (float, optional) — max hourly wage (yearly auto-converted)
      posted_within    (int, optional) — only jobs posted within N days
      time_type        (str, optional) — filter on detail_json->>'time_type'
    """
    from sqlalchemy import case as sa_case
    from postings.models import JobPosting

    region     = request.args.get("region", "austin_tx")
    h3_cell    = request.args.get("h3_cell")
    resolution = request.args.get("resolution", 7, type=int)
    mode       = request.args.get("mode", "all")
    category   = request.args.get("category")
    page       = max(1, request.args.get("page", 1, type=int))
    limit      = min(100, request.args.get("limit", 20, type=int))
    sort       = request.args.get("sort", "date")   # "date" | "wage"
    keyword    = request.args.get("q", "").strip()[:100]
    wage_min_filter = request.args.get("wage_min_filter", type=float)
    wage_max_filter = request.args.get("wage_max_filter", type=float)
    posted_within   = request.args.get("posted_within", type=int)
    _VALID_TIME_TYPES = {"Full-time", "Part-time", "Contract", "Temporary", "Internship"}
    time_type_raw    = request.args.get("time_type", "").strip()
    time_type        = time_type_raw if time_type_raw in _VALID_TIME_TYPES else ""

    engine  = init_db()
    session = get_session(engine)
    try:
        q = session.query(JobPosting).filter(
            JobPosting.region   == region,
            JobPosting.is_active.is_(True),
        )

        if h3_cell:
            if resolution <= 6:
                # r6 cell: expand to all r7 children and filter on h3_r7
                import h3 as h3lib_local
                children = list(h3lib_local.cell_to_children(h3_cell, 7))
                q = q.filter(JobPosting.h3_r7.in_(children))
            else:
                resolution = max(7, min(8, resolution))
                h3_col = getattr(JobPosting, f"h3_r{resolution}")
                q = q.filter(h3_col == h3_cell)
        elif mode == "local":
            q = q.filter(JobPosting.is_remote.isnot(True))
        elif mode == "remote":
            q = q.filter(JobPosting.is_remote.is_(True))

        if category:
            q = q.filter(JobPosting.industry == category)

        if keyword:
            like = f"%{keyword}%"
            q = q.filter(
                JobPosting.role_title.ilike(like) |
                JobPosting.raw_employer_name.ilike(like)
            )

        # ── Wage range filter (normalise yearly→hourly via case()) ────────
        if wage_min_filter is not None or wage_max_filter is not None:
            hourly_min_expr = sa_case(
                (JobPosting.wage_period == 'yearly', JobPosting.wage_min / 2080),
                (JobPosting.wage_period == 'monthly', JobPosting.wage_min / (2080 / 12)),
                (JobPosting.wage_period == 'weekly', JobPosting.wage_min / 40),
                else_=JobPosting.wage_min,
            )
            hourly_max_expr = sa_case(
                (JobPosting.wage_period == 'yearly', JobPosting.wage_max / 2080),
                (JobPosting.wage_period == 'monthly', JobPosting.wage_max / (2080 / 12)),
                (JobPosting.wage_period == 'weekly', JobPosting.wage_max / 40),
                else_=JobPosting.wage_max,
            )
            if wage_min_filter is not None:
                # Job's max hourly must be >= the filter minimum
                q = q.filter(hourly_max_expr >= wage_min_filter)
            if wage_max_filter is not None:
                # Job's min hourly must be <= the filter maximum
                q = q.filter(hourly_min_expr <= wage_max_filter)

        # ── Posted-within filter ──────────────────────────────────────────
        if posted_within:
            cutoff_date = datetime.utcnow() - timedelta(days=posted_within)
            q = q.filter(
                (JobPosting.posted_date >= cutoff_date) |
                (JobPosting.posted_date.is_(None))
            )

        # ── Time type filter (JSONB) ─────────────────────────────────────
        if time_type:
            q = q.filter(
                JobPosting.detail_json["time_type"].astext.ilike(f"%{time_type}%")
            )

        total = q.count()

        from sqlalchemy import nullslast
        if sort == "wage":
            order = [nullslast(JobPosting.wage_min.desc()), nullslast(JobPosting.posted_date.desc())]
        else:
            order = [nullslast(JobPosting.posted_date.desc())]

        postings = (
            q.order_by(*order)
             .offset((page - 1) * limit)
             .limit(limit)
             .all()
        )

        # Cap per (source, fingerprint) so one employer+source can't flood a page.
        # Keeps the N most-recent postings per group; others are pushed to later pages.
        _MAX_PER_GROUP = 5
        _grp: dict[tuple, int] = {}
        _deduped = []
        for jp in postings:
            _k = (jp.source, jp.fingerprint or jp.raw_employer_name)
            _grp[_k] = _grp.get(_k, 0) + 1
            if _grp[_k] <= _MAX_PER_GROUP:
                _deduped.append(jp)
        postings = _deduped

        def _wage_both(jp):
            """Return (primary_str, alt_str) showing both hourly and yearly.

            primary is in the source period; alt is the conversion.
            Both are None when no wage data exists.
            """
            if not jp.wage_min and not jp.wage_max:
                return None, None
            period = jp.wage_period or "hourly"

            lo_raw = jp.wage_min or 0.0
            hi_raw = jp.wage_max or 0.0

            if period == "yearly":
                lo_yr = lo_raw if jp.wage_min else None
                hi_yr = hi_raw if jp.wage_max else None
                lo_hr = round(lo_raw / 2080, 2) if jp.wage_min else None
                hi_hr = round(hi_raw / 2080, 2) if jp.wage_max else None
            elif period == "monthly":
                lo_yr = lo_raw * 12 if jp.wage_min else None
                hi_yr = hi_raw * 12 if jp.wage_max else None
                lo_hr = round((lo_raw * 12) / 2080, 2) if jp.wage_min else None
                hi_hr = round((hi_raw * 12) / 2080, 2) if jp.wage_max else None
            elif period == "weekly":
                lo_yr = lo_raw * 52 if jp.wage_min else None
                hi_yr = hi_raw * 52 if jp.wage_max else None
                lo_hr = round((lo_raw * 52) / 2080, 2) if jp.wage_min else None
                hi_hr = round((hi_raw * 52) / 2080, 2) if jp.wage_max else None
            else:  # hourly
                lo_hr = lo_raw if jp.wage_min else None
                hi_hr = hi_raw if jp.wage_max else None
                lo_yr = round(lo_raw * 2080) if jp.wage_min else None
                hi_yr = round(hi_raw * 2080) if jp.wage_max else None

            def _fmt_hr(lo, hi):
                parts = []
                if lo: parts.append(f"${lo:.2f}")
                if hi: parts.append(f"${hi:.2f}")
                return "\u2013".join(parts) + "/hr" if parts else None

            def _fmt_yr(lo, hi):
                parts = []
                if lo: parts.append(f"${int(lo / 1000)}k" if lo >= 1000 else f"${int(lo)}")
                if hi: parts.append(f"${int(hi / 1000)}k" if hi >= 1000 else f"${int(hi)}")
                return "\u2013".join(parts) + "/yr" if parts else None

            hr_str = _fmt_hr(lo_hr, hi_hr)
            yr_str = _fmt_yr(lo_yr, hi_yr)
            return hr_str, yr_str

        def _build_job(jp):
            hr_str, yr_str = _wage_both(jp)
            return {
                "id":          jp.id,
                "employer":    jp.raw_employer_name,
                "role_title":  jp.role_title,
                "industry":    jp.industry,
                "wage":        hr_str,
                "wage_yr":     yr_str,
                "is_remote":   jp.is_remote,
                "raw_address": jp.raw_address,
                "source_url":  jp.source_url,
                "referral_url": jp.referral_url,
                "posted_date": jp.posted_date.isoformat() if jp.posted_date else None,
                "source":      jp.source,
                "excerpt":     jp.job_excerpt,
                "detail":      jp.detail_json,
                "h3_r7":       jp.h3_r7,
                "h3_r8":       jp.h3_r8,
                "lat":         jp.lat,
                "lng":         jp.lng,
            }

        jobs = [_build_job(jp) for jp in postings]

        return jsonify({
            "status": "ok",
            "page":   page,
            "pages":  max(1, (total + limit - 1) // limit),
            "total":  total,
            "jobs":   jobs,
        })

    except Exception as e:
        logger.error("[jobs/listings] %s", e)
        return _err(e)
    finally:
        session.close()


@app.route("/api/jobs/categories")
def jobs_categories():
    """Distinct industry categories present in active job_postings.

    Query params:
      region  (default: austin_tx)
    """
    from sqlalchemy import func as sqlfunc
    from postings.models import JobPosting

    region  = request.args.get("region", "austin_tx")
    engine  = init_db()
    session = get_session(engine)
    try:
        taxonomy_map = {
            t.industry_key: t.display_name
            for t in session.query(IndustryTaxonomy).all()
        }
        rows = (
            session.query(JobPosting.industry, sqlfunc.count().label("count"))
            .filter(
                JobPosting.region   == region,
                JobPosting.is_active.is_(True),
                JobPosting.industry.isnot(None),
            )
            .group_by(JobPosting.industry)
            .order_by(sqlfunc.count().desc())
            .all()
        )
        categories = [
            {
                "key":   r.industry,
                "label": taxonomy_map.get(r.industry) or r.industry.replace("_", " ").title(),
                "count": r.count,
            }
            for r in rows
        ]
        return jsonify({"status": "ok", "categories": categories})

    except Exception as e:
        logger.error("[jobs/categories] %s", e)
        return _err(e)
    finally:
        session.close()


# ── Server startup ───────────────────────────────────────────────────────────

def create_app() -> Flask:
    """Application factory for Flask."""
    # Initialize database
    init_db()

    return app


if __name__ == "__main__":
    # Use _IPFreeFormatter for the root logger — defence-in-depth so that
    # any IP that leaks into a log message from exceptions or third-party
    # libraries is scrubbed before it reaches disk or stdout.
    _root_handler = logging.StreamHandler()
    _root_handler.setFormatter(_IPFreeFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(
        level=logging.INFO,
        handlers=[_root_handler],
    )

    parser = argparse.ArgumentParser(description="ChainStaffingTracker Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    args = parser.parse_args()

    create_app()
    app.run(host="0.0.0.0", port=args.port, debug=args.debug, use_reloader=False)
