"""
events/routes.py — Flask Blueprint for event endpoints.

Endpoints:
    GET /api/events/h3-map      H3 hex aggregation of active events
    GET /api/events/listings     Paginated event listings
    GET /api/events/categories   Distinct event categories with counts
    GET /api/events/venues       Active venues with event counts
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func as sqlfunc

from core.database import get_session, init_db
from events.models import Event, Venue

logger = logging.getLogger(__name__)

events_bp = Blueprint("events", __name__, url_prefix="/api/events")


# ── H3 hex map ────────────────────────────────────────────────────────────────

@events_bp.route("/h3-map")
def events_h3_map():
    """H3 hex aggregation of active events that have coordinates.

    Query params:
      resolution  (int, default 7)  — 7 or 8
      region      (default: austin_tx)
      category    (optional)
    """
    resolution = request.args.get("resolution", 7, type=int)
    region     = request.args.get("region", "austin_tx")
    category   = request.args.get("category")

    resolution = max(7, min(8, resolution))
    h3_col = Event.h3_r7 if resolution == 7 else Event.h3_r8

    engine  = init_db()
    session = get_session(engine)
    try:
        q = session.query(
            h3_col.label("cell_id"),
            sqlfunc.count().label("count"),
        ).filter(
            Event.region == region,
            Event.is_active.is_(True),
            h3_col.isnot(None),
        )

        if category:
            q = q.filter(Event.category == category)

        rows = q.group_by(h3_col).all()

        # Resolve cell centres
        import h3 as h3lib

        _cell_cache: dict[str, tuple[float, float]] = {}

        def _cell_latlng(cell_id: str) -> tuple[float, float]:
            if cell_id not in _cell_cache:
                _cell_cache[cell_id] = h3lib.cell_to_latlng(cell_id)
            return _cell_cache[cell_id]

        cells = []
        for row in rows:
            lat, lng = _cell_latlng(row.cell_id)
            cells.append({
                "cell_id": row.cell_id,
                "count": row.count,
                "lat": lat,
                "lng": lng,
            })

        return jsonify({
            "status": "ok",
            "resolution": resolution,
            "cell_count": len(cells),
            "cells": cells,
        })

    except Exception as e:
        logger.error("[events/h3-map] %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Paginated listings ────────────────────────────────────────────────────────

@events_bp.route("/listings")
def events_listings():
    """Paginated event listings.

    Query params:
      region      (default: austin_tx)
      h3_cell     (optional) — restrict to one H3 cell
      resolution  (int, default 7) — which h3 column when h3_cell given
      category    (optional) — event category filter
      is_free     (optional) — "true" / "false"
      page        (int, default 1)
      limit       (int, default 20, max 100)
    """
    region     = request.args.get("region", "austin_tx")
    h3_cell    = request.args.get("h3_cell")
    resolution = request.args.get("resolution", 7, type=int)
    category   = request.args.get("category")
    is_free    = request.args.get("is_free")
    page       = request.args.get("page", 1, type=int)
    limit      = min(request.args.get("limit", 20, type=int), 100)

    resolution = max(7, min(8, resolution))
    h3_col = Event.h3_r7 if resolution == 7 else Event.h3_r8

    engine  = init_db()
    session = get_session(engine)
    try:
        q = session.query(Event).filter(
            Event.region == region,
            Event.is_active.is_(True),
        )

        if h3_cell:
            q = q.filter(h3_col == h3_cell)

        if category:
            q = q.filter(Event.category == category)

        if is_free is not None:
            q = q.filter(Event.is_free.is_(is_free.lower() == "true"))

        total = q.count()
        events = (
            q.order_by(Event.start_time.asc().nullslast())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return jsonify({
            "status": "ok",
            "total": total,
            "page": page,
            "limit": limit,
            "events": [e.to_dict() for e in events],
        })

    except Exception as e:
        logger.error("[events/listings] %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Categories ────────────────────────────────────────────────────────────────

@events_bp.route("/categories")
def events_categories():
    """Distinct event categories with counts."""
    region = request.args.get("region", "austin_tx")

    engine  = init_db()
    session = get_session(engine)
    try:
        rows = (
            session.query(
                Event.category,
                sqlfunc.count().label("count"),
            )
            .filter(
                Event.region == region,
                Event.is_active.is_(True),
                Event.category.isnot(None),
            )
            .group_by(Event.category)
            .order_by(sqlfunc.count().desc())
            .all()
        )

        return jsonify({
            "status": "ok",
            "categories": [{"name": r.category, "count": r.count} for r in rows],
        })

    except Exception as e:
        logger.error("[events/categories] %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ── Venues ────────────────────────────────────────────────────────────────────

@events_bp.route("/venues")
def events_venues():
    """Active venues with upcoming event counts.

    Query params:
      region   (default: austin_tx)
      limit    (int, default 50, max 200)
    """
    region = request.args.get("region", "austin_tx")
    limit  = min(request.args.get("limit", 50, type=int), 200)

    engine  = init_db()
    session = get_session(engine)
    try:
        now = datetime.utcnow()
        rows = (
            session.query(
                Venue,
                sqlfunc.count(Event.id).label("upcoming_count"),
            )
            .outerjoin(Event, (Event.venue_id == Venue.id) & Event.is_active.is_(True) & (Event.start_time >= now))
            .filter(
                Venue.region == region,
                Venue.is_active.is_(True),
            )
            .group_by(Venue.id)
            .order_by(sqlfunc.count(Event.id).desc())
            .limit(limit)
            .all()
        )

        venues = []
        for venue, count in rows:
            d = venue.to_dict()
            d["upcoming_events"] = count
            venues.append(d)

        return jsonify({"status": "ok", "venues": venues})

    except Exception as e:
        logger.error("[events/venues] %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()
