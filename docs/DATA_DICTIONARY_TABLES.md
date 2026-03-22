# ChainStaffingTracker — Table-Level Data Dictionary

**Version:** 1.0
**Last Updated:** 2026-03-22
**Maintainer:** First-Helios Team
**Contact:** [Link to team/slack channel]

---

## Overview

This document describes the **purpose, source, and refresh cadence** of every table in `data/tracker.db`. Use this to understand the *intention* behind each table and decide where to fetch data for new features.

**Key Principle:** Each table has a single **authoritative source** and a **purpose** within the staffing-stress scoring pipeline.

---

## Table Index (by Schema)

### OPERATIONAL SCHEMA
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [stores](#stores) | Chain store locations in Austin MSA | Scrapers (AllThePlaces, Overture, OSM) | Weekly | 178 |
| [signals](#signals) | Raw observations from all sources | Scrapers (Careers API, Reddit, reviews, job boards) | Daily/6h | 497 |
| [scores](#scores) | Composite & sub-scores per store | Scoring engine | After each signal ingest | 712 |
| [wage_index](#wage_index) | Job posting wages across all sources | Scrapers (JobSpy, Workday, aggregators) | Weekly | 1318 |

### GROUND-TRUTH SCHEMA (BLS / Census)
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [qcew_data](#qcew_data) | County employment & establishment counts | BLS QCEW CSV API | Monthly (6mo lag) | 149 |
| [jolts_data](#jolts_data) | National turnover, openings, hires rates | BLS JOLTS API v2 | Monthly (2mo lag) | 730 |
| [laus_data](#laus_data) | County unemployment rates | BLS LAUS API v2 | Monthly (2mo lag) | 426 |
| [oews_data](#oews_data) | Occupation wage percentiles by MSA | BLS OEWS flat files | Annual (May) | 0 |
| [cbp_data](#cbp_data) | ZIP-level establishment counts | Census CBP API | Annual (18mo lag) | 0 |

### DERIVED SCHEMA
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [labor_market_baseline](#labor_market_baseline) | Computed ground-truth baseline | Derived from QCEW+JOLTS+OEWS+LAUS | After ground-truth fetch | 5 |

### OPERATIONAL (Non-scoring)
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [local_employers](#local_employers) | Non-chain employers (POIs) | Overture Maps, OSM | Monthly | 0 |

### REFERENCE SCHEMA
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [ref_brands](#ref_brands) | Brand metadata (Starbucks, Dutch Bros, etc.) | Manual config + web enrichment | Quarterly | 6 |
| [ref_industry](#ref_industry) | NAICS industry categories | BLS NAICS taxonomy | Annual | 11 |
| [ref_regions](#ref_regions) | Region definitions (Austin MSA) | Manual config + Census | Quarterly | 1 |
| [ref_category_map](#ref_category_map) | Mapping of category → industry | Manual + scrapers (Overture, OSM tags) | Quarterly | 168 |

### ALTERNATIVE LABOR STATISTICS SCHEMA
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [revelio_labor_metrics](#revelio_labor_metrics) | Employment, hiring, attrition by state/industry/occupation | Revelio Labs (proprietary web scraping) | Manual load (2021-2026 historical) | 23K+ (TX) |
| [revelio_layoff_notices](#revelio_layoff_notices) | WARN Act mass layoff filings by state & NAICS | Revelio Labs (WARN filings) | Manual load (2021-2026 historical) | 62 (national) |

### OPERATIONAL METADATA SCHEMA
| Table | Purpose | Source | Refresh | Rows |
|---|---|---|---|---|
| [api_sources](#api_sources) | API endpoint registry & rate limits | Manual config | As needed | 16 |
| [api_endpoints](#api_endpoints) | Specific adapter configs & health | Manual config + runtime health checks | Real-time | 16 |
| [api_request_log](#api_request_log) | HTTP request telemetry | Automatic on each request | Real-time | 24 |
| [rate_budgets](#rate_budgets) | Daily API quota usage per source | Automatic rollup from request_log | Daily | 2 |
| [source_freshness](#source_freshness) | Data staleness tracking | Automatic status checker | Daily | 0 |
| [snapshots](#snapshots) | Period scan summaries | Automatic after each full cycle | Weekly | 2 |
| [store_aliases](#store_aliases) | Store ID deduplication/merging history | Manual when stores merge/close | As needed | 0 |

---

## Data Flow & Schema Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     EXTERNAL SOURCES                             │
│  (BLS APIs, Census, Careers APIs, Job Boards, Reddit, Reviews)   │
└────────────────────────┬────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌─────────────────────────────────────────┐
   │  OPERATIONAL SCHEMA                     │
   │  (Live scraper data)                    │
   │  ┌─────────────┬──────────┬─────────┐   │
   │  │   stores    │ signals  │  wage_  │   │
   │  │             │          │  index  │   │
   │  └─────────────┴──────────┴─────────┘   │
   │         (scrapers → ingest → enrich)    │
   └──────────────┬──────────────────────────┘
                  │
        ┌─────────┼─────────┐
        │         │         │
        ▼         ▼         ▼
   ┌──────────────────────────────────────────────────────────┐
   │  GROUND-TRUTH SCHEMA (Government Labor Statistics)       │
   │  ┌──────────────┬──────────┬──────────┬────────────────┐ │
   │  │ qcew_data    │jolts_data│laus_data │oews_data cbp_ │ │
   │  │(quarterly)   │(monthly) │(monthly) │(annual) data  │ │
   │  └──────────────┴──────────┴──────────┴────────────────┘ │
   │  [Append-only from BLS/Census; 2-18mo lag]              │
   └──────────────┬───────────────────────────────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────────────────┐
   │  DERIVED SCHEMA (Computed Baselines)         │
   │  ┌──────────────────────────────────────────┐│
   │  │   labor_market_baseline                  ││
   │  │  (Combines all BLS ground-truth)         ││
   │  └──────────────────────────────────────────┘│
   └──────────────┬───────────────────────────────┘
                  │
        ┌─────────┘
        │
        ▼
   ┌──────────────────────────────────────────┐
   │  SCORING ENGINE                          │
   │  (Uses baselines as denominators)        │
   │  ┌──────────────────────────────────────┐│
   │  │           scores table                ││
   │  │ (composite + 4 sub-scores per store)  ││
   │  └──────────────────────────────────────┘│
   └──────────────┬───────────────────────────┘
                  │
        ┌─────────┴─────────────┐
        │                       │
        ▼                       ▼
   ┌─────────────────────┐  ┌──────────────────────────┐
   │ REFERENCE SCHEMA    │  │ OPERATIONAL METADATA     │
   │ (Master data)       │  │ (System health)          │
   │ ┌─────────────────┐ │  │ ┌────────────────────┐   │
   │ │ ref_brands      │ │  │ │api_sources         │   │
   │ │ ref_industry    │ │  │ │api_endpoints       │   │
   │ │ ref_regions     │ │  │ │api_request_log     │   │
   │ │ ref_category_map│ │  │ │rate_budgets        │   │
   │ └─────────────────┘ │  │ │source_freshness    │   │
   │ [Static lookups]    │  │ │snapshots           │   │
   └─────────────────────┘  │ │store_aliases       │   │
                             │ └────────────────────┘   │
                             │ [Telemetry & logs]      │
                             └──────────────────────────┘
                                      │
                                      ▼
                               ┌──────────────┐
                               │   Frontend   │
                               │  (map, api)  │
                               └──────────────┘
```

---

## Schema Organization

The database is logically organized into **5 distinct schemas** (though physically stored in one SQLite DB):

| Schema | Purpose | Tables | Refresh |
|---|---|---|---|
| **Operational** | Live scraper data and scoring | stores, signals, scores, wage_index | Daily/Real-time |
| **Ground-Truth (BLS/Census)** | Government labor statistics | qcew_data, jolts_data, laus_data, oews_data, cbp_data | Monthly–Annual |
| **Derived / Baseline** | Computed from ground-truth | labor_market_baseline | Weekly |
| **Reference / Master Data** | Lookup tables and configs | ref_brands, ref_industry, ref_regions, ref_category_map | Quarterly–Annual |
| **Operational Metadata** | System health and telemetry | api_sources, api_endpoints, api_request_log, rate_budgets, source_freshness, snapshots, store_aliases | Real-time |

**Why this organization?**
- **Operational** tables are written by scrapers; change frequently
- **Ground-Truth** tables are append-only from government sources; change on government schedule
- **Derived** tables are computed from ground-truth; updated after ground-truth arrives
- **Reference** tables are static master data; rarely change
- **Metadata** tables track system health and don't affect scoring

---

## Operational Tables (Core)

### stores

**Purpose:** Physical chain locations within the Austin MSA. Single source of truth for all geographic presence.

**Source:** Hybrid:
- [AllThePlaces](https://data.alltheplaces.xyz/) — GeoJSON snapshots of chain locations (Starbucks, Dutch Bros)
- [Overture Maps](https://www.overturemaps.org/) — High-accuracy location POI data
- [OpenStreetMap Overpass](https://overpass-turbo.eu/) — Community-maintained fallback

**Refresh Cadence:**
- Full scan: Weekly (Sundays 2-3am)
- Update existing: Real-time on observations (new address in signal triggers store lookup)

**Rows:** 178 (24 stores per chain + competitor context stores)

**Quality Notes:**
- Lat/lng may be NULL for historical records (geocoding not run)
- is_active = False indicates store has closed (but kept for historical scoring)
- store_num format: `{chain_prefix}-{location_id}` (e.g., `SB-03347`, `DB-08821`)

---

### signals

**Purpose:** Every raw observation from any public source. The foundation of the scoring pipeline.

**Sources (one row per source per observation):**
| Source | Signal Types | Refresh |
|---|---|---|
| careers_api | listing (Starbucks/Dutch Bros job postings) | Daily 3am |
| jobspy | listing (Indeed, Glassdoor, LinkedIn) + wage | Daily 4am |
| reddit | sentiment (keyword matches in r/austin, r/austinfood, etc.) | Every 6 hours |
| google_maps | review_score, staffing_keywords | Weekly Monday 5am |
| bls | establishment_count, wage (from QCEW) | Monthly |
| qcew | establishment_count, wage | Monthly |

**Refresh Cadence:** Continuous (stale signals >90 days are down-weighted in scoring)

**Rows:** 497 (growing as adapters run)

**Key Columns:**
- `value`: Normalized 0-1 (except wage postings, which are raw)
- `metadata_json`: Arbitrary per-source, typically includes store_name, url, address, engagement metrics
- `observed_at`: When the source published (not when we fetched it)

---

### scores

**Purpose:** Composite staffing-stress index per store + 4 sub-scores. Output of the scoring engine.

**Source:** Computed by `backend/scoring/engine.py` after each signal ingest.

**Refresh Cadence:** After every signal batch (daily/6-hourly depending on job)

**Rows:** 712 (24 stores × ~30 historical snapshots)

**Score Types:**
| score_type | Meaning | Range | Ideal |
|---|---|---|---|
| composite | Final weighted staffing-stress index | 0-100 | <50 |
| demand_pressure | Job postings relative to establishment norm | 0-100 | <50 |
| wage_competitiveness | Pay gap vs. local market | 0-100 | <50 |
| churn_signal | Postings explained by normal turnover? | 0-100 | <50 |
| qualitative | Reddit/review sentiment about staffing | 0-100 | <50 |

**Tiers:** `critical` (≥67th pctl), `elevated` (≥33rd pctl), `adequate` (<33rd pctl)

---

### wage_index

**Purpose:** Crowdsourced wage data from all job listings. Used to compute wage_competitiveness sub-score.

**Sources:**
| Source | Rows | Collection Method |
|---|---|---|
| jobspy (Indeed) | ~400 | Weekly via python-jobspy |
| jobspy (Glassdoor) | ~300 | Weekly via python-jobspy |
| jobspy (LinkedIn) | ~200 | Weekly via python-jobspy |
| workday (Starbucks) | ~50 | Daily from Starbucks careers page |
| Manual enrichment | ~100 | Quarterly spot-checks |

**Refresh Cadence:** Weekly (JobSpy job board scrape)

**Rows:** 1318 (growing; old rows >180 days retained for trend analysis)

**Key Columns:**
- `wage_min`, `wage_max`: Posted range (often missing on job boards)
- `wage_period`: `hourly` or `yearly`
- `is_chain`: True if employer is a major chain, False for local competitors
- `source_url`: Link to original posting

---

## Ground-Truth Schema (BLS / Census Labor Statistics)

**Purpose:** Authoritative labor market data from government sources. These tables are the denominators and benchmarks for all scoring formulas.

**Key Principle:** Append-only, never updated retroactively. New data arrives monthly–annually; old data retained for historical trending.

**Tables in this schema:**
- `qcew_data` — County employment & establishment counts (quarterly, 6mo lag)
- `jolts_data` — Job openings, quits, hires, separations (monthly, 2mo lag)
- `laus_data` — Unemployment rates & labor force (monthly, 2mo lag)
- `oews_data` — Occupation wage percentiles (annual, 12mo lag)
- `cbp_data` — ZIP-level establishments (annual, 18mo lag)

**Used by:**
- `labor_market_baseline` — Derives all benchmarks from these
- `scoring/engine.py` — Uses baselines as denominators in score formulas
- `targeting.py` — Identifies high-stress regions

---

### BLS Data: Understanding Government Labor Statistics

Before diving into individual tables, understand the **refresh cadences** and **data lags**:

| Survey | Monthly Release Date | Data Available (Example) | Table | Lag |
|---|---|---|---|---|
| **QCEW** | ~6 months after quarter | 2025-Q3 available March 2026 | qcew_data | 6 months |
| **JOLTS** | ~2 months after month | Dec 2025 available early Mar 2026 | jolts_data | 2 months |
| **LAUS** | ~2 months after month | Dec 2025 available early Mar 2026 | laus_data | 2 months |
| **OEWS** | May (annual only) | 2024 data May 2025 | oews_data | 12 months |
| **CBP** | ~18 months after year | 2024 data mid-2026 | cbp_data | 18 months |

**Key insight:** These tables are **append-only**. You never re-fetch old data; new data is always appended. Historical data is kept for trending.

**Impact on scoring:** The `labor_market_baseline` table uses the *latest available* data from all 5 BLS tables. If a table is stale, that metric is excluded from scoring (weights are redistributed).

---

### Ground-Truth Tables (BLS/Census)

These are fed by government labor statistics APIs. They have strict refresh schedules tied to government data release calendars.

### qcew_data

**Purpose:** County-level employment and establishment counts. The denominator for demand_pressure scoring.

**Source:** [BLS Quarterly Census of Employment & Wages (QCEW)](https://www.bls.gov/cew/) CSV API
**Data Lag:** ~6 months (Q3 2025 available as of 2026-03)

**Refresh Cadence:** 1st of month 7am (when new quarter is published) — active months: Jan, Apr, Jul, Oct

**Rows:** 149 (5 counties × 5 NAICS codes × 6 quarters)

**Coverage:**
- Counties: Travis (48453), Williamson (48491), Hays (48209), Bastrop (48021), Caldwell (48055)
- NAICS: 722515 (coffee), 722513 (limited-service), 722511 (full-service), 7225 (food services), 72 (accommodation & food)
- Ownership: 5 (private sector only)

**Key Columns:**
- `establishments`: Count of active employer locations
- `month1/2/3_employment`: Employment in each month of quarter
- `avg_annual_pay`: Annualized wage (not used directly; see wage_index)

---

### jolts_data

**Purpose:** National-level job opening, hiring, quit, and separation rates. Used for churn_signal sub-score.

**Source:** [BLS Job Openings & Labor Turnover Survey (JOLTS)](https://www.bls.gov/jlt/) API v2
**Data Lag:** ~2 months (Dec 2025 available as of 2026-03)

**Refresh Cadence:** Monday 6am (after BLS releases monthly data)

**Rows:** 730 (4 metrics × 2 industries × 12 months × 7+ years)

**Coverage:**
- Metrics: quits_rate, openings_rate, hires_rate, separations_rate
- Industries: National (all jobs), Industry 72 (accommodation & food)
- Time: Monthly, 2010–present

**Key Columns:**
- `value`: Seasonally adjusted percentage (e.g., 2.5 = 2.5% quits/month)
- `metric`: One of quits_rate, openings_rate, hires_rate, separations_rate

---

### laus_data

**Purpose:** County unemployment rates and labor force size. Used for baseline unemployment context.

**Source:** [BLS Local Area Unemployment Statistics (LAUS)](https://www.bls.gov/lau/) API v2
**Data Lag:** ~2 months

**Refresh Cadence:** Monday 6am

**Rows:** 426 (3 counties × 12 months × 12+ years)

**Coverage:**
- Counties: Travis, Williamson, Hays (main Austin MSA cores)
- Time: Monthly, 2010–present

**Key Columns:**
- `unemployment_rate`: Percentage unemployed (e.g., 3.5 = 3.5%)
- `labor_force`, `employed`, `unemployed`: Absolute counts

---

### oews_data

**Purpose:** Occupation-level wage percentiles (10th, 25th, median, 75th, 90th). Fine-grained wage benchmarking.

**Source:** [BLS Occupational Employment & Wage Statistics (OEWS)](https://www.bls.gov/oes/) flat files (Excel/CSV)
**Data Lag:** ~1 year (2024 data published May 2025, available 2026)

**Refresh Cadence:** Manual download in May (once per year); not yet automated

**Rows:** 0 (awaiting first import)

**Coverage:**
- Area: Austin-Round Rock-Georgetown MSA (area code 12420)
- SOC Occupations: 35-0000 (food prep/service), 35-3023, 35-2021, 35-1012, 35-3021 (detailed roles)
- Time: Annual

**Key Columns:**
- `wage_*pct`: Wage at 10th, 25th, 50th (median), 75th, 90th percentile
- `employment`: Number employed in occupation

---

### cbp_data

**Purpose:** ZIP-code-level establishment counts. Allows hyperlocal staffing stress targeting.

**Source:** [Census Bureau County Business Patterns (CBP)](https://www.census.gov/topics/employment/county-business-patterns.html) API
**Data Lag:** ~18 months (2024 data available 2026)

**Refresh Cadence:** Monday 8am (fresh checks; no automatic refresh schedule yet)

**Rows:** 0 (awaiting Census API key setup)

**Coverage:**
- ZIPs: 25 Austin area codes (downtown → suburbs → exurbs)
- NAICS: 722515, 722513, 722511 (same as QCEW)
- Time: Annual

**Key Columns:**
- `establishments`: Count per ZIP/NAICS/year
- `employment`: Total employment (may be withheld if <20 for privacy)
- `annual_payroll_k`: Total payroll in thousands

---

### Derived Schema: labor_market_baseline

**Purpose:** Computed baseline combining all BLS ground-truth tables (QCEW + JOLTS + OEWS + LAUS). Used as denominator in all scoring formulas. This is the bridge between raw government data and scoring logic.

**Source:** Derived table; computed by `backend/baseline.py` after ground-truth fetch
**Refresh Cadence:** Sunday 4am (after QCEW, JOLTS, LAUS are fetched)

**Rows:** 5 (1 per NAICS code tracked in region)

**Key Columns:**
- `establishment_count`: From QCEW
- `total_employment`: From QCEW (quarterly average)
- `expected_quits_rate`: From JOLTS
- `expected_monthly_separations`: Calculated from employment × quits_rate
- `occupation_median_wage`: From OEWS
- `unemployment_rate`: From LAUS
- `seasonal_index`: Calculated from quarterly employment variance

---

### local_employers

**Purpose:** Non-chain employers (POIs) to contextualize local labor market dynamics.

**Source:**
| Source | Filter |
|---|---|
| Overture Maps | category:`accommodation` or `food_and_drink` |
| OpenStreetMap | amenity:`restaurant`, `cafe`, `bar` (tags) |

**Refresh Cadence:** Monthly (Sunday 3am)

**Rows:** 0 (awaiting first Overture adapter run)

**Key Columns:**
- `overture_id`: Canonical ID from Overture
- `category`: Overture category code
- `confidence`: Quality score (0-1) from Overture

---

## Alternative Labor Statistics Schema (Revelio Labs)

**Purpose:** Premium labor market data from proprietary sources (web scraping of job boards + WARN Act filings). Complements government data with more current, granular, state-level metrics.

**Tables in this schema:**
- `revelio_labor_metrics` — Employment, hiring, attrition rates
- `revelio_layoff_notices` — WARN Act mass layoff filings

**Used by:**
- Baseline computation (optional fallback to JOLTS if stale)
- Scoring engine (alternative data for churn_signal)
- Targeting/analysis (hiring intensity by state/industry)

**Data Characteristics:**
- **Frequency:** Historical load (2021-2026 complete)
- **Granularity:** Monthly, by state, occupation (SOC 2-digit), industry (NAICS 2-digit)
- **Coverage:** All US states + territories
- **Lag:** Real-time to monthly (proprietary data, faster than JOLTS)

---

### revelio_labor_metrics

**Purpose:** Monthly employment, hiring rate, and attrition rate by state, industry, and occupation.

**Source:** [Revelio Labs](https://www.reveliolabs.com/public-labor-statistics/) — Proprietary employment data from 50+ job boards + LinkedIn + web scraping

**Refresh Cadence:** Manual load (historical data 2021-02-2026 available; new data arrives monthly but requires manual update)

**Rows:** ~23,200 per state × months (1.18M national)

**Key Columns:**
- `month` — YYYY-MM format (2021-01 to 2026-02)
- `state` — US state or territory
- `soc2d_code`, `soc2d_name` — Occupation (SOC 2-digit, e.g., "35" = Food Preparation & Service)
- `naics2d_code`, `naics2d_name` — Industry (NAICS 2-digit, e.g., "72" = Accommodation & Food Services)
- `count_nsa` — Employment count (not seasonally adjusted)
- `count_sa` — Employment count (seasonally adjusted)

**Comparison to Government Data:**
| Metric | JOLTS (Government) | Revelio (Private) |
|---|---|---|
| **Coverage** | National only | All states |
| **Granularity** | Industry (NAICS) | State × Industry × Occupation |
| **Currency** | 2-month lag | Real-time (monthly update) |
| **Source** | BLS survey of 16K+ establishments | Web scraping of 50+ job boards |

**Quality Notes:**
- Hiring/attrition rates derived from LinkedIn member flows + proprietary panel
- More current than JOLTS (real-time job board data)
- Good for state-level analysis (Texas accommodation & food)
- Can be compared to JOLTS for validation

---

### revelio_layoff_notices

**Purpose:** WARN Act mass layoff filings by state and industry.

**Source:** [Revelio Labs](https://www.reveliolabs.com/public-labor-statistics/) — WARN Act (Worker Adjustment & Retraining Notification) filings (official, public)

**Refresh Cadence:** Manual load (historical 2021-2026 available)

**Rows:** 2,433 (all states, monthly aggregates)

**Key Columns:**
- `month` — YYYY-MM format
- `state` — US state
- `num_employees_notified` — How many workers received WARN notices
- `num_notices_issued` — How many separate notices (companies)
- `num_employees_laidoff` — Actual layoffs (may be less than notified)

**Usage:**
- **Leading indicator:** Layoff notices precede employment drops by 2-3 months
- **Labor market shock detection:** Spike in notices → anticipate turnover surge
- **Regional analysis:** States/industries with high layoff activity

**Example (Texas 2021):**
```
2021-01: 1,130 notified, 16 notices, 1,129 laidoff
2021-02: 3,773 notified, 15 notices, 2,122 laidoff
```

---

## Reference Schema (Master Data / Lookups)

**Purpose:** Static or slowly-changing lookup tables that define the system's classification scheme.

**Key Principle:** These tables define *what we track* and *how we categorize it*. They rarely change (quarterly–annual updates).

**Tables in this schema:**
- `ref_brands` — Brand profiles (Starbucks, Dutch Bros, competitors)
- `ref_industry` — NAICS industry hierarchy
- `ref_regions` — Geographic region definitions
- `ref_category_map` — Cross-system category mappings (Overture → NAICS → internal)

**Used by:**
- All scrapers (to classify discovered locations)
- Scoring engine (to match stores to industry baselines)
- Frontend (to label and filter by chain/industry/region)

---

### Reference Tables (Lookup / Configuration)

These tables are primarily lookup tables that rarely change. They are the "master data" for the system.

### ref_brands

**Purpose:** Brand metadata (Starbucks, Dutch Bros, local competitors). Defines what chains/employers we track.

**Source:** Manual config (`config/chains.yaml`) + web enrichment (Wikipedia, company websites)

**Refresh Cadence:** Quarterly (Q1, Q2, Q3, Q4) when brands are added or company status changes

**Rows:** 6 (Starbucks, Dutch Bros + 4 competitor/context brands)

**Key Columns:**
- `brand_key`: Config identifier (e.g., `starbucks`, `dutch_bros`)
- `naics_code`: BLS industry code
- `atp_spider_names`: AllThePlaces name variants (JSON array)
- `overture_name_patterns`: Regex patterns to match Overture records
- `osm_tags`: OpenStreetMap tag filters
- `avg_starting_wage`: Historical posting wage (for baseline)
- `typical_store_staff`: Expected headcount (for staffing stress context)

---

### ref_industry

**Purpose:** NAICS industry hierarchy and characteristics.

**Source:** BLS NAICS taxonomy + manual enrichment

**Refresh Cadence:** Annual (when BLS updates NAICS codes)

**Rows:** 11 (food service, accommodation, beverage, etc.)

**Key Columns:**
- `naics_code`: BLS code (e.g., 722515)
- `internal_key`: Human-readable alias (e.g., `coffee_shops`)
- `parent_naics`: Broader category (e.g., 7225 is parent of 722515)
- `avg_employees_per_location`: Industry typical store size
- `seasonal_pattern`: `peak_summer`, `peak_holiday`, `steady`, etc.

---

### ref_regions

**Purpose:** Geographic region definitions (Austin MSA boundary, center, population).

**Source:** Manual config + Census Bureau (boundaries, population, income)

**Refresh Cadence:** Quarterly (as population estimates update)

**Rows:** 1 (Austin-Round Rock-Georgetown MSA, TX)

**Key Columns:**
- `center_lat`, `center_lng`: Map center
- `bbox_*`: Bounding box for spatial queries
- `population`: ACS estimate
- `unemployment_rate`: Current LAUS regional average
- `min_wage_state`: State minimum wage
- `min_wage_local`: City minimum wage (if applicable)
- `living_wage_1adult`: MIT living wage calculator for 1 adult

---

### ref_category_map

**Purpose:** Maps heterogeneous category systems (Overture, OSM, NAICS, job boards) to internal industry codes.

**Source:** Manual mapping + ML classifier (optional future)

**Refresh Cadence:** Quarterly (as new categories are encountered)

**Rows:** 168 (many category codes → 11 internal industries)

**Example Mappings:**
- Overture `food_and_drink` → internal `food_service`
- OSM `amenity:cafe` → internal `coffee_shops`
- Glassdoor job category "Hospitality" → internal `accommodation`

---

## Operational Metadata Schema (System Health / Telemetry)

**Purpose:** Track API health, rate limits, request logs, and data staleness. These tables are about the *system's plumbing*, not the actual labor market data.

**Key Principle:** Real-time monitoring. Write-heavy (logs); rarely read except for alerts and dashboards.

**Tables in this schema:**
- `api_sources` — API registry with rate limits
- `api_endpoints` — Adapter configurations and health
- `api_request_log` — Every HTTP request (telemetry)
- `rate_budgets` — Daily quota rollup
- `source_freshness` — Data staleness alerts
- `snapshots` — Period summaries for trending
- `store_aliases` — Deduplication log

**Used by:**
- `backend/tracked_request.py` — Logs every HTTP call
- `pipeline/health.py` — Staleness checking and alerts
- `server.py` — `/api/health` endpoint
- Scheduler — To disable failed adapters

---

### Operational / Health Tables

### api_sources

**Purpose:** Registry of all external API sources with rate limits and auth.

**Source:** Manual config in code; one per external API

**Refresh Cadence:** As-needed (when adding new API)

**Rows:** 16 (BLS, Census, Reddit, JobSpy, Google, Overture, OSM, etc.)

**Key Columns:**
- `source_key`: Config identifier (e.g., `bls_api_v2`, `census_cbp`)
- `auth_type`: `none`, `api_key`, `oauth`, `basic`
- `daily_limit`: Rate limit (requests/day)
- `min_delay_seconds`: Minimum delay between requests (pacing)

---

### api_endpoints

**Purpose:** Detailed config for each scraper/adapter with health tracking.

**Source:** Manual config + runtime metrics

**Refresh Cadence:** Real-time health checks (every 6 hours)

**Rows:** 16 (one per adapter)

**Key Columns:**
- `adapter_name`: Human-readable name (e.g., "Starbucks Careers API")
- `intent`: What data it fetches (e.g., `job_postings`, `sentiment`, `unemployment`)
- `route_status`: `active`, `deprecated`, `testing`, `failed`
- `consecutive_failures`: If > 5, auto-disabled
- `last_success_at`: Last time data was successfully fetched

---

### api_request_log

**Purpose:** Detailed HTTP telemetry for every external request.

**Source:** Automatic logging via `backend.tracked_request` wrapper

**Refresh Cadence:** Real-time (one row per HTTP request)

**Rows:** 24 (growing; typically rolled off after 30 days)

**Key Columns:**
- `source_key`: Which API (BLS, Census, etc.)
- `status_code`: HTTP status (200, 429, 500, etc.)
- `latency_ms`: Request duration
- `data_items_returned`: How many records fetched
- `error_message`: If failed, why

---

### rate_budgets

**Purpose:** Daily quota rollup per API source. Alerts when approaching limits.

**Source:** Aggregated from `api_request_log` (computed daily)

**Refresh Cadence:** Daily 11:59pm UTC

**Rows:** 2 (one per active API source)

**Key Columns:**
- `used`: Requests made today
- `daily_limit`: Quota
- `succeeded`, `failed`: Count of successful vs. failed requests

---

### source_freshness

**Purpose:** Track staleness of all data sources. Alerts when data hasn't updated in >N days.

**Source:** Automatic status checker in `pipeline/health.py`

**Refresh Cadence:** Daily

**Rows:** 0 (not yet populated)

**Key Columns:**
- `status`: `fresh`, `stale`, `missing`
- `threshold_days`: Alert if no data in >N days
- `last_collected_at`: Last time this source returned data

---

### snapshots

**Purpose:** Periodic summary of scan results (used for dashboard charts).

**Source:** Computed after each full scrape cycle

**Refresh Cadence:** Weekly (Sunday nights after all jobs complete)

**Rows:** 2 (growing; retained for trend analysis)

**Key Columns:**
- `scanned_at`: Timestamp of scan
- `store_count`: How many stores identified
- `signal_count`: How many raw signals collected
- `summary_json`: Arbitrary aggregates (by chain, by source, etc.)

---

### store_aliases

**Purpose:** Deduplication log. When two store_num entries refer to the same physical location, merge them here.

**Source:** Manual review + automated collision detection

**Refresh Cadence:** As-needed

**Rows:** 0 (not yet used; future feature for multi-source store reconciliation)

**Key Columns:**
- `old_store_num`: Duplicate ID
- `canonical_store_num`: ID to keep
- `source_prefix`: Which scraper created the duplicate

---

## Data Lineage Summary

```
┌─────────────────────────────────────────────────────────────────┐
│ External APIs / Scrapers                                        │
│ (BLS, Census, Careers APIs, Job Boards, Reddit, Google, etc.)  │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ├─→ signals (raw observations)
           │    ├─→ scored by scoring engine
           │    └─→ scores (composite + sub-scores)
           │
           ├─→ qcew_data, jolts_data, laus_data, oews_data (ground truth)
           │    └─→ labor_market_baseline (computed)
           │         └─→ used by scoring engine as denominators
           │
           ├─→ wage_index (crowd-sourced wages)
           │    └─→ used by scoring engine for wage_competitiveness
           │
           └─→ stores (locations)
                ├─→ scored per store
                └─→ linked in scores table

┌──────────────────────────────────────────────────────────────────┐
│ Frontend (server.py → /api routes)                               │
│ → Shows stores with scores on map                                │
│ → Drill-down into signal details, wage trends, baseline context  │
└──────────────────────────────────────────────────────────────────┘
```

---

## FAQ

**Q: How do I know if a data source is stale?**
A: Check `api_request_log` for the source_key's `last_success_at`. If > 7 days ago, investigate in `api_endpoints` (check `last_failure_reason`). For BLS data, check the "Data Lag" column above.

**Q: Why do some tables have 0 rows?**
A: `cbp_data`, `oews_data`, and `local_employers` require setup (API keys, manual download, adapter implementation). See CLAUDE_AGENT_HANDOFF.md section 10.

**Q: Where do I add a new data source?**
A:
1. Create a new scraper in `scrapers/{source_name}_adapter.py` inheriting from `BaseScraper`
2. Register it in `api_sources` and `api_endpoints` tables
3. Add a job to `backend/scheduler.py`
4. Add config to `config/chains.yaml`
5. Points to insert into will depend on signal type (see "signals" table purpose)

**Q: How is the composite score calculated?**
A: See `backend/scoring/engine.py`. It's a weighted sum of 4 sub-scores, with fallback to percentile ranking when ground-truth data is missing.

---

## Related Documents

- **Implementation:** `CLAUDE_AGENT_HANDOFF.md` — System architecture and outstanding work
- **Configuration:** `config/chains.yaml` — All tunable parameters
- **Data Model:** `backend/database.py` — SQLAlchemy table definitions
- **Scoring Logic:** `backend/scoring/engine.py` — How scores are computed
- **Ingestion:** `backend/ingest.py` — How signals become scores
