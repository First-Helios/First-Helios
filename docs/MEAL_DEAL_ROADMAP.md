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

## Phase 5 — Yelp Fusion Enrichment

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
