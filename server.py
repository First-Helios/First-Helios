"""
server.py — Chain Staffing Tracker
====================================
Replaces the plain python -m http.server.
Serves the frontend AND exposes a small API to trigger/monitor
the scraper from the browser.

Usage
-----
    python server.py                        # production
    python server.py --port 8765            # custom port
    python server.py --debug                # Flask debug mode (auto-reload)

API endpoints
-------------
GET  /api/scan/status
    Returns last-scan metadata + whether a re-scan is allowed.

POST /api/scan
    Body (JSON): { "location": "Seattle, WA, US", "radius": 25, "force": false }
    Starts a background scrape.  Returns immediately.
    "force": true bypasses the 7-day cooldown (dev mode).

Scan state machine:  idle → running → done | error
"""

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.models import db
from backend.api import spiritpool_bp

# ── Paths ──────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
FRONTEND    = ROOT / "frontend"
VACANCIES   = FRONTEND / "data" / "vacancies.json"
HISTORY     = FRONTEND / "data" / "history.json"
SCRAPER     = ROOT / "scraper" / "scrape.py"
PYTHON      = sys.executable          # same venv that runs this server
SCAN_LOG    = ROOT / "scraper" / "last_scan.log"
DB_PATH     = ROOT / "data" / "spiritpool.db"

# ── Config ─────────────────────────────────────────────────────────
STALE_AFTER_DAYS = 7      # days before data is considered stale
DEFAULT_RADIUS   = 25     # miles
DATABASE_URL     = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

# ── Flask app ──────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")

# SpiritPool database
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# CORS — allow extension origin (moz-extension://) to POST signals
CORS(app, resources={r"/api/spiritpool/*": {"origins": "*"}})

# Register SpiritPool API blueprint
app.register_blueprint(spiritpool_bp)

# Create tables on first run
with app.app_context():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.create_all()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── In-memory scan state (survives only while server is running) ───
_scan_lock  = threading.Lock()
_scan_state = {
    "status":      "idle",   # idle | running | done | error
    "location":    None,
    "radius":      None,
    "started_at":  None,
    "finished_at": None,
    "message":     "",
    "exit_code":   None,
}


# ── Helpers ────────────────────────────────────────────────────────

def _read_vacancies_meta() -> dict | None:
    """Read just the top-level metadata from vacancies.json (no store array)."""
    if not VACANCIES.exists():
        return None
    try:
        raw  = VACANCIES.read_text()
        data = json.loads(raw)
        return {
            "generated":    data.get("generated"),
            "location":     data.get("location"),
            "radius_mi":    data.get("radius_mi"),
            "total_stores": data.get("total_stores", 0),
        }
    except Exception as exc:
        log.warning("Could not read vacancies.json: %s", exc)
        return None


def _parse_generated(ts_str: str | None) -> datetime | None:
    """Parse the ISO-8601 'generated' timestamp from vacancies.json."""
    if not ts_str:
        return None
    try:
        # Python 3.11+ fromisoformat handles Z; earlier needs manual strip
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _is_stale(generated: datetime | None) -> bool:
    if generated is None:
        return True
    now = datetime.now(timezone.utc)
    # Make sure both are timezone-aware
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return (now - generated) > timedelta(days=STALE_AFTER_DAYS)


def _run_scraper(location: str, radius: int):
    """Run scrape.py in a background thread; updates _scan_state."""
    cmd = [
        PYTHON, str(SCRAPER),
        "--location", location,
        "--radius",   str(radius),
        "--merge",                   # accumulate across regions
    ]
    log.info("Scraper command: %s", " ".join(cmd))

    try:
        with open(SCAN_LOG, "w") as logfile:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                stdout=logfile,
                stderr=subprocess.STDOUT,
                timeout=600,         # 10 min hard cap
            )
        exit_code = proc.returncode
        msg       = f"Scraper exited with code {exit_code}."
    except subprocess.TimeoutExpired:
        exit_code = -1
        msg       = "Scraper timed out after 10 minutes."
        log.error(msg)
    except Exception as exc:
        exit_code = -1
        msg       = f"Scraper failed: {exc}"
        log.error(msg)

    with _scan_lock:
        _scan_state["status"]      = "done" if exit_code == 0 else "error"
        _scan_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        _scan_state["message"]     = msg
        _scan_state["exit_code"]   = exit_code

    log.info("Scan complete: %s", msg)


# ── API routes ─────────────────────────────────────────────────────

@app.route("/api/scan/status")
def api_scan_status():
    """Return current scraper state + last-scan metadata."""
    with _scan_lock:
        state = dict(_scan_state)

    meta      = _read_vacancies_meta()
    generated = _parse_generated(meta["generated"] if meta else None)
    stale     = _is_stale(generated)

    next_allowed = None
    if generated:
        next_ts = generated + timedelta(days=STALE_AFTER_DAYS)
        if generated.tzinfo is None:
            next_ts = next_ts.replace(tzinfo=timezone.utc)
        next_allowed = next_ts.isoformat()

    return jsonify({
        "scan":          state,
        "last_scan":     meta,
        "stale":         stale,
        "stale_days":    STALE_AFTER_DAYS,
        "next_allowed":  next_allowed,
    })


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Trigger a scraper run (if allowed)."""
    body     = request.get_json(silent=True) or {}
    location = (body.get("location") or "").strip()
    radius   = int(body.get("radius") or DEFAULT_RADIUS)
    force    = bool(body.get("force", False))

    if not location:
        return jsonify({"error": "location is required"}), 400

    with _scan_lock:
        if _scan_state["status"] == "running":
            return jsonify({
                "error":   "A scan is already running.",
                "started": _scan_state["started_at"],
            }), 409

        # Cooldown check (skipped if force=True or different region)
        if not force:
            meta      = _read_vacancies_meta()
            generated = _parse_generated(meta["generated"] if meta else None)
            # If the requested location differs from the last scan, allow immediately
            last_loc = (meta.get("location", "") or "").lower().strip() if meta else ""
            req_loc  = location.lower().strip()
            same_region = last_loc and (
                req_loc in last_loc or last_loc in req_loc
            )
            if same_region and not _is_stale(generated):
                if generated and generated.tzinfo is None:
                    generated = generated.replace(tzinfo=timezone.utc)
                next_ts = (generated + timedelta(days=STALE_AFTER_DAYS)).isoformat()
                return jsonify({
                    "error":        "Data is still fresh. Use force=true to override.",
                    "next_allowed": next_ts,
                    "generated":    meta["generated"] if meta else None,
                }), 429

        # Start background scrape
        _scan_state["status"]      = "running"
        _scan_state["location"]    = location
        _scan_state["radius"]      = radius
        _scan_state["started_at"]  = datetime.now(timezone.utc).isoformat()
        _scan_state["finished_at"] = None
        _scan_state["message"]     = "Scraping Starbucks careers listings…"
        _scan_state["exit_code"]   = None

    t = threading.Thread(target=_run_scraper, args=(location, radius), daemon=True)
    t.start()

    return jsonify({
        "status":   "started",
        "location": location,
        "radius":   radius,
        "force":    force,
    })


@app.route("/api/scan/log")
def api_scan_log():
    """Return the last scraper log (dev convenience)."""
    if not SCAN_LOG.exists():
        return jsonify({"log": "(no log yet)"}), 200
    return jsonify({"log": SCAN_LOG.read_text()[-8000:]})  # last 8 KB


@app.route("/api/history")
def api_history():
    """Return the full scan history array.

    Optional query params:
      ?location=Austin   — filter to snapshots whose loc contains keyword
      ?last=N            — return only the most recent N snapshots
    """
    if not HISTORY.exists():
        return jsonify([]), 200
    try:
        history = json.loads(HISTORY.read_text())
        if not isinstance(history, list):
            return jsonify([]), 200

        # Optional location filter
        loc_filter = request.args.get("location", "").strip().lower()
        if loc_filter:
            history = [h for h in history if loc_filter in h.get("loc", "").lower()]

        # Optional limit
        try:
            last_n = int(request.args.get("last", 0))
        except ValueError:
            last_n = 0
        if last_n > 0:
            history = history[-last_n:]

        return jsonify(history), 200
    except Exception as exc:
        log.warning("Could not read history.json: %s", exc)
        return jsonify([]), 200


# ── Static frontend ────────────────────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve any file from the frontend/ directory."""
    full = FRONTEND / path
    if path and full.exists() and full.is_file():
        return send_from_directory(str(FRONTEND), path)
    return send_from_directory(str(FRONTEND), "index.html")


# ── Entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Chain Staffing Tracker – dev server")
    p.add_argument("--port",  type=int, default=8765)
    p.add_argument("--host",  default="127.0.0.1")
    p.add_argument("--debug", action="store_true", help="Flask debug/reload mode")
    args = p.parse_args()

    # Ensure output dir exists
    (FRONTEND / "data").mkdir(parents=True, exist_ok=True)

    log.info("Starting server on http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)
