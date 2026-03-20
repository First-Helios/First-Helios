"""
SQLAlchemy models and database initialization for ChainStaffingTracker.

DB file: data/tracker.db (auto-created on first run)
NOTE: data/spiritpool.db is a separate extension DB — never write to it from here.

Depends on: SQLAlchemy, pathlib
Called by: backend/ingest.py, backend/scoring/, backend/targeting.py, server.py
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "tracker.db"


def _import_reference_models() -> None:
    """Import reference models so their tables register with Base.metadata.

    Called lazily in init_db() to avoid circular-import issues.
    """
    try:
        import backend.models.reference  # noqa: F401
    except ImportError:
        logger.debug("[Database] backend.models.reference not found — skipping")


class Base(DeclarativeBase):
    """Declarative base for all tracker models."""
    pass


# ── Models ───────────────────────────────────────────────────────────────────

class Store(Base):
    """One row per physical chain location."""

    __tablename__ = "stores"

    store_num = Column(String, primary_key=True)
    chain = Column(String, nullable=False, index=True)
    industry = Column(String, nullable=False)
    store_name = Column(String, nullable=False, default="")
    address = Column(String, nullable=False, default="")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    region = Column(String, nullable=False, index=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "store_num": self.store_num,
            "chain": self.chain,
            "industry": self.industry,
            "store_name": self.store_name,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "region": self.region,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_active": self.is_active,
        }


class Signal(Base):
    """Every raw observation from any source."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_num = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    signal_type = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    metadata_json = Column(Text, default="{}")
    observed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def get_metadata(self) -> dict:
        return json.loads(self.metadata_json) if self.metadata_json else {}

    def set_metadata(self, val: dict) -> None:
        self.metadata_json = json.dumps(val, default=str)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "store_num": self.store_num,
            "source": self.source,
            "signal_type": self.signal_type,
            "value": self.value,
            "metadata": self.get_metadata(),
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Snapshot(Base):
    """Periodic scan summaries."""

    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String, nullable=False, index=True)
    chain = Column(String, nullable=False)
    source = Column(String, nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    store_count = Column(Integer, default=0)
    signal_count = Column(Integer, default=0)
    summary_json = Column(Text, default="{}")

    def get_summary(self) -> dict:
        return json.loads(self.summary_json) if self.summary_json else {}

    def set_summary(self, val: dict) -> None:
        self.summary_json = json.dumps(val, default=str)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "region": self.region,
            "chain": self.chain,
            "source": self.source,
            "scanned_at": self.scanned_at.isoformat() if self.scanned_at else None,
            "store_count": self.store_count,
            "signal_count": self.signal_count,
            "summary": self.get_summary(),
        }


class Score(Base):
    """Computed per store, updated after ingestion."""

    __tablename__ = "scores"

    store_num = Column(String, primary_key=True)
    score_type = Column(String, primary_key=True)
    value = Column(Float, nullable=False, default=0.0)
    tier = Column(String, nullable=False, default="unknown")
    computed_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "store_num": self.store_num,
            "score_type": self.score_type,
            "value": self.value,
            "tier": self.tier,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }


class WageIndex(Base):
    """Local vs chain pay comparison data."""

    __tablename__ = "wage_index"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employer = Column(String, nullable=False)
    is_chain = Column(Boolean, nullable=False, default=False)
    chain_key = Column(String, nullable=True)
    industry = Column(String, nullable=False)
    role_title = Column(String, nullable=False)
    wage_min = Column(Float, nullable=True)
    wage_max = Column(Float, nullable=True)
    wage_period = Column(String, nullable=False, default="hourly")
    location = Column(String, nullable=False)
    zip_code = Column(String, nullable=True)
    source = Column(String, nullable=False)
    observed_at = Column(DateTime, default=datetime.utcnow)
    source_url = Column(String, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employer": self.employer,
            "is_chain": self.is_chain,
            "chain_key": self.chain_key,
            "industry": self.industry,
            "role_title": self.role_title,
            "wage_min": self.wage_min,
            "wage_max": self.wage_max,
            "wage_period": self.wage_period,
            "location": self.location,
            "zip_code": self.zip_code,
            "source": self.source,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source_url": self.source_url,
        }


class LocalEmployer(Base):
    """Local (non-chain) employer POI.

    Populated by OvertureLocalAdapter and OSM adapter.
    Used by targeting.py for local_alternatives score component.
    """

    __tablename__ = "local_employers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    overture_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    address = Column(String, nullable=True, default="")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    region = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "overture_id": self.overture_id,
            "name": self.name,
            "category": self.category,
            "industry": self.industry,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "region": self.region,
            "confidence": self.confidence,
            "is_active": self.is_active,
        }


# ── API Rate Tracking Models ────────────────────────────────────────────────

class ApiSource(Base):
    """Registry of every external API / data source the system touches.

    Every source gets a row regardless of whether it has hard rate limits.
    daily_limit is REQUIRED — set to 10000 for uncapped sources so we have
    a metric baseline for scalability planning.
    """

    __tablename__ = "api_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    base_url = Column(String, nullable=True)
    auth_type = Column(String, default="none")          # none | api_key | oauth | browser
    daily_limit = Column(Integer, nullable=False)        # REQUIRED — 10000 default for uncapped
    min_delay_seconds = Column(Float, default=1.0)
    reset_hour_utc = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "auth_type": self.auth_type,
            "daily_limit": self.daily_limit,
            "min_delay_seconds": self.min_delay_seconds,
            "reset_hour_utc": self.reset_hour_utc,
            "is_active": self.is_active,
            "notes": self.notes,
        }


class ApiRequestLog(Base):
    """Every individual external HTTP request the system makes.

    Granular request-level tracking for success/fail rates,
    latency percentiles, and data-yield metrics.
    """

    __tablename__ = "api_request_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String, nullable=False, index=True)
    request_type = Column(String, nullable=False)           # e.g. 'series_fetch', 'geocode', 'search'
    url = Column(String, nullable=True)
    method = Column(String, default="GET")                  # GET | POST
    status_code = Column(Integer, nullable=True)            # HTTP status or 0 for network error
    success = Column(Boolean, nullable=False)
    error_message = Column(String, nullable=True)
    latency_ms = Column(Integer, nullable=True)             # round-trip time
    response_bytes = Column(Integer, nullable=True)         # response size
    data_items_returned = Column(Integer, nullable=True)    # records / rows / signals yielded
    request_params_json = Column(Text, nullable=True)       # JSON — what was asked for
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_key": self.source_key,
            "request_type": self.request_type,
            "url": self.url,
            "method": self.method,
            "status_code": self.status_code,
            "success": self.success,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "response_bytes": self.response_bytes,
            "data_items_returned": self.data_items_returned,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
        }


class RateBudget(Base):
    """Daily usage rollup per API source.

    One row per (source_key, date). Tracks how much of the daily_limit
    has been consumed and how many requests succeeded vs failed.
    Used for pacing, exhaustion prediction, and scalability metrics.
    """

    __tablename__ = "rate_budgets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String, nullable=False, index=True)
    date = Column(String, nullable=False)                     # ISO 'YYYY-MM-DD'
    daily_limit = Column(Integer, nullable=False)
    used = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    total_latency_ms = Column(Integer, default=0)             # sum for avg calculation
    total_data_items = Column(Integer, default=0)             # total records fetched
    total_bytes = Column(Integer, default=0)                  # total response size
    last_request_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_key", "date", name="uq_rate_budget_source_date"),
    )

    @property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.used)

    @property
    def success_rate(self) -> float:
        if self.used == 0:
            return 0.0
        return round(self.succeeded / self.used * 100, 1)

    @property
    def avg_latency_ms(self) -> float:
        if self.used == 0:
            return 0.0
        return round(self.total_latency_ms / self.used, 1)

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "date": self.date,
            "daily_limit": self.daily_limit,
            "used": self.used,
            "remaining": self.remaining,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "total_data_items": self.total_data_items,
            "total_bytes": self.total_bytes,
            "utilization_pct": round(self.used / self.daily_limit * 100, 1) if self.daily_limit else 0,
            "last_request_at": self.last_request_at.isoformat() if self.last_request_at else None,
            "last_error": self.last_error,
        }


# ── Engine + Session factory ─────────────────────────────────────────────────

def get_engine(db_path: Path | None = None):
    """Create SQLAlchemy engine for tracker.db."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", echo=False)
    return engine


def init_db(db_path: Path | None = None):
    """Create all tables if they don't exist."""
    _import_reference_models()
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    logger.info("[Database] Initialized tracker.db at %s", db_path or DB_PATH)
    return engine


def get_session(engine=None) -> Session:
    """Return a new SQLAlchemy session."""
    if engine is None:
        engine = get_engine()
    SessionFactory = sessionmaker(bind=engine)
    return SessionFactory()
