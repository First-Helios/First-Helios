"""
Populate the metadata catalog with descriptions of all existing tables.

Run this once to seed the metadata system:
  python scripts/populate_metadata.py

This creates entries in:
  - meta_table_catalog (what tables exist?)
  - meta_column_catalog (what columns exist?)
  - meta_data_lineage (how does data flow?)
"""

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

# Add project root
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.database import get_session, init_db
from core.metadata import MetaTableCatalog, MetaColumnCatalog, MetaDataLineage


# ────────────────────────────────────────────────────────────────────────────
# Table Metadata Definitions
# ────────────────────────────────────────────────────────────────────────────

TABLE_METADATA = [
    # BUSINESS LOCATION LAYER
    {
        "table_name": "chain_locations",
        "layer": "business_locations",
        "source": "scrapers",
        "entity": "chain_location",
        "purpose": "Physical chain / franchise locations (Starbucks, Target, CVS, etc.). Discovered via AllThePlaces, Overture, OSM, Google Maps.",
        "owner_team": "Data Engineering",
        "append_only": False,  # Can be updated if location changes
    },
    {
        "table_name": "signals",
        "layer": "operational",
        "source": "scrapers",
        "entity": "observation",
        "purpose": "Raw observations from all data sources (job postings, sentiment, reviews). Foundation of scoring pipeline.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "scores",
        "layer": "business_logic",
        "source": "computed",
        "entity": "staffing_stress_score",
        "purpose": "Composite staffing-stress index per store (0-100). Output of scoring engine.",
        "owner_team": "Analytics",
        "append_only": True,
    },
    {
        "table_name": "wage_index",
        "layer": "operational",
        "source": "scrapers",
        "entity": "wage_observation",
        "purpose": "Job posting wages from all sources (Indeed, LinkedIn, etc.). Used for wage_competitiveness sub-score.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    # GROUND-TRUTH SCHEMA
    {
        "table_name": "qcew_data",
        "layer": "raw",
        "source": "bls",
        "entity": "county_employment",
        "purpose": "Quarterly Census of Employment & Wages from BLS. County-level employment by industry (6-month lag).",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "jolts_data",
        "layer": "raw",
        "source": "bls",
        "entity": "job_openings_turnover",
        "purpose": "Job Openings & Labor Turnover Survey from BLS. National monthly quits, openings, hires rates (2-month lag).",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "laus_data",
        "layer": "raw",
        "source": "bls",
        "entity": "unemployment",
        "purpose": "Local Area Unemployment Statistics from BLS. County monthly unemployment rates (2-month lag).",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "oews_data",
        "layer": "raw",
        "source": "bls",
        "entity": "occupation_wages",
        "purpose": "Occupational Employment & Wage Statistics from BLS. MSA-level wage percentiles by occupation (12-month lag).",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "cbp_data",
        "layer": "raw",
        "source": "census",
        "entity": "zip_establishments",
        "purpose": "Census County Business Patterns. ZIP-level establishment counts (18-month lag).",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    # DERIVED SCHEMA
    {
        "table_name": "labor_market_baseline",
        "layer": "derived",
        "source": "computed",
        "entity": "baseline_metrics",
        "purpose": "Computed baseline combining QCEW+JOLTS+OEWS+LAUS. Used as denominator in all scoring formulas.",
        "owner_team": "Analytics",
        "append_only": True,
    },
    # REFERENCE SCHEMA
    {
        "table_name": "ref_brands",
        "layer": "reference",
        "source": "manual",
        "entity": "brand",
        "purpose": "Brand metadata (Starbucks, Dutch Bros, competitors). Defines what chains we track.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "ref_industry",
        "layer": "reference",
        "source": "manual",
        "entity": "industry",
        "purpose": "NAICS industry hierarchy. Maps industry codes to categories.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "ref_regions",
        "layer": "reference",
        "source": "manual",
        "entity": "region",
        "purpose": "Region definitions (Austin MSA boundary, center, population). Single row per region.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "ref_category_map",
        "layer": "reference",
        "source": "manual",
        "entity": "category_mapping",
        "purpose": "Maps Overture/OSM/NAICS categories to internal industry codes. Reconciles diverse taxonomies.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    # METADATA SCHEMA
    {
        "table_name": "api_sources",
        "layer": "metadata",
        "source": "manual",
        "entity": "api_registry",
        "purpose": "Registry of all external APIs with rate limits and auth. Configuration layer.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "api_endpoints",
        "layer": "metadata",
        "source": "manual",
        "entity": "adapter_config",
        "purpose": "Specific adapter configs with health tracking. One per scraper/adapter.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "api_request_log",
        "layer": "metadata",
        "source": "automatic",
        "entity": "http_request",
        "purpose": "HTTP request telemetry for every external call. Debug and rate-limit tracking.",
        "owner_team": "DevOps",
        "append_only": True,
    },
    {
        "table_name": "rate_budgets",
        "layer": "metadata",
        "source": "automatic",
        "entity": "rate_limit_budget",
        "purpose": "Daily quota rollup per API source. Alerts when approaching limits.",
        "owner_team": "DevOps",
        "append_only": False,
    },
    {
        "table_name": "source_freshness",
        "layer": "metadata",
        "source": "automatic",
        "entity": "data_freshness",
        "purpose": "Data staleness tracking. Alerts when data hasn't updated in >N days.",
        "owner_team": "DevOps",
        "append_only": False,
    },
    {
        "table_name": "snapshots",
        "layer": "metadata",
        "source": "automatic",
        "entity": "period_summary",
        "purpose": "Periodic scan summaries. Used for dashboard charts and trend analysis.",
        "owner_team": "Analytics",
        "append_only": True,
    },
    {
        "table_name": "store_aliases",
        "layer": "reference",
        "source": "manual",
        "entity": "store_deduplication",
        "purpose": "Store ID deduplication log. Tracks when duplicate store entries are merged.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "local_employers",
        "layer": "business_locations",
        "source": "scrapers",
        "entity": "non_chain_employer",
        "purpose": "Local businesses with 1-10 locations. Populated by Overture/OSM. Local labor market context.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    # METADATA SCHEMA — self-describing
    {
        "table_name": "meta_table_catalog",
        "layer": "metadata",
        "source": "manual",
        "entity": "table_registry",
        "purpose": "Registry of every table with purpose, ownership, and SLA. The master index.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "meta_column_catalog",
        "layer": "metadata",
        "source": "manual",
        "entity": "column_registry",
        "purpose": "Documentation for every column in every table. Includes valid ranges and SLAs.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "meta_data_lineage",
        "layer": "metadata",
        "source": "manual",
        "entity": "data_flow",
        "purpose": "Tracks data flow from source to target tables. Used for impact analysis.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "meta_job_runs",
        "layer": "metadata",
        "source": "automatic",
        "entity": "job_log",
        "purpose": "Log of every scraper / computation job run. Status, duration, rows affected.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "meta_api_calls",
        "layer": "metadata",
        "source": "automatic",
        "entity": "api_request_deprecated",
        "purpose": "DEPRECATED — use api_request_log instead. Legacy API call tracking table, never populated.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    # ── SPIRITPOOL CONTRIBUTOR PIPELINE (FH-0) ───────────────────────────────
    {
        "table_name": "sp_events",
        "layer": "operational",
        "source": "spiritpool",
        "entity": "contributor_signal",
        "purpose": "Forward-compatible signal storage from SpiritPool contributors. Stores job listings, salary signals, business reviews, and event listings via POST /api/contribute.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "quarantine",
        "layer": "metadata",
        "source": "spiritpool",
        "entity": "pii_quarantine",
        "purpose": "PII-flagged payloads held for internal audit. Events matching email/phone/SSN/credit card patterns land here instead of sp_events. Never queryable by external APIs or dashboards.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "session_epochs",
        "layer": "operational",
        "source": "spiritpool",
        "entity": "session_lifecycle",
        "purpose": "Tracks SpiritPool session token lifecycle — creation, contributor linkage, and burn state. Auto-created on first POST per session_token.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
    {
        "table_name": "burn_pool",
        "layer": "operational",
        "source": "spiritpool",
        "entity": "burn_aggregate",
        "purpose": "Monthly aggregate of burned SpiritPool sessions. 1-year TTL enforced by daily maintenance job. No per-session burn records.",
        "owner_team": "Data Engineering",
        "append_only": True,
    },
    {
        "table_name": "contributors",
        "layer": "operational",
        "source": "spiritpool",
        "entity": "anonymous_contributor",
        "purpose": "Anonymous contributor volume tracking. UUID is extension-generated opaque identity. No PII stored. total_signals tracks volume only.",
        "owner_team": "Data Engineering",
        "append_only": False,
    },
]

# ────────────────────────────────────────────────────────────────────────────
# Column Metadata Definitions (Sample - Most Important Ones)
# ────────────────────────────────────────────────────────────────────────────

COLUMN_METADATA = [
    # chain_locations table
    {
        "table_name": "chain_locations",
        "column_name": "store_num",
        "data_type": "VARCHAR",
        "is_primary_key": True,
        "description": "Unique identifier for physical chain location (format: {brand_key}-{location_id})",
        "unit": "store_code",
        "source_of_truth": "AllThePlaces / Overture / OSM / Google Maps",
        "valid_range_min": None,
        "valid_range_max": None,
        "sla_freshness_days": 7,
    },
    {
        "table_name": "chain_locations",
        "column_name": "brand_key",
        "data_type": "VARCHAR",
        "description": "FK to ref_brands.brand_key — identifies which chain brand this location belongs to",
        "unit": "brand_code",
        "source_of_truth": "ref_brands",
        "sla_freshness_days": 30,
    },
    {
        "table_name": "chain_locations",
        "column_name": "source_discovery",
        "data_type": "VARCHAR",
        "description": "How this location was discovered (alltheplaces, overture, osm, gmaps, jobspy)",
        "unit": "enum",
        "valid_values": "alltheplaces,overture,osm,gmaps,jobspy",
        "sla_freshness_days": 30,
    },
    {
        "table_name": "chain_locations",
        "column_name": "lat",
        "data_type": "FLOAT",
        "description": "Location latitude in decimal degrees",
        "unit": "degrees",
        "source_of_truth": "Geocoding from address",
        "valid_range_min": "-90",
        "valid_range_max": "90",
        "sla_freshness_days": 30,
        "sla_null_allowed": True,
    },
    {
        "table_name": "chain_locations",
        "column_name": "lng",
        "data_type": "FLOAT",
        "description": "Location longitude in decimal degrees",
        "unit": "degrees",
        "source_of_truth": "Geocoding from address",
        "valid_range_min": "-180",
        "valid_range_max": "180",
        "sla_freshness_days": 30,
        "sla_null_allowed": True,
    },
    # signals table
    {
        "table_name": "signals",
        "column_name": "value",
        "data_type": "FLOAT",
        "description": "Normalized observation value (0-1 for most; raw numeric for wages)",
        "unit": "varies",
        "source_of_truth": "Signal source (careers API, reddit, jobspy, etc.)",
        "valid_range_min": "0",
        "valid_range_max": "1",
        "sla_freshness_days": 1,
    },
    {
        "table_name": "signals",
        "column_name": "observed_at",
        "data_type": "DATETIME",
        "description": "When the external source published this observation (not when we fetched)",
        "unit": "timestamp_utc",
        "source_of_truth": "Metadata from source",
        "sla_freshness_days": 1,
    },
    # scores table
    {
        "table_name": "scores",
        "column_name": "value",
        "data_type": "FLOAT",
        "description": "Staffing stress score or sub-score (0-100 scale)",
        "unit": "percent_equivalent",
        "source_of_truth": "Scoring engine computation",
        "valid_range_min": "0",
        "valid_range_max": "100",
        "sla_freshness_days": 1,
    },
    # QCEW table
    {
        "table_name": "qcew_data",
        "column_name": "establishments",
        "data_type": "INTEGER",
        "description": "Number of active employer locations in county/NAICS/quarter",
        "unit": "count",
        "source_of_truth": "BLS QCEW Survey",
        "valid_range_min": "0",
        "valid_range_max": "100000",
        "sla_freshness_days": 180,
    },
    {
        "table_name": "qcew_data",
        "column_name": "avg_weekly_wage",
        "data_type": "FLOAT",
        "description": "Average weekly wage paid in county/NAICS/quarter",
        "unit": "usd",
        "source_of_truth": "BLS QCEW Survey",
        "valid_range_min": "0",
        "valid_range_max": "10000",
        "sla_freshness_days": 180,
    },
    # JOLTS table
    {
        "table_name": "jolts_data",
        "column_name": "value",
        "data_type": "FLOAT",
        "description": "Job market rate (quits %, openings %, hires %, separations %)",
        "unit": "percent",
        "source_of_truth": "BLS JOLTS Survey",
        "valid_range_min": "0",
        "valid_range_max": "10",
        "sla_freshness_days": 60,
    },
    # Labor market baseline
    {
        "table_name": "labor_market_baseline",
        "column_name": "establishment_count",
        "data_type": "INTEGER",
        "description": "Regional establishment count used as denominator for demand_pressure scoring",
        "unit": "count",
        "source_of_truth": "QCEW aggregate",
        "valid_range_min": "0",
        "valid_range_max": "100000",
        "sla_freshness_days": 180,
    },
    # ── SPIRITPOOL: sp_events columns ─────────────────────────────────────────
    {
        "table_name": "sp_events",
        "column_name": "event_id",
        "data_type": "VARCHAR",
        "is_primary_key": True,
        "description": "Server-generated UUID primary key for each contributor signal event",
        "unit": "uuid",
        "source_of_truth": "Server (uuid4)",
    },
    {
        "table_name": "sp_events",
        "column_name": "session_token",
        "data_type": "TEXT",
        "description": "Opaque session token from SpiritPool extension. No length/format constraint — accepts UUID and 64-char hex",
        "unit": "opaque_token",
        "source_of_truth": "SpiritPool extension",
        "sla_null_allowed": False,
    },
    {
        "table_name": "sp_events",
        "column_name": "epoch_id",
        "data_type": "INTEGER",
        "description": "Consent version counter from SpiritPool extension. Starts at 1, increments on token rotation. No upper bound",
        "unit": "counter",
        "source_of_truth": "SpiritPool extension",
        "valid_range_min": "1",
        "sla_null_allowed": False,
    },
    {
        "table_name": "sp_events",
        "column_name": "event_type",
        "data_type": "VARCHAR",
        "description": "Signal type classification: job_listing, salary_signal, business_review, or event_listing",
        "unit": "enum",
        "valid_values": "job_listing,salary_signal,business_review,event_listing",
        "source_of_truth": "SpiritPool extension",
    },
    {
        "table_name": "sp_events",
        "column_name": "payload",
        "data_type": "JSONB",
        "description": "Structured extraction data from content script. Fields vary by source. Unknown future fields preserved without error",
        "unit": "json",
        "source_of_truth": "SpiritPool extension content scripts",
    },
    {
        "table_name": "sp_events",
        "column_name": "source_type",
        "data_type": "VARCHAR",
        "description": "Origin type of the signal, default 'extension' for SpiritPool browser extension",
        "unit": "enum",
        "valid_values": "extension",
        "source_of_truth": "Server default",
    },
    {
        "table_name": "sp_events",
        "column_name": "collected_at",
        "data_type": "DATETIME",
        "description": "Server-set timestamp when event was received. Never from client. Replaces stripped collectedAt",
        "unit": "timestamp_utc",
        "source_of_truth": "Server (NOW)",
        "sla_freshness_days": 3,
        "sla_null_allowed": False,
    },
    {
        "table_name": "sp_events",
        "column_name": "pipeline_version",
        "data_type": "INTEGER",
        "description": "PII rule version that processed this event. Enables re-processing old events through future NER pipeline",
        "unit": "version",
        "source_of_truth": "Server (set at ingest)",
        "valid_range_min": "1",
    },
    # ── SPIRITPOOL: quarantine columns ────────────────────────────────────────
    {
        "table_name": "quarantine",
        "column_name": "quarantine_id",
        "data_type": "VARCHAR",
        "is_primary_key": True,
        "description": "Server-generated UUID for quarantined payload",
        "unit": "uuid",
        "source_of_truth": "Server (uuid4)",
    },
    {
        "table_name": "quarantine",
        "column_name": "original_payload",
        "data_type": "JSONB",
        "description": "Complete original event body as received, before any processing. For audit re-evaluation only",
        "unit": "json",
        "source_of_truth": "SpiritPool POST body",
    },
    {
        "table_name": "quarantine",
        "column_name": "redaction_types",
        "data_type": "TEXT",
        "description": "JSON array of PII pattern types that triggered quarantine, e.g. [\"email\",\"phone\"]",
        "unit": "json_array",
        "source_of_truth": "PII detection engine",
    },
    {
        "table_name": "quarantine",
        "column_name": "rule_version",
        "data_type": "INTEGER",
        "description": "PII rule version that flagged this payload. Enables re-evaluation when rules improve",
        "unit": "version",
        "source_of_truth": "Server (pipeline_version at time of quarantine)",
        "valid_range_min": "1",
    },
    {
        "table_name": "quarantine",
        "column_name": "quarantined_at",
        "data_type": "DATETIME",
        "description": "Server timestamp when payload was quarantined",
        "unit": "timestamp_utc",
        "source_of_truth": "Server (NOW)",
    },
    # ── SPIRITPOOL: session_epochs columns ────────────────────────────────────
    {
        "table_name": "session_epochs",
        "column_name": "id",
        "data_type": "INTEGER",
        "is_primary_key": True,
        "description": "Auto-increment primary key for session epoch records",
        "unit": "id",
        "source_of_truth": "Database sequence",
    },
    {
        "table_name": "session_epochs",
        "column_name": "session_token",
        "data_type": "TEXT",
        "description": "Unique session token (one row per token). Matches sp_events.session_token via text match, not FK",
        "unit": "opaque_token",
        "source_of_truth": "SpiritPool extension",
    },
    {
        "table_name": "session_epochs",
        "column_name": "epoch_id",
        "data_type": "INTEGER",
        "description": "Consent epoch at time of session creation",
        "unit": "counter",
        "source_of_truth": "SpiritPool extension",
        "valid_range_min": "1",
    },
    {
        "table_name": "session_epochs",
        "column_name": "contributor_id",
        "data_type": "INTEGER",
        "description": "FK to contributors.id. Set to NULL on burn (deliberate data loss for privacy)",
        "unit": "fk",
        "source_of_truth": "Contributor registration or NULL",
        "sla_null_allowed": True,
    },
    {
        "table_name": "session_epochs",
        "column_name": "created_at",
        "data_type": "DATETIME",
        "description": "When this session epoch was first created (auto on first POST for token)",
        "unit": "timestamp_utc",
        "source_of_truth": "Server (NOW)",
    },
    {
        "table_name": "session_epochs",
        "column_name": "burned_at",
        "data_type": "DATETIME",
        "description": "When contributor burned this session. NULL while active",
        "unit": "timestamp_utc",
        "source_of_truth": "Burn endpoint",
        "sla_null_allowed": True,
    },
    # ── SPIRITPOOL: burn_pool columns ─────────────────────────────────────────
    {
        "table_name": "burn_pool",
        "column_name": "id",
        "data_type": "INTEGER",
        "is_primary_key": True,
        "description": "Auto-increment primary key for burn pool records",
        "unit": "id",
        "source_of_truth": "Database sequence",
    },
    {
        "table_name": "burn_pool",
        "column_name": "month_key",
        "data_type": "VARCHAR",
        "description": "Month of burn aggregation in YYYY-MM format",
        "unit": "year_month",
        "source_of_truth": "Burn endpoint (current month)",
    },
    {
        "table_name": "burn_pool",
        "column_name": "signal_count",
        "data_type": "INTEGER",
        "description": "Number of signals burned in this month. Incremented on each burn operation",
        "unit": "count",
        "source_of_truth": "Burn endpoint",
        "valid_range_min": "0",
    },
    {
        "table_name": "burn_pool",
        "column_name": "burned_at",
        "data_type": "DATETIME",
        "description": "Timestamp of the burn operation that created/updated this record",
        "unit": "timestamp_utc",
        "source_of_truth": "Server (NOW)",
    },
    {
        "table_name": "burn_pool",
        "column_name": "expires_at",
        "data_type": "DATETIME",
        "description": "Expiry timestamp (burned_at + 1 year). Records deleted by daily maintenance job after this date",
        "unit": "timestamp_utc",
        "source_of_truth": "Server (burned_at + 1 year)",
    },
    # ── SPIRITPOOL: contributors columns ──────────────────────────────────────
    {
        "table_name": "contributors",
        "column_name": "id",
        "data_type": "INTEGER",
        "is_primary_key": True,
        "description": "Auto-increment primary key for contributor records",
        "unit": "id",
        "source_of_truth": "Database sequence",
    },
    {
        "table_name": "contributors",
        "column_name": "uuid",
        "data_type": "TEXT",
        "description": "Per-install anonymous identity from SpiritPool extension. Opaque, no PII. Unique constraint enforced",
        "unit": "opaque_id",
        "source_of_truth": "SpiritPool extension",
    },
    {
        "table_name": "contributors",
        "column_name": "total_signals",
        "data_type": "INTEGER",
        "description": "Running count of signals contributed. Incremented on each successful ingest",
        "unit": "count",
        "source_of_truth": "Intake endpoint counter",
        "valid_range_min": "0",
    },
    {
        "table_name": "contributors",
        "column_name": "created_at",
        "data_type": "DATETIME",
        "description": "When this contributor was first registered",
        "unit": "timestamp_utc",
        "source_of_truth": "Server (NOW)",
    },
]

# ────────────────────────────────────────────────────────────────────────────
# Data Lineage Definitions
# ────────────────────────────────────────────────────────────────────────────

LINEAGE_METADATA = [
    {
        "source_table": "qcew_data",
        "source_column": None,
        "target_table": "labor_market_baseline",
        "target_column": None,
        "transformation_type": "aggregation",
        "transformation": "Aggregate QCEW by region and NAICS; compute 4-quarter average employment",
        "description": "County employment counts feed into regional baseline",
    },
    {
        "source_table": "jolts_data",
        "source_column": None,
        "target_table": "labor_market_baseline",
        "target_column": None,
        "transformation_type": "join",
        "transformation": "Join JOLTS quits rate by industry; multiply by expected employment",
        "description": "National quit rates provide churn expectations per region",
    },
    {
        "source_table": "oews_data",
        "source_column": "wage_median_hourly",
        "target_table": "labor_market_baseline",
        "target_column": "occupation_median_wage",
        "transformation_type": "direct",
        "transformation": "Map OEWS occupation median to region baseline",
        "description": "Wage percentiles become wage_competitiveness benchmark",
    },
    {
        "source_table": "labor_market_baseline",
        "source_column": None,
        "target_table": "scores",
        "target_column": None,
        "transformation_type": "calculation",
        "transformation": "Scoring engine uses baseline metrics as denominators in formula computation",
        "description": "Baseline denominators → final staffing stress score",
    },
    {
        "source_table": "signals",
        "source_column": None,
        "target_table": "scores",
        "target_column": None,
        "transformation_type": "aggregation",
        "transformation": "Aggregate signals per store; weight by freshness; compute 4 sub-scores",
        "description": "Raw signals → scoring metrics",
    },
    {
        "source_table": "laus_data",
        "source_column": "unemployment_rate",
        "target_table": "labor_market_baseline",
        "target_column": "unemployment_rate",
        "transformation_type": "direct",
        "transformation": "Map LAUS county unemployment rate to region baseline",
        "description": "Local unemployment rate feeds labor market tightness baseline",
    },
    {
        "source_table": "wage_index",
        "source_column": None,
        "target_table": "scores",
        "target_column": "value",
        "transformation_type": "calculation",
        "transformation": "Compare store wage postings vs OEWS occupation median via wage_index table",
        "description": "wage_index observed wages → wage_competitiveness sub-score",
    },
    {
        "source_table": "chain_locations",
        "source_column": "store_num",
        "target_table": "signals",
        "target_column": "store_num",
        "transformation_type": "join",
        "transformation": "FK join: signals.store_num references chain_locations.store_num",
        "description": "Each signal is linked to a physical chain location",
    },
    {
        "source_table": "chain_locations",
        "source_column": "store_num",
        "target_table": "scores",
        "target_column": "store_num",
        "transformation_type": "join",
        "transformation": "FK join: scores.store_num references chain_locations.store_num",
        "description": "Each score is computed for a specific chain location",
    },
    {
        "source_table": "ref_brands",
        "source_column": "brand_key",
        "target_table": "chain_locations",
        "target_column": "brand_key",
        "transformation_type": "join",
        "transformation": "FK: chain_locations.brand_key references ref_brands.brand_key",
        "description": "Brand taxonomy enriches each chain location with industry and metadata",
    },
    {
        "source_table": "ref_category_map",
        "source_column": "internal_industry",
        "target_table": "chain_locations",
        "target_column": "industry",
        "transformation_type": "calculation",
        "transformation": "Map Overture/OSM/NAICS category → internal industry via ref_category_map",
        "description": "Category mapping normalizes diverse source taxonomies to internal industry codes",
    },
    {
        "source_table": "cbp_data",
        "source_column": None,
        "target_table": "labor_market_baseline",
        "target_column": None,
        "transformation_type": "aggregation",
        "transformation": "ZIP-level CBP establishment counts aggregated to region-level baseline",
        "description": "Census CBP provides sub-metro establishment density data",
    },
    # ── SPIRITPOOL LINEAGE (FH-0) ────────────────────────────────────────────
    {
        "source_table": "spiritpool_post",
        "source_column": None,
        "target_table": "sp_events",
        "target_column": None,
        "transformation_type": "direct",
        "transformation": "POST /api/contribute → validate → strip tabUrl/collectedAt → set server fields → insert if clean",
        "description": "SpiritPool contributor signals flow to sp_events after field stripping and PII check",
    },
    {
        "source_table": "spiritpool_post",
        "source_column": None,
        "target_table": "quarantine",
        "target_column": None,
        "transformation_type": "filter",
        "transformation": "POST /api/contribute → PII regex scan → quarantine if email/phone/SSN/credit card detected",
        "description": "PII-flagged contributor payloads route to quarantine instead of sp_events",
    },
    {
        "source_table": "sp_events",
        "source_column": "session_token",
        "target_table": "session_epochs",
        "target_column": "session_token",
        "transformation_type": "direct",
        "transformation": "Auto-create session_epochs row on first POST for a given session_token",
        "description": "Session epoch auto-created when new session token first appears in contributor data",
    },
    {
        "source_table": "session_epochs",
        "source_column": "contributor_id",
        "target_table": "contributors",
        "target_column": "id",
        "transformation_type": "join",
        "transformation": "FK: session_epochs.contributor_id references contributors.id (set NULL on burn)",
        "description": "Session epochs link to anonymous contributor records for volume tracking",
    },
    {
        "source_table": "burn_endpoint",
        "source_column": None,
        "target_table": "burn_pool",
        "target_column": None,
        "transformation_type": "aggregation",
        "transformation": "POST /api/burn → NULL contributor_id on session_epochs → increment burn_pool monthly signal_count",
        "description": "Burn operations aggregate into monthly burn pool records with 1-year TTL",
    },
    {
        "source_table": "sp_events",
        "source_column": None,
        "target_table": "scores",
        "target_column": None,
        "transformation_type": "calculation",
        "transformation": "Contributor signals from sp_events feed into scoring pipeline alongside automated collector data",
        "description": "SpiritPool events contribute to staffing stress scores via scoring engine",
    },
]


def populate_table_catalog(session: Session) -> None:
    """Populate meta_table_catalog with all table metadata."""
    print("Populating meta_table_catalog...")

    for meta in TABLE_METADATA:
        # Check if already exists
        existing = session.query(MetaTableCatalog).filter_by(
            table_name=meta["table_name"]
        ).first()

        if existing:
            print(f"  ✓ {meta['table_name']} (already exists)")
            continue

        record = MetaTableCatalog(
            table_name=meta["table_name"],
            layer=meta["layer"],
            source=meta["source"],
            entity=meta["entity"],
            purpose=meta["purpose"],
            owner_team=meta.get("owner_team"),
            append_only=meta.get("append_only", True),
            created_at=datetime.utcnow(),
        )
        session.add(record)
        print(f"  + {meta['table_name']}")

    session.commit()
    print(f"✓ {len(TABLE_METADATA)} tables documented\n")


def populate_column_catalog(session: Session) -> None:
    """Populate meta_column_catalog with column metadata."""
    print("Populating meta_column_catalog...")

    for meta in COLUMN_METADATA:
        # Check if already exists
        existing = session.query(MetaColumnCatalog).filter_by(
            table_name=meta["table_name"],
            column_name=meta["column_name"],
        ).first()

        if existing:
            print(f"  ✓ {meta['table_name']}.{meta['column_name']} (already exists)")
            continue

        record = MetaColumnCatalog(
            table_name=meta["table_name"],
            column_name=meta["column_name"],
            data_type=meta["data_type"],
            is_primary_key=meta.get("is_primary_key", False),
            description=meta["description"],
            unit=meta.get("unit"),
            source_of_truth=meta.get("source_of_truth"),
            valid_range_min=meta.get("valid_range_min"),
            valid_range_max=meta.get("valid_range_max"),
            sla_freshness_days=meta.get("sla_freshness_days"),
            sla_null_allowed=meta.get("sla_null_allowed", False),
            created_at=datetime.utcnow(),
        )
        session.add(record)
        print(f"  + {meta['table_name']}.{meta['column_name']}")

    session.commit()
    print(f"✓ {len(COLUMN_METADATA)} columns documented\n")


def populate_data_lineage(session: Session) -> None:
    """Populate meta_data_lineage with data flow information."""
    print("Populating meta_data_lineage...")

    for meta in LINEAGE_METADATA:
        # Check if already exists
        existing = session.query(MetaDataLineage).filter_by(
            source_table=meta["source_table"],
            target_table=meta["target_table"],
        ).first()

        if existing:
            print(f"  ✓ {meta['source_table']} → {meta['target_table']} (already exists)")
            continue

        record = MetaDataLineage(
            source_table=meta["source_table"],
            source_column=meta.get("source_column"),
            target_table=meta["target_table"],
            target_column=meta.get("target_column"),
            transformation_type=meta["transformation_type"],
            transformation=meta["transformation"],
            description=meta["description"],
            created_at=datetime.utcnow(),
        )
        session.add(record)
        print(f"  + {meta['source_table']} → {meta['target_table']}")

    session.commit()
    print(f"✓ {len(LINEAGE_METADATA)} lineages documented\n")


def main() -> None:
    """Initialize database and populate metadata tables."""
    print("=" * 80)
    print("METADATA CATALOG INITIALIZATION")
    print("=" * 80)
    print()

    # Initialize DB (creates metadata tables if they don't exist)
    engine = init_db()
    session = get_session(engine)

    try:
        populate_table_catalog(session)
        populate_column_catalog(session)
        populate_data_lineage(session)

        print("=" * 80)
        print("✓ METADATA CATALOG POPULATED")
        print("=" * 80)
        print()
        print("Next steps:")
        print("  1. Query: SELECT * FROM meta_table_catalog;")
        print("  2. Run: python scripts/generate_health_dashboard.py")
        print("  3. Review: docs/SYSTEM_HEALTH.md")

    finally:
        session.close()


if __name__ == "__main__":
    main()
