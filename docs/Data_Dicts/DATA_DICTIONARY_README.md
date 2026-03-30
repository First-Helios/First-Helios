# Data Dictionary — Quick Start Guide

**This is the master guide to understanding and documenting all data in ChainStaffingTracker.**

Three documents work together:
1. **This file** — High-level orientation and FAQs
2. **[DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md)** — What each table *does* and where data comes from
3. **[DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)** — What each column *means* and valid values

---

## When to Use Each Document

### 👇 START HERE: "I'm adding a new data source"
1. Read section [Adding a New Data Source](#adding-a-new-data-source) below
2. Open [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md) and find the table that will store your data
3. Open [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md) and update the columns
4. Update `config/chains.yaml` and `backend/database.py`
5. Document in `CLAUDE_AGENT_HANDOFF.md`

### 👇 "I'm trying to understand where a metric comes from"
1. Find the metric name (e.g., "composite score", "wage_index", "employment")
2. Use Ctrl+F to search both dictionaries
3. DATA_DICTIONARY_TABLES.md will tell you which table stores it and how often it's updated
4. DATA_DICTIONARY_COLUMNS.md will tell you the exact column definition

### 👇 "I'm debugging a NULL value in a field"
1. Open [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)
2. Find the column and check **Nullable** and **SLA** columns
3. If Nullable=✓, the field is allowed to be NULL (check the **Source** and notes for why)
4. If Nullable=✗, NULLs indicate a data quality issue (check **SLA** column for expected freshness)

### 👇 "The database schema changed and I need to update docs"
1. Update the SQLAlchemy model in `backend/database.py`
2. Update both dictionaries in lockstep
3. Update `config/chains.yaml` if adding a configurable parameter
4. Add a version bump to the "Version History" section at the bottom

---

## Quick Reference: Table Categories

**Operational (live data from scrapers):**
- `stores` — Physical locations
- `signals` — Raw observations (job postings, sentiment, reviews)
- `scores` — Computed staffing-stress index
- `wage_index` — Posted wages from all sources

**Ground-Truth (government data, official source of truth):**
- `qcew_data` — County employment & establishments (BLS)
- `jolts_data` — Job openings, quits, hires rates (BLS)
- `laus_data` — Unemployment rates (BLS)
- `oews_data` — Occupation wages by percentile (BLS)
- `cbp_data` — ZIP-level establishments (Census)
- `labor_market_baseline` — Computed baseline from all ground-truth

**Reference (lookup tables, master data):**
- `ref_brands` — Brands we track
- `ref_industry` — Industry hierarchy (NAICS)
- `ref_regions` — Geographic boundaries
- `ref_category_map` — Category mappings (Overture → internal)

**Operational Metadata (system health & telemetry):**
- `api_sources` — External API registry
- `api_endpoints` — Scraper configurations
- `api_request_log` — HTTP request log
- `rate_budgets` — Daily API quota tracking
- `source_freshness` — Data staleness alerts
- `snapshots` — Period summaries for trending
- `store_aliases` — Deduplication log (future)

---

## Common Questions

### Q: Where do I find what data is available?
**A:** Start with [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md). Each table has:
- **Purpose** — What is the table for?
- **Source** — Where does the data come from?
- **Refresh Cadence** — How often is it updated?
- **Rows** — Current row count

### Q: I need to add a new BLS series. How do I do it?
**A:**
1. Add the series ID and description to `config/chains.yaml` under `bls_series`
2. Register it in `api_sources` table if it's a new API endpoint
3. Update [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md) in the `jolts_data`, `laus_data`, or `oews_data` section
4. Run the appropriate adapter (e.g., `python scrapers/bls_adapter.py --region austin_tx`)
5. Update [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md) "Rows" count in the table summary

### Q: How do I know if data is stale?
**A:**
1. Open [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)
2. Find your table/column
3. Check the **SLA** column — e.g., "Monthly (2mo lag)" means data updates monthly with 2-month delay
4. If current date exceeds expected update date, data is stale
5. Check `api_endpoints.last_success_at` to see when scraper last ran successfully
6. Check `source_freshness` table for automated staleness alerts

### Q: What does "nullable" mean?
**A:** Column can be NULL (empty). In [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md):
- **Nullable=✗** → Field is always required; NULL indicates a bug
- **Nullable=✓** → Field is optional; NULL is expected in some cases (see notes)

Example:
- `stores.lat` is Nullable=✓ because geocoding might fail on first scrape
- `stores.store_num` is Nullable=✗ because every store must have an ID

### Q: How is data quality monitored?
**A:** Three tables track health:
1. **api_request_log** — Every HTTP request is logged with status code and latency
2. **rate_budgets** — Daily quota rollup (alerts if approaching limits)
3. **source_freshness** — Automated staleness checker (alerts if data >N days old)

### Q: Why does my new field have NULL values everywhere?
**A:** Check the **Source** column in [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md):
- If Source="Computed", the column is populated by a job (check `backend/scheduler.py`)
- If Source="BLS" or "Census", the job hasn't run yet
- If Source="Scraper", the adapter needs to be run or fixed
- If Source="Manual", you need to populate it by hand or via a script

Example: `oews_data` has 0 rows because the source is "BLS OEWS flat files (manual download)" — the data hasn't been imported yet.

### Q: How do I add a new scraper?
**A:**
1. Create file `scrapers/my_new_scraper.py` inheriting from `BaseScraper`
2. Add entry to `api_sources` table (source_key, base_url, auth_type, daily_limit)
3. Add entry to `api_endpoints` table (adapter_name, scraper_module, intent, route_status)
4. Add job to `backend/scheduler.py` (cron schedule, runner function)
5. Add config to `config/chains.yaml`
6. Document in [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md) "Sources" column for relevant table
7. Document in [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md) if creating new columns

---

## Adding a New Data Source

**Step-by-step template:**

### 1. Understand what you're adding
- [ ] What table will store this data? (Create new or use existing?)
- [ ] What columns do you need?
- [ ] How often will it refresh?
- [ ] What's the data lag?
- [ ] What's the authoritative source?

### 2. Update SQLAlchemy model (`backend/database.py`)
```python
class MyNewTable(Base):
    __tablename__ = "my_new_table"
    id = Column(Integer, primary_key=True, autoincrement=True)
    # Add columns...
    created_at = Column(DateTime, default=datetime.utcnow)
```

### 3. Update `config/chains.yaml`
```yaml
my_new_api:
  base_url: "https://api.example.com"
  auth_type: "api_key"  # or "oauth", "none", etc.
  daily_limit: 1000
  rate_limits:
    my_new_api:
      delay_seconds: 0.5
```

### 4. Register in database tables
```python
# Add to api_sources
session.add(ApiSource(
    source_key="my_new_api",
    display_name="My New API",
    base_url="https://api.example.com",
    auth_type="api_key",
    daily_limit=1000,
))

# Add to api_endpoints
session.add(ApiEndpoint(
    adapter_name="MyNewScraper",
    source_key="my_new_api",
    intent="what_kind_of_data",
    data_type="signal_type_name",
    route_status="testing",
))
session.commit()
```

### 5. Create scraper (`scrapers/my_new_scraper.py`)
```python
from scrapers.base import BaseScraper, ScraperSignal

class MyNewScraper(BaseScraper):
    name = "MyNewScraper"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch data and return signals."""
        signals = []
        # ... fetch and parse data ...
        return signals
```

### 6. Add scheduler job (`backend/scheduler.py`)
```python
def _run_my_new_source():
    """Scheduled job to fetch from my new API."""
    from scrapers.my_new_scraper import MyNewScraper
    adapter = MyNewScraper()
    signals = adapter.scrape("austin_tx")
    # ... ingest signals ...

# In init_scheduler():
scheduler.add_job(_run_my_new_source, CronTrigger(hour=3, minute=30), id="my_new_source")
```

### 7. Update TABLE-LEVEL dictionary
Open [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md):
- [ ] Add row to [Table Index](#table-index)
- [ ] Create new `### my_new_table` section with Purpose, Source, Refresh Cadence, Rows, Quality Notes

### 8. Update COLUMN-LEVEL dictionary
Open [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md):
- [ ] Create new table section with all columns documented
- [ ] For each column: Type, Nullable, Description, Example, Valid Range, Source, SLA
- [ ] Add example values and constraints
- [ ] Document relationships (→ other tables, ← backreferences)

### 9. Update `CLAUDE_AGENT_HANDOFF.md`
Add to "Outstanding Work" section:
```markdown
### 10.X — My New Data Source (PRIORITY)
Description of what this does, how to run it, and what's needed.
```

### 10. Test & validate
```bash
source .venv/bin/activate
python scrapers/my_new_scraper.py --region austin_tx --no-ingest  # Test scraper
python -c "from backend.scheduler import init_scheduler; s = init_scheduler(); print([j.id for j in s.get_jobs()])"  # Verify scheduler job
```

---

## Data Dictionary Maintenance

**Who updates these docs:**
- **Data engineers / data scientists** — When adding new sources, adjust columns
- **Devs** — When changing schema in `backend/database.py`
- **Analysts** — When discovering data quality issues (update notes)
- **Architects** — When refactoring data models

**Review frequency:**
- Quarterly — Full review of Refresh Cadence and SLA columns (compare to actual)
- On PR merge — Any schema change triggers simultaneous dict update
- On release — Version bump at bottom of both docs

**Validation checklist before committing:**
- [ ] All tables in index have corresponding sections?
- [ ] All columns in sections exist in `backend/database.py`?
- [ ] All Examples are realistic (e.g., dates are not from 2020)?
- [ ] No broken cross-references (→ links to nonexistent tables)?
- [ ] Valid ranges make sense (e.g., unemployment_rate 0-100, not 0-1)?
- [ ] SLA cadences match actual scheduler jobs in `backend/scheduler.py`?

---

## Related Documents

- **[CLAUDE_AGENT_HANDOFF.md](../CLAUDE_AGENT_HANDOFF.md)** — Full system architecture and pending work
- **[config/chains.yaml](../config/chains.yaml)** — All tunable parameters and API configs
- **[backend/database.py](../backend/database.py)** — SQLAlchemy table definitions (source of truth for schema)
- **[backend/scheduler.py](../backend/scheduler.py)** — Scheduled jobs (source of truth for refresh cadence)

---

## Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-03-22 | Created comprehensive data dictionary suite (3 docs) |

---

## Questions / Feedback?

If you find gaps in the documentation:
1. Open an issue with the table/column name and what's missing
2. Update the docs locally and submit a PR
3. Slack the team to discuss structural changes

**Goal:** Make it so any team member can answer "where does this data come from?" in <2 minutes by searching these docs.
