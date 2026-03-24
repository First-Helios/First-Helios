# First Helios

A public labor market intelligence platform with two modes:

1. **Job Fair Targeting** — detects staffing stress at chain employer locations and surfaces where community job fairs have maximum impact
2. **Career Pathfinder** — shows workers what jobs they can realistically move into from where they are now, and maps where to apply nearby

**Current focus:** Austin, TX. One city, done right, before scaling.

---

## What It Does

### Mode 1: Job Fair Targeting (Organizer Tool)
Produces a ranked list of chain store locations where local independent employers can show up with a permitted booth and a job offer — timed to when workers have the most leverage.

### Mode 2: Career Pathfinder (Worker Tool)
Given a job title (or future: a resume), shows:
- What jobs workers in that role actually move into next (real transition data from 256k+ observed career moves)
- Which moves are upward (wage increase), lateral, or downward
- How hard the skill gap is to bridge (12 ISA skill dimensions)
- A map of nearby employers in the destination industries where they can apply today

---

## How It Works

```
Public Sources (free, legal, no login required)
┌─────────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
│ Chain Careers   │ │ Indeed /    │ │ Reddit API   │ │ Google Maps  │
│ APIs            │ │ Glassdoor   │ │ (public)     │ │ + Yelp       │
└────────┬────────┘ └──────┬──────┘ └──────┬───────┘ └──────┬───────┘
         └─────────────────┴───────────────┴─────────────────┘
                                   │
                         Normalized ScraperSignal objects
                                   │
                        PostgreSQL (helios, port 5432)
                 stores / signals / scores / wage_index / mob_*
                                   │
             ┌─────────────────────┼──────────────────────┐
             │                     │                      │
      Scoring Engine        Mobility Graph          Targeting Score
      (staffing stress)     (career transitions)    (job fair timing)
             │                     │                      │
                        Flask API + Dual-Mode Frontend
                     Job Fair Map  |  Career Pathfinder
```

---

## Repository Structure

```
First-Helios/
│
├── README.md                        ← you are here
├── RUNBOOK.md                       ← server startup, debugging, ops
├── CLAUDE_DATA_ENGINEERING_HANDOFF.md ← detailed data digest for agents
│
├── backend/
│   ├── database.py                  ← SQLAlchemy models (26+ tables) + init
│   ├── ingest.py                    ← Signal ingestion pipeline (scraper signals → DB)
│   ├── ingest_layer.py              ← Employer write path (normalize → fingerprint → upsert brand_groups → upsert local_employers)
│   ├── normalizer.py                ← Zero-DB normalization step upstream of ingest_layer
│   ├── baseline.py                  ← Labor market baseline (QCEW+JOLTS+OEWS+LAUS)
│   ├── scheduler.py                 ← APScheduler job definitions
│   ├── scoring/
│   │   ├── engine.py                ← 4-component composite staffing score
│   │   ├── careers.py               ← Careers API sub-score
│   │   ├── sentiment.py             ← Reddit + review sentiment
│   │   └── wage.py                  ← Wage gap sub-score
│   └── models/
│       └── reference.py             ← Reference + mobility graph models
│
├── scripts/
│   ├── populate_reference_data.py   ← Brands, regions, categories
│   ├── populate_industry_taxonomy.py ← ref_industry_taxonomy (SOC crosswalk)
│   ├── populate_mobility_data.py    ← mob_occupation (781) + mob_transition (256k rows) + dest_industry_keys crosswalk
│   ├── load_occupation_aliases.py   ← ref_occupation_aliases (18,981 Census job-title aliases for Pathfinder autocomplete)
│   ├── populate_metadata.py         ← meta_table_catalog, meta_column_catalog
│   ├── build_name_index.py          ← ref_employer_name_index
│   ├── classify_local_employers.py  ← Backfill location_count + purge chain-like records
│   ├── download_bls_bulk.py         ← BLS bulk data fetch
│   └── system_health_dashboard.py   ← Weekly audit tool
│
├── scrapers/
│   ├── base.py                      ← BaseScraper + ScraperSignal dataclass
│   ├── careers_api.py               ← Chain careers APIs (Starbucks, Dutch Bros)
│   ├── jobspy_adapter.py            ← python-jobspy → ScraperSignal
│   ├── reddit_adapter.py            ← PRAW → ScraperSignal
│   ├── reviews_adapter.py           ← Google Maps / Yelp → ScraperSignal
│   ├── overture_adapter.py          ← Overture Maps → store/employer discovery
│   └── geocoding.py                 ← Nominatim + overrides
│
├── server.py                        ← Flask API (port 8765)
│
├── frontend/
│   ├── index.html                   ← Dual-mode SPA (Leaflet map)
│   ├── css/style.css
│   └── js/
│       ├── app.js                   ← Job Fair Map mode: unified /api/map-employers loader, filters, mode switcher
│       └── pathfinder.js            ← Career Pathfinder mode
│
├── config/
│   ├── chains.yaml                  ← Chain targets, scoring weights, regions
│   └── loader.py                    ← Typed config access
│
├── .env                             ← DATABASE_URL and API keys (copy from .env.example)
│
├── Data_analysis/                   ← Jupyter notebooks
│   ├── data_exploration.ipynb       ← Score distribution, chain vs local analysis
│   └── employment_data_review.ipynb ← Mobility dataset exploration + recommendation engine
│
└── docs/
    ├── INDEX.md                     ← Documentation index
    ├── Data_Dicts/                  ← Table + column reference
    ├── Data_Ingestion/              ← Ingestion summaries per source
    └── BLS_GROUND_TRUTH_GUIDE.md    ← BLS series IDs and update schedules
```

---

## Database Tables (26 total)

### Operational / Signal Tables
| Table | Rows (est.) | Purpose |
|---|---|---|
| `chain_locations` | ~283 | Chain store locations (Starbucks, McDonald's, etc.) — ORM class `Store`, filtered by `brand_key` |
| `local_employers` | ~45,618 | Truly-local non-chain employer POIs from Overture Maps; includes `mobility_score` (wage-lift proxy) |
| `brand_groups` | ~36,563 | Deduplicated employer brand clusters; `location_count >= 5` → chain classification |
| `signals` | growing | Raw observations (job postings, reviews, Reddit) |
| `scores` | growing | Composite staffing-stress scores per store |
| `wage_index` | growing | Local vs chain pay comparison |
| `snapshots` | growing | Periodic scan summaries |

**Chain vs Local distinction:**
- `chain_locations` — scraped from career APIs / Overture with `brand_key` set (canonical key, e.g. `"starbucks"`)
- `local_employers` — all other POIs from Overture; chain-like records (≥5 locations in Austin) were purged by `scripts/classify_local_employers.py`

### BLS Ground Truth (Reference Denominators)
| Table | Purpose |
|---|---|
| `qcew_data` | County employment + wages (quarterly) |
| `cbp_data` | ZIP establishment counts (annual) |
| `jolts_data` | National job openings + quits rates |
| `oews_data` | MSA-level occupation wages (annual) |
| `laus_data` | County unemployment rates (monthly) |
| `labor_market_baseline` | Pre-computed denominators from above |

### Reference Tables
| Table | Rows | Purpose |
|---|---|---|
| `ref_brands` | ~200 | Known chain profiles + spider config; `brand_key` is the canonical chain identifier |
| `ref_industry` | ~30 | NAICS-based industry hierarchy |
| `ref_industry_taxonomy` | 20 | Internal industry key → SOC crosswalk + wage data |
| `ref_regions` | ~10 | Regional economic context |
| `ref_category_map` | ~500 | External taxonomy → internal industry crosswalk |
| `ref_employer_name_index` | growing | Employer name → chain/local classification |
| `ref_soc_major_groups` | ~23 | 2-digit SOC major group labels |
| `ref_occupation_aliases` | 18,981 | Census job-title aliases → SOC code crosswalk (powers Pathfinder autocomplete) |

### Mobility Graph Tables (Career Pathfinder)
| Table | Rows | Purpose |
|---|---|---|
| `mob_occupation` | 781 | SOC occupation nodes with wage + trajectory data |
| `mob_transition` | 256,831 | Directed edges: origin SOC → dest SOC with skill gaps, wage direction, frequency |

### Metadata / Audit
| Table | Purpose |
|---|---|
| `meta_table_catalog` | Table-level documentation + SLAs |
| `meta_column_catalog` | Column-level documentation |
| `meta_data_lineage` | Which tables feed which |
| `meta_job_runs` | Scraper/script run history |
| `meta_api_calls` | API call log + rate tracking |

---

## Mobility Graph — Career Pathfinder Data

The mobility graph is populated from the CTOT (Center for Occupational Transitions) Dashboard dataset, which tracks actual career moves of ~100k workers over 3, 5, and 10 years.

### Data Sources
| File | Purpose |
|---|---|
| `Emsi-dataset.dta` | 256k SOC→SOC transition pairs with 12 ISA skill dimension deltas, wage data, license flag |
| `Dashboard-transitions-dataset.dta` | Ranked frequency of observed moves (TransitionOrder 1 = most common) |
| `Dashboard-trajectories-dataset.dta` | 3/5/10yr wage growth outcomes by Census occupation code |

### Query Chain (Job Fair → Career Pathfinder)
```
store.industry (e.g. "fast_food")
  → ref_industry_taxonomy.primary_occ_code  (e.g. "35-3023")
  → mob_transition WHERE origin_soc = ?     (ranked by transition_order, wage_direction)
  → mob_occupation dest metadata            (title, wage, 3yr growth, dest_industry_keys)
  → chain_locations / local_employers       (WHERE industry IN dest_industry_keys AND near lat/lng)
  → [future] scraped job postings           (live openings at those employers)
```

### SOC Coverage Notes
- 458 occupation origins covered in Emsi (out of 781 SOC nodes)
- `fast_food` / `coffee_cafe` (SOC 35-3023) not in Emsi origins → fallback to 35-3031 (Waiters)
- `nonprofit` (SOC 21-1099) has no Emsi origin coverage
- Fallback hierarchy: exact → 5-char minor group → 2-char major group (picks lowest wage = most entry-level)

---

## API Endpoints

### Map Data
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/map-employers?region=austin_tx` | **Unified** — chain stores + local employers in one call; `chain` and `industry` filters apply to both |
| `GET` | `/api/stores?region=austin_tx` | Chain store locations only (chain filter uses `brand_key`) |
| `GET` | `/api/local-employers?region=austin_tx&sample=3000` | Local employer POIs; random sample for geographic coverage |

### Scoring & Targeting
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/scores?region=austin_tx` | All store staffing-stress scores |
| `GET` | `/api/targeting?industry=coffee_cafe&region=austin_tx` | Ranked job fair candidates |
| `GET` | `/api/wage-index?industry=coffee_cafe` | Local vs chain pay comparison |

### Reference Data
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/ref/summary?region=austin_tx` | **Dropdown data** — chains (by `brand_key`) + industries (by taxonomy key) with counts |
| `GET` | `/api/ref/industries` | NAICS industry hierarchy |
| `GET` | `/api/ref/brands` | Brand/chain profiles |
| `GET` | `/api/ref/categories` | Overture → internal industry crosswalk |

### Operations
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/scan` | Trigger scrape `{chain, region}` |
| `GET` | `/api/scheduler/status` | Next scheduled run times |
| `GET` | `/api/rate-budget` | API quota usage |

### Mobility (Career Pathfinder)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/mobility/search?job_title=cashier` | Match job title → origin SOC |
| `GET` | `/api/mobility/paths?soc=41-2011&wage_filter=up&limit=10` | Career transition recommendations |
| `GET` | `/api/mobility/employers?soc=41-2011&lat=30.26&lng=-97.74&radius=10` | Nearby employers for dest SOC |

**Chain filter note:** All endpoints that accept a `chain` parameter expect the canonical `brand_key` (e.g., `starbucks`, `mcdonalds`) — not the display name. The `/api/ref/summary` response includes both `chain_key` (filter value) and `chain_name` (display label).

---

## Scoring Model

### Staffing Stress Score (0–100)
```
Composite = (careers_weight × careers_score)
          + (job_boards_weight × board_score)
          + (sentiment_weight × sentiment_score)

Weights (configurable in config/chains.yaml):
  careers_api:  40%    job_boards: 35%    sentiment: 25%
```

### Targeting Score
```
Targeting = (staffing_stress    × 0.40)
          + (wage_gap           × 0.30)
          + (isolation          × 0.20)
          + (local_alternatives × 0.10)
```
`local_alternatives` = weighted sum of `mobility_score` of nearby active employers (threshold: sum of 3.0 = 100). Higher score means more high-mobility employers are already in the area competing for the same workers.

### Career Pathfinder Ranking
```
Rank destinations by:
  1. transition_order      — how commonly workers actually make this move (1 = most common)
  2. wage_direction        — 1 (up) > 0 (lateral) > -1 (down)
  3. avg_skill_gap         — lower = easier transition (12 ISA dimensions, 0–3 scale)
  4. traj_med_wage_growth  — 3yr/5yr/10yr wage growth trajectory at destination
```

---

## Quickstart

```bash
# 1. Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL=postgresql://user:pass@localhost:5432/helios
# Create the DB if it doesn't exist:  createdb helios

# 3. Initialize DB + reference data
python scripts/populate_reference_data.py
python scripts/populate_industry_taxonomy.py
python scripts/populate_mobility_data.py      # loads 781 occupations + 256k career transitions
python scripts/load_occupation_aliases.py     # loads 18,981 Census job-title aliases

# 5. Ingest Overture POI data (local employers + chain locations)
#    Either via S3/DuckDB:
python scrapers/overture_adapter.py --mode local --region austin_tx
#    Or from a locally downloaded GeoJSON:
python scrapers/overture_adapter.py --local-file data/austin_places.geojson

# 6. Classify and purge chain-like local employer records
python scripts/classify_local_employers.py    # backfills location_count + purges chains

# 7. Start server
python server.py --debug                      # http://localhost:8765

# 8. (Optional) Run chain scrapers
python scrapers/careers_api.py --region austin_tx
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx
```

---

## Third-Party Libraries

| Library | Purpose |
|---|---|
| `python-jobspy` | Scrapes Indeed/Glassdoor/LinkedIn → job listings DataFrame |
| `pyreadstat` | Reads Stata `.dta` files (for CTOT mobility dataset) |
| `PRAW` | Reddit API → worker sentiment |
| `google-maps-scraper` | Store ratings, lat/lng, permanently_closed flag |
| `Leaflet.js` | Interactive map in the frontend |

---

## Configuration

All chain targets, scoring weights, and region definitions live in `config/chains.yaml`. No hardcoded values in the codebase (exception: Emsi ISA column names, which are fixed by the dataset schema).

---

## Important Constraints

**Do not touch `spiritpool/`** — browser extension on hiatus, preserved intact.

**Public data only** — no logins, no paywalls, no bypassing access controls.

**Austin TX first** — the config supports multi-region; the pipeline focuses on one city until it's right.

---

## Background

Chain employers capture labor from local communities while wages and profits flow out. Local independent employers often pay more but lack recruiting infrastructure to compete.

This platform gives both sides better tools:
- **Organizers** get data-driven timing and placement for community job fairs
- **Workers** get a clear map of what they can realistically move into and where to apply

Everything uses publicly accessible sources. The legal framework was designed before any code was written.
