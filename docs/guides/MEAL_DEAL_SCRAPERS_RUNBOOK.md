# Meal Deal Scrapers — Runbook & Operations Guide

> Audience: developers/operators who run, tune, or debug the meal deal collection pipeline.

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

The meal deal system has three independent scrapers feeding into a shared ingest pipeline:

| Component | Targets | Schedule | Source Tag |
|---|---|---|---|
| **website_scraper** | Individual restaurant websites (non-chain) | Mon/Wed/Fri 2 AM | `website_scrape` |
| **chain_deals** | National chain deal pages (McDonald's, etc.) | Monday 6 AM | `chain_website` |
| **gbp_offers** | Google Business Profile offer posts via SerpApi | Tue/Fri 3 AM | `gbp_offer` |

Each scraper produces `DealSignal` objects that flow through `ingest_deal_signals()` into the `meal_deals` database table.

Supporting services:
- **OSM URL Resolver** — free batch URL discovery via OpenStreetMap Overpass
- **Google Places Resolver** — paid URL discovery for restaurants OSM misses
- **Stale Deal Sweep** — deactivates deals not re-verified in 14 days
- **Purge Script** — retroactive junk data cleanup

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
         ┌──────────────────┐
         │ ingest_deal_signals()  │
         │ dedup + brand fan-out  │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │   meal_deals      │
         │   (PostgreSQL)    │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │ deactivate_stale  │
         │ _deals() (Sun 5AM)│
         └──────────────────┘
```

---

## Running Individual Scrapers

### Website Scraper (local restaurants)

Scrapes non-chain restaurant websites by probing common deal paths: `/`, `/menu`, `/specials`, `/deals`, `/lunch`, `/happy-hour`, `/promotions`, `/offers`, plus dynamically discovered subpages.

> **Note:** robots.txt is intentionally ignored — we are promoting restaurants' own deals to drive them traffic and customers. Rate limiting (1 req/sec) and the `skip-checked-days` default (3 days) keep server load minimal.

```bash
# Activate environment
cd ~/First-Helios
source .venv/bin/activate
set -a && source .env && set +a

# Dry run — see what would be found, no DB writes
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --dry-run

# Live run — scrape and ingest into DB (default: 100 sites, skip recently checked)
PYTHONPATH=. python collectors/meal_deals/website_scraper.py

# Limit to 20 sites (useful for testing)
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --max-sites 20

# Lower-memory live run on Orange Pi
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --chunk-size 25

# SCAN EVERYTHING — all sites, ignore skip window, no DB writes
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --dry-run

# SCAN EVERYTHING — all sites, ignore skip window, write to DB
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0

# Force re-scrape all but still cap at 100 sites
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --skip-checked-days 0

# Target a specific region
PYTHONPATH=. python collectors/meal_deals/website_scraper.py --region austin_tx
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

#### What it does per site

1. Fetches each path in `DEAL_PATHS` (8 URLs, 1 req/sec)
2. Discovers additional deal subpages from homepage links (up to 4 more, 12 pages max per site)
3. Strips nav/footer/script/style HTML subtrees
4. Extracts text blocks from `<p>`, `<h1>`-`<h6>`, `<li>`, `<td>`, `<div>`, `<span>`, `<article>`, `<section>` tags
5. Parses JSON-LD structured data (`<script type="application/ld+json">`) for schema.org Offer/MenuItem types
6. Downloads and parses PDF menus/flyers found on pages (up to 3 per site, requires `pdfplumber`)
7. Filters through quality gates (keyword match, price required, no boilerplate)
8. Produces `DealSignal` objects → `ingest_deal_signals()` → DB
9. Writes audit log to `data/cache/website_scrape_audit.json`

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
PYTHONPATH=. python collectors/meal_deals/chain_deals.py --dry-run

# Live run
PYTHONPATH=. python collectors/meal_deals/chain_deals.py

# Specific region
PYTHONPATH=. python collectors/meal_deals/chain_deals.py --region austin_tx
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
PYTHONPATH=. python -m collectors.meal_deals.gbp_offers --max-calls 5 --dry-run

# Live run — default 100 API calls, writes to DB
PYTHONPATH=. python -m collectors.meal_deals.gbp_offers

# Query ALL restaurants (up to 200 API calls)
PYTHONPATH=. python -m collectors.meal_deals.gbp_offers --all

# Query ALL, dry run
PYTHONPATH=. python -m collectors.meal_deals.gbp_offers --all --dry-run

# Custom call budget
PYTHONPATH=. python -m collectors.meal_deals.gbp_offers --max-calls 50
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
PYTHONPATH=. python scripts/osm_url_resolver.py --dry-run

# Live — resolves URLs from OpenStreetMap Overpass
PYTHONPATH=. python scripts/osm_url_resolver.py
```

Runs weekly on Sunday 1 AM. Free, bulk, but incomplete (~40% coverage).

### Google Places Resolver (paid)

```bash
# Dry run — shows what would be resolved
PYTHONPATH=. python scripts/google_places_resolver.py --mode both --max-calls 50 --dry-run

# Live — resolve up to 200 URLs (brands first, then individual)
PYTHONPATH=. python scripts/google_places_resolver.py --mode both --max-calls 200
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
PYTHONPATH=. python scripts/purge_junk_deals.py

# Actually delete junk rows
PYTHONPATH=. python scripts/purge_junk_deals.py --apply
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

Every website scraper run writes an audit log with per-site outcomes.

### Audit log location

```
data/cache/website_scrape_audit.json
```

### Audit entry fields

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

### How to use the audit log

**1. Check overall success rate:**
```bash
cat data/cache/website_scrape_audit.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
outcomes = {}
for e in data:
    outcomes[e['outcome']] = outcomes.get(e['outcome'], 0) + 1
total = len(data)
for k, v in sorted(outcomes.items(), key=lambda x: -x[1]):
    print(f'  {k:20s} {v:4d}  ({v/total*100:.0f}%)')
print(f'  {\"TOTAL\":20s} {total:4d}')
"
```

**2. Find sites that need PDF reading:**
```bash
cat data/cache/website_scrape_audit.json | python3 -c "
import json, sys
for e in json.load(sys.stdin):
    if e.get('needs_pdf_reader'):
        print(f\"{e['name']:40s} {e['url']}\")
        for pdf in e.get('pdf_links', []):
            print(f\"  → {pdf}\")
"
```

**3. Review no-deal sites with text samples:**
```bash
cat data/cache/website_scrape_audit.json | python3 -c "
import json, sys
for e in json.load(sys.stdin):
    if e['outcome'] == 'no_deals' and e.get('sample_blocks'):
        print(f\"\\n=== {e['name']} ({e['url']}) ===\")
        print(f\"  Total text blocks: {e.get('total_blocks', '?')}\")
        for b in e['sample_blocks'][:3]:
            print(f\"  → {b[:120]}\")
"
```

### Manual assessment workflow

1. Run the scraper: `PYTHONPATH=. python collectors/meal_deals/website_scraper.py --max-sites 200`
2. Open `data/cache/website_scrape_audit.json`
3. Filter for `outcome: "no_deals"` entries
4. Review `sample_blocks` to determine why no deals were found:
   - **Blocks look like deals but were filtered** → loosen quality filters
   - **Blocks are all menu items** → site doesn't advertise deals on the web
   - **No text blocks extracted at all** → page is JS-rendered, may need Playwright
   - **PDF links present but `needs_pdf_reader: true`** → install `pdfplumber` (`pip install pdfplumber`)
   - **HTTP 403/503 errors** → site blocks scraping at HTTP level, enter deals manually via SpiritPool
5. Track improvement opportunities in `MEAL_DEAL_ROADMAP.md`

---

## Stale Deal Sweep

Deactivates deals not re-verified within a configurable window (default: 14 days).

```bash
# Via the full test script (runs automatically at end)
RUN_STALE_SWEEP=1 bash scripts/run_meal_deal_full_test.sh

# Inline Python (as used by the test script)
PYTHONPATH=. python -c "
from collectors.meal_deals.ingest import deactivate_stale_deals
for src in ['website_scrape', 'chain_website', 'google_places']:
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

### `meal_deals` table

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `local_employer_id` | Integer FK | Links to `local_employers.id` |
| `brand_group_id` | Integer FK | Nullable; chains have this set |
| `deal_name` | String | NOT NULL |
| `deal_description` | Text | Nullable; full text block |
| `deal_type` | String | `lunch_special`, `combo`, `bogo`, `happy_hour`, `kids_eat_free`, `daily_special` |
| `price` | Float | Nullable; extracted `$X.XX` value |
| `original_price` | Float | Nullable; before-discount price |
| `menu_avg_price` | Float | Nullable; average entrée price on same page |
| `calories` | Integer | Nullable; extracted kcal |
| `calorie_price_ratio` | Float | Nullable; `calories / price` |
| `valid_days` | String | Nullable; "Mon-Fri", "Tuesday", etc. |
| `valid_start_time` | String | Nullable; "11:00 AM" |
| `valid_end_time` | String | Nullable; "2:00 PM" |
| `is_recurring` | Boolean | Default `true` |
| `source` | String | `chain_website`, `website_scrape`, `gbp_offer`, `google_places`, `manual` |
| `source_url` | String | Nullable |
| `is_active` | Boolean | Default `true`; stale sweep sets to `false` |
| `verified_at` | DateTime | Nullable; last time deal was confirmed |
| `region` | String | Default `austin_tx` |

**Unique constraint:** `(local_employer_id, deal_name, source)` — prevents duplicate deals per restaurant per source.

### `restaurant_urls` table

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
