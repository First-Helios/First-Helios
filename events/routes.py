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

from core.database import get_engine, get_session
from events.models import Event, EventInteraction, Venue

logger = logging.getLogger(__name__)


def _err(e: Exception, status: int = 500):
    """Log exception server-side; return a generic message with no internal details."""
    logger.error("[events] %s", e, exc_info=True)
    return jsonify({"status": "error", "message": "An internal error occurred"}), status

events_bp = Blueprint("events", __name__, url_prefix="/api/events")

# Module-level singleton — avoids re-creating engine + DDL on every request
_engine = None


def _get_db_session():
    """Return a new Session using a lazily-initialised engine singleton."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return get_session(_engine)


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

    session = _get_db_session()
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
        return _err(e)
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

    session = _get_db_session()
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
        return _err(e)
    finally:
        session.close()


# ── Categories ────────────────────────────────────────────────────────────────

@events_bp.route("/categories")
def events_categories():
    """Distinct event categories with counts."""
    region = request.args.get("region", "austin_tx")

    session = _get_db_session()
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
        return _err(e)
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

    session = _get_db_session()
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
        return _err(e)
    finally:
        session.close()


# ── Interactions ──────────────────────────────────────────────────────────────

_VALID_INTERACTION_TYPES = {"view", "save", "click_url", "rating"}


@events_bp.route("/interactions", methods=["POST"])
def create_interaction():
    """Record a user interaction (view, save, click, rating).

    JSON body:
      event_id          (int, required)
      interaction_type  (str, required) — view / save / click_url / rating
      value             (float, optional) — for ratings
      session_id        (str, optional) — anonymized session identifier
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    event_id = data.get("event_id")
    itype = data.get("interaction_type")
    value = data.get("value")
    session_id = data.get("session_id")

    if not event_id or not isinstance(event_id, int):
        return jsonify({"status": "error", "message": "event_id (int) required"}), 400

    if itype not in _VALID_INTERACTION_TYPES:
        return jsonify({
            "status": "error",
            "message": f"interaction_type must be one of {sorted(_VALID_INTERACTION_TYPES)}",
        }), 400

    if value is not None and not isinstance(value, (int, float)):
        return jsonify({"status": "error", "message": "value must be numeric"}), 400

    session = _get_db_session()
    try:
        # Verify event exists
        evt = session.get(Event, event_id)
        if evt is None:
            return jsonify({"status": "error", "message": "event not found"}), 404

        interaction = EventInteraction(
            event_id=event_id,
            interaction_type=itype,
            value=value,
            session_id=session_id,
        )
        session.add(interaction)
        session.commit()

        return jsonify({
            "status": "ok",
            "interaction_id": interaction.id,
        }), 201

    except Exception as e:
        session.rollback()
        logger.error("[events/interactions] %s", e)
        return _err(e)
    finally:
        session.close()
