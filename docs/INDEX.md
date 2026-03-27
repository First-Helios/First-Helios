# Documentation Index — First-Helios

**Last Updated:** 2026-03-27

## Data Dictionary

Comprehensive documentation of all data tables, columns, and relationships. **Start here** if you need to understand what data is available or how to add a new source.

- **[DATA_DICTIONARY_README.md](./Data_Dicts/DATA_DICTIONARY_README.md)** — Quick start guide, FAQs, and step-by-step template for adding new data sources
- **[DATA_DICTIONARY_TABLES.md](./Data_Dicts/DATA_DICTIONARY_TABLES.md)** — Table-level overview organized by logical schemas:
  - Operational (chain_locations, local_employers, brand_groups, signals, scores, wages)
  - Ground-Truth (BLS/Census government data)
  - Derived (computed baselines)
  - Reference (master data, including `ref_occupation_aliases`)
  - Mobility Graph (mob_occupation, mob_transition — Career Pathfinder)
  - Metadata (system health)
- **[DATA_DICTIONARY_COLUMNS.md](./Data_Dicts/DATA_DICTIONARY_COLUMNS.md)** — Column-level details: type, nullability, examples, valid ranges, SLA

### 🎯 BLS-Specific Guides

Understanding the government labor statistics that power the scoring engine:

- **[BLS_GROUND_TRUTH_GUIDE.md](./BLS_GROUND_TRUTH_GUIDE.md)** — Deep dive on the 5 BLS/Census tables (QCEW, JOLTS, LAUS, OEWS, CBP)
  - When each data source updates and what you get
  - How they combine into `labor_market_baseline`
  - Why certain tables are empty (and how to populate them)

### 🗺️ Career Pathfinder Data

Documentation for the mobility graph (Career Pathfinder mode):

- **[DATA_DICTIONARY_TABLES.md → Mobility Graph Schema](./Data_Dicts/DATA_DICTIONARY_TABLES.md#mobility-graph-schema-career-pathfinder)** — `mob_occupation` (781 SOCs) and `mob_transition` (256,831 edges) table entries
- **[DATA_DICTIONARY_TABLES.md → ref_occupation_aliases](./Data_Dicts/DATA_DICTIONARY_TABLES.md#ref_occupation_aliases)** — 18,981 Census job-title aliases powering Pathfinder autocomplete
- Populate scripts: `scripts/populate_mobility_data.py`, `scripts/load_occupation_aliases.py`
- API endpoints: `GET /api/mobility/occupations`, `/api/mobility/paths`, `/api/mobility/employers`

### 📥 Data Ingestion Guides

- **[DATA_INGESTION_SUMMARY.md](./Data_Ingestion/DATA_INGESTION_SUMMARY.md)** — Ingestion status and step-by-step plan. Current state: OEWS Austin MSA loaded (638 occupations), mobility graph loaded (781 SOCs, 256k edges), Jobicy remote jobs ingested via `scrapers/jobicy_adapter.py`. Revelio tables remain unpopulated.

**Use case:** "Where does staffing stress score come from?" → Open README, search for "score", jump to DATA_DICTIONARY_TABLES.md for detail
**Use case:** "Why is my baseline stale?" → Open BLS_GROUND_TRUTH_GUIDE.md, check refresh schedules
**Use case:** "I have downloaded data — what should I do?" → Open DATA_INGESTION_SUMMARY.md for action items

---

## System Architecture & Operations

- **[../README.md](../README.md)** — Project overview, three-mode architecture, API endpoints, quickstart
- **[../RUNBOOK.md](../RUNBOOK.md)** — Server startup, PostgreSQL setup, populate-data sequence, full scheduler table, troubleshooting
- **[../PLAYBOOK.md](../PLAYBOOK.md)** — Development workflows: adding scrapers, job posting sources, API endpoints, map modes, conventions
- **[../CLAUDE_DATA_ENGINEERING_HANDOFF.md](../CLAUDE_DATA_ENGINEERING_HANDOFF.md)** — Data engineering guide: 6-layer architecture, ingest pipeline, validation rules, multi-industry setup
- **[../DATABASE_DESIGN_BEST_PRACTICES.md](../DATABASE_DESIGN_BEST_PRACTICES.md)** — 6-layer database architecture, metadata design, data contracts, lineage tracking

---

## Configuration

- **[../config/chains.yaml](../config/chains.yaml)** — All tunable parameters (brands, regions, scoring weights, API configs, scraper schedules)
- **[../.env.example](../.env.example)** — Environment variable templates (DATABASE_URL, BLS, Census, Reddit, Google)

---

## Code Documentation

- **[../backend/database.py](../backend/database.py)** — SQLAlchemy table definitions (schema source of truth)
- **[../backend/ingest_layer.py](../backend/ingest_layer.py)** — Single employer write path: normalize → fingerprint → brand_groups upsert → local_employers upsert
- **[../backend/scoring/engine.py](../backend/scoring/engine.py)** — How staffing-stress scores are computed
- **[../backend/targeting.py](../backend/targeting.py)** — Targeting score: staffing_stress + wage_gap + isolation + local_alternatives (mobility-weighted)
- **[../backend/baseline.py](../backend/baseline.py)** — Labor market baseline computation
- **[../scrapers/base.py](../scrapers/base.py)** — Base scraper interface and ScraperSignal dataclass

---

## Quick Navigation

### I want to...

**...understand the database**
→ Start: [DATA_DICTIONARY_README.md](./Data_Dicts/DATA_DICTIONARY_README.md)
→ Deep dive: [DATA_DICTIONARY_TABLES.md](./Data_Dicts/DATA_DICTIONARY_TABLES.md) then [DATA_DICTIONARY_COLUMNS.md](./Data_Dicts/DATA_DICTIONARY_COLUMNS.md)

**...set up the server from scratch**
→ Guide: [../RUNBOOK.md](../RUNBOOK.md) — PostgreSQL setup, populate scripts, start server

**...add a new data source**
→ Start: [../CLAUDE_DATA_ENGINEERING_HANDOFF.md](../CLAUDE_DATA_ENGINEERING_HANDOFF.md) (6-layer architecture guide)
→ Then update: [../config/chains.yaml](../config/chains.yaml), [../backend/database.py](../backend/database.py)

**...set up API keys**
→ Copy: [../.env.example](../.env.example) to `.env`
→ Required: `DATABASE_URL` (PostgreSQL connection string)
→ Optional: BLS_API_KEY, REDDIT_CLIENT_ID, etc.

**...understand the scoring system**
→ Overview: [../README.md](../README.md) — Scoring Model section
→ Code: [../backend/scoring/engine.py](../backend/scoring/engine.py)
→ Targeting: [../backend/targeting.py](../backend/targeting.py)

**...understand Career Pathfinder**
→ Data: [DATA_DICTIONARY_TABLES.md → Mobility Graph](./Data_Dicts/DATA_DICTIONARY_TABLES.md)
→ API: [../README.md](../README.md) — Mobility endpoints section
→ Frontend: [../frontend/js/pathfinder.js](../frontend/js/pathfinder.js)

**...understand Job Finder**
→ Model: [../listings/models.py](../listings/models.py) — JobPosting table (job_postings)
→ Ingest: [../listings/ingest.py](../listings/ingest.py) — single write path for all job posting sources
→ Scraper: [../scrapers/jobicy_adapter.py](../scrapers/jobicy_adapter.py) — remote jobs with hourly gate + file cache
→ API: [../README.md](../README.md) — Job Finder endpoints section
→ Frontend: [../frontend/js/jobfinder.js](../frontend/js/jobfinder.js)
→ Workflow: [../PLAYBOOK.md](../PLAYBOOK.md) — Adding a New Job Posting Source

**...see what data is stale** (weekly health check)
→ Run: `python scripts/system_health_dashboard.py`
→ Or query: `source_freshness` table (see [DATA_DICTIONARY_COLUMNS.md](./Data_Dicts/DATA_DICTIONARY_COLUMNS.md))

**...debug NULL values in the DB**
→ Open: [DATA_DICTIONARY_COLUMNS.md](./Data_Dicts/DATA_DICTIONARY_COLUMNS.md)
→ Find the column, check if Nullable=✓ (expected) or ✗ (indicates bug)

---

## Archive

Historical snapshots moved to `docs/archive/` — kept for reference, no longer authoritative:

| File | Reason archived |
|------|----------------|
| [archive/DATABASE_ASSESSMENT.md](./archive/DATABASE_ASSESSMENT.md) | Described SQLite schema with 0 rows; DB is now PostgreSQL |
| [archive/FRESH_START_STATUS.md](./archive/FRESH_START_STATUS.md) | Recorded the fresh-start event; that event is complete |
| [archive/DESIGN_FLAW_FOOD_SERVICE_ONLY.md](./archive/DESIGN_FLAW_FOOD_SERVICE_ONLY.md) | Flaw resolved; all 638 occupations loaded across all industries |
