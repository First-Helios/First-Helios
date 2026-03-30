# Database Design for Long-Term Multi-Source Data Projects

**A comprehensive guide for building maintainable, understandable data systems.**

---

## Part 1: Foundational Principles

### 1.1 The Core Problem

When an AI agent codes your system, you face **three critical challenges:**

1. **Unknown unknowns** — You don't know what patterns the agent established
2. **Hidden complexity** — Features exist that you're unaware of
3. **Maintenance burden** — You can't modify what you don't understand

**Solution:** Build for human understanding first, optimization second.

---

### 1.2 The Golden Rules

**Rule 1: One Source of Truth Per Data Point**
- Each fact should come from exactly one authoritative source
- Multiple sources = different tables, not duplicates
- Example: Employment count comes from QCEW, not both QCEW and BLS API

**Rule 2: Immutable Audit Trail**
- Never update historical data; only append
- Keep timestamps for everything (when observed, when fetched, when computed)
- Track data lineage (where did this come from?)

**Rule 3: Explicit Over Implicit**
- Column names should be self-documenting
- No abbreviations unless universally known
- Document *why* a column exists, not just *what* it contains

**Rule 4: Schemas Are Contracts**
- Database schema is a promise to future developers (including you)
- Breaking changes = migration cost
- Design for 5 years ahead, not 5 days

**Rule 5: Humans Must Understand Before Machines Run**
- If you can't explain it in plain English, it's too complex
- Every table should have a 2-sentence purpose statement
- Every column should have a clear unit (%, USD, count, timestamp format)

---

## Part 2: Database Organization Strategy

### 2.1 Schema Layers (Separation of Concerns)

Organize your database into **logical layers**, not physical schemas (though you can use both):

```
┌─────────────────────────────────────────────────────┐
│ LAYER 1: RAW DATA (External Sources)                │
│ ├─ [BLS Tables] qcew_data, jolts_data, laus_data   │
│ ├─ [Census] cbp_data, acs_data                      │
│ ├─ [Job Boards] jobspy_listings, careers_postings   │
│ └─ [Custom Scrapers] reddit_posts, google_reviews   │
│                                                      │
│ PRINCIPLE: Append-only, immutable, timestamped      │
│ Purpose: Store exactly what external systems gave us│
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│ LAYER 2: SIGNALS (Normalized Observations)          │
│ ├─ signals (raw observations from all sources)      │
│ └─ signals_parsed (cleaned, standardized)           │
│                                                      │
│ PRINCIPLE: Single observation model across all      │
│ Purpose: Normalize diverse inputs into one format   │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│ LAYER 3: DERIVED DATA (Computed/Transformed)        │
│ ├─ labor_market_baseline (computed from layer 1)    │
│ ├─ store_statistics (aggregated from signals)       │
│ └─ regional_metrics (aggregated from baselines)     │
│                                                      │
│ PRINCIPLE: Reproducible, re-computable, logged      │
│ Purpose: Combine sources into interpretable metrics │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│ LAYER 4: BUSINESS LOGIC (Scoring/Analysis)          │
│ ├─ scores (staffing stress scores per store)        │
│ ├─ reports (executive summaries)                    │
│ └─ alerts (anomalies, trends)                       │
│                                                      │
│ PRINCIPLE: Immutable outputs, version tracked       │
│ Purpose: Final answers that drive decisions         │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│ LAYER 5: REFERENCE DATA (Master Data)               │
│ ├─ ref_brands, ref_regions, ref_industry            │
│ ├─ geographic_boundaries (ZIPs, counties)           │
│ └─ taxonomies (occupation codes, industry codes)    │
│                                                      │
│ PRINCIPLE: Slowly changing, versioned, audited      │
│ Purpose: Dimension tables for joins & filtering     │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│ LAYER 6: METADATA (System Intelligence)             │
│ ├─ table_catalog (what tables exist & why)          │
│ ├─ column_catalog (what each column is & SLA)       │
│ ├─ data_lineage (where did this come from?)         │
│ ├─ job_history (what jobs ran, when, success?)      │
│ └─ api_metrics (request logs, rate limits, health)  │
│                                                      │
│ PRINCIPLE: Never delete, comprehensive logging      │
│ Purpose: Understand your own system                 │
└─────────────────────────────────────────────────────┘
```

**Why this matters:**
- **Traceability:** You can follow any fact back to its source
- **Reproducibility:** You can recalculate anything from Layer 1 data
- **Resilience:** If Layer 4 breaks, you fix it; Layer 1 is untouched
- **Understanding:** New developers see exactly how data flows

---

### 2.2 Table Naming Conventions

**Convention: `[layer]_[source]_[entity]` or `[layer]_[entity]_[source]`**

**Examples:**

```
RAW LAYER (External sources, append-only):
  raw_bls_qcew_county_employment
  raw_census_cbp_zip_establishments
  raw_jobspy_postings_indeed
  raw_reddit_posts_astaffing

SIGNALS LAYER (Normalized observations):
  signals (denormalized, all sources)
  signals_job_posting
  signals_sentiment_reddit
  signals_wage_observation

DERIVED LAYER (Computed):
  derived_labor_baseline_monthly
  derived_store_statistics_daily
  derived_regional_metrics_quarterly

BUSINESS LOGIC LAYER (Outputs):
  scores_staffing_stress_store
  scores_wage_competitiveness_store
  reports_executive_summary_weekly

REFERENCE LAYER (Master data):
  ref_brands (Starbucks, Dutch Bros)
  ref_naics_hierarchy (industry taxonomy)
  ref_geographic_boundaries (ZIPs, counties)

METADATA LAYER (System tracking):
  meta_table_catalog (what tables exist?)
  meta_column_catalog (what columns exist?)
  meta_job_runs (when did jobs run?)
  meta_api_requests (who called what API?)
```

**Benefits:**
- Table name tells you: layer, source, entity
- Easy to filter in queries: `SELECT * FROM raw_*` = all raw data
- Easy to trace: `signals_wage_observation` clearly comes from wage signals
- IDE autocomplete helps you discover available tables

---

### 2.3 Column Naming & Documentation

**Convention: `[entity]_[measurement]_[unit]` with required documentation**

**Examples:**

```
❌ POOR:
  col1 (what is this?)
  value (value of what?)
  ts (timestamp in what timezone?)
  id (id of what?)

✅ GOOD:
  store_id (which store?)
  employment_count_persons (how many people?)
  wage_median_usd_hourly (wage in what unit?)
  observation_timestamp_utc (when, in what timezone?)
  fetch_timestamp_utc (when did we fetch this data?)
  computed_timestamp_utc (when did we compute this?)
  data_source_key (where did it come from?)
```

**Required Documentation:**

Every column must have a **data card** in the data dictionary:

```markdown
### employment_count_persons

**Type:** INTEGER (NOT NULL for certain data sources)

**Unit:** Count of people (FTE if applicable, note in metadata)

**Source:**
  - BLS QCEW for official data
  - Revelio Labs for alternative
  - JobSpy aggregation for posting data

**Nullable When:**
  - Data not yet fetched
  - Source API returned NULL
  - Geographic resolution too fine (privacy)

**Valid Range:**
  - Min: 0
  - Max: 10,000,000 (US workforce)
  - Outliers: Flag if > 1,000,000 in single county

**SLA (Service Level Agreement):**
  - Should be populated within 7 days of observation
  - Refresh: Monthly (QCEW), Real-time (JobSpy)
  - Lag: 6 months (QCEW), 2 days (JobSpy)

**Example Values:**
  - 8,234 (Travis County, Q3 2025, QCEW)
  - 1,318 (Feb 2026, wage_index table from postings)

**Computation Logic (if derived):**
  - If this is computed: `employment_count = month1_emp + month2_emp + month3_emp / 3`
  - If this is observed: None (raw data)

**Related Columns:**
  - Links to: `wage_index.employment` (alternative source)
  - Compared against: `baseline_employment.expected`
```

---

## Part 3: Tracking Data & Understanding Your System

### 3.1 The Metadata Layer (Most Important)

You **must** track metadata to understand what happened:

**Table 1: `meta_table_catalog`**
```sql
CREATE TABLE meta_table_catalog (
  table_name VARCHAR,
  layer VARCHAR,  -- 'raw', 'signals', 'derived', 'business', 'reference', 'metadata'
  source VARCHAR,  -- 'bls', 'census', 'jobspy', 'reddit', 'computed', 'manual'
  entity VARCHAR,  -- 'employment', 'wage', 'store', 'score'
  purpose TEXT,  -- 2-sentence explanation

  row_count_estimate INT,
  row_count_checked_at TIMESTAMP,

  append_only BOOLEAN,  -- Can rows be updated? (should be false for raw/signals)
  retention_days INT,  -- How long to keep rows? (NULL = forever)

  owner_team VARCHAR,  -- Who maintains this?
  documentation_url VARCHAR,  -- Link to data dictionary

  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

**Table 2: `meta_column_catalog`**
```sql
CREATE TABLE meta_column_catalog (
  table_name VARCHAR,
  column_name VARCHAR,
  data_type VARCHAR,

  description TEXT,  -- What is this? (not what is it called)
  unit VARCHAR,  -- 'count', 'usd', 'percent', 'timestamp_utc', etc.

  is_nullable BOOLEAN,
  is_indexed BOOLEAN,
  is_primary_key BOOLEAN,

  source_of_truth VARCHAR,  -- Where does it come from?
  valid_range_min VARCHAR,  -- Example: '0' or '1900-01-01'
  valid_range_max VARCHAR,  -- Example: '10000000' or '2050-12-31'

  sla_freshness_days INT,  -- How stale before alerting?
  sla_null_allowed BOOLEAN,  -- Is NULL expected?

  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

**Table 3: `meta_data_lineage`**
```sql
CREATE TABLE meta_data_lineage (
  id INT PRIMARY KEY,
  source_table VARCHAR,
  source_column VARCHAR,
  target_table VARCHAR,
  target_column VARCHAR,

  transformation TEXT,  -- How did data change? SQL or description

  created_at TIMESTAMP,
  deprecated_at TIMESTAMP  -- When was this lineage obsolete?
);
```

**Table 4: `meta_job_runs`**
```sql
CREATE TABLE meta_job_runs (
  job_id VARCHAR,  -- 'qcew_fetch', 'sentiment_score', 'baseline_compute'
  run_timestamp TIMESTAMP,

  status VARCHAR,  -- 'success', 'partial', 'failed'
  rows_processed INT,
  rows_inserted INT,
  rows_updated INT,

  error_message TEXT,  -- If failed, why?

  duration_seconds INT,

  started_at TIMESTAMP,
  completed_at TIMESTAMP,

  triggered_by VARCHAR  -- 'scheduler', 'manual', 'api', 'test'
);
```

**Table 5: `meta_api_calls`**
```sql
CREATE TABLE meta_api_calls (
  id INT PRIMARY KEY,
  api_source VARCHAR,  -- 'bls_v2', 'census_cbp', 'jobspy'
  endpoint VARCHAR,

  status_code INT,
  success BOOLEAN,

  rows_returned INT,
  response_bytes INT,

  latency_ms INT,

  error_message TEXT,

  request_timestamp TIMESTAMP,

  rate_limit_remaining INT,
  rate_limit_reset_at TIMESTAMP
);
```

**Why this matters:**
- You can answer "What changed?" by querying `meta_job_runs`
- You can answer "Where did this come from?" by querying `meta_data_lineage`
- You can answer "Is this data stale?" by comparing current time to `run_timestamp`
- You can answer "What broke?" by checking `error_message`
- **Most important:** You can understand your own system

---

### 3.2 The Data Contract (What You Promise)

Every table should have a **data contract** that states:

```markdown
# Table: raw_bls_qcew_county_employment

## Contract

**This table promises to deliver:**
- County-level employment data for Austin MSA (5 counties)
- By NAICS industry code (5 industries)
- Quarterly updates (Jan, Apr, Jul, Oct)
- Data lag: 6 months (Q3 2025 data available March 2026)
- Never backfilled (historical data never changes)

**Precision:**
- Employment counts accurate to ±1 person
- Wage data accurate to ±$1

**Coverage:**
- 100% of private employers in Travis, Williamson, Hays, Bastrop, Caldwell counties
- Excludes government, military, self-employed

**SLA:**
- Data will arrive within 2 weeks of BLS release
- Queries will complete in <1 second
- 99.9% uptime (only down during backups)

**What can break this contract:**
- BLS discontinues QCEW (unlikely)
- Server runs out of disk space (would alert)
- Network outage for >24 hours (would be obvious)

**If this table ever violates the contract:**
- Escalate to data team immediately
- Check `meta_job_runs` for failed fetch jobs
- Check `meta_api_calls` for API errors
- Contact BLS if data is missing upstream
```

---

## Part 4: Navigation & Discovery

### 4.1 The Data Catalog (How to Find What You Need)

**Every project needs a single source of truth for "what data exists":**

```markdown
# Data Catalog

**Search by:**
- Table name (e.g., "employment")
- Data source (e.g., "BLS")
- Entity (e.g., "wage")
- Layer (e.g., "raw data")

## By Layer

### Raw Data (Authoritative External Sources)
- `raw_bls_qcew_county` — Employment & wages by county & industry
  - 149 rows, refreshed monthly, 6-month lag
  - Source: https://www.bls.gov/cew/
  - Documentation: [QCEW Guide](../BLS_GROUND_TRUTH_GUIDE.md)

- `raw_bls_jolts_national` — Job openings, quits, hires
  - 730 rows, refreshed monthly, 2-month lag
  - Source: https://www.bls.gov/jlt/
  - Documentation: [JOLTS Guide](../BLS_GROUND_TRUTH_GUIDE.md)

[... 20+ more raw tables ...]

### Signals (Normalized Observations)
- `signals` — All observations from all sources
  - 497 rows (growing)
  - Types: job_posting, wage, sentiment, review_score
  - Refreshed: Daily/Real-time depending on source

### Derived Data
- `derived_labor_baseline_monthly` — Computed from QCEW+JOLTS+OEWS+LAUS
  - 5 rows (one per NAICS code)
  - Refreshed: Weekly (Sunday 4am)
  - Dependencies: raw_bls_qcew, raw_bls_jolts, raw_bls_oews, raw_bls_laus

### Business Logic
- `scores_staffing_stress_store` — Final staffing-stress index per store
  - 24 rows (one per store)
  - Refreshed: After each signal ingest (daily)
  - Dependencies: signals, derived_labor_baseline

### Reference Data
- `ref_brands` — Brand metadata (Starbucks, Dutch Bros, etc.)
- `ref_naics_hierarchy` — Industry codes and titles
- `ref_geographic_boundaries` — ZIP codes, counties, MSAs

### Metadata
- `meta_table_catalog` — What tables exist and why
- `meta_column_catalog` — What each column means
- `meta_data_lineage` — How data flows through the system
- `meta_job_runs` — When jobs ran and if they succeeded
- `meta_api_calls` — API request log (for debugging)
```

---

### 4.2 The Understanding Checklist

**Before you trust any data, ask:**

```markdown
## Data Understanding Checklist

For any table you're about to use:

□ **Purpose:**
   - Can I explain in 1 sentence why this table exists?
   - Example: "QCEW data stores county-level employment from government"

□ **Source:**
   - Where did the data come from? (API, database, file)
   - Is it the authoritative source or a copy?
   - Who maintains the upstream source?

□ **Freshness:**
   - When was this data last updated?
   - Query: SELECT MAX(fetch_timestamp_utc) FROM {table}
   - Is it stale compared to SLA?

□ **Completeness:**
   - How many rows should there be?
   - Query: SELECT COUNT(*) FROM {table}
   - Are there unexpected NULLs?

□ **Accuracy:**
   - How was this data validated?
   - Are there sanity checks?
   - Example: "Employment should be 0-10,000,000"

□ **Lineage:**
   - Query: SELECT * FROM meta_data_lineage WHERE source_table = '{table}'
   - Does the lineage make sense?
   - Are there circular dependencies?

□ **Change History:**
   - Has this table ever been wrong?
   - Query: SELECT * FROM meta_job_runs WHERE job_id = '{table}_fetch'
   - When was it last successfully updated?

□ **Dependencies:**
   - What other tables depend on this one?
   - If this data breaks, what breaks downstream?
   - Query: SELECT * FROM meta_data_lineage WHERE source_table = '{table}'
```

---

## Part 5: Implementation: From Theory to Practice

### 5.1 Applying These Principles to Your System

**Three things to do immediately:**

1. **Create the Metadata Layer**
   - Add meta_* tables (5 tables)
   - Populate with descriptions of all existing tables
   - This is your "system documentation"

2. **Document Every Table**
   - Write 2-sentence purpose for each
   - Define the data contract
   - Link to data dictionary

3. **Track Every Job**
   - Every scraper job logs to meta_job_runs
   - Every API call logs to meta_api_calls
   - Every computation logs what was computed

**Four tables you're missing right now:**
1. `meta_table_catalog` — What tables exist?
2. `meta_column_catalog` — What columns exist?
3. `meta_job_runs` — Did jobs succeed?
4. `meta_api_calls` — What APIs did we call?

---

### 5.2 The Audit Trail

**For every piece of data, you should be able to answer:**

```sql
-- Where did this employment number come from?
SELECT
  source_table,
  source_column,
  data_lineage.transformation,
  meta_job_runs.status,
  meta_job_runs.completed_at
FROM meta_data_lineage
JOIN meta_job_runs ON meta_job_runs.job_id = meta_data_lineage.source_table
WHERE target_table = 'scores_staffing_stress_store'
AND target_column = 'demand_pressure_score';

-- Result: You can trace demand_pressure_score → signals → QCEW → BLS API
```

---

### 5.3 The Health Dashboard

**Create a query that shows system health:**

```sql
-- Are all my data sources fresh?
SELECT
  table_name,
  layer,
  source,
  MAX(run_timestamp) as last_update,
  CURRENT_TIMESTAMP - MAX(run_timestamp) as hours_since_update,
  CASE WHEN CURRENT_TIMESTAMP - MAX(run_timestamp) > INTERVAL '7 days' THEN 'STALE'
       WHEN CURRENT_TIMESTAMP - MAX(run_timestamp) > INTERVAL '3 days' THEN 'AGING'
       ELSE 'FRESH'
  END as freshness_status,
  status,
  CASE WHEN status = 'failed' THEN error_message ELSE 'OK' END as alert
FROM meta_table_catalog
LEFT JOIN meta_job_runs ON meta_table_catalog.table_name = meta_job_runs.job_id
WHERE MAX(run_timestamp) IS NOT NULL
ORDER BY hours_since_update DESC;
```

---

## Part 6: Avoiding Agent Blindness

### 6.1 The Knowledge Gap Problem

**The real risk:**
- Agent creates 10 tables
- You don't know they exist
- Agent builds logic on them
- System breaks, you can't debug it

**The solution:**
- **Every table must be documented at creation time**
- **Every job must log success/failure**
- **Every month, run the health dashboard**

### 6.2 Required Documentation Before Any Changes

When an agent (or you) adds a table, it MUST have:

```markdown
## New Table: raw_google_maps_reviews

**Mandatory:**
- [ ] Purpose (why does this table exist?)
- [ ] Source (where do rows come from?)
- [ ] Row insertion date
- [ ] Ownership (who's responsible?)
- [ ] SLA (how fresh should it be?)
- [ ] Column definitions (every column documented)
- [ ] Sample row (show what it looks like)
- [ ] Entry in meta_table_catalog
- [ ] Entry in meta_column_catalog (one per column)
- [ ] First fetch job logs to meta_job_runs

**Verification:**
- [ ] Query returns results
- [ ] Row count makes sense
- [ ] NULLs are only in expected columns
- [ ] Timestamps are reasonable
- [ ] No circular dependencies

**Documentation:**
- [ ] Added to data dictionary
- [ ] Added to data catalog
- [ ] Added to system diagram
- [ ] Added to INDEX.md navigation
```

### 6.3 Monthly Audit

**Do this once a month to catch drift:**

```bash
#!/bin/bash
# Check 1: Do all tables mentioned in code actually exist?
grep -r "SELECT.*FROM" code/ | grep -oE "FROM [a-z_]+" | sort | uniq > mentioned_tables.txt
sqlite3 tracker.db "SELECT name FROM sqlite_master WHERE type='table';" | sort > actual_tables.txt
diff mentioned_tables.txt actual_tables.txt  # Should be empty

# Check 2: Are any tables older than SLA?
sqlite3 tracker.db "SELECT table_name, MAX(last_update) FROM meta_job_runs GROUP BY table_name WHERE MAX(last_update) < DATE('now', '-7 days');" # Shows stale tables

# Check 3: Do all tables have documentation?
sqlite3 tracker.db "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN (SELECT table_name FROM meta_table_catalog);" # Shows undocumented tables

# Check 4: Have any jobs failed in the last week?
sqlite3 tracker.db "SELECT * FROM meta_job_runs WHERE status != 'success' AND run_timestamp > DATE('now', '-7 days');"
```

---

## Summary: The Checklist

**When building a multi-source data project:**

- ✅ Organize into **layers** (raw → signals → derived → business → reference → metadata)
- ✅ Name tables consistently: `[layer]_[source]_[entity]`
- ✅ Document every column: type, unit, source, SLA, valid range
- ✅ Create metadata tables: table_catalog, column_catalog, data_lineage, job_runs, api_calls
- ✅ Write data contracts: promises about accuracy, freshness, coverage
- ✅ Build a data catalog: single source of truth for "what exists"
- ✅ Track everything: metadata is more important than data
- ✅ Monthly audits: catch drift before it becomes a problem
- ✅ Make it human-readable: if you can't explain it, it's wrong

**The goal:**
- You understand your own system
- An agent can't surprise you
- You can debug without asking "what did I build?"
- New developers can onboard in 1 hour instead of 1 week

---

## References

- **Data Mesh** — Zhamak Dehghani (ThoughtWorks)
- **Fundamentals of Data Engineering** — Joe Reis & Matt Housley
- **dbt Labs Data Contracts** — https://docs.getdbt.com/
- **Dataedo** — Data dictionary best practices
