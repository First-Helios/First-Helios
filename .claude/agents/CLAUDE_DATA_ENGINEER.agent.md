# Data Engineer Guide for First Helios

This guide covers how to work with our metadata system, add new data sources, and maintain data quality. Use this alongside `docs/DATABASE_DESIGN_BEST_PRACTICES.md` for architecture context.

## Quick Start: Understanding What We Have

**The problem this solves:** When agents build things, humans can't see what was built. This guide and the metadata system are your insurance policy.

### Check System Health (Do This Weekly)
```bash
python scripts/system_health_dashboard.py
```

This tells you:
- 🟢 FRESH tables (updated in last 3 days)
- 🟡 AGING tables (3-7 days old)
- 🔴 STALE tables (7+ days old, SLA violated)
- Recent job failures and API errors
- Rate limit consumption across all sources

### Check Specific Table Lineage (Do This Before Depending on a Table)
```bash
sqlite3 data/tracker.db "SELECT source_table, target_table, transformation FROM meta_data_lineage WHERE target_table = 'business_scores';"
```

This shows you exactly what tables feed into a given output, so you know if an upstream change will affect you.

### Query the Table Registry (Do This to Find Data)
```bash
sqlite3 data/tracker.db "SELECT table_name, purpose, owner_team FROM meta_table_catalog WHERE layer = 'derived';"
```

This lists all derived tables (tables that are computed from raw data), their purpose, and who owns them.

---

## Adding a New Data Source: Step-by-Step Checklist

When you're about to ingest a new data source, follow this checklist. It prevents architectural debt and makes the system self-documenting.

### 1. **Assess the Source** (Before Writing Any Code)

Ask yourself:
- [ ] What's the source? (API? CSV? Database?)
- [ ] How frequently is it updated? (hourly, daily, weekly, monthly?)
- [ ] What's the coverage? (Austin only? National? By MSA?)
- [ ] How fresh must our copy be? (same day? next day? weekly?)
- [ ] Is this the ground truth or a filtered view?
- [ ] What's the license / data use agreement?

**Document this in a PR or issue.** Example:
```
Source: BLS Quarterly Census of Employment and Wages (QCEW)
- API: BLS Data Tools API (seriesid endpoint)
- Frequency: Monthly (released 6 weeks later)
- Coverage: Austin MSA (area code 12420)
- Freshness requirement: Fetch within 1 week of release
- Ground truth: Yes (official employment statistics)
- License: Public domain
```

### 2. **Define Your Tables**

Create tables following the naming convention: `[layer]_[source]_[entity]`

Examples:
- `raw_bls_qcew_employment` (raw layer, BLS source, employment entity)
- `signals_revelio_compensation` (signals layer, Revelio source, compensation entity)
- `derived_austin_employment_trends` (derived layer)

**Do not name tables like:** `table1`, `employment_data`, `temp_qcew` (no source context, no layer context, looks temporary)

### 3. **Register Your Tables in Metadata**

Before you write any scraper or ingestion code, register the tables by running:

```bash
sqlite3 data/tracker.db
```

Then insert into `meta_table_catalog`:
```sql
INSERT INTO meta_table_catalog
  (table_name, layer, source, entity, purpose, description, append_only, owner_team, documentation_url, created_at, updated_at)
VALUES
  ('raw_bls_qcew_employment', 'raw', 'bls', 'employment',
   'Raw employment data from BLS QCEW API by occupation and industry for Austin MSA.',
   'Fetched monthly. Contains counts of covered employment and wages by industry classification.',
   1, 'data-engineering', 'https://bls.gov/cew/', datetime('now'), datetime('now'));
```

For each important column, also register it in `meta_column_catalog`:
```sql
INSERT INTO meta_column_catalog
  (table_name, column_name, ordinal_position, data_type, is_nullable, description, unit, source_of_truth, valid_range_min, valid_range_max, sla_freshness_days)
VALUES
  ('raw_bls_qcew_employment', 'area_code', 1, 'VARCHAR', 0, 'FIPS MSA code identifying geographic area', 'fips_code', 'BLS QCEW', '12420', '12420', 30),
  ('raw_bls_qcew_employment', 'total_employment', 5, 'INTEGER', 0, 'Total covered employment in period', 'count', 'BLS QCEW', '0', '10000000', 30);
```

**Why do this before writing code?**
- Forces you to think about what you're actually building
- Makes the table discoverable (other agents will see it in the registry)
- SLA definitions catch mistakes early (if you promise freshness in 7 days and your API breaks, you'll see it)
- Documentation prevents someone from using the data wrong 6 months from now

### 4. **Write the Ingestion Script**

Place it in `scripts/ingest_[source].py`.

**Required pattern:**
```python
from datetime import datetime
from sqlalchemy import text
from backend.database import get_session, init_db

def ingest_bls_qcew():
    """Fetch QCEW data and insert into raw_bls_qcew_employment."""
    engine = init_db()
    session = get_session(engine)

    try:
        # 1. Fetch from source
        data = fetch_from_bls_api(...)

        # 2. Log the job start
        job_run = MetaJobRun(
            job_id='bls_qcew_fetch',
            job_type='scraper',
            status='in_progress',
            started_at=datetime.utcnow(),
            run_timestamp=datetime.utcnow(),
            triggered_by='scheduler',
        )
        session.add(job_run)
        session.flush()  # Get the ID

        # 3. Validate, transform, insert
        rows_inserted = 0
        for record in data:
            # Validate against valid_range_min/max from meta_column_catalog
            if not validate(record):
                job_run.rows_skipped += 1
                continue

            session.add(RawBlsQcewEmployment(**record))
            rows_inserted += 1

        # 4. Log API calls (if applicable)
        api_call = MetaApiCall(
            api_source='bls_v2',
            endpoint='/timeseries/data',
            status_code=200,
            success=True,
            rows_returned=len(data),
            latency_ms=query_duration_ms,
            request_timestamp=datetime.utcnow(),
            job_run_id=job_run.id,
        )
        session.add(api_call)

        # 5. Finalize job log
        job_run.completed_at = datetime.utcnow()
        job_run.status = 'success'
        job_run.rows_inserted = rows_inserted
        job_run.duration_seconds = (job_run.completed_at - job_run.started_at).total_seconds()

        session.commit()
        print(f"✓ Inserted {rows_inserted} rows into raw_bls_qcew_employment")

    except Exception as e:
        job_run.status = 'failed'
        job_run.error_message = str(e)
        job_run.completed_at = datetime.utcnow()
        session.commit()
        print(f"✗ Job failed: {e}")
        raise

    finally:
        session.close()

if __name__ == '__main__':
    ingest_bls_qcew()
```

**Key requirements:**
- Always create a `MetaJobRun` entry (so we know when it ran and if it succeeded)
- Always log `MetaApiCall` entries for external APIs (so we can track rate limits and errors)
- Validate against SLA ranges (if meta_column_catalog says valid_range is 0-10M, check that)
- Handle failures explicitly (don't silent-fail)
- Update `meta_job_runs` with row counts and durations

### 5. **Register Data Lineage**

Once the table exists, document how it feeds downstream:

```sql
INSERT INTO meta_data_lineage
  (source_table, source_column, target_table, target_column, transformation_type, transformation, created_at)
VALUES
  ('raw_bls_qcew_employment', 'total_employment', 'derived_austin_employment_trends', 'bls_employment',
   'aggregation', 'GROUP BY period, industry, SUM(total_employment)', datetime('now'));
```

This tells future engineers (or agents) that if they change raw_bls_qcew_employment, they should check if derived_austin_employment_trends needs updating.

### 6. **Add a Data Contract**

Create `docs/contracts/[table_name]_contract.md`:

```markdown
# Data Contract: raw_bls_qcew_employment

## Accuracy
- Source of truth: BLS QCEW API
- Validation: All rows must have area_code = 12420 (Austin MSA only)
- Expected row counts: ~500-1000 records per fetch (by occupation × industry)

## Freshness
- SLA: Must be updated within 7 days of BLS release
- Monitoring: system_health_dashboard.py alerts if stale
- Fallback: If fetch fails, use previous month's data (marked with flag)

## Coverage
- Geographic: Austin MSA only (area_code 12420)
- Temporal: Monthly snapshots (one row per month per occupation/industry)
- Industry detail: All major NAICS divisions

## What can break
- API endpoint changes or deprecation
- BLS data format changes
- Geographic code changes
- Network/API timeout (monitor in meta_api_calls)

## Downstream consumers
- derived_austin_employment_trends (used for market analysis)
- business_scores (employment component of score)
- Dashboard (for visualizations)

## Fallback strategy
If the BLS API fails:
1. Fetch manually from BLS FTP
2. Use previous month's data with 'preliminary' flag
3. Alert the data engineering team

## Contact
Owner: data-engineering team
Slack: #data-engineering
```

---

## Monthly Audit Procedure

Run this checklist monthly to catch drift before it becomes a problem:

### 1. **System Health Check** (5 minutes)
```bash
python scripts/system_health_dashboard.py --detailed
```

Should show all tables as 🟢 FRESH. If any are 🟡 or 🔴:
- [ ] Check the job logs: why did it fail?
- [ ] Is the SLA realistic? If not, update meta_table_catalog
- [ ] Is the data source down? Check meta_api_calls for errors

### 2. **Table Completeness Check** (10 minutes)
```bash
sqlite3 data/tracker.db "
SELECT table_name, COUNT(*) as columns_documented
FROM meta_column_catalog
GROUP BY table_name
ORDER BY columns_documented;
"
```

Every table should have at least 70% of its columns documented in meta_column_catalog.

If a table is missing column docs:
- [ ] Open an issue to document it
- [ ] Add entries to meta_column_catalog with descriptions and valid ranges

### 3. **Lineage Completeness Check** (10 minutes)
```bash
sqlite3 data/tracker.db "
SELECT source_table, COUNT(*) as lineage_count
FROM meta_data_lineage
WHERE deprecated_at IS NULL
GROUP BY source_table;
"
```

If a table has no outbound lineage (count = 0) and it's not a reference table:
- [ ] Is it really used? If not, consider archiving it
- [ ] If it is used, add lineage entries to meta_data_lineage

### 4. **Data Quality Check** (15 minutes)

For each raw/signals layer table:
```sql
SELECT
  table_name,
  COUNT(*) as total_rows,
  COUNT(CASE WHEN [null_column] IS NULL THEN 1 END) as nulls_in_key_column
FROM [table_name]
WHERE DATE(created_at) >= DATE('now', '-30 days');
```

- [ ] Are row counts stable month-to-month? (Use meta_job_runs to see trend)
- [ ] Are null rates as expected? (Compare against meta_column_catalog.sla_null_allowed)

### 5. **SLA Validation** (10 minutes)
```bash
sqlite3 data/tracker.db "
SELECT
  mtc.table_name,
  MAX(mjr.run_timestamp) as last_update,
  CAST((julianday('now') - julianday(MAX(mjr.run_timestamp))) AS INTEGER) as hours_since_update,
  mtc.retention_days
FROM meta_table_catalog mtc
LEFT JOIN meta_job_runs mjr ON mtc.table_name = mjr.job_id
GROUP BY mtc.table_name;
"
```

For each table with SLA:
- [ ] Is last_update older than the SLA? If so, why?
- [ ] Is there a documented fallback strategy in the data contract?

### 6. **Documentation Review** (15 minutes)

- [ ] Any new tables added in the last month? Check docs/contracts/ for their data contracts
- [ ] Any columns changed? Update meta_column_catalog
- [ ] Any lineage changes? Update meta_data_lineage
- [ ] Any infrastructure changes? Update DATABASE_DESIGN_BEST_PRACTICES.md

---

## Troubleshooting: Common Scenarios

### "A table is stale, what do I do?"

1. Check what job is supposed to update it:
```bash
sqlite3 data/tracker.db "SELECT * FROM meta_job_runs WHERE job_id = 'qcew_fetch' ORDER BY run_timestamp DESC LIMIT 5;"
```

2. Look at the most recent failure:
```bash
sqlite3 data/tracker.db "SELECT job_id, status, error_message FROM meta_job_runs WHERE status != 'success' ORDER BY run_timestamp DESC LIMIT 3;"
```

3. Check if the API is down:
```bash
sqlite3 data/tracker.db "SELECT api_source, status_code, error_message FROM meta_api_calls WHERE success = 0 ORDER BY request_timestamp DESC LIMIT 5;"
```

4. If the API is fine:
   - Check network connectivity
   - Check API credentials in .env
   - Run the script manually: `python scripts/ingest_[source].py`

### "I need to understand how data flows from source A to table B"

```bash
sqlite3 data/tracker.db "
WITH RECURSIVE lineage AS (
  SELECT source_table, target_table, transformation_type, 1 as depth
  FROM meta_data_lineage
  WHERE source_table = 'raw_bls_qcew_employment' AND deprecated_at IS NULL

  UNION ALL

  SELECT l.source_table, m.target_table, m.transformation_type, l.depth + 1
  FROM lineage l
  JOIN meta_data_lineage m ON l.target_table = m.source_table
  WHERE l.depth < 5 AND m.deprecated_at IS NULL
)
SELECT REPEAT('  ', depth - 1) || target_table as flow, transformation_type
FROM lineage
ORDER BY depth, target_table;
"
```

This shows the full chain: raw → signals → derived → business → reference.

### "A table is missing columns, what do I do?"

1. Identify what columns exist:
```bash
sqlite3 data/tracker.db ".schema [table_name]"
```

2. Check what's documented:
```bash
sqlite3 data/tracker.db "SELECT column_name FROM meta_column_catalog WHERE table_name = '[table_name]';"
```

3. For missing columns, add entries to meta_column_catalog:
```sql
INSERT INTO meta_column_catalog
  (table_name, column_name, ordinal_position, data_type, is_nullable, description, unit, sla_freshness_days)
VALUES
  ('[table_name]', '[column_name]', 1, 'VARCHAR', 0, 'What is this column?', '', 30);
```

---

## Metadata System API

Reference for querying the metadata tables directly:

### List all tables by layer
```sql
SELECT table_name, layer, source, entity, purpose
FROM meta_table_catalog
WHERE layer = 'derived'
ORDER BY table_name;
```

### Check column SLAs
```sql
SELECT table_name, column_name, data_type, sla_freshness_days, valid_range_min, valid_range_max
FROM meta_column_catalog
WHERE sla_freshness_days < 30
ORDER BY sla_freshness_days;
```

### See job run history
```sql
SELECT job_id, COUNT(*) as runs,
       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failures
FROM meta_job_runs
GROUP BY job_id
ORDER BY job_id;
```

### Track rate limit consumption
```sql
SELECT api_source,
       SUM(rate_limit_remaining) as total_remaining,
       MAX(request_timestamp) as last_request,
       COUNT(*) as request_count
FROM meta_api_calls
WHERE DATE(request_timestamp) = DATE('now')
GROUP BY api_source;
```

---

## When You're Done: The "Agent Audit"

After any major data engineering work (new source, significant refactor, bug fix), verify the system still makes sense:

- [ ] Run `system_health_dashboard.py` - does it match reality?
- [ ] Query `meta_data_lineage` - does the dependency graph match what you built?
- [ ] Check `meta_column_catalog` for your new columns - are they documented?
- [ ] Review the data contracts in `docs/contracts/` - do they reflect what you actually built?

This is your insurance policy against agent blindness. If the metadata system doesn't match the database, you'll know immediately, and you can fix it before it causes real damage.

---

## Questions?

- Architecture questions: See `docs/DATABASE_DESIGN_BEST_PRACTICES.md`
- Specific table questions: Query `meta_table_catalog` and read the data contract in `docs/contracts/`
- Data lineage questions: Query `meta_data_lineage` or run the recursive query above
- System health: Run `python scripts/system_health_dashboard.py`
