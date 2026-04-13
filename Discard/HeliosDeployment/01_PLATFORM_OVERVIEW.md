# 1. Platform Overview

> **Audience:** Anyone encountering this project for the first time — developers, agents, or stakeholders.

---

## What Is First Helios?

First Helios is a **broad-scope data intelligence platform** for the Austin, TX regional labor market. It ingests, documents, and serves structured data across every domain relevant to workers and community — jobs, events, businesses, wages, economic indicators, and career mobility — into dashboards people actually use.

> Austin first. One city done right before scaling.

---

## The Five Dashboards

| Dashboard | What It Shows |
|-----------|--------------|
| **Job Fair Targeting** | Which employers to prioritize for outreach based on staffing stress, wage gaps, and worker isolation |
| **Career Pathfinder** | Realistic lateral and upward career moves with wage data and nearby employers |
| **Job Finder** | Active job postings mapped by H3 hex cell across Austin |
| **Events Hub** | Local events from 6+ sources with venue mapping and social-density scoring |
| **Business Intelligence** | 45K+ employer locations with brand clustering, industry classification, and mobility scoring |

Everything in the backend exists to feed these dashboards with accurate, fresh, documented data.

---

## How Data Enters the System

Data arrives from two paths:

### 1. Automated Collectors (50+ API Sources)

Scheduled jobs pull from public data sources on cron schedules:

| Domain | Sources | Examples |
|--------|---------|---------|
| **Jobs** | 8+ adapters | JobSpy, SerpAPI, Jobicy, TheirStack, Workday, USA Jobs, ActiveJobs |
| **Events** | 6 live collectors | Ticketmaster, Eventbrite, Meetup, Do512, Austin City Calendar, Visit Austin |
| **Labor Market** | 5 BLS programs | QCEW, JOLTS, OEWS, LAUS, CBP — ground-truth economic data |
| **Employers** | 3 geo sources | Overture Maps (45K+ POIs), AllThePlaces, OpenStreetMap |
| **Sentiment** | 2 sources | Reddit, Google Maps reviews |

Collectors run via APScheduler (29 scheduled jobs in `core/scheduler.py`, configured via `config/scheduler.yaml`). Rate limits are managed per-source in `rate_budgets`.

### 2. SpiritPool Contributors (Browser Extension)

Real people run the **SpiritPool browser extension** (Manifest V3, Firefox) and donate signals as they browse job boards, business directories, and event sites. The extension:

- Extracts structured data from allowlisted sites (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Maps, Google Jobs)
- Caches signals locally in `browser.storage.local`
- Periodically flushes to `POST /api/contribute` on First Helios

Contributors participate because the system earns trust through three commitments:

1. **Secure data & profiles** — PII is quarantined, not stored. IPs are never logged. Session tokens are opaque and unrecoverable.
2. **Transparent systems** — Every table is documented in the metadata catalog. Every data flow has lineage. Collection health is visible.
3. **Broad collection under trust** — Collect widely, govern responsibly, show your work.

---

## Data Domains

| Domain | What Gets Collected | Where It Lives |
|--------|-------------------|---------------|
| **Jobs** | Active postings, salary data, applicant counts, hiring badges | `job_postings`, `sp_events` |
| **Events** | Local events with dates, venues, categories, images | `events`, `venues`, `sp_events` |
| **Business** | Employer locations, brand profiles, reviews, ratings | `local_employers`, `brand_groups`, `sp_events` |
| **Wages** | Occupation-level wage data (hourly, annual) by industry | `oews_data`, `wage_index` |
| **Labor Market** | Employment counts, job openings, unemployment, business patterns | `qcew_data`, `jolts_data`, `laus_data`, `cbp_data` |
| **Mobility** | SOC occupation transitions, wage trajectories, career paths | `mob_occupations`, `mob_transitions` |

---

## Repository Structure

```
First-Helios/
├── server.py                    # Flask app — API server (port 8765)
├── collector_main.py            # Standalone scheduler entry point
│
├── core/                        # Core pipeline + scoring + privacy
│   ├── database.py              # SQLAlchemy ORM (48 tables), engine, Base class
│   ├── contribute_routes.py     # POST /api/contribute + POST /api/burn (FH-0)
│   ├── privacy.py               # Field stripping + PII detection (FH-1)
│   ├── ingest.py                # ScraperSignal → signals / scores
│   ├── ingest_layer.py          # Employer write path → local_employers
│   ├── scheduler.py             # 29+ APScheduler jobs
│   ├── rate_manager.py          # API quota enforcement
│   ├── metadata.py              # MetaTableCatalog, MetaColumnCatalog, MetaDataLineage
│   ├── scoring/                 # Staffing stress engine, careers, sentiment, wages
│   └── models/
│       ├── reference.py         # Taxonomy, brand profiles, mobility data
│       └── spiritpool.py        # SpEvent, Quarantine, SessionEpoch, BurnPool, Contributor
│
├── collectors/                  # All automated data collection
│   ├── job_boards/              # 8 job source adapters
│   ├── events/                  # 6 event source collectors (plugin registry)
│   ├── labor_data/              # BLS adapters (QCEW, JOLTS, OEWS, LAUS, CBP)
│   ├── employer_data/           # Overture Maps, AllThePlaces, OSM
│   └── sentiment/               # Reddit, Google Maps reviews
│
├── postings/                    # Job posting pipeline
│   ├── ingest.py                # Normalize → geocode → H3 → match → upsert
│   ├── models.py                # JobPosting ORM model
│   └── spiritpool_routes.py     # Legacy /api/spiritpool/contribute (v1)
│
├── events/                      # Automated events hub
│   ├── models.py                # Venue, Event, EventInteraction ORM models
│   ├── ingest.py                # Event write path
│   └── routes.py                # Events API endpoints
│
├── config/                      # YAML configuration
│   ├── scheduler.yaml           # Cron schedules for all jobs
│   ├── event_sources.yaml       # Event collector registry
│   └── labor_market.yaml        # BLS MSA codes, SOC configs
│
├── scripts/                     # One-time data population + maintenance
│   ├── populate_metadata.py     # Register all tables/columns/lineage
│   ├── system_health_dashboard.py  # SLA monitoring
│   └── ...                      # Geocoding, H3, taxonomy, mobility scripts
│
├── docs/                        # Documentation
│   ├── HeliosDeployment/        # ← YOU ARE HERE
│   ├── architecture/            # DB design, data streams
│   ├── contracts/               # Data SLA contracts
│   ├── data/                    # Dictionary, ingestion guides
│   └── guides/                  # Spirit Pool, geocoding, missed schedules
│
├── agentMailbox/                # Handoff specs for AI agents
│   ├── FH-0_intake_foundation.md  # Forward-compatible schema spec
│   ├── FH-1_backend_hardening.md  # Privacy controls spec
│   ├── FH-2_source_onboarding.md  # Per-source dedup and payload shapes
│   └── SPIRITPOOL_CONTEXT.md      # Privacy contract governing all data handling
│
├── alembic/                     # Database migrations
└── tests/                       # Test suite
```

---

## Technology Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| **Web server** | Flask + Gunicorn | 9 workers, 2 threads, port 8765 behind nginx |
| **Database** | PostgreSQL 14 | Production. SQLite for local dev. |
| **ORM** | SQLAlchemy 2.x | DeclarativeBase, 48 tables |
| **Migrations** | Alembic | 4 migration files in `alembic/versions/` |
| **Scheduler** | APScheduler | BackgroundScheduler, cron + interval triggers |
| **Hardware** | Orange Pi 5 Plus | ARM64/RK3588, 32GB RAM, Ubuntu 22.04 headless |
| **Deployment** | systemd + auto-pull | `helios-update.timer` polls GitHub every 5 min |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Austin only** | Prove the model in one city before scaling. All data scoped to Austin MSA. |
| **Three repos** | Backend, frontend, and host infra are independent. One can be deployed without the others. |
| **SpiritPool table named `sp_events`** | The `events` table was already taken by the automated events collector (Ticketmaster, Eventbrite). Both coexist. |
| **No FK from sp_events → session_epochs** | Relationship is via text match on `session_token`, not a foreign key. Enables forward compatibility across Helios eras. |
| **JSONB payload** | SpiritPool payloads must accept unknown fields from future eras. JSONB stores them without schema changes. |
| **IP never stored** | Flask's `request.remote_addr` is overridden to `0.0.0.0`. Log formatters strip IPs. This is structural, not policy. |
| **Metadata-first** | No table may accept data until it's registered in `meta_table_catalog`. Policy rule #11. |
