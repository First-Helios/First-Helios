# Meal Deal Scrapers — Runbook & Operations Guide

Updated: 2026-04-21

> Audience: developers/operators who run, tune, or debug the meal deal collection pipeline.

Quick links:

- Short restart path: [MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md](MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md)
- Replay-first workflow: [MEAL_DEAL_REPLAY_WORKFLOW.md](MEAL_DEAL_REPLAY_WORKFLOW.md)
- Full ingestion reference: [../data/ingestion/MEAL_DEAL_INGESTION.md](../data/ingestion/MEAL_DEAL_INGESTION.md)

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Data Flow](#data-flow)
- [Running Individual Scrapers](#running-individual-scrapers)
  - [Website Scraper (local restaurants)](#website-scraper-local-restaurants)
  - [Chain Deals Scraper (franchises)](#chain-deals-scraper-franchises)
  - [GBP Offers (Google Business Profile)](#gbp-offers-google-business-profile)
- [URL Resolution (prerequisite)](#url-resolution-prerequisite)
- [Full Pipeline Test Script](#full-pipeline-test-script)
- [Data Quality & Purge](#data-quality--purge)
- [Audit & Review Process](#audit--review-process)
- [Stale Deal Sweep](#stale-deal-sweep)
- [Scheduling](#scheduling)
- [Quality Filters Reference](#quality-filters-reference)
- [Database Schema Reference](#database-schema-reference)
- [Configuration Files](#configuration-files)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

The meal-deal system has three collectors feeding into a shared canonical ingest pipeline:

| Component | Targets | Schedule | Collector tag | `DealSignal.source` |
|---|---|---|---|---|
| **website_scraper** | First-party restaurant websites queued from `restaurant_urls` for active `food_full_service`, `fast_food`, and `bar_nightlife` employers | Mon/Wed/Fri 2 AM | `website_scraper` | `website_scrape` |
| **chain_deals** | National chain deal pages (McDonald's, etc.) | Monday 6 AM | `chain_deals` | `chain_website` |
| **gbp_offers** | Google Business Profile offer posts via SerpApi | Tue/Fri 3 AM | `gbp_offers` | `gbp_offer` |

Each collector emits `DealSignal` objects. `ingest_deal_signals()` then:

- computes quality and value scoring
- upserts canonical `deal_observations`
- syncs `deal_applicability`
- refreshes `deal_materializations`, the API read layer
- still dual-writes `meal_deals` as a compatibility table

Supporting services:

- **OSM URL Resolver** — free batch URL discovery via OpenStreetMap Overpass
- **Google Places Resolver** — paid URL discovery for restaurants OSM misses
- **Replay/debug bundle cache** — per-site HTML, PDF, signal, sidecar, render-policy, and hint-provenance artifacts under `data/cache/website_scrape_debug/`
- **Pre-flight gate + canary flow** — bounded restart workflow before broad scrapes
- **Review queue write-backs** — manual site and venue-alias decisions refresh canonical state
- **Stale Deal Sweep** — deactivates deals not re-verified in 14 days
- **Purge Script** — retroactive junk data cleanup
- **Scrape-denial queue** — `scripts/build_scrape_denial_queue.py` queries `restaurant_urls` for URLs that were `last_checked` but returned NULL or non-2xx status (Cloudflare/anti-bot silent failures) and whose brand has zero `deal_observations`. Output feeds the SpiritPool dev-user capture worklist; full pipeline documented in [SPIRITPOOL_DEV_CAPTURE_PIPELINE.md](SPIRITPOOL_DEV_CAPTURE_PIPELINE.md).

---

## Data Flow

```
  ┌───────────────────┐     ┌──────────────────┐
  │  OSM URL Resolver  │     │ Google Places     │
  │  (Sunday 1 AM)     │     │ Resolver (Tue 2AM)│
  └────────┬──────────┘     └────────┬─────────┘
           │  restaurant_urls table   │
           └──────────┬──────────────┘
                      ▼
  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐
  │ website_scraper│  │ chain_deals   │  │ gbp_offers    │
  │ (M/W/F 2 AM)  │  │ (Monday 6 AM) │  │ (Tue/Fri 3AM) │
  └──────┬────────┘  └──────┬───────┘  └──────┬───────┘
         │  list[DealSignal] │                 │
         └──────────┬────────┴─────────────────┘
                    ▼
    ┌────────────────────────────┐
    │ ingest_deal_signals()      │
    │ score + observation upsert │
    │ + applicability sync       │
    └────────────┬───────────────┘
           ▼
     ┌───────────────────────────┐
     │ deal_observations         │
     │ deal_applicability        │
     │ deal_materializations     │
     └────────────┬──────────────┘
            │
    ┌─────────────┴──────────────┐
    ▼                            ▼
  ┌──────────────────┐        ┌──────────────────┐
  │ /api/deals*      │        │ meal_deals       │
  │ canonical read   │        │ compatibility    │
  │ layer            │        │ write path       │
  └──────────────────┘        └──────────────────┘

  website_scraper also writes:
    data/cache/website_scrape_audit.json
    data/cache/website_scrape_debug/*.json
```

---

## Running Individual Scrapers

### Website Scraper (local restaurants)

Scrapes first-party restaurant websites queued from `restaurant_urls` for active `food_full_service`, `fast_food`, and `bar_nightlife` employers by probing common deal paths such as `/`, `/menu`, `/specials`, `/deals`, `/lunch`, `/happy-hour`, `/promotions`, and `/offers`, plus dynamically discovered same-domain pages, structured menu URLs promoted from JSON-LD, and bounded locator-to-corporate hint routes.

> **Note:** robots.txt is intentionally ignored — we are promoting restaurants' own deals to drive them traffic and customers. Rate limiting (1 req/sec) and the `skip-checked-days` default (3 days) keep server load minimal.

Recommended operator order before a broad live run:

1. Sync production-like data and replay bundles locally when needed: `bash dev/sync_from_opi.sh`
2. Apply migrations: `.venv/bin/alembic upgrade head`
3. Run the pre-flight gate
4. Run a 5-site dry-run canary
5. Run a small targeted refresh when the change is discovery- or parser-only
6. Inspect the newest bundles before starting any wider scrape
7. Prefer a replay-backed full pass before live crawling when cache coverage is already good
8. Backfill menu tables and audit the Price Index path when menu structure is in scope

For the short version, use [MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md](MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md).

```bash
# Standard local setup
cd /home/fortune/CodeProjects/First-Helios
set -a && source .env && set +a

# Sync replay corpus and production-like meal-deal tables when needed
bash dev/sync_from_opi.sh

# Apply migrations before validation or live runs
.venv/bin/alembic upgrade head

# Pre-flight gate before any broad live scrape
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0

# Dry-run canary
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx

# Targeted refresh of under-covered sites before a broad live run
PYTHONPATH=. .venv/bin/python scripts/refresh_targeted_sites.py --ids 18354 7047 26123 3570 3063

# Dry run — see what would be found, no DB writes
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --dry-run

# Live run — scrape and ingest into DB (default: 100 sites, skip recently checked)
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py

# Limit to 20 sites (useful for testing)
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 20

# Lower-memory live run on Orange Pi
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --chunk-size 25

# SCAN EVERYTHING — all sites, ignore skip window, no DB writes
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --dry-run

# SCAN EVERYTHING — all sites, ignore skip window, write to DB
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0

# Force re-scrape all but still cap at 100 sites
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --skip-checked-days 0

# Target a specific region
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --region austin_tx

# Replay locally saved debug bundles instead of live fetches
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --replay-debug-cache --max-sites 5 --skip-checked-days 0 --region austin_tx
```

#### CLI Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--max-sites` | int | 100 | Maximum number of restaurant websites to scrape |
| `--all` | flag | false | Scan ALL sites (overrides `--max-sites`) |
| `--dry-run` | flag | false | Preview mode — extract deals but don't write to DB |
| `--chunk-size` | int | 25 | Unique-site batch size before inline ingest and audit flush |
| `--region` | str | `austin_tx` | Geographic region scope |
| `--skip-checked-days` | int | 3 | Skip sites checked within N days. Use `0` to force re-scrape all |
| `--replay-debug-cache` | flag | false | Replay locally saved site bundles instead of live fetching |

#### Full-scan rerun sequence

Use this order after scraper heuristics, quality gates, or menu extraction logic change:

```bash
# 1) Sync production-like state and migrate.
bash dev/sync_from_opi.sh
.venv/bin/alembic upgrade head

# 2) Clear pre-flight blockers and inspect a canary first.
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx

# 3) If replay coverage is good, repopulate canonical deal layers from replay first.
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --replay-debug-cache --all --skip-checked-days 0 --chunk-size 25 --region austin_tx

# 4) Only fall back to a fresh live crawl if replay coverage is too sparse.
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --chunk-size 25 --region austin_tx

# 5) Re-audit only if scoring or gating changed.
PYTHONPATH=. .venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx --apply

# 6) Materialize menu tables and audit the menu read path.
PYTHONPATH=. .venv/bin/python scripts/backfill_menu_tables.py
PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --limit 20 --show-rows 5
```

Important integration note:

- `website_scraper.py` writes through canonical ingest during the run, chunk by chunk
- `scripts/backfill_menu_tables.py` is the separate step that materializes `menu_persistence_shape` into the persistent menu tables used by `/api/price-index`
- a full rerun is not complete until both the deal APIs and the menu APIs are revalidated

#### What it does per site

1. Loads deduped site targets from `restaurant_urls` and filters obvious non-first-party domain families before queue slots are consumed
2. Fetches bounded first-party paths and discovers additional same-domain candidates
3. Applies locator-to-corporate hint routing and exploration-only registry hints when relevant
4. Extracts DOM text, JSON-LD, page-level prices, and bounded PDF content
5. Builds `menu_sidecar`, offer-target metadata, and value-profile hints when real menu structure is present
6. Records `render_decisions` and `render_budget` in audit-only mode for static-empty but menu-critical pages
7. Produces `DealSignal` objects and feeds them through canonical ingest into `deal_observations`, `deal_applicability`, and `deal_materializations`, with `meal_deals` dual-written for compatibility
8. Writes `data/cache/website_scrape_audit.json` plus replay bundles under `data/cache/website_scrape_debug/`

Important caching/runtime notes:

- each fetched page snapshot is written to the debug bundle immediately
- each parsed PDF text snapshot is also written immediately
- page cache durability is therefore not tied to the 25-site chunk size
- the chunk size exists to limit in-memory signal and audit buildup on smaller hosts such as the Orange Pi

#### Output

```
--- Website Scraper Stats ---
  signals_found: 47
  rows_written: 1031
  skipped: 0
  sites_scanned: 100
  chunk_size: 25
```

---

### Chain Deals Scraper (franchises)

Scrapes deal pages for national chains defined in `config/meal_deal_sources.yaml`.

```bash
# Dry run — print deals without writing
PYTHONPATH=. .venv/bin/python collectors/meal_deals/chain_deals.py --dry-run

# Live run
PYTHONPATH=. .venv/bin/python collectors/meal_deals/chain_deals.py

# Specific region
PYTHONPATH=. .venv/bin/python collectors/meal_deals/chain_deals.py --region austin_tx
```

#### CLI Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--dry-run` | bool | false | Print deals without writing to DB |
| `--region` | str | `austin_tx` | Geographic region scope |

#### Strategies per chain

Each chain in `config/meal_deal_sources.yaml` declares a scraping strategy:

| Strategy | Method | Use Case |
|---|---|---|
| `static_html` | requests + BeautifulSoup | Simple deal pages (Taco Bell, Papa Johns) |
| `menu_only` | requests + BS4 + deal keyword filter | Pages that mix menu + deals |
| `playwright_required` | Headless Chromium (async) | JS-rendered pages (Chick-fil-A) |
| `app_only` | Skipped entirely | Deals only available in app (no public web page) |

The chain scraper fans out deals to all matching `local_employer` locations in the region via `brand_group_id`.

---

### GBP Offers (Google Business Profile)

Scrapes "offer" posts from restaurant Google Business Profiles via SerpApi's Google Maps engine. Many restaurants post weekly specials on their GBP even when their website is sparse.

Requires `SERPAPI_KEY` in `.env` (same key used by `serpapi_adapter.py` for job search).

```bash
# Activate environment
cd ~/First-Helios
source .venv/bin/activate
set -a && source .env && set +a

# Dry run — see what would be found, no DB writes (5 API calls)
PYTHONPATH=. .venv/bin/python -m collectors.meal_deals.gbp_offers --max-calls 5 --dry-run

# Live run — default 100 API calls, writes to DB
PYTHONPATH=. .venv/bin/python -m collectors.meal_deals.gbp_offers

# Query ALL restaurants (up to 200 API calls)
PYTHONPATH=. .venv/bin/python -m collectors.meal_deals.gbp_offers --all

# Query ALL, dry run
PYTHONPATH=. .venv/bin/python -m collectors.meal_deals.gbp_offers --all --dry-run

# Custom call budget
PYTHONPATH=. .venv/bin/python -m collectors.meal_deals.gbp_offers --max-calls 50
```

#### CLI Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--max-calls` | int | 100 | Maximum SerpApi API calls per run |
| `--all` | flag | false | Query ALL restaurants (up to 200 calls) |
| `--dry-run` | flag | false | Preview mode — don't write to DB |
| `--region` | str | `austin_tx` | Geographic region scope |

#### How it works

1. **Phase 1 (brands):** Queries brand groups by `location_count DESC` — one API call per brand, fan-out to all locations via `brand_fingerprint` in ingest
2. **Phase 2 (locals):** If budget remains, queries individual local restaurants with Google Places URLs
3. Extracts posts/updates/offers from SerpApi Google Maps results
4. Filters for deal keywords (same set as website scraper)
5. Produces `DealSignal` objects with `source="gbp_offer"` → `ingest_deal_signals()` → DB
6. Rate limit: 0.5 sec between API calls

#### Cost

Each SerpApi call costs ~$0.01. Default budget of 100 calls/run = ~$1.00 per run, $2/week at the Tue/Fri schedule.

---

## URL Resolution (prerequisite)

Before the website scraper can run, restaurants need URLs in the `restaurant_urls` table. Two resolvers populate them:

### OSM URL Resolver (free)

```bash
# Dry run
PYTHONPATH=. .venv/bin/python scripts/osm_url_resolver.py --dry-run

# Live — resolves URLs from OpenStreetMap Overpass
PYTHONPATH=. .venv/bin/python scripts/osm_url_resolver.py
```

Runs weekly on Sunday 1 AM. Free, bulk, but incomplete (~40% coverage).

### Google Places Resolver (paid)

```bash
# Dry run — shows what would be resolved
PYTHONPATH=. .venv/bin/python scripts/google_places_resolver.py --mode both --max-calls 50 --dry-run

# Live — resolve up to 200 URLs (brands first, then individual)
PYTHONPATH=. .venv/bin/python scripts/google_places_resolver.py --mode both --max-calls 200
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--mode` | str | `both` | `brands` (chains first), `individual` (local), or `both` |
| `--max-calls` | int | 200 | API call budget (each call costs ~$0.003) |
| `--dry-run` | bool | false | Preview without API calls |

Runs weekly on Tuesday 2 AM. Requires `GOOGLE_MAPS_API_KEY` in `.env`.

---

## Full Pipeline Test Script

The one-shot script runs the entire pipeline end-to-end with before/after snapshots.

```bash
# Standard test (dry-run + live, conservative limits)
bash scripts/run_meal_deal_full_test.sh

# Full production run (unlimited, skip already-checked sites)
bash scripts/run_meal_deal_full_test.sh --full
```

### Environment Variable Overrides

| Variable | Default | `--full` Mode | Description |
|---|---|---|---|
| `DRY_GOOGLE_CALLS` | 50 | 0 (skip) | Google Places API budget for dry-run phase |
| `LIVE_GOOGLE_CALLS` | 200 | 999999 | Google Places API budget for live phase |
| `DRY_MAX_SITES` | 100 | 0 (skip) | Website scraper site limit for dry-run |
| `LIVE_MAX_SITES` | 200 | 999999 | Website scraper site limit for live phase |
| `SCRAPER_SKIP_DAYS` | _(none)_ | 1 | Skip sites checked within N days |
| `RUN_STALE_SWEEP` | 1 | 1 | Run stale deal deactivation (0 to skip) |

Example with custom limits:

```bash
LIVE_MAX_SITES=50 LIVE_GOOGLE_CALLS=100 bash scripts/run_meal_deal_full_test.sh
```

### Steps executed

1. **Alembic migration check** — stamps head if schema exists but alembic_version missing
2. **Pre-snapshot** — captures DB counts to `before_snapshot.json`
3. **Phase 1 (dry-run)** — OSM, Google Places, chain deals, website scraper (all `--dry-run`)
4. **Phase 2 (live)** — same pipeline without `--dry-run`
5. **Stale sweep** — deactivates deals older than 14 days
6. **Post-snapshot** — captures DB counts to `after_snapshot.json`
7. **Delta report** — prints before/after comparison

### Running on Orange Pi

```bash
sshpass -p 'orangepi' ssh -o StrictHostKeyChecking=no orangepi@192.168.1.191 \
  'cd ~/First-Helios && source .venv/bin/activate && set -a && source .env && set +a && \
   bash scripts/run_meal_deal_full_test.sh'
```

---

## Data Quality & Purge

### Running the Purge Script

Retroactively removes junk deals from the database using the same quality filters as the scraper.

```bash
# Dry run — see what would be deleted, with breakdown by reason
PYTHONPATH=. .venv/bin/python scripts/purge_junk_deals.py

# Actually delete junk rows
PYTHONPATH=. .venv/bin/python scripts/purge_junk_deals.py --apply
```

#### What it filters

| Reason Code | Description | Applies To |
|---|---|---|
| `spam:X` | Casino/gambling/pharma content injected into pages | All sources |
| `boilerplate:X` | Nav/footer/cookie/legal text scraped as a "deal" | All sources |
| `negative_context` | "special occasion", "pre-order", "no substitution" | website_scrape only |
| `no_deal_keyword` | Text has no deal keyword at all (word-boundary matched) | website_scrape only |
| `keyword_only_no_price` | Has keyword but no `$X.XX` price and no self-validating phrase | website_scrape only |

**Chain deals (`chain_website` source) are exempt** from keyword/price checks — they already passed `chain_deals.py` quality filters.

#### Output example

```
Junk breakdown:
  no_deal_keyword                     570
  keyword_only_no_price               374
  boilerplate:gift card               82
  negative_context                    27
  spam:casino                         16
  TOTAL JUNK                          1240
  CLEAN (keeping)                     1031
```

---

## Audit & Review Process

Every website scraper run now writes two operator-facing evidence layers:

- `data/cache/website_scrape_audit.json` — per-site outcome snapshot
- `data/cache/website_scrape_debug/*.json` — per-site replay bundles with fetched HTML, PDFs, extracted signals, sidecar output, render-policy decisions, and hint provenance

Use the audit snapshot for fast counts and triage. Use the debug bundles for replay-first root-cause analysis.

For the full replay workflow, use [MEAL_DEAL_REPLAY_WORKFLOW.md](MEAL_DEAL_REPLAY_WORKFLOW.md).

### Audit snapshot location

```
data/cache/website_scrape_audit.json
```

### Replay bundle location

```
data/cache/website_scrape_debug/
```

### Audit snapshot fields

| Field | When Present | Description |
|---|---|---|
| `employer_id` | Always | Database ID of the restaurant |
| `name` | Always | Restaurant name |
| `url` | Always | Website URL scraped |
| `scraped_at` | Always | ISO timestamp |
| `deals_found` | Always | Number of deals extracted (0 if none) |
| `outcome` | Always | `deals_found`, `no_deals`, or `error` |
| `deal_names` | `deals_found` | List of extracted deal names |
| `sample_blocks` | `no_deals` | Up to 10 text block samples from the page (for manual review) |
| `total_blocks` | `no_deals` | Total text blocks extracted from the page |
| `pdf_links` | `no_deals` + PDFs exist | PDF URLs found on the page |
| `needs_pdf_reader` | `no_deals` + PDFs exist | `true` — site may have deals in PDF menus |
| `error` | `error` | Error message (truncated to 200 chars) |

Current success-path entries may also include the same structural context used for failure rows, such as discovered-page counts, PDF counts, and structured-data presence.

### What to inspect in replay bundles

- `render_decisions` and `render_budget` on fetched first-party pages
- `menu_persistence_summary` only when the canary actually materializes sidecar structure
- `hint_audit` only when hint-driven exploration was used
- `fk_violations == []` whenever `menu_persistence_summary` is present

### Quick audit commands

Check overall success rate:

```bash
PYTHONPATH=. .venv/bin/python scripts/summarize_website_scrape_audit.py
```

Build replay manifests for targeted bundle sets:

```bash
PYTHONPATH=. .venv/bin/python scripts/build_website_scrape_replay_manifests.py --per-set 6
```

### Manual assessment workflow

1. Run the pre-flight gate and a dry-run canary, or use [MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md](MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md)
2. Review `data/cache/website_scrape_audit.json` for outcome mix and likely failure families
3. Open the newest per-site bundles under `data/cache/website_scrape_debug/` for root-cause evidence
4. If `sample_blocks` look deal-like, consider extraction or quality-filter changes
5. If `render_decisions` show static-empty, menu-critical pages, treat them as `RENDER-01` or JS-render follow-up candidates rather than generic no-deal failures
6. If a site or venue mapping looks wrong, use `/api/deals/review-queue` and `/api/deals/review-queue/actions` to resolve canonical ownership rather than only patching downstream rows
7. Track parser and discovery follow-ups in `docs/guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md`

---

## Stale Deal Sweep

Deactivates deals not re-verified within a configurable window (default: 14 days).

```bash
# Via the full test script (runs automatically at end)
RUN_STALE_SWEEP=1 bash scripts/run_meal_deal_full_test.sh

# Inline Python (as used by the test script)
PYTHONPATH=. .venv/bin/python -c "
from collectors.meal_deals.ingest import deactivate_stale_deals
for src in ['website_scrape', 'chain_website', 'gbp_offer']:
    n = deactivate_stale_deals(src, region='austin_tx', max_age_days=14)
    print(f'  {src}: {n} stale deals deactivated')
"
```

Scheduled via `deal_stale_sweep` in `config/scheduler.yaml` — Sunday 5 AM.

---

## Scheduling

All meal deal jobs are defined in `config/scheduler.yaml`:

| Job ID | Schedule | Description |
|---|---|---|
| `osm_url_resolver` | Sunday 1:00 AM | Discover restaurant URLs from OSM (free) |
| `google_places_resolver` | Tuesday 2:00 AM | Discover URLs via Google Places API (paid) |
| `deal_chain_deals` | Monday 6:00 AM | Scrape chain franchise deal pages |
| `deal_website_scraper` | Mon/Wed/Fri 2:00 AM | Scrape local restaurant websites |
| `deal_gbp_offers` | Tue/Fri 3:00 AM | Scrape GBP offer posts via SerpApi |
| `deal_stale_sweep` | Sunday 5:00 AM | Deactivate deals not seen in 14+ days |

The scheduler runs as the `helios-collector` systemd service on the Orange Pi.

---

## Quality Filters Reference

### Website scraper extraction rules

A text block passes the quality gate if **ALL** of these are true:

1. **Not boilerplate** — doesn't contain nav/footer/legal phrases
2. **Not spam** — no casino/gambling/pharma content
3. **Not negative context** — no "special occasion", "pre-order", "no substitution"
4. **Has a deal keyword** (word-boundary matched) — "special", "deal", "combo", "bogo", "buy one", "happy hour", "kids eat free", "early bird", "discount", "limited time", "save", "promotion", "offer", "half off", "half price", "% off", "2 for", etc.
5. **AND one of:**
   - A price (`$X.XX`) appears in the same text block
   - A self-validating keyword appears: "bogo", "buy one get one", "kids eat free", "happy hour", "half off", "half price", "% off"

### Why "specialty" doesn't match "special"

Keywords are matched with `\b` (word boundary) regex, so "specialty pizza" does not trigger the "special" keyword.

### Boilerplate phrases (always rejected)

`privacy`, `terms of use`, `site map`, `cookie`, `toggle header`, `toggle menu`, `toggle nav`, `newsroom`, `gift card`, `careers`, `about us`, `rewards`, `sign in`, `log in`, `sign up`, `download the app`, `mobile app`, `international sites`, `franchise`, `copyright`, `all rights reserved`, `skip to content`, `skip to main`, `open menu close menu`, `locations specials jobs`

### Spam phrases (always rejected)

`casino`, `gambling`, `gamstop`, `slot machine`, `poker`, `roulette`, `blackjack`, `betting`, `live dealer`, `online casino`, `sports betting`, `erectile`, `viagra`, `cbd gummies`, `crypto`, `bitcoin`, `nft`

---

## Database Schema Reference

This runbook keeps the schema view operator-focused. For the deeper end-to-end reference, use [../data/ingestion/MEAL_DEAL_INGESTION.md](../data/ingestion/MEAL_DEAL_INGESTION.md).

### Canonical meal-deal tables

| Table | Purpose | Operator note |
|---|---|---|
| `canonical_venues` | Canonical physical venue identity | Venue-level targeting and dedupe live here, not in raw `local_employers`. |
| `canonical_venue_aliases` | Maps `local_employers` to canonical venues | Review-queue alias actions update this table. |
| `site_identities` | Canonical normalized website identity | Contested-site state and ownership scope live here. |
| `site_assignments` | Maps sites to venue or brand scope | Site review actions write back here. |
| `deal_observations` | Canonical observed deal artifact | First place to debug `review_state`, `signal_quality`, and raw evidence. |
| `deal_applicability` | Venue or brand targeting for an observation | Drives where observations materialize. |
| `deal_materializations` | Consumer-facing per-venue deal rows | `/api/deals`, `/api/deals/stats`, and `/api/deals/brands` read this layer. |

### Operational and compatibility tables

#### `restaurant_urls` table

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `local_employer_id` | Integer FK | Which restaurant |
| `url` | String | Website URL |
| `source` | String | `osm`, `google_places`, `manual`, `chain_config` |
| `is_active` | Boolean | Default `true` |
| `last_checked` | DateTime | Last scrape attempt |
| `last_http_status` | Integer | HTTP status from last fetch |
| `has_deals_page` | Boolean | `true` if deals were found last run |

#### `meal_deals` compatibility table

`meal_deals` is still dual-written, but it is no longer the primary semantic read source.

| Column | Type | Notes |
|---|---|---|
| `local_employer_id` | Integer FK | Nullable for some historical or chain-template rows |
| `brand_group_id` | Integer FK | Set for chain-scoped rows |
| `deal_name` | String | Compatibility display field |
| `deal_description` | Text | Raw or normalized deal text |
| `price`, `original_price`, `menu_avg_price` | Float | Legacy-compatible pricing fields |
| `valid_days`, `valid_start_time`, `valid_end_time` | String | Normalized temporal fields |
| `source` | String | `website_scrape`, `chain_website`, `gbp_offer`, `manual`, and other legacy values |
| `verified_at` | DateTime | Used by stale sweep |
| `is_active` | Boolean | Legacy visibility flag |

**Unique constraint:** `(local_employer_id, deal_name, source)` remains the compatibility dedupe key in `meal_deals`.

---

## Configuration Files

| File | Purpose |
|---|---|
| `config/meal_deal_sources.yaml` | Chain deal source configurations (URL, strategy, selectors) |
| `config/scheduler.yaml` | Cron schedules for all meal deal jobs |
| `config/chains.yaml` | Chain store/jobs metadata (not meal deals) |
| `.env` | API keys (`GOOGLE_MAPS_API_KEY`, `SERPAPI_KEY`, etc.) |

### Adding a new chain to `config/meal_deal_sources.yaml`

```yaml
chain_deal_sources:
  new_chain:
    display_name: "New Chain Name"
    strategy: static_html          # or menu_only, playwright_required, app_only
    url: "https://www.newchain.com/deals"
    fingerprint: "new_chain"       # must match brand_groups.fingerprint
    selectors:
      deal_sections: "h2, h3"
      deal_description: "p"
      price_pattern: '\$\d+\.?\d*'
```

---

## Troubleshooting

### "No module named 'sqlalchemy'" on Orange Pi

The venv is missing dependencies. Re-install:
```bash
cd ~/First-Helios && source .venv/bin/activate
pip install -r requirements.txt
```

### DuplicateTable error on Alembic migration

The DB schema exists but `alembic_version` table is empty. The test script handles this automatically with `alembic stamp head`. Manually:
```bash
alembic stamp head && alembic upgrade head
```

### Website scraper finds 0 deals for a known restaurant

1. Check the audit log: `cat data/cache/website_scrape_audit.json | python3 -m json.tool | grep -A 20 "RestaurantName"`
2. If `sample_blocks` shows deal-like text → the quality filter is too strict
3. If `total_blocks: 0` → page is JS-rendered, may need Playwright
4. If `needs_pdf_reader: true` → deals are in PDF menu files
5. If the site returns HTTP 403/503 → may need Playwright or manual entry via SpiritPool
6. If discovered pages or sections increase but items stay at 0, discovery improved but extraction is still blocked by a price-less item list or JS-rendered menu. Treat that as `DOM-01` or `RENDER-01`, not a target-selection failure.

### Chain scraper returns empty for a specific chain

1. Visit the chain's deal URL in a browser — the page may have changed
2. Check if the strategy is `app_only` (no web deals available)
3. For `playwright_required` chains, ensure Chromium is installed: `playwright install chromium`
4. Check `config/meal_deal_sources.yaml` for stale selectors

### Purge script flags legitimate deals as junk

If a real deal is caught by `keyword_only_no_price`, the deal text block likely doesn't contain a `$X.XX` price pattern. Options:
- Add the specific phrase to `_SELF_VALIDATING_KEYWORDS` in `website_scraper.py`
- Add a price to the source page (SpiritPool manual entry)
- If the source is `chain_website`, it should already be exempt — check the `source` column
