# Meal Deal Data Ingestion Process

**Date:** 2026-04-13
**Status:** Phase 1–4 implemented and operational. Scheduler integrated.

---

## Overview

The meal deal ingestion pipeline discovers restaurant deals/specials for
employers in the `local_employers` table and stores them in `meal_deals`.
It uses a three-stage approach to minimize API costs:

1. **URL Resolution** — Find restaurant website URLs (free OSM first, then Google Places for gaps)
2. **Deal Extraction** — Scrape websites for deal content (chain pages + local keyword scan)
3. **Ingest & Dedup** — Normalize to `DealSignal`, fan out to locations, upsert into `meal_deals`

---

## Database Tables

### `restaurant_urls` (Reference Data — Layer 1)

Cached website URLs for local employers. One row per employer per source.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `local_employer_id` | FK → local_employers | Which restaurant |
| `brand_group_id` | FK → brand_groups | Nullable, for chain URLs |
| `url` | VARCHAR | Resolved website URL |
| `source` | VARCHAR | `osm`, `google_places`, `manual`, `chain_config` |
| `confidence` | FLOAT | 0.0–1.0 (OSM=0.8, Google=0.9) |
| `is_active` | BOOLEAN | URL still valid |
| `last_checked` | TIMESTAMP | When last verified |
| `last_http_status` | INTEGER | Last HTTP response code |
| `has_deals_page` | BOOLEAN | Whether deals content was found |
| `deals_page_url` | VARCHAR | Specific deals sub-page URL if found |

**Unique constraint:** `(local_employer_id, source)` — one URL per source per employer.

### `meal_deals` (Consumer Intelligence — Layer 5)

Individual deal records, one per deal per restaurant location.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `local_employer_id` | FK → local_employers | Which location |
| `brand_group_id` | FK → brand_groups | Chain link (nullable) |
| `deal_name` | VARCHAR | e.g. "$5.99 Lunch Combo" |
| `deal_description` | TEXT | Full deal text |
| `deal_type` | VARCHAR | `lunch_special`, `combo`, `bogo`, `happy_hour`, `kids_eat_free`, `daily_special` |
| `price` / `original_price` | FLOAT | Deal price and regular price |
| `valid_days` / `valid_start_time` / `valid_end_time` | VARCHAR/TIME | When the deal is valid |
| `source` | VARCHAR | `chain_website`, `website_scrape`, `manual`, `google_places`, `yelp` |
| `source_url` | VARCHAR | Where the deal was found |
| `verified_at` | TIMESTAMP | Last time the deal was confirmed active |
| `is_active` | BOOLEAN | Deactivated after 14 days without re-verification |

**Unique constraint:** `(local_employer_id, deal_name, source)` — prevents duplicates, enables upsert.

---

## Pipeline Stages

### Stage 1: URL Resolution

```
local_employers (5,662 food/drink locations)
        │
        ├─→ OSM Overpass (FREE, runs Sunday 1 AM)
        │     Query: amenity=restaurant|cafe|fast_food|bar|pub with website tag
        │     Match: fingerprint + proximity (0.3 mi), brand fan-out
        │     Result: 758 unique employer URLs from 1,758 OSM POIs
        │
        ├─→ Google Places API ($32/1K calls, runs Tuesday 2 AM)
        │     Mode 1: "brands" — one call per brand_group, fan out to all locations
        │     Mode 2: "locals" — one call per individual employer
        │     Budget: $200 free credits → ~6,250 calls max
        │     Result: 824 unique employer URLs from 50 API calls (brands mode)
        │
        └─→ restaurant_urls table (1,582 / 5,662 = 27% coverage)
```

**Cost so far:** $1.60 of $200 Google credits used. OSM is free.

### Stage 2: Deal Extraction

```
restaurant_urls
        │
        ├─→ Chain Deal Scraper (runs Monday 6 AM)
        │     Config: config/meal_deal_sources.yaml (15 chains)
        │     Method: requests + BeautifulSoup (static HTML)
        │     Strategy: heading scan + link card scan + price regex
        │     Output: DealSignal per deal, with brand_fingerprint for fan-out
        │
        ├─→ Website Scraper (runs Wed + Sat 2 AM)
        │     Targets: employers with URLs in restaurant_urls
        │     Method: probe homepage + /menu, /specials, /deals, /lunch, /happy-hour
        │     Keyword scan: "special", "deal", "combo", "BOGO", "$X.99", etc.
        │     Rate limit: 1 req/sec, respects robots.txt
        │     Output: DealSignal per detected deal
        │
        └─→ Manual Ingest (CLI, on-demand)
              Input: CSV or JSON file
              Source: SpiritPool human contributions
              Tool: python collectors/meal_deals/manual_ingest.py --file deals.csv
```

### Stage 3: Ingest & Storage

```
list[DealSignal]
        │
        ├─→ Brand Fan-Out
        │     If signal.brand_fingerprint set:
        │       Find all local_employers for that brand in the region
        │       Create one meal_deals row per location
        │     If signal.local_employer_id set:
        │       Single-location write
        │
        ├─→ Dedup Upsert
        │     PostgreSQL: INSERT ... ON CONFLICT (local_employer_id, deal_name, source) DO UPDATE
        │     SQLite fallback: query-then-update pattern
        │     Updates: description, type, price, valid_days/times, source_url, verified_at
        │
        └─→ meal_deals table
              Stale sweep: deals not verified in 14 days → is_active = false (Sunday 5 AM)
```

---

## CLI Commands

```bash
# ── URL Resolution ──────────────────────────────────────────────────
# OSM Overpass (free)
PYTHONPATH=. python collectors/meal_deals/osm_url_resolver.py [--dry-run]

# Google Places — brands first (highest ROI)
PYTHONPATH=. python collectors/meal_deals/google_places_resolver.py --mode brands --max-calls 50 [--dry-run]

# Google Places — individual locals
PYTHONPATH=. python collectors/meal_deals/google_places_resolver.py --mode locals --max-calls 200 [--dry-run]

# Google Places — both (brands then locals with remaining budget)
PYTHONPATH=. python collectors/meal_deals/google_places_resolver.py --mode both --max-calls 250 [--dry-run]

# ── Deal Extraction ─────────────────────────────────────────────────
# Chain deals
PYTHONPATH=. python collectors/meal_deals/chain_deals.py [--dry-run]

# Website scraper
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --max-sites 100 [--dry-run]

# Manual ingest (CSV/JSON)
PYTHONPATH=. python collectors/meal_deals/manual_ingest.py --file deals.csv --region austin_tx [--dry-run]
```

---

## Scheduler Jobs

All configured in `config/scheduler.yaml`:

| Job | Schedule | What It Does |
|-----|----------|--------------|
| `osm_url_resolver` | Sun 1:00 AM | Re-query OSM Overpass for new restaurant websites |
| `google_places_resolver` | Tue 2:00 AM | Resolve remaining brand URLs (200 calls/run max) |
| `deal_chain_deals` | Mon 6:00 AM | Scrape chain restaurant deal pages |
| `deal_website_scraper` | Wed + Sat 2:00 AM | Scrape local restaurant websites for deals |
| `deal_stale_sweep` | Sun 5:00 AM | Deactivate deals not verified in 14+ days |

**Recommended overnight window:** URL resolution (Sun/Tue nights) → deal extraction (Mon/Wed/Sat mornings) → stale cleanup (Sun morning).

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/deals` | GET | List deals with geo-filter (`lat`, `lng`, `radius_mi`), `deal_type`, `brand`, pagination |
| `/api/deals/stats` | GET | Aggregate counts by type, source, restaurant, brand |
| `/api/deals/brands` | GET | List brands with active deal counts |

---

## Data Quality Notes

- **OSM coverage**: 13% of food employers (758/5,662). Strong in central Austin, thinner in suburbs.
- **Google Places coverage**: 14% additional (824/5,662) from just 50 API calls on high-location brands.
- **Chain deal extraction**: 151 signals from 8 chains in dry-run. ThunderCloud Subs over-extracts (80 items — most are menu items, not deals). Pizza Hut timed out. Jimmy John's returns 0 (JS-heavy).
- **Fingerprint matching**: Uses lowercase, punctuation-stripped, space-collapsed names. Possessive stripping (`'s` → `s`). 0.3-mile proximity threshold for location matching.
- **Brand fan-out**: One Subway deal × 82 Subway locations = 82 `meal_deals` rows. All share the same `brand_group_id`.

---

## Cost Tracking

| Resource | Used | Remaining | Projected Depletion |
|----------|------|-----------|---------------------|
| Google Places API | $1.60 (50 calls) | $198.40 | ~31 weeks at 200 calls/week |
| OSM Overpass | Free | Unlimited | — |
| SerpAPI (if used) | N/A | N/A | — |

---

## Module Map

```
collectors/meal_deals/
├── __init__.py                  # Module docstring
├── models.py                    # DealSignal dataclass
├── registry.py                  # @deal_collector decorator + get_all()
├── chain_deals.py               # Chain website scraper (static HTML)
├── osm_url_resolver.py          # OSM Overpass → restaurant_urls
├── google_places_resolver.py    # Google Places API → restaurant_urls
├── website_scraper.py           # Local website keyword scanner
├── ingest.py                    # DealSignal → meal_deals upsert pipeline
├── manual_ingest.py             # CSV/JSON CLI for SpiritPool
└── routes.py                    # Flask Blueprint /api/deals
```
