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
