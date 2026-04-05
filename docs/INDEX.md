# First-Helios Documentation

## Architecture
How the system is designed and why.

- [Database Design](architecture/DATABASE_DESIGN_BEST_PRACTICES.md) — 6-layer DB architecture, metadata contracts, audit trail patterns
- [Data Streams](architecture/DATA_STREAMS.md) — Every data source, collection method, DB table, and downstream consumer

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
