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


ENDPOINT_FAILURE_THRESHOLD = 3   # consecutive failures before auto-deactivation


class ApiEndpoint(Base):
    """One row per (adapter_name, intent) binding — the unit of endpoint health tracking.

    An adapter like AllThePlacesAdapter can serve multiple intents, so each
    combination gets its own row with independent health state.  The orchestrator
    builds its system prompt from healthy rows only, so a broken source is
    automatically excluded without any code change.
    """

    __tablename__ = "api_endpoints"

    id              = Column(Integer, primary_key=True, autoincrement=True)

    # ── Identity ──────────────────────────────────────────────────
    adapter_name    = Column(String, nullable=False, index=True)   # "AllThePlacesAdapter"
    scraper_module  = Column(String, nullable=True)                # "scrapers.alltheplaces_adapter"
    source_key      = Column(String, nullable=False, default="", index=True)  # FK-like to api_sources.source_key; "" for DB-internal
    intent          = Column(String, nullable=False, index=True)   # Intent enum value
    data_type       = Column(String, nullable=False, default="")   # "Store" | "Signal" | "WageIndex"
    route_status    = Column(String, nullable=False, default="live")  # "live" | "unwired" | "suggested"
    notes           = Column(Text, nullable=True)

    # ── Coverage scope (NULL = covers all) ───────────────────────
    industries_json = Column(Text, nullable=True)   # JSON list of industry keys
    brands_json     = Column(Text, nullable=True)   # JSON list of brand keys
    regions_json    = Column(Text, nullable=True)   # JSON list of region keys

    # ── URL / access pattern ──────────────────────────────────────
    base_url        = Column(String, nullable=True)
    url_pattern     = Column(String, nullable=True)

    # ── Health tracking ───────────────────────────────────────────
    is_active            = Column(Boolean, default=True, nullable=False, index=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    success_count        = Column(Integer, default=0, nullable=False)
    failure_count        = Column(Integer, default=0, nullable=False)
    last_verified_at     = Column(DateTime, nullable=True)
    last_success_at      = Column(DateTime, nullable=True)
    last_failure_reason  = Column(String, nullable=True)

    # How many hours before health-check result is considered stale
    health_check_freshness_hours = Column(Float, default=6.0, nullable=False)

    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("adapter_name", "source_key", "intent", name="uq_endpoint_adapter_source_intent"),
    )

    # ── JSON property helpers ──────────────────────────────────────
    @property
    def industries(self) -> list[str] | None:
        return json.loads(self.industries_json) if self.industries_json else None

    @industries.setter
    def industries(self, value: list[str] | None) -> None:
        self.industries_json = json.dumps(value) if value is not None else None

    @property
    def brands(self) -> list[str] | None:
        return json.loads(self.brands_json) if self.brands_json else None

    @brands.setter
    def brands(self, value: list[str] | None) -> None:
        self.brands_json = json.dumps(value) if value is not None else None

    @property
    def regions(self) -> list[str] | None:
        return json.loads(self.regions_json) if self.regions_json else None

    @regions.setter
    def regions(self, value: list[str] | None) -> None:
        self.regions_json = json.dumps(value) if value is not None else None

    # ── Computed health properties ─────────────────────────────────
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return round(self.success_count / total * 100, 1) if total > 0 else 0.0

    @property
    def health_check_is_stale(self) -> bool:
        if not self.last_verified_at:
            return True
        age_hours = (datetime.utcnow() - self.last_verified_at).total_seconds() / 3600
        return age_hours > self.health_check_freshness_hours

    @property
    def is_healthy(self) -> bool:
        return self.is_active and self.consecutive_failures < ENDPOINT_FAILURE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "adapter_name": self.adapter_name,
            "scraper_module": self.scraper_module,
            "source_key": self.source_key,
            "intent": self.intent,
            "data_type": self.data_type,
            "route_status": self.route_status,
            "notes": self.notes,
            "industries": self.industries,
            "brands": self.brands,
            "regions": self.regions,
            "base_url": self.base_url,
            "url_pattern": self.url_pattern,
            "is_active": self.is_active,
            "is_healthy": self.is_healthy,
            "consecutive_failures": self.consecutive_failures,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_failure_reason": self.last_failure_reason,
            "health_check_is_stale": self.health_check_is_stale,
            "health_check_freshness_hours": self.health_check_freshness_hours,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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


class SourceFreshness(Base):
    """Tracks when each source/intent/brand/industry/region combination was last collected.

    The agent checks this before executing a query. If data is younger than
    the freshness threshold for that intent, the query is skipped as redundant.

    Thresholds (in days, configured in agent_interface/schemas.py):
        job_posting_volume  → 14   (job boards change biweekly)
        sentiment_check     → 14   (opinions shift slowly)
        poi_chain_locations → 60   (locations rarely change)
        poi_local_density   → 60
        wage_baseline       → 90   (BLS quarterly)
        economic_context    → 90
        score_refresh       → 1    (always recompute)
        data_quality_audit  → 0    (always runs)
        campaign_status     → 0    (always runs)
    """

    __tablename__ = "source_freshness"

    id = Column(Integer, primary_key=True, autoincrement=True)
    intent = Column(String, nullable=False, index=True)           # e.g. 'poi_chain_locations'
    region = Column(String, nullable=False, index=True)           # e.g. 'austin_tx'
    brand = Column(String, nullable=True)                         # e.g. 'starbucks' (null for non-brand intents)
    industry = Column(String, nullable=True)                      # e.g. 'coffee_cafe' (null when not applicable)
    source_key = Column(String, nullable=True)                    # which API source was used
    last_collected_at = Column(DateTime, nullable=False, index=True)
    records_collected = Column(Integer, default=0)                # how many records were returned
    status = Column(String, nullable=False, default="completed")  # completed | partial | failed
    threshold_days = Column(Float, nullable=False, default=14.0)  # snapshot of threshold at collection time
    notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "intent", "region", "brand", "industry",
            name="uq_freshness_intent_region_brand_industry",
        ),
    )

    @property
    def age_days(self) -> float:
        """How many days since last collection."""
        if not self.last_collected_at:
            return float("inf")
        return (datetime.utcnow() - self.last_collected_at).total_seconds() / 86400

    @property
    def is_stale(self) -> bool:
        """True if data is older than threshold and should be re-collected."""
        return self.age_days > self.threshold_days

    @property
    def next_due_at(self) -> datetime | None:
        """When this data should next be collected."""
        if not self.last_collected_at:
            return None
        from datetime import timedelta
        return self.last_collected_at + timedelta(days=self.threshold_days)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "intent": self.intent,
            "region": self.region,
            "brand": self.brand,
            "industry": self.industry,
            "source_key": self.source_key,
            "last_collected_at": self.last_collected_at.isoformat() if self.last_collected_at else None,
            "records_collected": self.records_collected,
            "status": self.status,
            "threshold_days": self.threshold_days,
            "age_days": round(self.age_days, 1),
            "is_stale": self.is_stale,
            "next_due_at": self.next_due_at.isoformat() if self.next_due_at else None,
            "notes": self.notes,
        }


# ── Freshness helpers ─────────────────────────────────────────────────────────

def upsert_freshness(
    intent: str,
    region: str,
    brand: str | None,
    industry: str | None,
    records_collected: int,
    status: str = "completed",
    source_key: str | None = None,
    threshold_days: float = 14.0,
    notes: str | None = None,
    db_session: Session | None = None,
) -> SourceFreshness:
    """Insert or update a freshness record after data collection.

    Uses the composite key (intent, region, brand, industry) to upsert.
    """
    close_session = False
    if db_session is None:
        db_session = get_session(get_engine())
        close_session = True

    try:
        existing = db_session.query(SourceFreshness).filter(
            SourceFreshness.intent == intent,
            SourceFreshness.region == region,
            SourceFreshness.brand == (brand or None),
            SourceFreshness.industry == (industry or None),
        ).first()

        if existing:
            existing.last_collected_at = datetime.utcnow()
            existing.records_collected = records_collected
            existing.status = status
            existing.source_key = source_key
            existing.threshold_days = threshold_days
            existing.notes = notes
        else:
            existing = SourceFreshness(
                intent=intent,
                region=region,
                brand=brand or None,
                industry=industry or None,
                source_key=source_key,
                last_collected_at=datetime.utcnow(),
                records_collected=records_collected,
                status=status,
                threshold_days=threshold_days,
                notes=notes,
            )
            db_session.add(existing)

        db_session.commit()
        # Eagerly load all attributes before the session might close
        db_session.refresh(existing)
        db_session.expunge(existing)
        return existing

    except Exception as e:
        db_session.rollback()
        logger.error("[Database] Freshness upsert failed: %s", e)
        raise
    finally:
        if close_session:
            db_session.close()


def check_freshness(
    intent: str,
    region: str,
    brand: str | None = None,
    industry: str | None = None,
    db_session: Session | None = None,
) -> dict:
    """Check how fresh existing data is for a given query.

    Returns:
        dict with keys: is_stale, age_days, last_collected_at,
        records_collected, threshold_days, next_due_at
    """
    close_session = False
    if db_session is None:
        db_session = get_session(get_engine())
        close_session = True

    try:
        record = db_session.query(SourceFreshness).filter(
            SourceFreshness.intent == intent,
            SourceFreshness.region == region,
            SourceFreshness.brand == (brand or None),
            SourceFreshness.industry == (industry or None),
        ).first()

        if record is None:
            return {
                "is_stale": True,
                "age_days": None,
                "last_collected_at": None,
                "records_collected": 0,
                "threshold_days": None,
                "next_due_at": None,
                "never_collected": True,
            }

        return {
            "is_stale": record.is_stale,
            "age_days": round(record.age_days, 1),
            "last_collected_at": record.last_collected_at.isoformat() if record.last_collected_at else None,
            "records_collected": record.records_collected,
            "threshold_days": record.threshold_days,
            "next_due_at": record.next_due_at.isoformat() if record.next_due_at else None,
            "never_collected": False,
        }

    finally:
        if close_session:
            db_session.close()


def get_all_freshness(db_session: Session | None = None) -> list[dict]:
    """Return all freshness records, sorted by staleness (most stale first)."""
    close_session = False
    if db_session is None:
        db_session = get_session(get_engine())
        close_session = True

    try:
        records = db_session.query(SourceFreshness).order_by(
            SourceFreshness.last_collected_at.asc()
        ).all()
        return [r.to_dict() for r in records]
    finally:
        if close_session:
            db_session.close()


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
