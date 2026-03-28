# Documentation Index — First-Helios

**Last Updated:** 2026-03-27 (scheduler setup, USAJobs + WorkdayGov added)

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

- **[../config/scheduler.yaml](../config/scheduler.yaml)** — All 17 scheduled job definitions: cron times, `enabled` flags, descriptions. Edit here to change schedules or disable jobs.
- **[../config/chains.yaml](../config/chains.yaml)** — Manually maintained employer chain definitions (Starbucks, Dutch Bros) and gov employer portals
- **[../config/labor_market.yaml](../config/labor_market.yaml)** — Auto-generated from OEWS: regions, scoring weights, BLS params (do not hand-edit)
- **[../.env.example](../.env.example)** — Environment variable templates (DATABASE_URL, BLS, Census, Reddit, Google, USAJobs)

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
→ Scrapers: [../scrapers/jobicy_adapter.py](../scrapers/jobicy_adapter.py) (remote, hourly gate), [../scrapers/usajobs_adapter.py](../scrapers/usajobs_adapter.py) (federal), [../scrapers/workday_gov_adapter.py](../scrapers/workday_gov_adapter.py) (City of Austin)
→ API: [../README.md](../README.md) — Job Finder endpoints section
→ Frontend: [../frontend/js/jobfinder.js](../frontend/js/jobfinder.js)
→ Workflow: [../PLAYBOOK.md](../PLAYBOOK.md) — Adding a New Job Posting Source

**...add or change a scheduled job**
→ Schedule config: [../config/scheduler.yaml](../config/scheduler.yaml) — set `enabled: false` to pause, edit `cron:` to reschedule
→ Job functions: [../backend/scheduler.py](../backend/scheduler.py) — `_run_<id>()` functions, one per job
→ Ops guide: [../RUNBOOK.md](../RUNBOOK.md) — full schedule table with descriptions

**...see what data is stale** (weekly health check)
→ Run: `python scripts/system_health_dashboard.py`
→ Or query: `source_freshness` table (see [DATA_DICTIONARY_COLUMNS.md](./Data_Dicts/DATA_DICTIONARY_COLUMNS.md))

**...debug NULL values in the DB**
→ Open: [DATA_DICTIONARY_COLUMNS.md](./Data_Dicts/DATA_DICTIONARY_COLUMNS.md)
→ Find the column, check if Nullable=✓ (expected) or ✗ (indicates bug)

---

## Roadmap

Ordered by priority. "Foundation" items unblock later work.

### Near-term — Data Pipeline

| Item | Status | Notes |
|------|--------|-------|
| USAJobs federal listings | ✅ Done | `scrapers/usajobs_adapter.py` — requires `USAJOBS_API_KEY` + `USAJOBS_EMAIL` in `.env` |
| City of Austin Workday | ✅ Done | `scrapers/workday_gov_adapter.py` — salary parsed from HTML description |
| Scheduler operational | ✅ Done | `config/scheduler.yaml` owns all 17 jobs; `enabled` flag per job |
| WorkdayGov description parsing | 🔧 Incomplete | Section extraction works for most COA posts; edge cases exist where salary/location are in non-standard HTML structures — improve `_extract_sections()` and `_parse_salary_from_sections()` as more real examples surface |
| Additional government job portals | 🔜 Planned | Travis County, Austin ISD, UT Austin — all use Workday; add entries to `WORKDAY_GOV_SITES` in `workday_gov_adapter.py` |
| Texas state agency jobs | 🔜 Planned | CAPPS/WorkInTexas portal — separate adapter needed |

### Near-term — Scoring & Intelligence

| Item | Status | Notes |
|------|--------|-------|
| Multi-industry scoring config | 🔧 Partial | Scoring weights in `config/labor_market.yaml` work for food service; other industries need tuning |
| Job posting → employer match improvement | 🔜 Planned | `PROXIMITY_THRESHOLD_M = 150` (half a block) misses some valid matches; consider fuzzy name matching as secondary pass |
| Federal/gov jobs in Job Fair map | 🔜 Planned | USAJobs and WorkdayGov postings are ingested but not yet surfaced on the h3 map as a distinct filter layer |

### Medium-term — Staffing Intelligence Engine

This is the core product goal from `Todos/StaffingEngine.md`:

| Item | Status | Notes |
|------|--------|-------|
| Staffing capacity model | 🔜 Planned | Estimate max staffing from store sq-ft + industry benchmarks (Space-to-Service formula) |
| Review sentiment NLP | 🔜 Planned | Flag "understaffed", "short-staffed", "wait time" keywords in scraped Google/Yelp reviews — extend `reviews_adapter.py` |
| Labor Pressure Index | 🔜 Planned | Composite 1–100 score: staffing stress + wage gap + dwell-time signal + review sentiment |
| Recruitment heatmap | 🔜 Planned | Overlay "short-staffed" flags with BLS unemployment by ZIP — identify easy-hire zones |

### Longer-term — Data Enrichment

| Item | Status | Notes |
|------|--------|-------|
| Mobile dwell-time signal | 💡 Research | Placer.ai / Near / Advan trial — anonymized pings to estimate current staff vs. customers |
| Revelio Labs historical headcount | 💡 Research | Tables exist (`revelio_*`) but data unpopulated; licensing required |
| Property tax / sq-ft data | 💡 Research | Austin Open Data portal has parcel records — free, no API key |
| Competitor service decay tracking | 💡 Research | Track staffing-stress trend slope over 90-day windows per chain location |

---

## Archive

Historical snapshots moved to `docs/archive/` — kept for reference, no longer authoritative:

| File | Reason archived |
|------|----------------|
| [archive/DATABASE_ASSESSMENT.md](./archive/DATABASE_ASSESSMENT.md) | Described SQLite schema with 0 rows; DB is now PostgreSQL |
| [archive/FRESH_START_STATUS.md](./archive/FRESH_START_STATUS.md) | Recorded the fresh-start event; that event is complete |
| [archive/DESIGN_FLAW_FOOD_SERVICE_ONLY.md](./archive/DESIGN_FLAW_FOOD_SERVICE_ONLY.md) | Flaw resolved; all 638 occupations loaded across all industries |
