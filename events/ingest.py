"""
events/ingest.py — Single write path for all Event + Venue records.

Every events source (Ticketmaster, Eventbrite, etc.) calls
ingest_event() instead of writing directly.

Pipeline per signal:
  1. Extract venue name, address, lat/lng, event fields from metadata
  2. Deduplicate via (source, external_id) — skip if active, refresh if existing
  3. Normalize venue name + compute fingerprint
  4. Geocode if lat/lng absent and raw_address present
  5. Compute H3 cells (r7, r8) from lat/lng
  6. Match or upsert Venue
  7. Compute expires_at from start_time or scraped_at + TTL
  8. Upsert Event via PostgreSQL INSERT … ON CONFLICT DO UPDATE
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text as _sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.database import get_engine, get_session, init_db
from core.normalizer import make_fingerprint, normalize_name
from events.models import Event, Venue

logger = logging.getLogger(__name__)

EVENT_TTL_DAYS = int(os.environ.get("EVENT_TTL_DAYS", 14))


# ── Event signal dataclass ────────────────────────────────────────────────────

@dataclass
class EventSignal:
    """Normalised container produced by all event collectors."""

    source: str               # "ticketmaster" | "eventbrite"
    external_id: str          # stable ID from the source API
    title: str
    description: str | None = None

    # Venue
    venue_name: str | None = None
    venue_address: str | None = None
    lat: float | None = None
    lng: float | None = None

    # Classification
    category: str | None = None       # music / food / sports / outdoor / etc.
    subcategory: str | None = None    # live_music / farmers_market / etc.

    # Timing
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Pricing
    price_min: float | None = None
    price_max: float | None = None
    is_free: bool | None = None

    # Flags
    is_recurring: bool | None = None

    # Links
    source_url: str | None = None
    ticket_url: str | None = None

    # Extras
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=datetime.utcnow)


# ── H3 computation ────────────────────────────────────────────────────────────

def _compute_h3(
    lat: float | None,
    lng: float | None,
) -> tuple[str | None, str | None]:
    if lat is None or lng is None:
        return None, None
    try:
        import h3
        return h3.latlng_to_cell(lat, lng, 7), h3.latlng_to_cell(lat, lng, 8)
    except Exception as exc:
        logger.warning("[EventIngest] H3 failed for (%s, %s): %s", lat, lng, exc)
        return None, None


# ── Geocoding helper ──────────────────────────────────────────────────────────

def _geocode_if_needed(
    lat: float | None,
    lng: float | None,
    address: str | None,
) -> tuple[float | None, float | None]:
    if lat is not None and lng is not None:
        return lat, lng
    if not address:
        return None, None
    try:
        from collectors.geocoding import geocode
        glat, glng = geocode(address)
        if glat is not None:
            return glat, glng
    except Exception as exc:
        logger.warning("[EventIngest] Geocode failed for %r: %s", address, exc)
    return None, None


# ── Venue upsert ──────────────────────────────────────────────────────────────

def _upsert_venue(
    session: Session,
    signal: EventSignal,
    region: str,
    lat: float | None,
    lng: float | None,
    h3_r7: str | None,
    h3_r8: str | None,
) -> int | None:
    """Match or create a Venue row.  Returns venue.id or None."""
    if not signal.venue_name:
        return None

    normalized = normalize_name(signal.venue_name)
    fingerprint = make_fingerprint(signal.venue_name)

    # Try computing h3_r9 for the venue
    h3_r9: str | None = None
    if lat is not None and lng is not None:
        try:
            import h3
            h3_r9 = h3.latlng_to_cell(lat, lng, 9)
        except Exception:
            pass

    venue_data = {
        "name": signal.venue_name,
        "canonical_name": normalized,
        "fingerprint": fingerprint,
        "address": signal.venue_address,
        "lat": lat,
        "lng": lng,
        "h3_r7": h3_r7,
        "h3_r8": h3_r8,
        "h3_r9": h3_r9,
        "category": signal.metadata.get("venue_category"),
        "source": signal.source,
        "region": region,
        "is_active": True,
    }

    stmt = (
        pg_insert(Venue)
        .values(**venue_data)
        .on_conflict_do_update(
            constraint="uq_venue_fp_region",
            set_={
                "name": signal.venue_name,
                "address": signal.venue_address or Venue.address,
                "lat": lat or Venue.lat,
                "lng": lng or Venue.lng,
                "h3_r7": h3_r7 or Venue.h3_r7,
                "h3_r8": h3_r8 or Venue.h3_r8,
                "h3_r9": h3_r9 or Venue.h3_r9,
                "is_active": True,
                "updated_at": datetime.utcnow(),
            },
        )
        .returning(Venue.id)
    )
    result = session.execute(stmt)
    row = result.fetchone()
    return row[0] if row else None


# ── Main ingest function ──────────────────────────────────────────────────────

def ingest_event(
    signal: EventSignal,
    region: str,
    session: Session | None = None,
    ttl_days: int = EVENT_TTL_DAYS,
) -> "tuple[Event | None, bool]":
    """Normalise and upsert one event signal.

    Returns (Event ORM row or None, is_new bool).
    """
    if not signal.title or not signal.external_id:
        logger.debug("[EventIngest] Missing title or external_id — skipping")
        return None, False

    _owns_session = session is None
    if _owns_session:
        engine = init_db()
        session = get_session(engine)

    try:
        # ── Geocode ───────────────────────────────────────────────────────────
        lat, lng = _geocode_if_needed(signal.lat, signal.lng, signal.venue_address)

        # ── H3 ────────────────────────────────────────────────────────────────
        h3_r7, h3_r8 = _compute_h3(lat, lng)

        # ── Venue ─────────────────────────────────────────────────────────────
        venue_id = _upsert_venue(session, signal, region, lat, lng, h3_r7, h3_r8)

        # ── Expires ───────────────────────────────────────────────────────────
        now = datetime.utcnow()
        if signal.start_time and signal.start_time > now:
            # Future event: expires one day after it ends (or starts if no end)
            anchor = signal.end_time or signal.start_time
            expires_at = anchor + timedelta(days=1)
        else:
            expires_at = now + timedelta(days=ttl_days)

        # ── Detail JSON ───────────────────────────────────────────────────────
        detail_json: dict | None = None
        _EXTRA_KEYS = ("image_url", "tags", "age_restriction", "performers",
                       "accessibility", "parking")
        extras = {k: signal.metadata[k] for k in _EXTRA_KEYS if signal.metadata.get(k)}
        if extras:
            detail_json = extras

        # ── Upsert ────────────────────────────────────────────────────────────
        event_data = {
            "source":          signal.source,
            "external_id":     signal.external_id,
            "title":           signal.title,
            "description":     signal.description,
            "venue_id":        venue_id,
            "raw_venue_name":  signal.venue_name,
            "raw_address":     signal.venue_address,
            "lat":             lat,
            "lng":             lng,
            "h3_r7":           h3_r7,
            "h3_r8":           h3_r8,
            "category":        signal.category,
            "subcategory":     signal.subcategory,
            "start_time":      signal.start_time,
            "end_time":        signal.end_time,
            "price_min":       signal.price_min,
            "price_max":       signal.price_max,
            "is_free":         signal.is_free,
            "is_recurring":    signal.is_recurring,
            "source_url":      signal.source_url,
            "ticket_url":      signal.ticket_url,
            "region":          region,
            "is_active":       True,
            "scraped_at":      now,
            "expires_at":      expires_at,
            "detail_json":     detail_json,
        }

        stmt = (
            pg_insert(Event)
            .values(**event_data)
            .on_conflict_do_update(
                constraint="uq_event_source_external",
                set_={
                    "title":          signal.title,
                    "description":    signal.description,
                    "venue_id":       venue_id,
                    "raw_venue_name": signal.venue_name,
                    "raw_address":    signal.venue_address,
                    "lat":            lat,
                    "lng":            lng,
                    "h3_r7":          h3_r7,
                    "h3_r8":          h3_r8,
                    "category":       signal.category,
                    "subcategory":    signal.subcategory,
                    "start_time":     signal.start_time,
                    "end_time":       signal.end_time,
                    "price_min":      signal.price_min,
                    "price_max":      signal.price_max,
                    "is_free":        signal.is_free,
                    "is_recurring":   signal.is_recurring,
                    "source_url":     signal.source_url,
                    "ticket_url":     signal.ticket_url,
                    "detail_json":    detail_json,
                    "is_active":      True,
                    "scraped_at":     now,
                    "expires_at":     expires_at,
                },
            )
            .returning(Event.id, _sa_text("(xmax = 0)").label("is_new"))
        )

        result = session.execute(stmt)
        session.commit()
        row = result.fetchone()
        row_id, is_new = row[0], bool(row[1])

        logger.debug(
            "[EventIngest] Upserted event id=%s %r (%s) venue=%s",
            row_id, signal.title[:50], signal.source, venue_id,
        )

        evt = session.get(Event, row_id)
        return evt, is_new

    except Exception:
        session.rollback()
        logger.exception("[EventIngest] Failed to ingest event %r", signal.title)
        return None, False
    finally:
        if _owns_session:
            session.close()


# ── Expiry sweep ──────────────────────────────────────────────────────────────

def expire_stale_events(region: str, session: Session | None = None) -> int:
    """Bulk-expire events past their expires_at. Returns count expired."""
    _owns_session = session is None
    if _owns_session:
        engine = init_db()
        session = get_session(engine)

    try:
        now = datetime.utcnow()
        count = (
            session.query(Event)
            .filter(
                Event.region == region,
                Event.is_active.is_(True),
                Event.expires_at <= now,
            )
            .update({"is_active": False}, synchronize_session=False)
        )
        session.commit()
        logger.info("[EventIngest] Expired %d stale events in %s", count, region)
        return count
    except Exception:
        session.rollback()
        logger.exception("[EventIngest] Expiry sweep failed for %s", region)
        return 0
    finally:
        if _owns_session:
            session.close()
