# Project Intent Evaluation: ChainStaffingTracker (First Helios)

**Date:** 2026-03-22  
**Purpose:** Independent code-based assessment of what this project actually does, what the intent was, and how the database should be organized.

---

## 1. What This Project Is Actually Doing

After reading the code (not just the docs), here is my assessment of the project's real intent:

### The Core Idea

**This is a community job fair targeting tool for Austin, TX.** It answers one question:

> "If we want to hold a community job fair near a business location, which locations have the most staffing stress, and therefore the most need?"

The system:
1. Tracks **all business locations** across Austin, organized into two categories:
   - **Chains** — large-cap organizations with many spanning locations (Starbucks, Jiffy Lube, Super Cuts, Americas Best, etc.)
   - **Local** — independent businesses with 1-10 locations
2. Continuously collects **staffing stress signals** from public data sources (government labor data, job boards, public reviews, social media sentiment)
3. Computes a **composite staffing stress score** per location (0-100, tiers: critical/elevated/adequate)
4. Ranks locations by a **targeting score** that combines staffing stress with wage gap, geographic isolation, and local employer density
5. Serves this via a **Flask API + map frontend** where someone can see which business locations are the best candidates for job fair placement

> **NOTE:** This is a recent evolution from an earlier food-service-only focus. The system is now intended to cover ALL industries, not just restaurants and retail.

### The Decision It Supports

The targeting module (`backend/targeting.py`) makes this explicit. The output is a ranked list with fields like:
- `staffing_stress` — is this store struggling to hire?
- `wage_gap` — are chains here underpaying vs. local market?
- `isolation` — is this store far from other same-chain stores (harder to share staff)?
- `local_alternatives` — are there non-chain employers nearby (good for job fair attendees)?
- `recommended_timing` — "Immediate", "Within 2 weeks", or "Monitor"

This is not a general-purpose labor analytics platform. **It is a tactical decision tool for placing community employment events near specific business locations — both chain and local — that show hiring distress.**

---

## 2. How the Code Actually Works (The Real Pipeline)

### Data Collection Layer

The system has ~15 scraper adapters. These fall into two categories:

#### Active Sources (public data APIs, third-party aggregators)

| Source | What It Gets | How It's Used |
|---|---|---|
| **JobSpy (Indeed/Glassdoor)** | Job postings + wage data for chains AND local employers | Demand + wage gap signals |
| **BLS QCEW** | County-level establishment counts & wages by NAICS | Ground-truth baseline denominator |
| **BLS JOLTS** | National quit rates & job openings by industry | Expected churn benchmark |
| **BLS OEWS** | Occupation wages by MSA (638 occupations) | Market median wage reference |
| **BLS LAUS** | County unemployment rates | Labor market tightness |
| **Census CBP** | ZIP-level establishment counts | Sub-metro geographic granularity |
| **Reddit** | Sentiment posts about businesses | Qualitative stress signal |
| **Google Maps** | Review scores | Qualitative signal |
| **Overture/OSM/AllThePlaces** | Business location POIs (chain + local) | Location discovery + local alternatives |
| **NLRB** | Labor unrest filings | Stress signal |
| **WARN Act** | Layoff notices | Labor market signal |
| **Revelio Labs** | Third-party labor analytics (pre-downloaded CSVs) | Employment, salary, attrition data |

#### Future Plans — Direct Website Scraping (separate project)

| Source | What It Scrapes | Status |
|---|---|---|
| **Starbucks Workday API** (`careers_api.py`) | Job postings from Starbucks careers portal | Built, but belongs in separate web-scraping project |
| **Workday Playwright fallback** (`playwright_fallback.py:WorkdayScraper`) | Same data via headless browser | Built, same — separate project |
| **Legacy CLI** (`scraper/scrape.py`) | Thin wrapper around careers_api.py | Same — separate project |

> **Decision:** Any scraping that targets a specific business's website (Workday portals, company career pages) requires its own project with dedicated anti-bot handling, session management, and maintenance. These are architecturally distinct from consuming public APIs.

All active-source scrapers normalize to `ScraperSignal` objects and feed through `backend/ingest.py`. Scrapers never write directly to the DB.

### Scoring Layer

The scoring engine (`backend/scoring/engine.py`) computes four sub-scores:

1. **Demand Pressure** (35%) — Active postings per establishment vs. regional baseline. Uses QCEW establishment counts as denominator.
2. **Wage Competitiveness** (25%) — How far below market median the chain pays. Uses OEWS median wage.
3. **Churn Signal** (25%) — Posting velocity vs. expected turnover. Uses JOLTS quit rate × employment.
4. **Qualitative** (15%) — Sentiment from Reddit + Google Reviews.

These combine into a composite 0-100 score. Seasonal adjustment is applied if QCEW quarterly data shows current quarter above/below annual average.

### Targeting Layer

Sits on top of scoring. Takes the composite score and adds:
- Wage gap (chain vs. local avg)
- Geographic isolation (distance to nearest same-chain store)
- Local employer density (how many non-chain employers nearby = more job fair value)

Output: ranked locations with tiers (prime/strong/moderate) and recommended timing.

---

## 3. What's Actually in the Database Right Now

| Table | Rows | Assessment |
|---|---|---|
| `stores` | 178 | 154 are "bls" pseudo-stores (QCEW data points shoehorned into the store model), 24 are "qcew" pseudo-stores. **Zero actual chain store locations.** |
| `signals` | 497 | All from `bls_cpi`, `bls_eci`, and `qcew` sources. **Zero career posting signals, zero sentiment signals, zero review signals.** |
| `scores` | 712 | All composite scores are `0.0` tier "adequate". **No meaningful scores have been computed.** |
| `wage_index` | 1,318 | QCEW-derived wage entries. No chain-specific or job-posting-derived wages. |
| `qcew_data` | 149 | Actual QCEW data from BLS. This is real ground-truth data. |
| `jolts_data` | 730 | Actual JOLTS time series. Real data. |
| `oews_data` | 638 | All Austin MSA occupations. Real data. |
| `laus_data` | 426 | Local unemployment stats. Real data. |
| `cbp_data` | 0 | Empty. Never fetched. |
| `labor_market_baseline` | 5 | 5 NAICS codes for Austin (food service sub-sectors). |
| `local_employers` | 0 | Empty. Never populated. |
| `ref_brands` | 6 | Starbucks, Dutch Bros, McDonald's, Whataburger, Target, Chipotle. |
| `ref_industry` | 11 | NAICS hierarchy for accommodation/food + retail. |
| `ref_regions` | 1 | Austin, TX only. |
| `meta_job_runs` | 0 | **No jobs have been tracked.** |
| `meta_api_calls` | 0 | **No API calls tracked in meta system.** |

### What This Tells Us

**The government data layer (QCEW, JOLTS, OEWS, LAUS) is populated and real.** These are the baseline/benchmark tables and they have meaningful data.

**The operational layer (stores, signals, scores) has been co-opted.** BLS economic indicators and QCEW data points were stuffed into the `stores` and `signals` tables as pseudo-records (store_num like `QCEW-austin_tx-hvac_skilled_trades`). This was likely done because the scrapers that produce real chain-store signals (careers API, JobSpy, Reddit, Google) haven't been successfully run against the database yet.

**The metadata system exists but is empty operationally.** Tables are defined and cataloged (22 entries in meta_table_catalog), but `meta_job_runs` and `meta_api_calls` have zero entries, meaning no scraper has actually logged through the metadata system.

---

## 4. Where Intent and Reality Diverge

### Intent vs. Code vs. Data

| Aspect | Documented Intent | What Code Does | What Data Shows |
|---|---|---|---|
| Business tracking | Track ALL businesses (chains + local) | Models stores but conflates with econ data | No real business locations — only QCEW pseudo-stores |
| Direct website scraping | Company careers pages | Built (Workday API + Playwright) | **Out of scope** — belongs in separate project |
| JobSpy wage collection | Local vs chain wage comparison | Fully built (chain + wage modes) | No job-board-derived wage data |
| Sentiment | Reddit + Google Reviews | Adapters exist | 0 sentiment signals |
| Scoring | Economically-grounded 4-component score | Fully built with ground-truth + fallback | All scores are 0.0 (no input signals to score) |
| Targeting | Ranked job fair locations | Fully built with haversine distance | No meaningful targets (nothing to rank) |
| Multi-industry | ALL industries, not just food service | Config auto-generated from OEWS | Database still primarily food-service focused (baselines only for NAICS 72xxx) |

### The Multi-Industry Gap

The config (`chains.yaml`) was auto-generated to cover all 22 SOC industry groups (Management, IT, Healthcare, etc.) — **and this IS the intent**. But the code and data haven't caught up:
- The `ref_industry` table only has 11 entries, all in accommodation/food/retail
- The `ref_brands` table has 6 entries, all food service + 1 retail (Target)
- The baseline computation only maps NAICS 72 (food) and 44-45 (retail) to JOLTS codes
- The scoring engine defaults to NAICS 7225 (restaurants) if it can't determine the chain's industry

The all-industry intent is correct. The code and reference data need to be expanded to match it.

---

## 5. The Core Architecture Assessment

### What's Well-Designed

1. **The scraper → signal → ingest pipeline** is solid. `ScraperSignal` as a universal interface, with `backend/ingest.py` as the single write gate, is clean.
2. **The scoring formula** is economically sensible. Using QCEW establishment counts as denominator, JOLTS quit rates as churn benchmark, and OEWS median wages as market reference is the right approach.
3. **The ground-truth data tables** (qcew_data, jolts_data, oews_data, laus_data) are well-modeled with proper unique constraints and temporal keys.
4. **The rate manager** is thorough — 16 API sources registered with daily budgets, latency tracking, and scalability metrics.
5. **The targeting concept** (combining staffing stress + wage gap + isolation + local alternatives) is a genuinely useful community development tool.
6. **The all-industry config generation** (from OEWS data) is the right approach — derive config from data, not maintain it manually.

### What's Problematic

1. **The `stores` table conflates chains, local businesses, and economic data.** A BLS series ID is not a store. QCEW county aggregates are not stores. And chain locations vs. local businesses have fundamentally different data profiles. The table needs to be split.

2. **The `signals` table is too generic.** Everything is a "signal" with a float `value` — but establishment counts, CPI index values, wages, and job posting counts are categorically different things. The metadata_json blob compensates, but at the cost of queryability.

3. **The database has no separation between "physical-location data" and "regional-economic data."** QCEW county-level establishment counts should not live in the same conceptual space as "how many job postings does a specific business have."

4. **Direct website scraping is mixed into the main project.** `careers_api.py` and the Workday Playwright fallback are architecturally different from consuming public APIs (BLS, JobSpy, Overture). They require their own anti-bot handling, session management, and per-site maintenance.

5. **The metadata system is infrastructure without content.** The tables exist, the ORM models work, but nothing writes to `meta_job_runs` or `meta_api_calls`. The health dashboard would show nothing useful.

6. **Reference data is still food-service-centric despite all-industry intent.** `ref_industry` (11 entries, all food/accommodation/retail), `ref_brands` (6 entries, all food + 1 retail), and the baseline NAICS→JOLTS mapping all need expansion.

---

## 6. Recommended Database Organization

Given what this project is *really doing*, here's how I'd organize the database to match intent:

### Principle 1: Separate "Where" from "What We Know About There"

The fundamental confusion in the current schema is that geographic/economic context data is being forced through the same model as business-location tracking. These are two different concerns.

### Principle 2: Chains vs. Local is a first-class distinction

The system tracks ALL businesses, but the two populations are fundamentally different:
- **Chains** (large-cap orgs with spanning locations): discovered via AllThePlaces, Overture, OSM. Matched to `ref_brands`. Tracked individually by store ID.
- **Local** (1-10 locations): discovered via Overture, OSM, job boards. No brand profile. Tracked as employer POIs.

This distinction affects how signals are collected, how scores are computed, and how targeting works.

### Principle 3: Direct website scraping is a separate project

The data pipeline should rely on:
- Government APIs (BLS, Census, NLRB, WARN)
- Third-party job board aggregators (JobSpy → Indeed/Glassdoor)
- Public POI datasets (Overture, OSM, AllThePlaces)
- Public review/social data (Google Maps reviews, Reddit)

Scraping individual company websites (Workday portals, etc.) requires different infrastructure (anti-bot, session management, per-site maintenance). This lives in a `future_plans/web_scraping/` directory.

### Proposed Layer Structure

```
LAYER 1: GROUND TRUTH (Government Labor Data)
├── qcew_data          — County establishment counts & wages by NAICS (quarterly)
├── jolts_data         — National turnover rates by industry (monthly)
├── oews_data          — MSA occupation wages (annual)
├── laus_data          — County unemployment (monthly)
└── cbp_data           — ZIP establishment counts (annual)

  Purpose: Denominators and benchmarks. These NEVER become stores or signals.
  These are the "physics" of the local labor market.
  Covers ALL industries, not just food service.

LAYER 2: BUSINESS LOCATIONS (What exists and where)
├── chains             — Locations of large multi-location organizations
│                        (discovered via AllThePlaces, Overture, OSM)
│                        Linked to ref_brands. Has store_id, chain, lat/lng.
├── local_businesses   — Independent businesses (1-10 locations)
│                        (discovered via Overture, OSM, job boards)
│                        No brand profile. Has name, category, lat/lng.
└── store_aliases      — Deduplication across discovery sources

  Purpose: The physical "where" layer. One row = one real place.
  Chain vs. local is a first-class distinction.

LAYER 3: SIGNALS (What we observe about specific locations)
├── signals            — Observations tied to specific locations
│                        (job postings, review scores, sentiment mentions)
│                        FK to chains or local_businesses.
└── wage_index         — Wage observations from job boards
│                        Chain wages (tied to chain locations)
│                        Local market wages (tied to geographic areas)

  Purpose: Time-series observations about real places.
  ONLY data that ties to a physical location belongs here.

LAYER 4: DERIVED / COMPUTED
├── labor_market_baseline  — Combines QCEW+JOLTS+OEWS+LAUS per region+NAICS
└── (future: regional_metrics, seasonal_indices)

  Purpose: Pre-computed benchmarks the scoring engine needs.
  Should cover ALL NAICS codes, not just food service.

LAYER 5: BUSINESS OUTPUT
├── scores             — Per-location staffing stress scores (composite + sub-scores)
├── snapshots          — Periodic scrape summaries
└── (future: targeting_cache, alerts)

  Purpose: The answers that drive decisions.

LAYER 6: REFERENCE
├── ref_brands         — Chain profiles (any large multi-location org)
├── ref_industry       — NAICS hierarchy (ALL industries)
├── ref_regions        — Regional economic context
├── ref_category_map   — External taxonomy crosswalk

  Purpose: Slowly-changing dimension data.
  ref_brands + ref_industry need expansion beyond food service.

LAYER 7: SYSTEM TRACKING
├── api_sources        — Registry of external APIs
├── api_request_log    — Individual HTTP request log
├── rate_budgets       — Daily rate limit rollups
├── meta_table_catalog — Table registry
├── meta_column_catalog— Column documentation
├── meta_data_lineage  — Data flow tracking
├── meta_job_runs      — Job execution log
└── meta_api_calls     — API call tracking (consolidate with api_request_log)
```

### Key Changes From Current State

1. **Split `stores` into `chains` and `local_businesses`.** The current system conflates chain locations, local employers, and economic data pseudo-records in one table. The new structure makes the chain-vs-local distinction explicit and enforces that only real physical locations get rows.

2. **Stop creating pseudo-stores for economic data.** QCEW records stay in `qcew_data`. BLS series data stays in their dedicated tables. The business-location tables are reserved exclusively for real places with addresses and coordinates.

3. **Clean the `signals` table.** Signals should only be things observed about a specific location: job posting count, review score, sentiment mention. Not CPI indices or establishment counts.

4. **The `wage_index` should have two clear populations:**
   - Chain wages (from job boards, tied to specific chains)
   - Local market wages (from job boards, tied to geographic areas)
   
   Currently it's being populated with QCEW aggregate data, which is a misuse. QCEW wage data belongs in `qcew_data`.

5. **Move direct website scrapers to `future_plans/web_scraping/`.** Files: `scrapers/careers_api.py`, the `WorkdayScraper` class from `scrapers/playwright_fallback.py`, and `scraper/scrape.py`. These are a separate project.

6. **Consolidate API tracking.** There are currently TWO parallel systems:
   - `meta_api_calls` (from metadata.py) — 0 rows, never used
   - `api_request_log` + `rate_budgets` (from rate_manager.py) — 24 rows, actually used
   
   Pick one. The rate_manager system is the one with actual data.

7. **Expand reference data to all industries.** `ref_industry` needs entries for all NAICS sectors, not just food/accommodation/retail. `ref_brands` needs entries for chains in healthcare, logistics, retail, etc. The baseline computation needs NAICS → JOLTS mappings for all sectors.

8. **The metadata tables need actual content.** `meta_column_catalog` has 10 entries for a database with 200+ columns. `meta_data_lineage` has 5 entries for a system with 30+ table-to-table relationships. Either invest in filling these out or simplify to what's maintainable.

---

## 7. Summary: What I Think This Project Is

**ChainStaffingTracker is a community-facing labor intelligence tool focused on Austin, TX.**

Its intent is to identify which business locations — both chain and local, across ALL industries — are experiencing the most staffing stress, so that community organizations (workforce development, nonprofits, local government) can target job fairs, training programs, or other employment interventions to the locations where they'll have the most impact.

The two key entity types:
- **Chains** — large-cap multi-location organizations (Starbucks, Target, HEB, etc.)
- **Local businesses** — independent operations with 1-10 locations

It does this by combining:
- **Government ground truth** (how many establishments exist, what's normal turnover, what's the market wage)
- **Real-time signals from public sources** (job board postings, public reviews, social media sentiment)
- **Geographic context** (how isolated is this location, what are the local employer alternatives)

Into a scored, ranked, map-visualized decision support tool.

**Data collection relies on public APIs and third-party aggregators.** Direct scraping of individual company websites (Workday portals, etc.) is a separate project with different infrastructure needs.

**The code is architecturally sound for this purpose.** The scraper pipeline, scoring formula, and targeting logic are well-thought-out. The government data tables are properly modeled.

**The execution gap is that the operational layer (location discovery → signals → scores) hasn't been run yet.** The government data is loaded, the infrastructure is built, but the business location discovery and signal collection that feeds the scoring hasn't produced data. And in the meantime, economic indicators were pushed into the store/signal model as a workaround, muddying the schema's intent.

---

## 8. If We Agree: Next Steps

If this assessment matches your understanding, I recommend:

1. **Split `stores` into `chains` + `local_businesses`** — make the distinction first-class, remove pseudo-stores, enforce that only real locations get rows
2. **Move direct website scrapers** — `careers_api.py`, `WorkdayScraper`, `scraper/scrape.py` → `future_plans/web_scraping/`
3. **Expand reference data to all industries** — `ref_industry` and `ref_brands` need entries beyond food service
4. **Expand baseline computation** — NAICS → JOLTS mappings for all sectors, not just 72 and 44-45
5. **Clean signals + wage_index** — remove economic-indicator pseudo-signals, keep QCEW data in QCEW tables
6. **Consolidate API tracking** — pick `api_request_log` or `meta_api_calls`, not both
7. **Enforce layer boundaries in code** — validation that prevents economic data from entering business-location tables
8. **Populate metadata or simplify** — decide investment level for meta_ tables

The database reorganization separates chains from local businesses, cleans the layer boundaries, and prepares the schema for all-industry coverage.
