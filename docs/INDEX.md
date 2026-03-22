# Documentation Index

## Data Dictionary (New)

Comprehensive documentation of all data tables, columns, and relationships. **Start here** if you need to understand what data is available or how to add a new source.

- **[DATA_DICTIONARY_README.md](./DATA_DICTIONARY_README.md)** — Quick start guide, FAQs, and step-by-step template for adding new data sources
- **[DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md)** — Table-level overview organized by **5 logical schemas**:
  - Operational (stores, signals, scores, wages)
  - Ground-Truth (BLS/Census government data)
  - Derived (computed baselines)
  - Reference (master data)
  - Metadata (system health)
- **[DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)** — Column-level details: type, nullability, examples, valid ranges, SLA

### 🎯 BLS-Specific Guides

Understanding the government labor statistics that power the scoring engine:

- **[BLS_GROUND_TRUTH_GUIDE.md](./BLS_GROUND_TRUTH_GUIDE.md)** — Deep dive on the 5 BLS/Census tables (QCEW, JOLTS, LAUS, OEWS, CBP)
  - When each data source updates and what you get
  - How they combine into `labor_market_baseline`
  - Why certain tables are empty (and how to populate them)

### 📥 Manual Data Ingestion Guides

Downloaded data analysis and ingestion workflows:

- **[MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md](./MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md)** — Complete analysis of 571 MB of downloaded data
  - OEWS national data (national only, need Austin MSA file)
  - Revelio Labs premium labor statistics (ready to ingest)
  - Data quality assessment
  - Gap analysis and recommendations

- **[DATA_INGESTION_SUMMARY.md](./DATA_INGESTION_SUMMARY.md)** — Step-by-step ingestion plan
  - 5-phase implementation checklist
  - Timeline & dependencies
  - Quick-start options (1 hour, 1.5 hours, week-long)
  - Database schema requirements
  - Scoring impact analysis

**Use case:** "Where does staffing stress score come from?" → Open README, search for "score", jump to tables doc for detail
**Use case:** "Why is my baseline stale?" → Open BLS_GROUND_TRUTH_GUIDE.md, check refresh schedules
**Use case:** "I have downloaded data — what should I do?" → Open DATA_INGESTION_SUMMARY.md for action items
**Use case:** "What data gaps exist?" → Open MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md for gap analysis

---

## System Architecture & Operations

- **[../CLAUDE_AGENT_HANDOFF.md](../CLAUDE_AGENT_HANDOFF.md)** — Full system overview, tech stack, outstanding work, and quick validation commands
- **[../DATABASE_DESIGN_BEST_PRACTICES.md](../DATABASE_DESIGN_BEST_PRACTICES.md)** — 6-layer database architecture, metadata design, data contracts, lineage tracking, and agent blindness solutions
- **[../CLAUDE_DATA_ENGINEER.md](../CLAUDE_DATA_ENGINEER.md)** — **Start here** as a data engineer. Operational guide with quick health checks, step-by-step checklists for adding new sources, data contracts, troubleshooting, and monthly audit procedures

---

## Configuration

- **[../config/chains.yaml](../config/chains.yaml)** — All tunable parameters (brands, regions, scoring weights, API configs, scraper schedules)
- **[../.env.example](../.env.example)** — API key templates (BLS, Census, Reddit, Google)

---

## Code Documentation

- **[../backend/database.py](../backend/database.py)** — SQLAlchemy table definitions (schema source of truth)
- **[../backend/scoring/engine.py](../backend/scoring/engine.py)** — How staffing-stress scores are computed
- **[../backend/baseline.py](../backend/baseline.py)** — Labor market baseline computation
- **[../backend/scheduler.py](../backend/scheduler.py)** — Scheduled jobs and their triggers
- **[../scrapers/base.py](../backend/scrapers/base.py)** — Base scraper interface and ScraperSignal dataclass

---

## Quick Navigation

### I want to...

**...understand the database**
→ Start: [DATA_DICTIONARY_README.md](./DATA_DICTIONARY_README.md)
→ Deep dive: [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md) then [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)

**...add a new data source**
→ Start: [../CLAUDE_DATA_ENGINEER.md](../CLAUDE_DATA_ENGINEER.md#adding-a-new-data-source-step-by-step-checklist) (6-step checklist)
→ Then update: [../config/chains.yaml](../config/chains.yaml), [../backend/database.py](../backend/database.py), [../backend/scheduler.py](../backend/scheduler.py)

**...set up API keys**
→ Copy: [../.env.example](../.env.example) to `.env`
→ Fill in: BLS_API_KEY, CBP_API_KEY, etc.

**...understand the scoring system**
→ Read: [../CLAUDE_AGENT_HANDOFF.md](../CLAUDE_AGENT_HANDOFF.md) section 6 (Scoring Engine Architecture)
→ Code: [../backend/scoring/engine.py](../backend/scoring/engine.py)

**...see what data is stale** (weekly health check)
→ Run: `python scripts/system_health_dashboard.py`
→ Or query: `source_freshness` table (see [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md#source_freshness))
→ Guide: [../CLAUDE_DATA_ENGINEER.md](../CLAUDE_DATA_ENGINEER.md#check-system-health-do-this-weekly)

**...run the server locally**
→ Guide: [../CLAUDE_AGENT_HANDOFF.md](../CLAUDE_AGENT_HANDOFF.md) section 9 (How to Run)
→ Config: [../.env.example](../.env.example)

**...understand a specific column**
→ Search: [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md) (Ctrl+F)
→ Find: Type, nullability, examples, valid ranges, source, SLA

**...debug NULL values in the DB**
→ Open: [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)
→ Find the column, check if Nullable=✓ (expected) or ✗ (indicates bug)
→ Check the "Source" and "SLA" to see if data hasn't been collected yet
