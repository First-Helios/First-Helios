"""
Metadata tables for system intelligence and tracking.

These tables answer critical questions:
  - What tables exist in this system?
  - What does each column mean?
  - Where did the data come from?
  - Did the job succeed or fail?
  - What API calls happened?

Depends on: SQLAlchemy
Called by: backend/database.py, CLI tools, audits
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from core.database import Base


def _utcnow() -> datetime:
    """Return naive UTC timestamps without using deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ────────────────────────────────────────────────────────────────────────────
# Core Metadata Tables
# ────────────────────────────────────────────────────────────────────────────


class MetaTableCatalog(Base):
    """Registry of all tables in the system with their purpose and SLA."""

    __tablename__ = "meta_table_catalog"

    id = Column(Integer, primary_key=True)

    # Identity
    table_name = Column(String, nullable=False, unique=True, index=True)
    layer = Column(String, nullable=False)  # raw, signals, derived, business, reference, metadata
    source = Column(String, nullable=False)  # bls, census, jobspy, reddit, computed, manual
    entity = Column(String, nullable=False)  # employment, wage, store, score

    # Documentation
    purpose = Column(Text, nullable=False)  # 2-sentence explanation
    description = Column(Text)  # Longer description

    # Content
    row_count_estimate = Column(Integer)
    row_count_checked_at = Column(DateTime)

    # Governance
    append_only = Column(Boolean, default=True)  # Can rows be updated?
    retention_days = Column(Integer)  # NULL = forever
    owner_team = Column(String)  # Who maintains this?

    # Links
    documentation_url = Column(String)  # Link to data dictionary

    # Audit
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("idx_layer_source", "layer", "source"),
        Index("idx_entity", "entity"),
    )


class MetaColumnCatalog(Base):
    """Detailed documentation for every column in every table."""

    __tablename__ = "meta_column_catalog"

    id = Column(Integer, primary_key=True)

    # Identity
    table_name = Column(String, nullable=False, index=True)
    column_name = Column(String, nullable=False)
    ordinal_position = Column(Integer)  # Order in table

    # Type & Structure
    data_type = Column(String, nullable=False)  # VARCHAR, INTEGER, FLOAT, DATETIME, etc.
    is_nullable = Column(Boolean, nullable=False, default=True)
    is_indexed = Column(Boolean, default=False)
    is_primary_key = Column(Boolean, default=False)

    # Documentation
    description = Column(Text, nullable=False)  # What is this column? (the why, not the what)
    unit = Column(String)  # 'count', 'usd', 'percent', 'timestamp_utc', 'fips_code', etc.

    # Data Quality
    source_of_truth = Column(String)  # Where does it come from?
    valid_range_min = Column(String)  # Example: '0' or '1900-01-01'
    valid_range_max = Column(String)  # Example: '10000000' or '2050-12-31'
    valid_values = Column(Text)  # If enum: 'success,partial,failed' (comma-separated)

    # SLA
    sla_freshness_days = Column(Integer)  # How stale before alerting?
    sla_null_allowed = Column(Boolean, default=False)  # Is NULL expected?

    # Audit
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("table_name", "column_name"),
        Index("idx_table_column", "table_name", "column_name"),
    )


class MetaDataLineage(Base):
    """Tracks how data flows through the system (source → target transformations)."""

    __tablename__ = "meta_data_lineage"

    id = Column(Integer, primary_key=True)

    # Relationship
    source_table = Column(String, nullable=False, index=True)
    source_column = Column(String)  # NULL if entire table is source
    target_table = Column(String, nullable=False, index=True)
    target_column = Column(String)  # NULL if entire table is target

    # Transformation
    transformation = Column(Text)  # SQL or plain English description
    transformation_type = Column(String)  # 'direct', 'aggregation', 'calculation', 'join', 'filter'

    # Metadata
    description = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    deprecated_at = Column(DateTime)  # When was this lineage obsolete?

    __table_args__ = (
        Index("idx_source_target", "source_table", "target_table"),
    )


class MetaJobRun(Base):
    """Log of every scheduled job and manual data collection run."""

    __tablename__ = "meta_job_runs"

    id = Column(Integer, primary_key=True)

    # Identity
    job_id = Column(String, nullable=False, index=True)  # 'qcew_fetch', 'sentiment_score'
    job_type = Column(String, nullable=False)  # 'scraper', 'computation', 'aggregation', 'validation'

    # Execution
    run_timestamp = Column(DateTime, nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)

    # Status
    status = Column(String, nullable=False)  # 'success', 'partial', 'failed'
    error_message = Column(Text)  # If failed, why?

    # Metrics
    rows_processed = Column(Integer)
    rows_inserted = Column(Integer)
    rows_updated = Column(Integer)
    rows_deleted = Column(Integer)
    rows_skipped = Column(Integer)

    # Trigger
    triggered_by = Column(String)  # 'scheduler', 'manual', 'api', 'test'
    triggered_by_user = Column(String)  # Username if manual

    # Source targeting
    region = Column(String)  # If job is region-specific
    source_key = Column(String)  # If job is API-specific (e.g., 'bls_v2')

    # Related data
    api_calls_count = Column(Integer)
    api_errors_count = Column(Integer)

    __table_args__ = (
        Index("idx_job_timestamp", "job_id", "run_timestamp"),
        Index("idx_status", "status"),
    )


class MetaApiCall(Base):
    """DEPRECATED — Use api_request_log + rate_budgets instead.

    This table was created as part of the metadata system but was never
    populated.  The canonical API tracking lives in:
      - api_sources      → registry of all external APIs
      - api_request_log  → per-request log (latency, status, data yield)
      - rate_budgets     → daily usage rollups per source

    Kept for backward compatibility with existing schema; do not add
    new writes to this table.  Will be dropped in a future migration.
    """

    __tablename__ = "meta_api_calls"

    id = Column(Integer, primary_key=True)

    # Identity
    api_source = Column(String, nullable=False, index=True)  # 'bls_v2', 'census_cbp', 'jobspy'
    endpoint = Column(String, nullable=False)
    method = Column(String, default='GET')  # GET, POST, etc.

    # Request
    url = Column(String)
    request_params = Column(Text)  # JSON of params

    # Response
    status_code = Column(Integer)
    success = Column(Boolean, nullable=False)
    response_bytes = Column(Integer)

    # Data
    rows_returned = Column(Integer)

    # Performance
    latency_ms = Column(Integer)

    # Errors
    error_message = Column(Text)

    # Rate limiting
    rate_limit_remaining = Column(Integer)
    rate_limit_reset_at = Column(DateTime)
    rate_limit_reset_seconds = Column(Integer)

    # Timing
    request_timestamp = Column(DateTime, nullable=False, index=True)

    # Related
    job_run_id = Column(Integer)  # FK to meta_job_runs.id (optional)

    __table_args__ = (
        Index("idx_source_timestamp", "api_source", "request_timestamp"),
        Index("idx_success", "success"),
    )
