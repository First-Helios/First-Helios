# First-Helios

A public labor market intelligence platform for Austin, TX. Four tools in one:

- **Job Fair Targeting** — helps organizers identify which employers to prioritize for outreach based on staffing stress, wage gaps, and worker isolation
- **Career Pathfinder** — shows workers realistic lateral and upward moves with wage data and nearby employers
- **Job Finder** — maps active job postings by H3 hex cell across Austin
- **Events Hub** — aggregates local events from 6+ sources (Ticketmaster, Eventbrite, Meetup, Do512, City of Austin, Visit Austin) with venue mapping and social-density scoring

> Austin first. One city done right before scaling.

---

## Architecture

```
Browser (plain HTML/CSS/JS)
        │
      nginx (:80)
        │
   Gunicorn (9 workers)
        │
   Flask — server.py (:8765)
        │
   ┌────┴────────────────────────────────┐
   │                │                    │
core/           postings/           events/
ingest_layer.py ingest.py           ingest.py
ingest.py       matcher.py          models.py
normalizer.py   models.py           routes.py
scoring/
rate_manager.py
        │
   PostgreSQL 14
        ↑
collectors/  ←  collector_main.py (APScheduler)
job_boards/
labor_data/
employer_data/
events/          ←  plugin registry (auto-discovered)
sentiment/
```

Data flows:

```
collectors/       →  ScraperSignal  →  core/ingest.py      →  signals / scores / wage_index
                                    →  postings/ingest.py  →  job_postings

collectors/events/ →  @event_collector registry  →  events/ingest.py  →  venues / events

Overture POI      →  core/ingest_layer.py  →  local_employers / brand_groups
```

---

## Infrastructure

| Component | Detail |
|-----------|--------|
| Hardware | Orange Pi 5 Plus — ARM64/RK3588, 32GB RAM |
| OS | Ubuntu Jammy (22.04), headless |
| LAN address | 192.168.0.104 |
| Web server | nginx → Gunicorn (9 workers, 2 threads) → Flask |
| Database | PostgreSQL 14 |
| Process mgmt | systemd (helios, helios-collector, nginx, postgresql, cpugov) |
| Auto-deploy | Pulls from GitHub every 5 min via `helios-update.timer` |
| Repo | https://github.com/4Fortune8/First-Helios.git |

---

## Repo Structure

```
First-Helios/
├── server.py                    # Flask app (port 8765)
├── collector_main.py            # Standalone collector / scheduler runner
├── requirements.txt
│
├── collectors/                  # All data collection
│   ├── base.py                  # BaseScraper + ScraperSignal dataclass
│   ├── cache.py                 # File cache utilities
│   ├── geocoding.py             # Nominatim + facility index overrides
│   ├── rotation.py              # Industry tag rotation (SerpAPI, Jobicy)
│   ├── job_boards/              # jobspy, jobicy, serpapi, usajobs, workday_gov,
│   │                            #   activejobs, juju, theirstack adapters
│   ├── labor_data/              # bls, qcew, cbp, nlrb, warn adapters
│   ├── employer_data/           # overture, alltheplaces, osm adapters
│   ├── events/                  # ticketmaster, eventbrite, meetup, do512,
│   │                            #   austin_city_calendar, austintexas_org
│   │                            #   + registry.py (decorator-based plugin system)
│   └── sentiment/               # reddit, reviews adapters
│
├── core/                        # Core pipeline + scoring
│   ├── database.py              # SQLAlchemy models (43 tables) + init
│   ├── ingest.py                # ScraperSignal → signals / scores
│   ├── ingest_layer.py          # Employer write path → local_employers / brand_groups
│   ├── normalizer.py            # Zero-DB normalization (upstream of ingest_layer)
│   ├── scheduler.py             # APScheduler job definitions (29 jobs)
│   ├── rate_manager.py          # API quota enforcement
│   ├── baseline.py              # Labor market baseline computation
│   ├── targeting.py             # Targeting score computation
│   └── scoring/                 # engine.py, careers.py, sentiment.py, wage.py
│
├── postings/                    # Job posting models + ingest pipeline
│   ├── ingest.py                # Single write path: normalize → geocode → H3 → match → upsert
│   ├── matcher.py               # Match posting to LocalEmployer by fingerprint + proximity
│   ├── models.py                # JobPosting SQLAlchemy model
│   └── config.py                # TTL, proximity threshold, match confidence
│
├── events/                      # Events hub silo
│   ├── models.py                # Venue, Event, EventInteraction SQLAlchemy models
│   ├── ingest.py                # Event write path
│   └── routes.py                # Events API endpoints
│
├── config/
│   ├── loader.py                # Typed config access
│   ├── scheduler.yaml           # Cron schedules + enabled flags for all 29 jobs
│   ├── event_sources.yaml       # Event source catalog (6 live, 14 future)
│   └── search_rotation.yaml     # 20-entry industry rotation for SerpAPI + Jobicy
│
├── frontend/                    # Static SPA — no build step
│   ├── index.html
│   ├── css/style.css
│   └── js/                      # app.js, jobfinder.js, ...
│
├── scripts/                     # One-time data population scripts
├── notebooks/                   # Exploration notebooks
└── dev/
    ├── opi5_setup.sh            # Orange Pi provisioning script
    ├── update.sh                # Auto-deploy script (run by helios-update.timer)
    └── sync_from_opi.sh         # Pull live DB snapshot from OPi → local
```

---

## Quickstart (local dev)

```bash
git clone https://github.com/4Fortune8/First-Helios.git
cd First-Helios

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios
```

**Pull live data from OPi (requires LAN access to 192.168.0.104):**
```bash
bash dev/sync_from_opi.sh     # ~30s stream from OPi PostgreSQL → local
bash dev/sync_from_opi.sh --dry-run   # compare row counts without syncing
```

**Or populate from scratch** — see RUNBOOK.md for script order.

```bash
python server.py              # http://localhost:8765
```

**Run or test the collector:**
```bash
python collector_main.py --list-jobs          # see all job IDs (* = included in --run-now)
python collector_main.py --job jobicy         # fire one job by ID
python collector_main.py --run-now            # fire all daily jobs sequentially
python collector_main.py                      # start persistent scheduler
```

---

## Database

43 tables across 7 logical schemas. Key tables:

| Table | Rows | Description |
|-------|------|-------------|
| `mob_transition` | 256,831 | SOC → SOC career transition edges |
| `ref_texaswages` | 86,528 | Texas wage reference by occupation |
| `local_employers` | 45,618 | Austin employer POIs from Overture Maps |
| `ref_employer_name_index` | 37,128 | Employer name normalization index |
| `brand_groups` | 36,563 | Deduplicated employer brand clusters |
| `revelio_employment` | 23,188 | Employment signal data |
| `revelio_hiring` | 23,188 | Hiring signal data |
| `ref_occupation_aliases` | 18,981 | Census job-title aliases (Pathfinder autocomplete) |
| `scores` | 16,363 | Composite staffing stress scores |
| `venues` | — | Event venue POIs with H3 cells (new) |
| `events` | — | Multi-source event aggregation (new) |
| `event_interactions` | — | User interaction tracking stub (new) |
| **Total DB** | — | **249 MB** |

> Row counts as of 2026-04-03. The collector adds new rows daily.

---

## API Endpoints

### Map Data
| Endpoint | Description |
|----------|-------------|
| `GET /api/map-employers?region=austin_tx` | Unified chain + local employer map data |
| `GET /api/map-employers?region=austin_tx&h3_cell=<id>&resolution=<n>` | Employers in one H3 cell |
| `GET /api/ref/summary?region=austin_tx` | Chains + industries for filter dropdowns |

### Job Finder
| Endpoint | Description |
|----------|-------------|
| `GET /api/jobs/h3-map?region=austin_tx&resolution=7&mode=local` | H3 hex aggregates — mode: local/remote/all |
| `GET /api/jobs/listings?region=austin_tx&mode=remote&page=1` | Paginated job listing cards |
| `GET /api/jobs/categories?region=austin_tx` | Job categories with counts |

### Scoring & Targeting
| Endpoint | Description |
|----------|-------------|
| `GET /api/scores?region=austin_tx` | All store staffing-stress scores |
| `GET /api/targeting?industry=coffee_cafe&region=austin_tx` | Ranked job fair candidates |
| `GET /api/wage-index?industry=coffee_cafe&region=austin_tx` | Wage comparison |

### Career Pathfinder
| Endpoint | Description |
|----------|-------------|
| `GET /api/mobility/occupations` | All 781 SOC occupations (autocomplete) |
| `GET /api/mobility/paths?soc=35-3023&wage_filter=up&limit=15` | Career transition recommendations |
| `GET /api/mobility/employers?soc=35-3023&lat=30.27&lng=-97.74&radius=30` | Nearby employers for dest SOC |

### Events Hub
| Endpoint | Description |
|----------|-------------|
| `GET /api/events?region=austin_tx` | Active events with filters |
| `GET /api/events/categories?region=austin_tx` | Event categories with counts |
| `GET /api/events/venues?region=austin_tx` | Venue directory |

### Operations
| Endpoint | Description |
|----------|-------------|
| `GET /api/scheduler/status` | Scheduler job status + next run times |
| `GET /api/rate-budget` | API quota usage across all sources |

---

## Scoring Model

### Staffing Stress Score (0–100)
| Signal | Weight |
|--------|--------|
| Careers API activity | 40% |
| Job board postings | 35% |
| Sentiment (Reddit + reviews) | 25% |

### Targeting Score
| Factor | Weight |
|--------|--------|
| Staffing stress | 40% |
| Wage gap vs. local median | 30% |
| Worker isolation | 20% |
| Local employer alternatives | 10% |

### Pathfinder Ranking
Destinations ranked by: `transition_order` → `wage_direction` → `avg_skill_gap` → `traj_med_wage_growth`

---

## Key Invariants

- **Never write directly to `local_employers` or `brand_groups`** — all employer data flows through `core/ingest_layer.py`
- **Never write directly to `job_postings`** — all posting data flows through `postings/ingest.py`
- **Never write directly to `events` or `venues`** — all event data flows through `events/ingest.py`
- **Never call external APIs without rate manager** — always `rate_manager.can_request()` + `rate_manager.log_request()`
- **New event collectors must use `@event_collector` decorator** — auto-discovered by the scheduler
- **H3 cells are pre-computed at ingest** — never compute at query time
- **No frontend build step** — plain HTML/CSS/JS only, no npm or bundler
- **Public data only** — no logins, no paywalls, no proprietary sources

---

## Background

Chain employers capture labor from local communities while wages and profits flow out. This platform gives organizers, workers, and job seekers better visibility into the Austin labor market using publicly accessible data.
