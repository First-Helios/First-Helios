# First-Helios Documentation

## Helios Deployment (Start Here)
Comprehensive project documentation — platform overview, data architecture, privacy, and progress tracking.

- [Documentation Index](HeliosDeployment/README.md) — Entry point to all deployment docs
- [Platform Overview](HeliosDeployment/01_PLATFORM_OVERVIEW.md) — What First Helios is, three-repo architecture, data domains
- [Data Architecture](HeliosDeployment/02_DATA_ARCHITECTURE.md) — 6-layer model, 48 tables, write paths, metadata system
- [SpiritPool Intake Pipeline](HeliosDeployment/03_SPIRITPOOL_INTAKE_PIPELINE.md) — FH-0/FH-1 contributor pipeline, endpoints, processing flow
- [Privacy & Governance](HeliosDeployment/04_PRIVACY_AND_GOVERNANCE.md) — IP suppression, PII quarantine, 18 non-negotiable rules
- [Deployment Progress](HeliosDeployment/05_DEPLOYMENT_PROGRESS.md) — Tier checklists, what's built, what's next
- [Infrastructure & Operations](HeliosDeployment/06_INFRASTRUCTURE.md) — OrangePi host, systemd, scheduler, rate management

## Architecture
How the system is designed and why.

- [Database Design](architecture/DATABASE_DESIGN_BEST_PRACTICES.md) — 6-layer DB architecture, metadata contracts, audit trail patterns
- [Data Streams](architecture/DATA_STREAMS.md) — Every data source, collection method, DB table, and downstream consumer
- [PII Filter Guide](architecture/PII_FILTER_GUIDE.md) — How to view quarantined data, why fields are filtered, and how to add exemptions or dead-weight rules
- [Dev Capture Mode ADR](architecture/ADR_DEV_MODE.md) — Decision record for raw signal A/B comparison in dev schema

## Events Hub
Multi-source event aggregation for Austin.

- [Event Sources Catalog](../config/event_sources.yaml) — Master list of all event sources by tier (6 live, 14 future)
- Event collectors use a decorator-based plugin system: see `collectors/events/registry.py`
- Schema: `venues`, `events`, `event_interactions` tables — see [Data Dictionary](data/dictionary/DATA_DICTIONARY_TABLES.md)

## Data

- [BLS Ground Truth Guide](data/BLS_GROUND_TRUTH_GUIDE.md) — QCEW, JOLTS, LAUS, OEWS, CBP: update cadence, what you get, how they feed the scoring engine

### Data Dictionary
- [Overview & Template](data/dictionary/DATA_DICTIONARY_README.md) — How to use the dictionary; step-by-step template for adding new sources
- [Tables](data/dictionary/DATA_DICTIONARY_TABLES.md) — All tables by logical schema layer (operational, ground-truth, derived, reference, mobility, metadata)
- [Columns](data/dictionary/DATA_DICTIONARY_COLUMNS.md) — Column-level reference: type, nullability, examples, SLA

### Data Ingestion
- [Ingestion Summary](data/ingestion/DATA_INGESTION_SUMMARY.md) — Current ingestion status by source, expected row counts, what's still missing
- [OEWS Ingestion](data/ingestion/OEWS_DATA_INGESTION_SUMMARY.md) — Austin MSA OEWS: 638 occupations across 23 industry groups

## Guides
How-to docs for contributors.

- [Geocoding Guide](guides/GEOCODING_AGENT.md) — Rules for extracting geocodable locations from job APIs; checklist for new adapters
- [Meal Deal Replay Workflow](guides/MEAL_DEAL_REPLAY_WORKFLOW.md) — How to sync, summarize, manifest, and replay website scrape bundles locally
- [Meal Deal Scraper Signal Refinement Roadmap](guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md) — Open website scraper tasks grouped by complexity and recommended agent power
- [Spirit Pool Integration](guides/SPIRIT_POOL_INTEGRATION.md) — Browser extension integration: what's built, what remains, signal format

---


## Quick Navigation

| I want to... | Go to |
|---|---|
| Understand the database schema | [Data Dictionary](data/dictionary/DATA_DICTIONARY_README.md) |
| Set up the backend server | [RUNBOOK.md](../RUNBOOK.md) |
| Add a new data collector | [PLAYBOOK.md](../PLAYBOOK.md) + [Data Streams](architecture/DATA_STREAMS.md) |
| Add a new event collector | [PLAYBOOK.md](../PLAYBOOK.md) § "Adding a New Event Collector" + [Event Sources](../config/event_sources.yaml) |
| Understand the scoring system | [README.md](../README.md) → Scoring Model |
| Add a scheduled job | `config/scheduler.yaml` + `core/scheduler.py` |
| Recover missed schedules | [Missed Schedule Recovery](guides/MISSED_SCHEDULE_RECOVERY.md) |
| Debug NULL values | [Columns dictionary](data/dictionary/DATA_DICTIONARY_COLUMNS.md) |
| Check data freshness | `python scripts/system_health_dashboard.py` |
| Understand BLS data lag | [BLS Ground Truth Guide](data/BLS_GROUND_TRUTH_GUIDE.md) |

---

## Cross-Repo Architecture

This documentation is for the **backend/API** only. For the full platform:

- **Frontend:** [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend)
- **Host/infra:** [First-Helios_Orangepi_Host](https://github.com/4Fortune8/First-Helios_Orangepi_Host)

See those repos for UI, deployment, and systemd/nginx configuration.
