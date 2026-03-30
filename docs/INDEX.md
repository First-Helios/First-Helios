# First-Helios Documentation

## Architecture
How the system is designed and why.

- [Database Design](architecture/DATABASE_DESIGN_BEST_PRACTICES.md) — 6-layer DB architecture, metadata contracts, audit trail patterns
- [Data Streams](architecture/DATA_STREAMS.md) — Every data source, collection method, DB table, and downstream consumer

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
| Set up the server from scratch | [RUNBOOK.md](../RUNBOOK.md) |
| Add a new data collector | [PLAYBOOK.md](../PLAYBOOK.md) + [Data Streams](architecture/DATA_STREAMS.md) |
| Understand the scoring system | [README.md](../README.md) → Scoring Model |
| Add a scheduled job | `config/scheduler.yaml` + `core/scheduler.py` |
| Debug NULL values | [Columns dictionary](data/dictionary/DATA_DICTIONARY_COLUMNS.md) |
| Check data freshness | `python scripts/system_health_dashboard.py` |
| Understand BLS data lag | [BLS Ground Truth Guide](data/BLS_GROUND_TRUTH_GUIDE.md) |
