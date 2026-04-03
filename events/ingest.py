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
from events.models import BronzeEventPayload, Event, Venue

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

    # Bronze layer — raw API response for replay
    raw_payload: dict[str, Any] | None = None

    # Lineage — set by collector runner
    collector_run_id: int | None = None


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


# ── Bronze payload storage ────────────────────────────────────────────────────

def _save_bronze_payload(
    session: Session,
    signal: EventSignal,
) -> None:
    """Persist the raw API response before normalization."""
    if signal.raw_payload is None:
        return
    try:
        stmt = (
            pg_insert(BronzeEventPayload)
            .values(
                source=signal.source,
                external_id=signal.external_id,
                collector_run_id=signal.collector_run_id,
                raw_payload=signal.raw_payload,
                scraped_at=datetime.utcnow(),
            )
            .on_conflict_do_nothing()   # no unique constraint — append-only
        )
        session.execute(stmt)
    except Exception as exc:
        logger.warning("[EventIngest] Failed to save bronze payload: %s", exc)


# ── Social scoring computation ────────────────────────────────────────────────

# Categories that tend to be interactive / social
_HIGH_SOCIAL_CATEGORIES = {"community", "nightlife", "food", "outdoor", "family"}
_MEDIUM_SOCIAL_CATEGORIES = {"music", "sports", "arts"}

# Subcategory keywords that boost friend-making score
_INTERACTIVE_KEYWORDS = frozenset({
    "class", "workshop", "meetup", "open_mic", "trivia", "game",
    "board_game", "run_club", "volunteer", "potluck", "mixer",
    "social", "networking", "dance", "karaoke", "comedy",
    "farmers_market", "craft", "book_club", "hiking",
})

# Keywords suggesting large anonymous crowds (lower friend-making)
_SPECTATOR_KEYWORDS = frozenset({
    "concert", "festival", "stadium", "arena", "conference",
    "expo", "convention", "parade", "marathon", "race",
})


def _compute_social_scores(
    signal: EventSignal,
) -> tuple[list[str] | None, str | None, float | None]:
    """Derive audience_tags, social_density, and friend_making_score.

    Returns (audience_tags, social_density, friend_making_score).
    """
    # ── Audience tags ─────────────────────────────────────────────────────────
    tags: list[str] = []

    if signal.is_free:
        tags.append("free")
    if signal.price_min is not None and signal.price_min > 50:
        tags.append("premium")

    title_lower = (signal.title or "").lower()
    desc_lower = (signal.description or "").lower()
    combined = f"{title_lower} {desc_lower}"

    if any(w in combined for w in ("family", "kid", "children", "all ages")):
        tags.append("family")
    if any(w in combined for w in ("21+", "21 and over", "bar", "cocktail")):
        tags.append("21+")
    if any(w in combined for w in ("beginner", "intro", "101", "first time")):
        tags.append("beginner_friendly")
    if any(w in combined for w in ("lgbtq", "pride", "queer", "drag")):
        tags.append("lgbtq+")
    if any(w in combined for w in ("nerd", "anime", "cosplay", "gaming", "d&d", "comic")):
        tags.append("nerds")
    if any(w in combined for w in ("outdoor", "park", "trail", "hike", "lake")):
        tags.append("outdoor")
    if any(w in combined for w in ("dog", "pet", "pup")):
        tags.append("pet_friendly")

    # ── Social density ────────────────────────────────────────────────────────
    density: str | None = None
    cap = signal.metadata.get("capacity")

    if cap and isinstance(cap, (int, float)):
        if cap <= 30:
            density = "intimate"
        elif cap <= 200:
            density = "medium"
        elif cap <= 2000:
            density = "large"
        else:
            density = "festival"
    else:
        # Infer from category/subcategory/keywords
        sub = (signal.subcategory or "").lower()
        if any(w in combined for w in ("festival", "parade", "marathon", "expo")):
            density = "festival"
        elif any(w in combined for w in ("stadium", "arena", "amphitheater")):
            density = "large"
        elif any(w in combined for w in ("class", "workshop", "meetup", "book_club")):
            density = "intimate"
        elif signal.category in _HIGH_SOCIAL_CATEGORIES:
            density = "medium"
        else:
            density = "medium"

    # ── Friend-making score ───────────────────────────────────────────────────
    score = 0.5  # baseline

    sub_lower = (signal.subcategory or "").lower()
    all_text = f"{combined} {sub_lower}"

    # Boost for interactive formats
    interactive_hits = sum(1 for kw in _INTERACTIVE_KEYWORDS if kw in all_text)
    score += min(interactive_hits * 0.1, 0.3)

    # Penalize spectator events
    spectator_hits = sum(1 for kw in _SPECTATOR_KEYWORDS if kw in all_text)
    score -= min(spectator_hits * 0.1, 0.2)

    # Small groups → easier to meet people
    if density == "intimate":
        score += 0.15
    elif density == "festival":
        score -= 0.1

    # Free events attract more casual/social attendees
    if signal.is_free:
        score += 0.05

    # Recurring events build community
    if signal.is_recurring:
        score += 0.1

    # Category adjustments
    if signal.category in _HIGH_SOCIAL_CATEGORIES:
        score += 0.05
    elif signal.category in _MEDIUM_SOCIAL_CATEGORIES:
        score += 0.0

    # Clamp
    score = round(max(0.0, min(1.0, score)), 2)

    return (tags if tags else None, density, score)


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
        # ── Bronze layer — persist raw payload before any normalisation ─────
        _save_bronze_payload(session, signal)

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
            "collector_run_id": signal.collector_run_id,
            "detail_json":     detail_json,
        }

        # ── Social scoring ────────────────────────────────────────────────────
        audience_tags, social_density, friend_making_score = _compute_social_scores(signal)
        if audience_tags:
            event_data["audience_tags"] = audience_tags
        if social_density:
            event_data["social_density"] = social_density
        if friend_making_score is not None:
            event_data["friend_making_score"] = friend_making_score

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
                    "collector_run_id": signal.collector_run_id,
                    "detail_json":    detail_json,
                    "audience_tags":  event_data.get("audience_tags"),
                    "social_density": event_data.get("social_density"),
                    "friend_making_score": event_data.get("friend_making_score"),
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
