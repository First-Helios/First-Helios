"""
SQLAlchemy models and database initialization for First-Helios.

Multi-domain data platform: jobs, events, businesses, wages, economic
indicators, career mobility. Data arrives from 50+ automated collectors
and real-time SpiritPool contributor signals.

DB file: data/tracker.db (auto-created on first run)
NOTE: data/spiritpool.db is a separate extension DB — never write to it from here.

Depends on: SQLAlchemy, pathlib
Called by: core/ingest.py, core/scoring/, core/targeting.py, server.py
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
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
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "tracker.db"


def _import_reference_models() -> None:
    """Import reference models so their tables register with Base.metadata.

    Called lazily in init_db() to avoid circular-import issues.
    """
    try:
        import core.models.reference  # noqa: F401
    except ImportError:
        logger.debug("[Database] backend.models.reference not found — skipping")


def _import_metadata_models() -> None:
    """Import metadata models so their tables register with Base.metadata.

    Called lazily in init_db() to avoid circular-import issues.
    """
    try:
        import core.metadata  # noqa: F401
    except ImportError:
        logger.debug("[Database] backend.metadata not found — skipping")


def _import_listings_models() -> None:
    """Import listings models so their tables register with Base.metadata.

    Called lazily in init_db() to avoid circular-import issues.
    The listings/ layer is optional — if absent the app starts normally.
    """
    try:
        import postings.models  # noqa: F401
    except ImportError:
        logger.debug("[Database] listings.models not found — skipping")


def _import_events_models() -> None:
    """Import events models so their tables register with Base.metadata."""
    try:
        import events.models  # noqa: F401
    except ImportError:
        logger.debug("[Database] events.models not found — skipping")


def _import_spiritpool_models() -> None:
    """Import SpiritPool models so their tables register with Base.metadata."""
    try:
        import core.models.spiritpool  # noqa: F401
    except ImportError:
        logger.debug("[Database] core.models.spiritpool not found — skipping")


def _import_dev_capture_models() -> None:
    """Import dev-capture models (dev_capture schema) for dev-mode raw signals."""
    try:
        import core.models.dev_capture  # noqa: F401
    except ImportError:
        logger.debug("[Database] core.models.dev_capture not found — skipping")


class Base(DeclarativeBase):
    """Declarative base for all tracker models."""
    pass


# ── Models ───────────────────────────────────────────────────────────────────

class Store(Base):
    """One row per physical chain / franchise location.

    Represents large-cap multi-location organizations (Starbucks, Target,
    Jiffy Lube, etc.).  Discovered via AllThePlaces, Overture, OSM, or
    Google Maps.  Linked to ref_brands by brand_key.

    Layer: Business Locations (Layer 2)
    """

    __tablename__ = "chain_locations"

    store_num = Column(String, primary_key=True)
    brand_key = Column(String, nullable=True, index=True)  # FK ref_brands.brand_key
    chain = Column(String, nullable=False, index=True)      # Display name
    industry = Column(String, nullable=False)
    store_name = Column(String, nullable=False, default="")
    address = Column(String, nullable=False, default="")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    region = Column(String, nullable=False, index=True)
    source_discovery = Column(String, nullable=True)  # alltheplaces, overture, osm, gmaps, jobspy
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # ── H3 hexagonal index ────────────────────────────────────────────────────
    h3_r8 = Column(String(15), nullable=True, index=True)  # corridor  ~156 cells
    h3_r9 = Column(String(15), nullable=True, index=True)  # block

    def to_dict(self) -> dict:
        return {
            "store_num": self.store_num,
            "brand_key": self.brand_key,
            "chain": self.chain,
            "industry": self.industry,
            "store_name": self.store_name,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "region": self.region,
            "source_discovery": self.source_discovery,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_active": self.is_active,
        }


# Removed duplicate alias ChainLocation — use Store everywhere.


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

    __table_args__ = (
        Index("ix_signals_store_source", "store_num", "source"),
        Index("ix_signals_observed_at", "observed_at"),
    )


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


class QCEWRecord(Base):
    """County-level establishment & employment from BLS QCEW.

    Quarterly Census of Employment & Wages — the authoritative
    denominator for all posting-based metrics.  Updated quarterly
    with ~6 month lag.
    """

    __tablename__ = "qcew_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fips_code = Column(String(5), nullable=False, index=True)  # county FIPS
    naics_code = Column(String(6), nullable=False, index=True)
    naics_title = Column(String, nullable=True)
    year = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)  # 1-4
    ownership_code = Column(String(2), default="5")  # 5 = private
    establishments = Column(Integer, nullable=True)
    month1_employment = Column(Integer, nullable=True)
    month2_employment = Column(Integer, nullable=True)
    month3_employment = Column(Integer, nullable=True)
    total_wages = Column(Float, nullable=True)
    avg_weekly_wage = Column(Float, nullable=True)
    avg_annual_pay = Column(Float, nullable=True)
    region = Column(String, nullable=True, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "fips_code", "naics_code", "year", "quarter", "ownership_code",
            name="uq_qcew_record",
        ),
    )

    @property
    def avg_employment(self) -> float | None:
        """Average employment across the 3 months of the quarter."""
        vals = [v for v in [self.month1_employment, self.month2_employment, self.month3_employment] if v]
        return sum(vals) / len(vals) if vals else None

    @property
    def avg_employees_per_establishment(self) -> float | None:
        emp = self.avg_employment
        if emp and self.establishments:
            return emp / self.establishments
        return None

    def to_dict(self) -> dict:
        return {
            "fips_code": self.fips_code,
            "naics_code": self.naics_code,
            "naics_title": self.naics_title,
            "year": self.year,
            "quarter": self.quarter,
            "establishments": self.establishments,
            "avg_employment": self.avg_employment,
            "avg_weekly_wage": self.avg_weekly_wage,
            "avg_annual_pay": self.avg_annual_pay,
            "avg_employees_per_establishment": self.avg_employees_per_establishment,
            "region": self.region,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


class CBPRecord(Base):
    """ZIP-level establishment counts from Census County Business Patterns.

    Annual release, ~18 month lag.  Gives sub-metro geographic granularity
    for establishment density and employment.
    """

    __tablename__ = "cbp_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zip_code = Column(String(5), nullable=False, index=True)
    naics_code = Column(String(6), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    establishments = Column(Integer, nullable=True)
    employment = Column(Integer, nullable=True)
    employment_noise_flag = Column(String(1), nullable=True)  # Census noise flag
    annual_payroll_k = Column(Float, nullable=True)  # in thousands
    region = Column(String, nullable=True, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "zip_code", "naics_code", "year",
            name="uq_cbp_record",
        ),
    )

    @property
    def avg_employees_per_establishment(self) -> float | None:
        if self.employment and self.establishments:
            return self.employment / self.establishments
        return None

    def to_dict(self) -> dict:
        return {
            "zip_code": self.zip_code,
            "naics_code": self.naics_code,
            "year": self.year,
            "establishments": self.establishments,
            "employment": self.employment,
            "annual_payroll_k": self.annual_payroll_k,
            "avg_employees_per_establishment": self.avg_employees_per_establishment,
            "region": self.region,
        }


class JOLTSRecord(Base):
    """National/regional job openings & turnover from BLS JOLTS.

    Gives expected turnover rate by industry — the benchmark that
    distinguishes normal replacement hiring from staffing stress.
    """

    __tablename__ = "jolts_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(String, nullable=False)
    series_description = Column(String, nullable=True)
    metric = Column(String, nullable=False)  # quits_rate, openings_rate, hires_rate, separations_rate
    industry_code = Column(String, nullable=True)  # NAICS-like
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)  # 1-12
    value = Column(Float, nullable=False)  # rate as percentage
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "series_id", "year", "month",
            name="uq_jolts_record",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "series_id": self.series_id,
            "metric": self.metric,
            "industry_code": self.industry_code,
            "year": self.year,
            "month": self.month,
            "value": self.value,
        }


class OEWSRecord(Base):
    """MSA-level occupation employment & wages from BLS OEWS.

    Maps SOC occupation codes to employment counts and wage percentiles.
    """

    __tablename__ = "oews_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    area_code = Column(String, nullable=False, index=True)  # MSA FIPS
    area_title = Column(String, nullable=True)
    occ_code = Column(String(7), nullable=False, index=True)  # SOC code e.g. 35-3023
    occ_title = Column(String, nullable=True)
    naics_code = Column(String(6), nullable=True)
    employment = Column(Integer, nullable=True)
    wage_mean_hourly = Column(Float, nullable=True)
    wage_median_hourly = Column(Float, nullable=True)
    wage_10pct = Column(Float, nullable=True)
    wage_25pct = Column(Float, nullable=True)
    wage_75pct = Column(Float, nullable=True)
    wage_90pct = Column(Float, nullable=True)
    year = Column(Integer, nullable=False)
    region = Column(String, nullable=True, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "area_code", "occ_code", "year",
            name="uq_oews_record",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "area_code": self.area_code,
            "area_title": self.area_title,
            "occ_code": self.occ_code,
            "occ_title": self.occ_title,
            "employment": self.employment,
            "wage_mean_hourly": self.wage_mean_hourly,
            "wage_median_hourly": self.wage_median_hourly,
            "year": self.year,
            "region": self.region,
        }


class LAUSRecord(Base):
    """County-level unemployment from BLS Local Area Unemployment Statistics.

    Monthly release with ~2 month lag.  Measures labor market tightness.
    """

    __tablename__ = "laus_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fips_code = Column(String(5), nullable=False, index=True)
    area_title = Column(String, nullable=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    labor_force = Column(Integer, nullable=True)
    employed = Column(Integer, nullable=True)
    unemployed = Column(Integer, nullable=True)
    unemployment_rate = Column(Float, nullable=True)
    region = Column(String, nullable=True, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "fips_code", "year", "month",
            name="uq_laus_record",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "fips_code": self.fips_code,
            "area_title": self.area_title,
            "year": self.year,
            "month": self.month,
            "labor_force": self.labor_force,
            "unemployment_rate": self.unemployment_rate,
        }


class LaborMarketBaseline(Base):
    """Pre-computed baseline metrics from ground-truth sources.

    Combines QCEW, JOLTS, OEWS, and LAUS into the denominators
    and benchmarks that the scoring engine needs.  Recomputed after
    each ground-truth data fetch.
    """

    __tablename__ = "labor_market_baseline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String, nullable=False, index=True)
    naics_code = Column(String(6), nullable=False)
    period_label = Column(String, nullable=False)  # e.g. "2025-Q3" or "2025-11"

    # From QCEW
    establishment_count = Column(Integer, nullable=True)
    total_employment = Column(Integer, nullable=True)
    avg_weekly_wage = Column(Float, nullable=True)
    avg_employees_per_establishment = Column(Float, nullable=True)

    # From JOLTS
    expected_quits_rate = Column(Float, nullable=True)  # monthly %
    expected_openings_rate = Column(Float, nullable=True)
    expected_monthly_separations = Column(Integer, nullable=True)

    # From OEWS
    occupation_median_wage = Column(Float, nullable=True)
    occupation_employment = Column(Integer, nullable=True)

    # From LAUS
    unemployment_rate = Column(Float, nullable=True)
    labor_force = Column(Integer, nullable=True)

    # Derived metrics
    hiring_intensity_baseline = Column(Float, nullable=True)  # postings / establishment at normal
    seasonal_index = Column(Float, nullable=True)  # month-over-month ratio vs annual avg

    computed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "region", "naics_code", "period_label",
            name="uq_labor_baseline",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "naics_code": self.naics_code,
            "period_label": self.period_label,
            "establishment_count": self.establishment_count,
            "total_employment": self.total_employment,
            "avg_weekly_wage": self.avg_weekly_wage,
            "avg_employees_per_establishment": self.avg_employees_per_establishment,
            "expected_quits_rate": self.expected_quits_rate,
            "expected_openings_rate": self.expected_openings_rate,
            "expected_monthly_separations": self.expected_monthly_separations,
            "occupation_median_wage": self.occupation_median_wage,
            "unemployment_rate": self.unemployment_rate,
            "hiring_intensity_baseline": self.hiring_intensity_baseline,
            "seasonal_index": self.seasonal_index,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }


class BrandGroup(Base):
    """Canonical brand identity — one row per unique business fingerprint.

    Maintained incrementally by backend/ingest_layer.py.
    location_count is updated atomically on each employer insert so it is
    always current without a full table scan.

    A business is classified as a brand when location_count >= CHAIN_THRESHOLD (5).

    Layer: Reference Data (Layer 1)
    """

    __tablename__ = "brand_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fingerprint = Column(String, nullable=False, unique=True, index=True)
    canonical_name = Column(String, nullable=False)
    location_count = Column(Integer, nullable=False, default=0)
    industry = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fingerprint": self.fingerprint,
            "canonical_name": self.canonical_name,
            "location_count": self.location_count,
            "industry": self.industry,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class LocalEmployer(Base):
    """Every employer POI — brands and local businesses in a single table.

    Populated exclusively through backend/ingest_layer.py, which normalizes
    names and maintains brand_groups counts before writing here.

    brand_group_id links to BrandGroup. Query brand_groups.location_count >= 5
    to identify brand-class employers at read time.

    Layer: Business Locations (Layer 2)
    """

    __tablename__ = "local_employers"

    # ── Internal stable key ───────────────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Source identity (not the PK — can be corrected without losing the row) ─
    overture_id = Column(String, nullable=True, index=True)   # null for non-Overture sources
    source = Column(String, nullable=False, default="overture")  # overture | bls | yelp | manual

    # ── Name — both raw and normalized ───────────────────────────────────────
    raw_name = Column(String, nullable=False)                  # exactly as ingested
    name = Column(String, nullable=False)                      # canonical_name (display)
    fingerprint = Column(String, nullable=True, index=True)    # rigour key for grouping

    # ── Brand group link ──────────────────────────────────────────────────────
    brand_group_id = Column(Integer, ForeignKey("brand_groups.id"), nullable=True, index=True)
    location_count = Column(Integer, nullable=True)            # denorm cache from brand_groups

    # ── Classification ────────────────────────────────────────────────────────
    category = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    mobility_score = Column(Float, nullable=True)  # 0.0–1.0; wage lift + career ceiling vs service baseline

    # ── Location ──────────────────────────────────────────────────────────────
    address = Column(String, nullable=True, default="")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    region = Column(String, nullable=True)

    # ── H3 hexagonal index (pre-computed at ingest / backfill) ────────────────
    h3_r6 = Column(String(15), nullable=True, index=True)  # city overview   ~25 cells
    h3_r7 = Column(String(15), nullable=True, index=True)  # neighborhood  ~453 cells
    h3_r8 = Column(String(15), nullable=True, index=True)  # corridor     ~1915 cells
    h3_r9 = Column(String(15), nullable=True, index=True)  # block        ~8000 cells

    # ── Provenance ────────────────────────────────────────────────────────────
    source_discovery = Column(String, nullable=True)           # overture_local | osm | jobspy
    confidence = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "overture_id": self.overture_id,
            "source": self.source,
            "raw_name": self.raw_name,
            "name": self.name,
            "fingerprint": self.fingerprint,
            "brand_group_id": self.brand_group_id,
            "location_count": self.location_count,
            "category": self.category,
            "industry": self.industry,
            "mobility_score": self.mobility_score,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "region": self.region,
            "source_discovery": self.source_discovery,
            "confidence": self.confidence,
            "is_active": self.is_active,
        }

    __table_args__ = (
        UniqueConstraint("fingerprint", "region", name="uq_local_employer_fp_region"),
    )


class EmployerNameIndex(Base):
    """Canonical name registry for every unique employer name seen in local_employers.

    Classifies each name as national_chain, regional_chain, or local so the
    scoring engine and UI can filter / weight accordingly.

    Populated by scripts/build_name_index.py and refreshed weekly by the scheduler.

    Layer: Reference Data (Layer 1)
    """

    __tablename__ = "ref_employer_name_index"

    name = Column(String, primary_key=True)
    austin_location_count = Column(Integer, default=1)   # occurrences in local_employers
    classification = Column(String, nullable=False)       # national_chain | regional_chain | local
    industry = Column(String, nullable=True)              # most common industry for this name
    category = Column(String, nullable=True)              # most common Overture category
    is_chain = Column(Boolean, default=False)             # True for regional + national
    notes = Column(String, nullable=True)                 # e.g. "Texas regional", "excluded chain"
    reviewed = Column(Boolean, default=False)             # manually reviewed flag
    updated_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "austin_location_count": self.austin_location_count,
            "classification": self.classification,
            "industry": self.industry,
            "category": self.category,
            "is_chain": self.is_chain,
            "notes": self.notes,
            "reviewed": self.reviewed,
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


# ── Revelio Labs Labor Market Data ──────────────────────────────────────────

class RevelioEmployment(Base):
    """State-level employment counts from Revelio Labs proprietary data.

    Monthly granularity by state, occupation (2-digit SOC), and industry (2-digit NAICS).
    Includes both seasonally adjusted (SA) and non-seasonally adjusted (NSA) counts.
    """

    __tablename__ = "revelio_employment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String, nullable=False, index=True)  # YYYY-MM format
    state = Column(String, nullable=False, index=True)
    naics2d_code = Column(Integer, nullable=True)  # Nullable: some data has ranges like "31-33"
    naics2d_name = Column(String, nullable=True)
    soc2d_code = Column(Integer, nullable=False)
    soc2d_name = Column(String, nullable=True)
    count_nsa = Column(Float, nullable=True)  # Non-seasonally adjusted
    count_sa = Column(Float, nullable=True)   # Seasonally adjusted
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "month", "state", "naics2d_code", "soc2d_code",
            name="uq_revelio_employment",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "state": self.state,
            "naics2d_code": self.naics2d_code,
            "naics2d_name": self.naics2d_name,
            "soc2d_code": self.soc2d_code,
            "soc2d_name": self.soc2d_name,
            "count_nsa": self.count_nsa,
            "count_sa": self.count_sa,
        }


class RevelioHiring(Base):
    """State-level hiring and attrition rates from Revelio Labs.

    Monthly granularity by state, occupation (2-digit SOC), and industry (2-digit NAICS).
    Revelio proprietary hiring rate (rl_*) and attrition rate metrics.
    """

    __tablename__ = "revelio_hiring"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String, nullable=False, index=True)  # YYYY-MM format
    state = Column(String, nullable=False, index=True)
    naics2d_code = Column(Integer, nullable=True)  # Nullable: some data has ranges like "31-33"
    naics2d_name = Column(String, nullable=True)
    soc2d_code = Column(Integer, nullable=False)
    soc2d_name = Column(String, nullable=True)
    hiring_rate_nsa = Column(Float, nullable=True)      # Non-seasonally adjusted
    hiring_rate_sa = Column(Float, nullable=True)       # Seasonally adjusted
    attrition_rate_nsa = Column(Float, nullable=True)
    attrition_rate_sa = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "month", "state", "naics2d_code", "soc2d_code",
            name="uq_revelio_hiring",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "state": self.state,
            "naics2d_code": self.naics2d_code,
            "naics2d_name": self.naics2d_name,
            "soc2d_code": self.soc2d_code,
            "soc2d_name": self.soc2d_name,
            "hiring_rate_nsa": self.hiring_rate_nsa,
            "hiring_rate_sa": self.hiring_rate_sa,
            "attrition_rate_nsa": self.attrition_rate_nsa,
            "attrition_rate_sa": self.attrition_rate_sa,
        }


class RevelioPostings(Base):
    """Active job postings from Revelio Labs aggregated data.

    Monthly counts by state, occupation (2-digit SOC), and industry (2-digit NAICS).
    Aggregated from 50+ job boards.
    """

    __tablename__ = "revelio_postings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String, nullable=False, index=True)  # YYYY-MM format
    state = Column(String, nullable=False, index=True)
    naics2d_code = Column(Integer, nullable=False)
    naics2d_name = Column(String, nullable=True)
    soc2d_code = Column(Integer, nullable=False)
    soc2d_name = Column(String, nullable=True)
    active_postings_nsa = Column(Float, nullable=True)  # Non-seasonally adjusted
    active_postings_sa = Column(Float, nullable=True)   # Seasonally adjusted
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "month", "state", "naics2d_code", "soc2d_code",
            name="uq_revelio_postings",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "state": self.state,
            "naics2d_code": self.naics2d_code,
            "naics2d_name": self.naics2d_name,
            "soc2d_code": self.soc2d_code,
            "soc2d_name": self.soc2d_name,
            "active_postings_nsa": self.active_postings_nsa,
            "active_postings_sa": self.active_postings_sa,
        }


class RevelioSalaries(Base):
    """Salary data aggregated from job postings by Revelio Labs.

    Monthly salary metrics by state, occupation (2-digit SOC), and industry (2-digit NAICS).
    Derived from active job posting salary disclosures.
    """

    __tablename__ = "revelio_salaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String, nullable=False, index=True)  # YYYY-MM format
    state = Column(String, nullable=False, index=True)
    naics2d_code = Column(Integer, nullable=False)
    naics2d_name = Column(String, nullable=True)
    soc2d_code = Column(Integer, nullable=False)
    soc2d_name = Column(String, nullable=True)
    salary_nsa = Column(Float, nullable=True)           # Annual salary USD, non-seasonally adjusted
    salary_sa = Column(Float, nullable=True)            # Seasonally adjusted
    salary_count = Column(Float, nullable=True)         # Number of postings with salary data
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "month", "state", "naics2d_code", "soc2d_code",
            name="uq_revelio_salaries",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "state": self.state,
            "naics2d_code": self.naics2d_code,
            "naics2d_name": self.naics2d_name,
            "soc2d_code": self.soc2d_code,
            "soc2d_name": self.soc2d_name,
            "salary_nsa": self.salary_nsa,
            "salary_sa": self.salary_sa,
            "salary_count": self.salary_count,
        }


class RevelioLayoffs(Base):
    """Mass layoff notices from Revelio Labs (WARN Act filings).

    Monthly aggregated data by state and industry. Includes both state-level
    and industry-level (NAICS 2-digit) breakdowns of layoff activity.
    """

    __tablename__ = "revelio_layoffs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String, nullable=False, index=True)  # YYYY-MM format
    state = Column(String, nullable=True, index=True)   # Nullable for 'total' records
    naics2d_code = Column(Integer, nullable=True)       # Nullable for 'total' records
    naics2d_name = Column(String, nullable=True)
    layoff_type = Column(String, nullable=False)        # 'by_state' | 'by_naics' | 'total'
    employees_notified = Column(Float, nullable=True)
    notices_issued = Column(Float, nullable=True)
    employees_laidoff = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "month", "state", "naics2d_code", "layoff_type",
            name="uq_revelio_layoffs",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "state": self.state,
            "naics2d_code": self.naics2d_code,
            "naics2d_name": self.naics2d_name,
            "layoff_type": self.layoff_type,
            "employees_notified": self.employees_notified,
            "notices_issued": self.notices_issued,
            "employees_laidoff": self.employees_laidoff,
        }


class CollectorRun(Base):
    """Tracks per-pull stats for rate-limited job board collectors."""
    __tablename__ = "collector_runs"

    id           = Column(Integer, primary_key=True)
    source       = Column(String(64), nullable=False, index=True)
    industry_key = Column(String(64), nullable=True)
    search_term  = Column(String(512), nullable=True)
    fetched      = Column(Integer, default=0)
    new          = Column(Integer, default=0)
    updated      = Column(Integer, default=0)
    skipped      = Column(Integer, default=0)
    run_at       = Column(DateTime, nullable=False, index=True)


class RestaurantURL(Base):
    """Cached website URLs for local_employers — resolved from OSM, Google Places, or manual entry.

    One row per employer. Multiple resolution sources write here; the highest-confidence
    source wins via the `source` + `confidence` pattern.

    URL data is reusable across all downstream scrapers (meal deals, job postings, events).

    Layer: Reference Data (Layer 1)
    """

    __tablename__ = "restaurant_urls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    local_employer_id = Column(Integer, ForeignKey("local_employers.id"), nullable=False, index=True)
    brand_group_id = Column(Integer, ForeignKey("brand_groups.id"), nullable=True, index=True)
    url = Column(String, nullable=False)
    source = Column(String, nullable=False)  # osm | google_places | manual | chain_config
    confidence = Column(Float, nullable=True, default=1.0)
    is_active = Column(Boolean, default=True)
    is_permanent = Column(Boolean, default=False)          # True = URL unlikely to change (e.g. Google Places)
    last_checked = Column(DateTime, nullable=True)
    last_http_status = Column(Integer, nullable=True)
    has_deals_page = Column(Boolean, nullable=True)
    deals_page_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "local_employer_id": self.local_employer_id,
            "brand_group_id": self.brand_group_id,
            "url": self.url,
            "source": self.source,
            "confidence": self.confidence,
            "is_active": self.is_active,
            "is_permanent": self.is_permanent,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "last_http_status": self.last_http_status,
            "has_deals_page": self.has_deals_page,
            "deals_page_url": self.deals_page_url,
        }

    __table_args__ = (
        UniqueConstraint("local_employer_id", "source", name="uq_restaurant_url_employer_source"),
    )


class MealDeal(Base):
    """A meal deal / special offered by a restaurant in local_employers.

    Populated by collectors/meal_deals/ scrapers. Each row represents one
    deal at one location (chain-wide deals fan out to one row per location).

    Layer: Consumer Intelligence (Layer 5)
    """

    __tablename__ = "meal_deals"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Restaurant link ───────────────────────────────────────────────────────
    local_employer_id = Column(Integer, ForeignKey("local_employers.id"), nullable=False, index=True)
    brand_group_id = Column(Integer, ForeignKey("brand_groups.id"), nullable=True, index=True)

    # ── Deal detail ───────────────────────────────────────────────────────────
    deal_name = Column(String, nullable=False)
    deal_description = Column(Text, nullable=True)
    deal_type = Column(String, nullable=False, index=True)
    # lunch_special | combo | bogo | happy_hour | kids_eat_free | daily_special

    # ── Pricing ───────────────────────────────────────────────────────────────
    price = Column(Float, nullable=True)
    original_price = Column(Float, nullable=True)
    menu_avg_price = Column(Float, nullable=True)          # avg entrée price on same menu

    # ── Nutrition ─────────────────────────────────────────────────────────────
    calories = Column(Integer, nullable=True)               # kcal for the deal item
    calorie_price_ratio = Column(Float, nullable=True)      # kcal per dollar

    # ── Validity window ───────────────────────────────────────────────────────
    valid_days = Column(String, nullable=True)          # "Mon-Fri" or "Tuesday" or null=everyday
    valid_start_time = Column(String, nullable=True)    # "11:00"
    valid_end_time = Column(String, nullable=True)      # "14:00"
    is_recurring = Column(Boolean, default=True)
    start_date = Column(DateTime, nullable=True)        # seasonal deals
    end_date = Column(DateTime, nullable=True)

    # ── Source provenance ─────────────────────────────────────────────────────
    source = Column(String, nullable=False)             # chain_website | google_places | yelp | manual | website_scrape
    source_url = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True, index=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Denormalized location (from local_employer) ───────────────────────────
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    region = Column(String, nullable=False, default="austin_tx", index=True)

    __table_args__ = (
        UniqueConstraint("local_employer_id", "deal_name", "source", name="uq_meal_deal_employer_name_source"),
        Index("ix_meal_deals_employer_active", "local_employer_id", "is_active"),
        Index("ix_meal_deals_brand_active", "brand_group_id", "is_active"),
        Index("ix_meal_deals_region_active", "region", "is_active"),
        Index("ix_meal_deals_type_region", "deal_type", "region"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "local_employer_id": self.local_employer_id,
            "brand_group_id": self.brand_group_id,
            "deal_name": self.deal_name,
            "deal_description": self.deal_description,
            "deal_type": self.deal_type,
            "price": self.price,
            "original_price": self.original_price,
            "menu_avg_price": self.menu_avg_price,
            "calories": self.calories,
            "calorie_price_ratio": self.calorie_price_ratio,
            "valid_days": self.valid_days,
            "valid_start_time": self.valid_start_time,
            "valid_end_time": self.valid_end_time,
            "is_recurring": self.is_recurring,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "source": self.source,
            "source_url": self.source_url,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "lat": self.lat,
            "lng": self.lng,
            "region": self.region,
        }


class GooglePlacesFailure(Base):
    """Tracks brands/employers that returned no result from Google Places API.

    Used to avoid wasting API budget re-resolving known failures.
    Run the resolver with --retry-failed to attempt these again.

    failure_reason values:
      no_website  — API returned a place but no websiteUri
      no_result   — API returned no matching place at all
      api_error   — HTTP error (non-429)

    retry_count increments each time a retry attempt is made and still fails,
    so you can prioritise / deprioritise based on how many times we've tried.
    """
    __tablename__ = "google_places_failures"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    entity_type    = Column(String(20), nullable=False)   # 'brand_group' | 'local_employer'
    entity_id      = Column(Integer, nullable=False)
    canonical_name = Column(String(255), nullable=True)   # human-readable for manual lookup
    failure_reason = Column(String(20), nullable=True)    # no_website | no_result | api_error
    failed_at      = Column(DateTime, default=datetime.utcnow)
    retry_count    = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_gp_failure_entity"),
    )


# ── Engine + Session factory ─────────────────────────────────────────────────

def get_engine(db_path: Path | None = None):
    """Create SQLAlchemy engine.

    Priority:
      1. DATABASE_URL environment variable → PostgreSQL (or any SQLAlchemy URL)
      2. db_path argument → SQLite at that path
      3. Default → SQLite at data/tracker.db
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        engine = create_engine(url, echo=False, pool_pre_ping=True)
        return engine
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def init_db(db_path: Path | None = None):
    """Create all tables if they don't exist."""
    _import_reference_models()
    _import_metadata_models()
    _import_listings_models()
    _import_events_models()
    _import_spiritpool_models()
    _import_dev_capture_models()
    engine = get_engine(db_path)
    if os.environ.get("DATABASE_URL"):
        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS dev_capture"))
            conn.commit()
    Base.metadata.create_all(engine)
    db_label = os.environ.get("DATABASE_URL") or str(db_path or DB_PATH)
    logger.info("[Database] Initialized at %s", db_label)
    return engine


def get_session(engine=None) -> Session:
    """Return a new SQLAlchemy session."""
    if engine is None:
        engine = get_engine()
    SessionFactory = sessionmaker(bind=engine)
    return SessionFactory()
