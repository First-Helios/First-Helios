"""
core/models/spiritpool.py — ORM models for SpiritPool contributor pipeline.

Tables:
    sp_events        — Forward-compatible signal storage from SpiritPool contributors
    quarantine       — PII-flagged payloads held for audit (never exposed to APIs/dashboards)
    session_epochs   — Session token lifecycle tracking
    burn_pool        — Monthly aggregate of burned sessions (1-year TTL)
    contributors     — Anonymous contributor volume tracking

Named sp_events (not "events") because events/ already owns the automated
events-collector table (Ticketmaster, Eventbrite, etc.).

Layer: operational (sp_events), metadata (quarantine), operational (session_epochs,
       burn_pool, contributors)

Depends on: core.database.Base
Called by: intake endpoint (POST /api/contribute), burn endpoint, scheduler cleanup
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


# ── Portable JSON column ─────────────────────────────────────────────────────
# Use JSONB on PostgreSQL, fallback to JSON on SQLite.
try:
    from sqlalchemy.dialects.sqlite import JSON as _SQLiteJSON
except ImportError:
    _SQLiteJSON = None

# SQLAlchemy JSONB works on Postgres; on SQLite it degrades to plain TEXT.
# We keep JSONB as the declared type so Alembic generates correct DDL when
# DATABASE_URL points to Postgres, while SQLite still functions for local dev.


class SpEvent(Base):
    """One contributor signal — job listing, salary, business review, or event.

    Forward-compatible across First/Second/Third Helios eras:
      - session_token is TEXT with no length constraint (UUID now, 64-char hex later)
      - epoch_id has no upper bound
      - payload JSONB stores unknown future fields without error

    Server-set fields: event_id, collected_at, pipeline_version.
    Client fields that must NEVER appear: tabUrl, collectedAt, IP address.
    """

    __tablename__ = "sp_events"

    # Using TEXT event_id (UUID generated in Python) for SQLite compat
    event_id = Column(String, primary_key=True)  # uuid4() set server-side
    session_token = Column(Text, nullable=False)  # opaque, no length constraint
    epoch_id = Column(Integer, nullable=False)  # consent version counter, no upper bound
    event_type = Column(String, nullable=False)  # job_listing | salary_signal | business_review | event_listing
    payload = Column(JSONB, nullable=False)  # structured extraction data, unknown fields preserved
    source_type = Column(String, nullable=False, default="extension")
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow)  # server-set, never from client
    pipeline_version = Column(Integer, nullable=False, default=1)  # PII rule version for re-processing

    __table_args__ = (
        Index("idx_sp_events_session_epoch", "session_token", "epoch_id"),
        Index("idx_sp_events_type_collected", "event_type", "collected_at"),
    )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "session_token": self.session_token,
            "epoch_id": self.epoch_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "source_type": self.source_type,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
            "pipeline_version": self.pipeline_version,
        }


class Quarantine(Base):
    """PII-flagged payloads held for internal audit only.

    Events matching any PII regex pattern land here instead of sp_events.
    Never queryable by external APIs or dashboards.
    """

    __tablename__ = "quarantine"

    quarantine_id = Column(String, primary_key=True)  # uuid4() set server-side
    original_payload = Column(JSONB, nullable=False)  # complete original event body
    redaction_types = Column(Text, nullable=False)  # JSON array e.g. '["email","phone"]'
    rule_version = Column(Integer, nullable=False)  # matches pipeline_version logic
    quarantined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "quarantine_id": self.quarantine_id,
            "redaction_types": self.redaction_types,
            "rule_version": self.rule_version,
            "quarantined_at": self.quarantined_at.isoformat() if self.quarantined_at else None,
        }


class SessionEpoch(Base):
    """Tracks session token lifecycle — creation, contributor link, and burn state.

    No FK from sp_events → session_epochs; relationship is via text match on session_token.
    contributor_id set to NULL on burn (deliberate data loss for privacy).
    """

    __tablename__ = "session_epochs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_token = Column(Text, nullable=False, unique=True)  # one row per token
    epoch_id = Column(Integer, nullable=False)
    contributor_id = Column(Integer, ForeignKey("contributors.id"), nullable=True)  # NULL on burn
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    burned_at = Column(DateTime, nullable=True)  # set on burn, NULL while active

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_token": self.session_token,
            "epoch_id": self.epoch_id,
            "contributor_id": self.contributor_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "burned_at": self.burned_at.isoformat() if self.burned_at else None,
        }


class BurnPool(Base):
    """Monthly aggregate of burned sessions — 1-year TTL.

    No per-session burn records — only monthly signal_count.
    Maintenance job: DELETE FROM burn_pool WHERE expires_at < NOW()
    """

    __tablename__ = "burn_pool"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month_key = Column(String, nullable=False)  # 'YYYY-MM'
    signal_count = Column(Integer, nullable=False, default=0)  # incremented on burn
    burned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # burned_at + 1 year

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "month_key": self.month_key,
            "signal_count": self.signal_count,
            "burned_at": self.burned_at.isoformat() if self.burned_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class Contributor(Base):
    """Anonymous contributor identity — volume tracking only, no PII.

    uuid is extension-generated (opaque per-install identity).
    total_signals incremented on ingest.
    """

    __tablename__ = "contributors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(Text, nullable=False, unique=True)  # per-install anonymous identity
    total_signals = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "total_signals": self.total_signals,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
