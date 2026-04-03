"""
events/models.py — SQLAlchemy models for venues and events.

Completely separate from job data — no FK relationships to existing tables.
Registered with the shared Base so Alembic can track migrations.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from core.database import Base


class Venue(Base):
    """A physical location where events happen (music venue, park, market, etc.)."""

    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    name = Column(String, nullable=False)
    canonical_name = Column(String, nullable=False)
    fingerprint = Column(String, nullable=False, index=True)

    # ── Location ──────────────────────────────────────────────────────────────
    address = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    h3_r7 = Column(String(15), nullable=True, index=True)
    h3_r8 = Column(String(15), nullable=True, index=True)
    h3_r9 = Column(String(15), nullable=True, index=True)

    # ── Classification ────────────────────────────────────────────────────────
    category = Column(String, nullable=True)  # music_venue / park / market / museum / etc.
    website = Column(String, nullable=True)
    capacity = Column(Integer, nullable=True)

    # ── Source ────────────────────────────────────────────────────────────────
    source = Column(String, nullable=True)
    source_id = Column(String, nullable=True)

    # ── Scope ─────────────────────────────────────────────────────────────────
    region = Column(String, nullable=False, default="austin_tx", index=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("fingerprint", "region", name="uq_venue_fp_region"),
        Index("ix_venues_h3r7_region", "h3_r7", "region"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "category": self.category,
            "website": self.website,
            "capacity": self.capacity,
            "region": self.region,
        }


class Event(Base):
    """One event occurrence — concert, market day, class, festival, etc."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Source provenance ─────────────────────────────────────────────────────
    source = Column(String, nullable=False, index=True)
    external_id = Column(String, nullable=False)

    # ── Event detail ──────────────────────────────────────────────────────────
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # ── Venue link (nullable — outdoor/unnamed events) ────────────────────────
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True, index=True)
    raw_venue_name = Column(String, nullable=True)
    raw_address = Column(String, nullable=True)

    # ── Location ──────────────────────────────────────────────────────────────
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    h3_r7 = Column(String(15), nullable=True, index=True)
    h3_r8 = Column(String(15), nullable=True, index=True)

    # ── Classification ────────────────────────────────────────────────────────
    category = Column(String, nullable=True, index=True)
    # music / food / sports / outdoor / arts / community / family / nightlife
    subcategory = Column(String, nullable=True)
    # live_music / farmers_market / hiking / festival / etc.

    # ── Timing ────────────────────────────────────────────────────────────────
    start_time = Column(DateTime, nullable=True, index=True)
    end_time = Column(DateTime, nullable=True)

    # ── Pricing ───────────────────────────────────────────────────────────────
    price_min = Column(Float, nullable=True)
    price_max = Column(Float, nullable=True)
    is_free = Column(Boolean, nullable=True)

    # ── Recurrence ────────────────────────────────────────────────────────────
    is_recurring = Column(Boolean, nullable=True)

    # ── Links ─────────────────────────────────────────────────────────────────
    source_url = Column(String, nullable=True)
    ticket_url = Column(String, nullable=True)

    # ── Scope ─────────────────────────────────────────────────────────────────
    region = Column(String, nullable=False, default="austin_tx", index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # ── Freshness ─────────────────────────────────────────────────────────────
    scraped_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True, index=True)

    # ── Rich detail (JSONB) ───────────────────────────────────────────────────
    detail_json = Column(JSONB, nullable=True)

    # ── Audience / social context — for future personality profiling ───────────
    audience_tags = Column(ARRAY(Text), nullable=True)   # ["beginner_friendly", "21+", "family", "lgbtq+", "nerds"]
    social_density = Column(String, nullable=True)       # "intimate" / "medium" / "large" / "festival"
    friend_making_score = Column(Float, nullable=True)   # 0-1, how conducive to meeting people

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_event_source_external"),
        Index("ix_events_active_region", "is_active", "region"),
        Index("ix_events_h3r7_active", "h3_r7", "is_active"),
        Index("ix_events_h3r8_active", "h3_r8", "is_active"),
        Index("ix_events_category_active_region", "category", "is_active", "region"),
        Index("ix_events_start_active", "start_time", "is_active"),
        Index("ix_events_start_region_active", "start_time", "region", "is_active"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "title": self.title,
            "description": self.description,
            "venue_id": self.venue_id,
            "raw_venue_name": self.raw_venue_name,
            "raw_address": self.raw_address,
            "lat": self.lat,
            "lng": self.lng,
            "h3_r7": self.h3_r7,
            "h3_r8": self.h3_r8,
            "category": self.category,
            "subcategory": self.subcategory,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "is_free": self.is_free,
            "is_recurring": self.is_recurring,
            "source_url": self.source_url,
            "ticket_url": self.ticket_url,
            "region": self.region,
            "is_active": self.is_active,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "detail": self.detail_json,
            "audience_tags": self.audience_tags,
            "social_density": self.social_density,
            "friend_making_score": self.friend_making_score,
        }


class EventInteraction(Base):
    """Future: user clicks, saves, ratings. Not populated yet — stub for schema planning.

    Defined now so it's part of Alembic from the start, avoiding a retrofit
    migration later when user profiling is implemented.
    """

    __tablename__ = "event_interactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    interaction_type = Column(String, nullable=False)  # "view" / "save" / "click_url" / "rating"
    value = Column(Float, nullable=True)               # for ratings
    session_id = Column(String, nullable=True)         # anonymized session (no PII yet)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
