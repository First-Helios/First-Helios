# Meal Deal Collector — Integration Roadmap

> **Objective:** Build a `collectors/meal_deals/` module that discovers meal deals for restaurants already in our `local_employers` table and surfaces them on the Job Faire map alongside employer data.

---

## What We Have Today

| Asset | Details |
|-------|---------|
| **Full-service restaurants** | 1,924 rows in `local_employers` (industry = `food_full_service`) |
| **Fast food** | 3,245 rows (industry = `fast_food`) |
| **Bars / nightlife** | 494 rows (industry = `bar_nightlife`) |
| **Brand groups** | Top chains identified with `location_count` — Subway (82), McDonald's (58), Sonic (46), Whataburger (36), etc. |
| **Per-location data** | Name, normalized fingerprint, address, lat/lng, H3 hex cells, Overture ID, category, brand_group_id |
| **Ingest pipeline** | `core/ingest_layer.py` handles all writes — normalization, fingerprint, brand_group upsert |
| **Collector patterns** | `collectors/events/` uses a decorator registry + `EventSignal` dataclass; `collectors/base.py` has `BaseScraper` + `ScraperSignal` |
| **Geocoding** | `collectors/geocoding.py` — Nominatim with Austin overrides |

**Key insight:** We already know *where* the restaurants are and *what* they're called. The problem is finding *what deals they offer* — which lives on their websites, Google Business Profiles, and third-party aggregators.

---

## Architecture Overview

```
collectors/meal_deals/
├── __init__.py
├── registry.py          # @deal_collector decorator (mirrors events/registry.py)
├── models.py            # MealDeal SQLAlchemy model + DealSignal dataclass
├── google_places.py     # Step 1: resolve local_employers → website URLs via Places API
├── chain_deals.py       # Step 2: scrape known chain deal pages (static URLs)
├── website_scraper.py   # Step 3: crawl individual restaurant sites for deal keywords
├── yelp_offers.py       # Step 4: Yelp Fusion "deals/offers" enrichment
└── manual_ingest.py     # SpiritPool / CSV fallback for human-sourced deals
```

---

## Phase 1 — Schema & Foundation

### 1a. `meal_deals` Table

New table in `core/database.py`:

```
meal_deals
├── id                  INTEGER PK
├── local_employer_id   FK → local_employers.id   (which restaurant)
├── brand_group_id      FK → brand_groups.id       (nullable, for chain-wide deals)
├── deal_name           VARCHAR                    ("$5.99 Lunch Combo")
├── deal_description    TEXT                       (full text of the deal)
├── deal_type           VARCHAR                    (lunch_special | combo | bogo | happy_hour | kids_eat_free | daily_special)
├── price               FLOAT nullable             (deal price if stated)
├── original_price      FLOAT nullable             (regular price for comparison)
├── valid_days          VARCHAR nullable            ("Mon-Fri" or "Tuesday" or null=everyday)
├── valid_start_time    TIME nullable               (11:00)
├── valid_end_time      TIME nullable               (14:00)
├── is_recurring        BOOLEAN default true
├── start_date          DATE nullable               (seasonal deals)
├── end_date            DATE nullable
├── source              VARCHAR                    ("chain_website" | "google_places" | "yelp" | "manual" | "website_scrape")
├── source_url          VARCHAR nullable
├── verified_at         TIMESTAMP
├── is_active           BOOLEAN default true
├── created_at          TIMESTAMP
├── updated_at          TIMESTAMP
├── lat                 FLOAT                      (denormalized from local_employer)
├── lng                 FLOAT
├── region              VARCHAR default 'austin_tx'
```

**Indexes:** `local_employer_id`, `brand_group_id`, `deal_type`, `region`, `is_active`.

### 1b. `DealSignal` Dataclass

Analogous to `ScraperSignal` and `EventSignal` — the normalized container all deal collectors produce before DB write.

### 1c. Deal Collector Registry

Mirror `collectors/events/registry.py` — `@deal_collector("chain_deals", schedule="0 6 * * 1")` decorator so the scheduler auto-discovers deal collectors.

---

## Phase 2 — Website URL Resolution (Google Places API)

**Problem:** `local_employers` has name + address but *not* website URLs. We need URLs before we can scrape for deals.

**Approach:** Use the Google Places API (Text Search or Find Place) to match our existing `name + address` pairs to a Place, then extract the `website` field.

```
Input:  "Bee Cave Bistro", "11715 FM 2244, Bee Cave, TX"
Output: { place_id: "ChIJ...", website: "https://beecavebistro.com", ... }
```

**Cost management:**
- Google Places Text Search: $32/1000 requests (expensive at 5,663 restaurants)
- Strategy: batch by brand_group first — resolve one Subway website and apply to all 82 locations
- **Chain websites are static** — only ~200 unique brand_groups need resolution, not 5,663 individual locations
- For local (non-chain) restaurants: prioritize those on the Job Faire map first, backfill others weekly
- Cache results in a new `employer_websites` column or small `restaurant_urls` lookup table
- Budget estimate: ~200 brand lookups + ~500 local priority lookups = ~700 calls = ~$22

**Alternative (free):** Use the Overpass/Nominatim pipeline we already have — OSM has `website` tags on many POIs. Query first, use Google Places only for gaps.

**Priority order for URL resolution:**
1. OSM Overpass `website` tag (free, ~30-40% coverage)
2. Google Places API for remaining high-priority locations
3. Manual/SpiritPool for stragglers

---

## Phase 3 — Chain Deal Scraper

**This is the highest-ROI step.** Chains publish deals on predictable, stable URLs. One scrape covers dozens/hundreds of locations.

### Target Chains (from brand_groups data)

| Chain | Locations | Typical Deal Page Pattern |
|-------|-----------|--------------------------|
| Subway | 82 | subway.com/deals |
| McDonald's | 58 | mcdonalds.com/us/en-us/deals.html |
| Sonic | 46 | sonicdrivein.com/deals |
| Jack in the Box | 45 | jackinthebox.com/deals |
| Taco Bell | 38 | tacobell.com/deals |
| Whataburger | 36 | whataburger.com/offers |
| P. Terry's | 35 | pterrys.com (local chain — check menu page) |
| Pizza Hut | 34 | pizzahut.com/deals |
| Domino's | 55 | dominos.com/deals |
| Wendy's | 30 | wendys.com/deals |
| ThunderCloud Subs | 30 | thundercloud.com (local — menu page) |
| Chipotle | 29 | chipotle.com/deals |
| Jimmy John's | 24 | jimmyjohns.com/menu |
| Smoothie King | 24 | smoothieking.com/deals |
| Taco Cabana | 23 | tacocabana.com/deals |

**Implementation:**
- One static config mapping `brand_group.fingerprint → deal_page_url`
- Use `requests` + `BeautifulSoup` (already in the project's toolchain) to parse deal pages
- Extract: deal name, price, description, valid days/times
- Some chains serve deals via JavaScript-rendered pages → use `collectors/playwright_fallback.py` (already exists)
- Run weekly (deals change slowly); cron schedule `0 6 * * 1` (Monday 6 AM)

**Output:** For each deal found, create one `meal_deals` row per location of that chain. e.g. 1 Subway deal × 82 locations = 82 rows, all linked via `brand_group_id`.

---

## Phase 4 — Local Restaurant Website Scraper

For non-chain restaurants (~1,200 unique local `food_full_service` employers):

1. **Keyword scan:** Crawl the restaurant's homepage + `/menu`, `/specials`, `/deals`, `/lunch` pages
2. **Signal keywords:** "special", "deal", "combo", "$X.99", "lunch special", "happy hour", "BOGO", "kids eat free", "early bird", "daily special", "Monday", "Tuesday" (day-of-week patterns)
3. **LLM extraction (optional future):** For unstructured pages, pass the text to a cheap model (Haiku) to extract structured deal info — but this is a Phase 5 optimization, not needed at launch

**Rate limiting:** Max 1 req/sec, respect robots.txt. Use `collectors/rotation.py` user-agent rotation already in the project.

**Prioritization:**
- Start with restaurants that already have a `website` URL from Phase 2
- Skip restaurants with no web presence (flag for SpiritPool human collection)

---

## Phase 5 — Yelp Fusion Enrichment ##SKIP NO FREE TRIAL. Must be done via SpiritPool. 

Yelp Fusion API (free, 5,000 calls/day):
- `GET /v3/businesses/search` by name + lat/lng to match our employers
- Check `transactions` field for "deals" flag
- Check `special_hours` for limited-time promotions
- Use as validation layer to confirm deals found via web scraping

**Not a primary source** — Yelp rarely surfaces specific deal text. Use as a signal boost.

---

## Phase 6 — SpiritPool / Manual Ingest Fallback

For restaurants with no web presence or JavaScript-heavy sites:
- `collectors/meal_deals/manual_ingest.py` accepts CSV or JSON
- Schema: `restaurant_name, address, deal_name, deal_description, deal_type, price, valid_days, valid_times`
- SpiritPool contributors can submit deals via the existing contributor pipeline
- Verified deals get `source = "manual"` and a `verified_at` timestamp

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    local_employers                               │
│         (5,663 food/drink locations with name, address, lat/lng)│
└───────────────────────┬─────────────────────────────────────────┘
                        │
              ┌─────────▼──────────┐
              │  URL Resolution    │
              │  OSM → Google API  │
              └─────────┬──────────┘
                        │
          ┌─────────────┼─────────────────┐
          ▼             ▼                 ▼
   Chain Deals     Website Scraper    Manual / SpiritPool
   (15-20 chains)  (local restaurants)  (human fallback)
          │             │                 │
          └─────────────┼─────────────────┘
                        ▼
              ┌─────────────────────┐
              │   DealSignal        │
              │   (normalized)      │
              └─────────┬───────────┘
                        ▼
              ┌─────────────────────┐
              │   meal_deals table  │
              │   (PostgreSQL)      │
              └─────────┬───────────┘
                        ▼
              ┌─────────────────────┐
              │   API / Map Layer   │
              │   (Job Faire Map)   │
              └─────────────────────┘
```

---

## Implementation Order

| Step | What | Effort | Depends On |
|------|------|--------|------------|
| **1** | Schema: `meal_deals` table + `DealSignal` dataclass + migration | Small | — |
| **2** | Registry: `collectors/meal_deals/registry.py` | Small | — |
| **3** | OSM website URL extraction (free, batch) | Small | — |
| **4** | Chain deal scraper (top 15 chains = 630 locations covered) | Medium | Steps 1-2 |
| **5** | Google Places URL resolution for remaining locals | Small | API key + budget |
| **6** | Local website scraper (keyword-based) | Medium | Steps 1-2, 3 or 5 |
| **7** | Manual ingest CLI for SpiritPool | Small | Step 1 |
| **8** | API endpoint: `GET /api/deals?lat=&lng=&radius=` | Small | Step 1 |
| **9** | Map layer integration (deal pins/overlay on Job Faire) | Medium | Step 8 |
| **10** | Yelp enrichment pass | Small | Step 1 |

**Recommended starting point:** Steps 1-4 — schema + chain deals. This covers ~630 locations (Subway, McDonald's, Sonic, etc.) with minimal effort since chain deal pages are stable and predictable.

---

## API Design (for Step 8)

```
GET /api/deals
  ?lat=30.27&lng=-97.74         # center point
  &radius_mi=5                  # search radius
  &deal_type=lunch_special      # optional filter
  &day=monday                   # optional: show deals valid today
  &active_only=true             # default true

Response:
{
  "deals": [
    {
      "id": 42,
      "restaurant_name": "Subway",
      "address": "123 Congress Ave, Austin, TX",
      "lat": 30.2672,
      "lng": -97.7431,
      "deal_name": "$5.99 Footlong",
      "deal_description": "Any footlong sub for $5.99",
      "deal_type": "combo",
      "price": 5.99,
      "valid_days": "Mon-Fri",
      "valid_start_time": "11:00",
      "valid_end_time": "14:00",
      "source": "chain_website",
      "verified_at": "2026-04-13T06:00:00Z"
    }
  ],
  "count": 47,
  "region": "austin_tx"
}
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Chain deal pages are JS-rendered (React/Angular) | `collectors/playwright_fallback.py` already exists for this |
| Google Places API cost overrun | OSM-first strategy; batch by brand_group; cap daily budget |
| Deal data goes stale quickly | Weekly refresh for chains, monthly for locals; `verified_at` timestamp on every row; surface staleness in UI |
| robots.txt blocks scraping | Respect it; fall back to SpiritPool manual entry |
| Low coverage for local restaurants | Acceptable — chains cover the high-traffic locations; locals are a long tail |

---

## Success Metrics

- **Phase 1 target:** 15+ chain brands with active deals loaded (covering ~630 locations)
- **Phase 2 target:** 100+ local restaurants with at least one deal
- **Freshness:** 90% of chain deals verified within the last 7 days
- **Map coverage:** Deals visible on Job Faire map pins for all covered restaurants

---

## Current Implementation Status (Updated April 13, 2026)

### Completed

| Step | Status | Details |
|------|--------|---------|
| **1** Schema | ✅ Done | `meal_deals` table + `restaurant_urls` table — migrations applied (`c412787993e6`, `c8edac5d7232`) |
| **2** Registry | ✅ Done | `@deal_collector` decorator in `collectors/meal_deals/registry.py` — auto-discovered by scheduler |
| **3** OSM URL extraction | ✅ Done | `osm_url_resolver.py` — 1,758 OSM POIs queried, 758 unique employer URLs stored (free) |
| **4** Chain deal scraper | ✅ Done | `chain_deals.py` — static + Playwright strategies. 54 signals → 961 deal rows ingested (fanned out across locations) |
| **5** Google Places resolver | ✅ Done | `google_places_resolver.py` — 250 API calls → 1,344 URLs stored (217 brands resolved). Mode: brands/locals/both |
| **6** Website scraper (Phase 4) | ✅ Done | `website_scraper.py` — keyword-based crawl. robots.txt blocked → SpiritPool flagging. Schedule: Mon/Wed/Fri. |
| **7** Manual ingest CLI | ✅ Done | `manual_ingest.py` — CSV/JSON for SpiritPool contributions |
| **8** API endpoints | ✅ Done | `GET /api/deals`, `/api/deals/stats`, `/api/deals/brands` — geo-filtered, paginated |
| **9** Map layer integration | 🔲 Spec ready | Mailbox doc created: `agentMailbox/FH-3_meal_deal_map_layer.md` |
| **10** Yelp enrichment | ⏭ Skipped | No free trial. Manual via SpiritPool instead. |
| **PW** Playwright integration | ✅ Done | `chain_deals.py` handles `playwright_required` strategy. 6 chains configured. |
| **UTM** URL cleaning | ✅ Done | Both resolvers strip UTM/tracking params from URLs before storage |
| **RL** Overpass rate limiting | ✅ Done | 60s cooldown between Overpass queries + 60s/120s exponential backoff on 429/504 |
| **Filter** ThunderCloud fix | ✅ Done | `menu_only` strategy now filters with deal-signal keywords — reduced from 80 to 6 results |
| **SP** SpiritPool handoff | ✅ Done | `agentMailbox/ToSpiritPool/07_MEAL_DEAL_BLOCKED_SITES.md` — blocked sites flagged automatically |
| **Live** Chain ingest | ✅ Done | 961 active deal rows in `meal_deals` table across 3 chain brands |

### Data Coverage

| Source | URLs Resolved | Notes |
|--------|--------------|-------|
| OSM Overpass | 758 unique employers | Free. 1,758 POIs fetched, matched by fingerprint + proximity |
| Google Places | 1,344 unique employers | 250 API calls (~$8 of $200 budget). Brand batch mode. |
| **Total** | **2,102 / 5,662** (37%) | Remaining 3,560 mostly single-location locals |

| Metric | Value |
|--------|-------|
| Active meal deals | 961 rows |
| Deal sources | chain_website |
| Brands with deals | 3 (McDonald's, Taco Bell, Domino's + others via fingerprint match) |
| Google API budget used | ~$8.00 / $200 = **$192 remaining** (~24 more weekly runs) |
| Google trial window | 90 days from activation |

### Chain Scraper Results by Strategy

| Chain | Strategy | Deals Found | Notes |
|-------|----------|-------------|-------|
| McDonald's | static_html | 12 | ✅ |
| Taco Bell | static_html | 20 | ✅ |
| Domino's | static_html | 7 | ✅ |
| Wendy's | static_html | 3 | ✅ |
| Taco Cabana | static_html | 4 | ✅ |
| P. Terry's | menu_only | 2 | ✅ Filtered — only actual deals, not full menu |
| ThunderCloud | menu_only | 6 | ✅ Fixed — was 80 items before deal keyword filter |
| Pizza Hut | playwright_required | — | Reclassified — static fetch always times out |
| Jimmy John's | playwright_required | — | Reclassified — static returned 0 deals |
| Subway | playwright_required | — | HTTP2 protocol error — aggressive bot protection |
| Sonic | playwright_required | 0 | Page loads but deals live in dynamic JS components |
| Jack in the Box | playwright_required | 0 | SPA with dynamic client routing |
| Chipotle | playwright_required | — | Rewards-based promotions, not traditional deals |
| Smoothie King | playwright_required | — | DoubleClick redirect chain |
| Whataburger | app_only | skipped | Deals exclusive to MyWhataburger app |

### Scheduler Integration

All jobs registered in `config/scheduler.yaml` and `core/scheduler.py`:

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `osm_url_resolver` | Sunday 1:00 AM | Re-query OSM Overpass for new restaurant websites |
| `google_places_resolver` | Tuesday 2:00 AM | Resolve remaining brand URLs (200 calls/run budget) |
| `deal_chain_deals` | Monday 6:00 AM | Scrape chain restaurant deal pages (all strategies) |
| `deal_website_scraper` | Mon + Wed + Fri 2:00 AM | Scrape local restaurant websites for deals |
| `deal_stale_sweep` | Sunday 5:00 AM | Deactivate deals not verified in 14+ days |

### Files Created / Modified

| File | Purpose |
|------|---------|
| `core/database.py` | Added `MealDeal` + `RestaurantURL` models |
| `collectors/meal_deals/__init__.py` | Module init |
| `collectors/meal_deals/models.py` | `DealSignal` dataclass |
| `collectors/meal_deals/registry.py` | `@deal_collector` decorator + registry |
| `collectors/meal_deals/chain_deals.py` | Chain scraper — static + menu_only + Playwright strategies |
| `collectors/meal_deals/osm_url_resolver.py` | OSM Overpass → restaurant_urls (with rate limiting + URL cleaning) |
| `collectors/meal_deals/google_places_resolver.py` | Google Places API → restaurant_urls (with UTM stripping) |
| `collectors/meal_deals/website_scraper.py` | Local website scanner — blocked sites → SpiritPool flagging |
| `collectors/meal_deals/ingest.py` | DealSignal → meal_deals upsert pipeline |
| `collectors/meal_deals/manual_ingest.py` | CSV/JSON CLI for SpiritPool |
| `collectors/meal_deals/routes.py` | Flask Blueprint `/api/deals` |
| `config/meal_deal_sources.yaml` | 15-chain config (static/menu/playwright/app strategies) |
| `config/scheduler.yaml` | 5 meal deal scheduler jobs |
| `core/scheduler.py` | `_register_deal_collectors`, URL resolver runners, stale sweep |
| `server.py` | Registered `deals_bp` + `RestaurantURL` import |
| `agentMailbox/FH-3_meal_deal_map_layer.md` | Frontend map integration spec |
| `agentMailbox/ToSpiritPool/07_MEAL_DEAL_BLOCKED_SITES.md` | SpiritPool blocked-site manual collection spec |

### Remaining TODOs

1. **Playwright chain tuning** — Subway (HTTP2 error), Sonic/Jack in the Box (0 deals from JS SPA). Need deeper DOM inspection or API discovery for these chains. Consider monitoring their mobile app traffic.
2. **Google Places local resolution** — 3,560 individual employers still need URLs. Scheduler runs `--mode both --max-calls 200` weekly. Budget: $192 remaining → ~24 weeks of runway within 90-day trial.
3. **Map layer integration (Step 9)** — Spec in `agentMailbox/FH-3_meal_deal_map_layer.md`. Frontend team needs to implement deal pins, filter controls, and deal cards.
4. **Deploy to OrangePi server** — Ingest + scheduler should run on the OrangePi (192.168.1.191), not local dev. Sync codebase and configure cron/systemd.
5. **Website scraper first live run** — Now that 2,102 URLs exist, run `website_scraper.py` to discover local restaurant deals.
6. **Fingerprint gaps** — 32 chain deal signals skipped due to missing brand_group fingerprint matches. Need to audit/add fingerprints for McDonald's, Wendy's, etc. in `meal_deal_sources.yaml`.

### Cautions

- **Google Places API budget**: $200 free credits (90-day trial). ~$8 used → **$192 remaining**. At 200 calls/week × $0.032/call = $6.40/week → budget covers ~30 weeks but trial expires in ~77 days.
- **Overpass rate limits**: Enforced with 60s cooldown file (`data/cache/.overpass_last_query`) + 60s/120s exponential backoff on 429/504. Never run concurrent Overpass queries.
- **robots.txt → SpiritPool**: Sites that block all deal paths via robots.txt are auto-flagged to `data/cache/spiritpool_blocked_sites.json` and documented in `agentMailbox/ToSpiritPool/07_MEAL_DEAL_BLOCKED_SITES.md`.
- **Stale deals**: 14-day expiry. Chain deals refresh weekly (Monday). Local deals refresh Mon/Wed/Fri. Stale sweep runs Sunday 5 AM.
- **URL quality**: UTM/tracking params are now stripped from all URLs before storage. Both `_normalize_url()` functions filter `utm_*`, `fbclid`, `gclid`, `mc_*`, `ref`, `source` params.
- **Playwright chains**: 6 chains require Playwright (Pizza Hut, Jimmy John's, Subway, Sonic, Jack in the Box, Chipotle, Smoothie King). Some have aggressive bot protection — may need SpiritPool fallback for persistent failures.
