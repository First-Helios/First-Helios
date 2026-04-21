# 2. Data Architecture

> **Audience:** Developers and agents working with the database, adding tables, or debugging data flows.

---

## The 6-Layer Model

All tables in First Helios belong to one of six logical layers. Data flows downward — raw → operational → business. Reference data feeds any layer. Metadata tracks everything.

```
┌───────────────────────────────────────────────────────────────────┐
│  LAYER 1: RAW — Untransformed external data                      │
│  Tables: qcew_data, jolts_data, oews_data, laus_data, cbp_data   │
│  Principle: Append-only, immutable, timestamped                   │
└───────────────────────────────────────────────────────────────────┘
                              ↓
┌───────────────────────────────────────────────────────────────────┐
│  LAYER 2: OPERATIONAL — Normalized, geocoded, deduplicated        │
│  Tables: signals, wage_index, job_postings, events, venues,       │
│          sp_events, local_employers, brand_groups                  │
│  Principle: Single record per entity, dedup keys enforced         │
└───────────────────────────────────────────────────────────────────┘
                              ↓
┌───────────────────────────────────────────────────────────────────┐
│  LAYER 3: BUSINESS — Computed scores and indices                  │
│  Tables: scores, targeting_results                                │
│  Principle: Reproducible, version-tracked, re-computable          │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  LAYER 4: REFERENCE — Lookup tables, taxonomies, brand profiles   │
│  Tables: industry_taxonomy, brand_profiles, region_profiles,      │
│          soc_major_groups, mob_occupations, mob_transitions,       │
│          occupation_aliases, category_mappings                     │
│  Principle: Curated, versioned, feeds into any layer              │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  LAYER 5: METADATA — System intelligence and audit trail          │
│  Tables: meta_table_catalog, meta_column_catalog,                 │
│          meta_data_lineage, meta_job_runs                         │
│  Principle: Documents everything, breaks nothing                  │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│  LAYER 6: BRONZE — Raw API payloads for replay                    │
│  Tables: bronze_event_payloads                                    │
│  Principle: Immutable archive, enables re-processing              │
└───────────────────────────────────────────────────────────────────┘
```

---

## Table Inventory (48 Tables)

### Raw Layer
| Table | Source | Update Cadence |
|-------|--------|---------------|
| `qcew_data` | BLS QCEW — establishment counts, wages | Quarterly (5-month lag) |
| `jolts_data` | BLS JOLTS — job openings, hires, separations | Monthly (2-month lag) |
| `oews_data` | BLS OEWS — occupation wages by industry | Annual (10-month lag) |
| `laus_data` | BLS LAUS — unemployment rates | Monthly (1-month lag) |
| `cbp_data` | Census CBP — business patterns by industry | Annual (18-month lag) |

### Operational Layer
| Table | Purpose | Dedup Key |
|-------|---------|-----------|
| `signals` | Normalized observations from all automated sources | `(source, external_id)` |
| `job_postings` | Geocoded, H3-indexed job listings | `(source, external_id)` |
| `events` | Automated event collection (Ticketmaster, Eventbrite, etc.) | `(source, external_id)` |
| `venues` | Event venue locations with geocoding | `(source, venue_id)` |
| `sp_events` | SpiritPool contributor signals (FH-0) | `(session_token, epoch_id, event_type)` |
| `local_employers` | 45K+ employer locations from Overture/ATP/OSM | `(fingerprint, lat/lng proximity)` |
| `brand_groups` | Parent brand profiles for employer clustering | `(name, industry)` |
| `wage_index` | Processed wage benchmarks by occupation | `(soc_code, area)` |
| `session_epochs` | SpiritPool session token lifecycle | `(session_token)` UNIQUE |
| `burn_pool` | Monthly aggregate of burned sessions | `(month_key, session_token)` |
| `contributors` | Anonymous contributor volume tracking | `(id)` |
| `quarantine` | PII-flagged payloads — never exposed externally | `(quarantine_id)` |

### Business Layer
| Table | Purpose |
|-------|---------|
| `scores` | Staffing stress scores per employer location |
| `targeting_results` | Job fair targeting recommendations |

### Reference Layer
| Table | Purpose |
|-------|---------|
| `industry_taxonomy` | Industry classification hierarchy |
| `brand_profiles` | Brand-level aggregations (avg wage, headcount) |
| `region_profiles` | Regional economic profiles |
| `soc_major_groups` | SOC occupation group headers |
| `mob_occupations` | Career mobility occupation data |
| `mob_transitions` | SOC-to-SOC transition probabilities |
| `occupation_aliases` | Common titles mapping to SOC codes |
| `category_mappings` | Industry category cross-references |

### Metadata Layer
| Table | Purpose |
|-------|---------|
| `meta_table_catalog` | Registry of every table — layer, source, entity, purpose, owner |
| `meta_column_catalog` | Column documentation — type, unit, valid range, SLA |
| `meta_data_lineage` | Source → target transformation documentation |
| `meta_job_runs` | Ingest job audit trail — rows processed, status, errors |
| `api_sources` | External API registry — auth type, daily limit |
| `api_request_log` | Per-request audit — latency, status, rate limit state |
| `rate_budgets` | Daily rate limit tracking per API source |

### Bronze Layer
| Table | Purpose |
|-------|---------|
| `bronze_event_payloads` | Raw Ticketmaster/Eventbrite JSON for replay |

---

## The Three Write Paths

Data enters operational tables through exactly three sanctioned write paths. Never insert directly.

### 1. Employer Records
```
core/ingest_layer.py:ingest_employer(signal, region)
```
Pipeline: normalize → fingerprint → upsert `brand_groups` → upsert `local_employers`

### 2. Job Postings
```
postings/ingest.py:ingest_job_posting(signal, region)
```
Pipeline: normalize → geocode → assign H3 cell → match to employer → upsert `job_postings`

### 3. Events (Automated)
```
events/ingest.py:ingest_event(signal, region, session)
```
Pipeline: validate → dedup by `(source, external_id)` → upsert `venues` → upsert `events`

### 4. Contributor Signals (SpiritPool — NEW)
```
POST /api/contribute → core/contribute_routes.py
```
Pipeline: strip forbidden fields → validate → server-set fields → PII scan → route to `sp_events` or `quarantine` → auto-create `session_epochs`

---

## Metadata System

Every table in First Helios is documented in the metadata layer. This is not optional — it's policy rule #11.

### meta_table_catalog
Registers every table with: `table_name`, `schema_layer`, `source`, `entity`, `purpose`, `owner_team`, `sla_freshness_days`.

### meta_column_catalog
Documents every meaningful column with: `column_name`, `table_name`, `description`, `data_type`, `unit`, `valid_range_min`, `valid_range_max`, `sla_null_allowed`.

### meta_data_lineage
Maps every data flow: `source_table` → `target_table` with `transformation_type`, `description`, `schedule`.

### meta_job_runs
Audit trail for every ingest job: `job_id`, `run_timestamp`, `rows_processed`, `rows_inserted`, `rows_skipped`, `status`, `error_message`.

### How to populate metadata
```bash
python scripts/one_shot/populate_metadata.py
```
This is idempotent — safe to run repeatedly. New entries are inserted, existing entries are updated.

### How to verify metadata completeness
```bash
python scripts/system_health_dashboard.py
```
Shows freshness SLAs, stale tables, undocumented columns, and job run failures.

---

## Data Contracts

Tables that serve downstream consumers (scoring, dashboards, APIs) have formal contracts in `docs/contracts/`. Each contract defines:

- **Schema** — exact columns, types, constraints
- **SLAs** — freshness, null tolerance, coverage scope
- **Consumers** — who depends on this table and how
- **What can break** — known fragility points
- **Fallback** — what happens when the source is unavailable

Current contracts:

| Contract | Table | Layer |
|----------|-------|-------|
| [sp_events_contract.md](../contracts/sp_events_contract.md) | `sp_events` | Operational |
| [quarantine_contract.md](../contracts/quarantine_contract.md) | `quarantine` | Metadata |
| [session_epochs_contract.md](../contracts/session_epochs_contract.md) | `session_epochs` | Operational |
| [burn_pool_contract.md](../contracts/burn_pool_contract.md) | `burn_pool` | Operational |

---

## Data Lineage (Current Flows)

```
External APIs ──────► raw layer (qcew_data, jolts_data, ...)
                            │
                            ▼
                     operational (signals, wage_index, job_postings)
                            │
                            ▼
                     business (scores, targeting_results)

Event APIs ─────────► bronze_event_payloads ──► events / venues

Overture/ATP/OSM ───► local_employers / brand_groups

SpiritPool POST ────► sp_events ──► scores (planned)
              │              │
              │              └──► session_epochs ──► contributors
              │
              └────► quarantine (PII path)

Burn POST ──────────► burn_pool
```

Full lineage is queryable:
```sql
SELECT source_table, target_table, transformation_type, description
FROM meta_data_lineage
WHERE deprecated_at IS NULL
ORDER BY source_table;
```

---

## Deduplication Keys

Every operational table has documented dedup keys. These are enforced at the database level via unique indexes or constraints.

| Table | Dedup Key | Enforcement |
|-------|-----------|-------------|
| `job_postings` | `(source, external_id)` | Unique index |
| `events` | `(source, external_id)` | Unique index |
| `local_employers` | `(fingerprint, lat/lng proximity)` | Fingerprint match + distance check |
| `sp_events` | `(session_token, epoch_id)` index | Composite index (not unique — multiple event types per epoch) |
| `session_epochs` | `(session_token)` | UNIQUE constraint |
| `burn_pool` | `(month_key, session_token)` | UNIQUE constraint |

---

## Database Access

### Production (OrangePi)
```
postgresql+psycopg://helios:helios@localhost:5432/helios
```

### Local Development
Falls back to SQLite if `DATABASE_URL` is not set:
```
sqlite:///data/tracker.db
```

### Connection pattern
```python
from core.database import get_engine, get_session, init_db

engine = init_db()        # Creates tables if needed, returns engine
session = get_session(engine)
try:
    # ... queries ...
    session.commit()
finally:
    session.close()
```
