# Helios V2

A trustworthy, queryable map of real food deals in Austin — rebuilt from scratch with professional rigor.

**Status:** planning / Phase 0. No feature code yet.

## Start here

- [ROADMAP.md](./ROADMAP.md) — what we're building, in what order, and why.
- [LEARNING_GUIDE.md](./LEARNING_GUIDE.md) — the twelve-module course that runs alongside the build.

## Day 1

See the [Day-1 Kickoff Checklist](./ROADMAP.md#7-day-1-kickoff-checklist) in the roadmap.

## V1 archive

All legacy V1 code lives on the [`V1-Graveyard`](https://github.com/4Fortune8/First-Helios/tree/V1-Graveyard) branch of this repository. `main` is reserved for V2.

```bash
# browse V1 code without affecting your V2 working copy
git fetch origin V1-Graveyard
git worktree add ../helios-v1 V1-Graveyard
```

## License

TBD (add in Phase 0).
# First-Helios

A broad-scope data intelligence platform for Austin, TX — ingesting, documenting, and serving structured data across jobs, events, businesses, wages, economic indicators, and career mobility into dashboards people actually use.

- **Job Fair Targeting** — helps organizers identify which employers to prioritize for outreach based on staffing stress, wage gaps, and worker isolation
- **Career Pathfinder** — shows workers realistic lateral and upward moves with wage data and nearby employers
- **Job Finder** — maps active job postings by H3 hex cell across Austin
- **Events Hub** — aggregates local events from 6+ sources (Ticketmaster, Eventbrite, Meetup, Do512, City of Austin, Visit Austin) with venue mapping and social-density scoring
- **Meal Deals** — scrapes restaurant menus, GBP posts, and chain deal pages to surface active specials (happy hour, breakfast, lunch, BOGO, kids-eat-free) with temporal and pricing structure
- **Business Intelligence** — 45K+ employer locations with brand clustering, industry classification, and mobility scoring

Data enters from two paths: **50+ automated API collectors** (BLS, job boards, event aggregators, Overture Maps) running on schedules, and the **SpiritPool browser extension** where real people contribute signals under explicit consent.

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
| LAN address | 192.168.1.191 |
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
│   ├── meal_deals/              # website_scraper, chain_deals, gbp_offers,
│   │                            #   render_policy (ARCH-03), hint_registry (ARCH-04),
│   │                            #   menu_sidecar, menu_persistence_schema (ARCH-01),
│   │                            #   ingest.py, routes.py
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
 
│
├── scripts/                     # One-time data population scripts
├── notebooks/                   # Exploration notebooks
 
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


**To run locally:**
```bash
git clone https://github.com/4Fortune8/First-Helios.git
cd First-Helios
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios
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

### Meal Deals
| Endpoint | Description |
|----------|-------------|
| `GET /api/deals?deal_type=breakfast&region=austin_tx` | Paginated deals with geo/type/brand filters |
| `GET /api/deals/stats?region=austin_tx` | Deal counts by type / source / brand |
| `GET /api/deals/brands?region=austin_tx` | Brands with active deals and counts |
| `GET /api/deals/review-queue?region=austin_tx` | Contested-site + ambiguous-alias review queue |

Deal types: `breakfast`, `lunch_special`, `happy_hour`, `combo`, `bogo`, `kids_eat_free`, `daily_special`.

### Food Price Index
| Endpoint | Description |
|----------|-------------|
| `GET /api/price-index?region=austin_tx&limit=50` | Baseline menu item search sorted by price |
| `GET /api/price-index?q=taco&region=austin_tx` | Keyword search across scraped menu items |
| `GET /api/price-index?sort=price_per_calorie&region=austin_tx` | Sort by price-per-calorie when calorie data exists |
| `GET /api/price-index/facets?region=austin_tx` | Facets for cuisine, course, brand, and price bands |

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
- **Never write directly to `meal_deals` or `deal_materializations`** — all deal data flows through `collectors/meal_deals/ingest.py` and the semantic-layer materializer
- **Never call external APIs without rate manager** — always `rate_manager.can_request()` + `rate_manager.log_request()`
- **New event collectors must use `@event_collector` decorator** — auto-discovered by the scheduler
- **H3 cells are pre-computed at ingest** — never compute at query time

- **Public data only** — no logins, no paywalls, no proprietary sources

---

## Background


---

## Cross-Repo Architecture

This repository is now **backend-only**. For the full platform:

- **Frontend:** [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend)
- **Host/infra:** [First-Helios_Orangepi_Host](https://github.com/4Fortune8/First-Helios_Orangepi_Host)

See those repos for UI, deployment, and systemd/nginx configuration.
