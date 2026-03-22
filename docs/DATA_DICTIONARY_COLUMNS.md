# ChainStaffingTracker — Column-Level Data Dictionary

**Version:** 1.0
**Last Updated:** 2026-03-22
**Format:** Following [Data Mesh](https://www.datamesh.io/) output port contract principles

---

## How to Use This Document

Each table's column definitions include:
1. **Column Name** — The field name in the database
2. **Type** — SQLAlchemy type (VARCHAR, INTEGER, FLOAT, DATETIME, BOOLEAN)
3. **Primary Key / Unique** — Constraint info
4. **Nullable** — Whether NULL is allowed
5. **Description** — What the field represents
6. **Example** — Real or realistic value
7. **Valid Range / Enum** — Constraints and valid values
8. **Source** — Where the value comes from (hardcoded, scraped, computed, etc.)
9. **SLA / Freshness** — How often updated and acceptable staleness

---

## Operational Tables

### stores

**Purpose:** Physical chain locations. Single row = one store.
**Primary Key:** `store_num`
**Relationships:** ← signals, ← scores

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| store_num | VARCHAR | ✗ | Unique store identifier (canonical) | `SB-03347` | Format: `{chain_prefix}-{id}`, e.g., SB, DB, XX | AllThePlaces, Overture, OSM, manual | Latest location capture |
| chain | VARCHAR | ✗ | Brand/chain identifier | `starbucks` | `starbucks`, `dutch_bros`, `local`, `qcew` | `config/chains.yaml` brands | At store creation |
| industry | VARCHAR | ✗ | Internal industry key | `coffee_shops` | One of 11 keys in `ref_industry.internal_key` | Derived from chain config | At store creation |
| store_name | VARCHAR | ✗ | Display name | `Starbucks - Congress Ave` | Free text | Job postings, Google Maps, OSM | Updated weekly |
| address | VARCHAR | ✗ | Physical street address | `123 Congress Ave, Austin, TX 78701` | Formatted street address | Google geocoder, AllThePlaces, Overture | Updated weekly |
| lat | FLOAT | ✓ | Latitude (WGS84) | `30.2672` | -90 to 90 | Overture, Google Geocoder, OSM | Updated weekly |
| lng | FLOAT | ✓ | Longitude (WGS84) | `-97.7431` | -180 to 180 | Overture, Google Geocoder, OSM | Updated weekly |
| region | VARCHAR | ✗ | Region key | `austin_tx` | One of `ref_regions.region_key` | Config | At store creation |
| first_seen | DATETIME | ✓ | When this store was first identified | `2025-10-15 14:32:00` | ISO 8601 UTC | Adapter run time | Set at insert |
| last_seen | DATETIME | ✓ | Last time this store was observed active | `2026-03-22 10:45:00` | ISO 8601 UTC | Adapter run time on each matching fetch | Real-time |
| is_active | BOOLEAN | ✓ | Is the store currently operating? | `true`, `false` | true, false | Manual flag or adapter detection of closure | Updated weekly |

**Notes:**
- `lat`, `lng` may be NULL if geocoding failed; these are back-filled asynchronously
- `store_num` is immutable once created; duplicates are reconciled in `store_aliases` table
- Stores persist even if `is_active=false` (closed stores) for historical scoring comparison

---

### signals

**Purpose:** Raw observations from external sources. One row = one observation at one point in time. Single observation can feed multiple score types.
**Primary Key:** `id` (auto-increment)
**Relationships:** → stores (via store_num), → scores (via scoring engine)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Unique observation ID | `48291` | Auto-increment, >= 1 | System (auto-generated) | Immutable |
| store_num | VARCHAR | ✗ | Which store this observation is about | `SB-03347` | Must exist in `stores.store_num` | Scraper extraction / geocoding | At insert |
| source | VARCHAR | ✗ | Which adapter collected this | `careers_api` | `careers_api`, `jobspy`, `reddit`, `google_maps`, `qcew`, `bls` | Scraper name (hardcoded in adapter) | At insert |
| signal_type | VARCHAR | ✗ | What kind of observation | `listing` | `listing`, `wage`, `sentiment`, `review_score`, `establishment_count`, `staffing_keywords` | Adapter-specific; see below | At insert |
| value | FLOAT | ✗ | Observation value, normalized or raw | `0.72` (sentiment) or `42000` (wage) | 0-1 for normalized; unlimited for wage/counts | Scraper computation | At insert |
| metadata_json | TEXT | ✓ | Scraper-specific context (JSON) | `{"url": "...", "review_count": 127, ...}` | Valid JSON object | Scraper-dependent | At insert |
| observed_at | DATETIME | ✗ | When was this observation made (source time) | `2026-03-22 08:15:00` | ISO 8601 UTC | Source timestamp (job posting date, Reddit post date, review date, etc.) | Set by source |
| created_at | DATETIME | ✓ | When was this record inserted | `2026-03-22 10:30:45` | ISO 8601 UTC | System time at ingestion | Set at insert |

**Signal Types & Value Ranges:**

| signal_type | source | value range | metadata includes | interpretation |
|---|---|---|---|---|
| `listing` | careers_api, jobspy | 0-1 (listing age weight) | url, title, role, location, wage_min, wage_max, posted_days_ago | A job posting exists; value reflects recency weight (fresh=1, stale>90d=0) |
| `wage` | jobspy, wage_index | raw dollars | wage_min, wage_max, wage_period, currency, source_url | Posted wage range; not normalized |
| `sentiment` | reddit | 0-1 | title, subreddit, url, score, num_comments, matched_keywords | Staffing-stress sentiment; 0=positive/none, 1=high stress language |
| `review_score` | google_maps | 0-5 | store_name, address, lat, lng, rating, review_count, url | Google Maps star rating |
| `staffing_keywords` | google_maps | 0-1 | matched_keywords, keyword_count, review_sample_count | Staffing-stress language detected in review text |
| `establishment_count` | qcew, bls | raw count | year, quarter, naics_code, employment, avg_wage | Employer location count from government source |

**Notes:**
- Duplicate signals (same store_num, source, signal_type, observed_at) are deduplicated during ingest
- Signals >90 days old are kept but down-weighted in scoring
- `metadata_json` is unstructured; scrapers may add arbitrary context

---

### scores

**Purpose:** Computed staffing-stress index per store. One row per (store, score_type) pair per computation cycle.
**Primary Key:** (store_num, score_type)
**Relationships:** → stores, ← signals (computed from)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| store_num | VARCHAR | ✗ | Which store | `SB-03347` | Must exist in `stores.store_num` | From store at scoring time | At compute |
| score_type | VARCHAR | ✗ | Which component | `composite` | `composite`, `demand_pressure`, `wage_competitiveness`, `churn_signal`, `qualitative` | Fixed enum | At compute |
| value | FLOAT | ✗ | Normalized score (higher = more staffing stress) | `67.3` | 0-100 | Scoring engine | Updated after each signal batch |
| tier | VARCHAR | ✓ | Human-readable category | `critical` | `critical` (≥67th pctl), `elevated` (≥33rd), `adequate` (<33rd) | Computed from percentile ranks | Updated after each signal batch |
| computed_at | DATETIME | ✓ | When was this score computed | `2026-03-22 10:45:00` | ISO 8601 UTC | System time at scoring | At compute |

**Score Type Details:**

| score_type | Formula | Data Source | Interpretation |
|---|---|---|---|
| `composite` | 0.35 × demand_pressure + 0.25 × wage_competitiveness + 0.25 × churn_signal + 0.15 × qualitative | All sub-scores | Overall staffing stress index; 50=normal, 100=2× worse |
| `demand_pressure` | (store_weighted_listings / regional_per_establishment) × 50, capped at 100 | signals (listings), qcew_data (establishment counts) | How many job postings relative to what's normal for this many locations |
| `wage_competitiveness` | 50 + gap_pct where gap = (market_median − chain_wage) / market_median × 100 | wage_index, oews_data | How far below market wage the chain is paying |
| `churn_signal` | (store_weighted_listings / expected_monthly_separations) × 50, capped at 100 | signals (listings), jolts_data (quit rates), qcew_data (employment) | Are postings above what normal turnover explains? |
| `qualitative` | Weighted average of sentiment + review_score signals, normalized 0-1 then × 100 | signals (sentiment, review_score, staffing_keywords) | Customer/employee perception of staffing problems |

**Notes:**
- If ground-truth data (QCEW/JOLTS) is missing, engine falls back to percentile ranking within region
- `tier` is computed from 33rd and 67th percentiles across all stores in region
- Scores are immutable after computation (new rows on each cycle; old rows never deleted)
- Historical scores allow trend analysis (e.g., "was this store always stressed or recent spike?")

---

### wage_index

**Purpose:** Crowd-sourced wage data from job postings. One row per (employer, role, location) posting.
**Primary Key:** `id` (auto-increment)
**Relationships:** ← signals, → scores (via wage_competitiveness)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Unique wage posting ID | `8821` | Auto-increment, >= 1 | System | Immutable |
| employer | VARCHAR | ✗ | Company name | `Starbucks` | Free text | Job posting / scraper | At insert |
| is_chain | BOOLEAN | ✗ | Is employer a major chain? | `true` | true, false | Scraper lookup in `ref_brands` | At insert |
| chain_key | VARCHAR | ✓ | Config chain ID if is_chain=true | `starbucks` | Must match `ref_brands.brand_key` if set | Config lookup | At insert |
| industry | VARCHAR | ✗ | Internal industry key | `coffee_shops` | One of 11 keys in `ref_industry` | Derived from chain / job title | At insert |
| role_title | VARCHAR | ✗ | Job title | `Barista` | Free text | Job posting | At insert |
| wage_min | FLOAT | ✓ | Minimum posted wage | `17.50` | >= 0 | Job posting | At insert |
| wage_max | FLOAT | ✓ | Maximum posted wage | `21.00` | >= wage_min if both set | Job posting | At insert |
| wage_period | VARCHAR | ✗ | Wage time period | `hourly` | `hourly`, `yearly` | Job posting / inferred | At insert |
| location | VARCHAR | ✗ | Job location (region name or ZIP) | `Austin, TX` | Free text | Job posting | At insert |
| zip_code | VARCHAR | ✓ | ZIP code (if extracted) | `78701` | Valid 5-digit ZIP | Geocoding from location | At insert |
| source | VARCHAR | ✗ | Which job board scraped it | `jobspy` | `jobspy`, `careers_api`, `indeed_scraper`, etc. | Scraper name | At insert |
| observed_at | DATETIME | ✓ | When was posting published (source time) | `2026-03-20 12:00:00` | ISO 8601 UTC | Job posting date | At insert |
| source_url | VARCHAR | ✓ | Link to original posting | `https://jobs.indeed.com/...` | Valid URL | Job posting | At insert |

**Notes:**
- `wage_min` or `wage_max` may be NULL if not posted (common on some boards)
- Wage periods are normalized to hourly; yearly postings are converted ÷ 2080 hrs
- Duplicate postings (same employer, role, location, observed_at, wage_min/max) are deduplicated
- Old rows (>180 days ago) are retained for trend analysis but excluded from current wage_competitiveness

---

## Ground-Truth Tables

### qcew_data

**Purpose:** County-level employment & establishment counts from BLS. One row per (county, NAICS code, quarter).
**Primary Key:** `id`
**Source:** BLS QCEW CSV API (never updated, only appended)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | `149` | Auto-increment | System | Immutable |
| fips_code | VARCHAR(5) | ✗ | County FIPS code | `48453` | One of 5 Austin-area counties: 48453, 48491, 48209, 48021, 48055 | BLS | At insert |
| naics_code | VARCHAR(6) | ✗ | Industry code | `722515` | One of 5 configured codes: 722515, 722513, 722511, 7225, 72 | BLS | At insert |
| naics_title | VARCHAR | ✓ | Industry description | `Snack and Nonalcoholic Beverage Bars` | Free text from BLS | BLS | At insert |
| year | INTEGER | ✗ | Year (YYYY) | `2025` | 2000–present | BLS | At insert |
| quarter | INTEGER | ✗ | Quarter (Q1=1, Q4=4) | `3` | 1, 2, 3, 4 | BLS | At insert |
| ownership_code | VARCHAR(2) | ✓ | Ownership sector | `5` | `1`=private, `2`=government, `5`=private (filtered) | BLS | At insert |
| establishments | INTEGER | ✓ | Number of active employer locations | `127` | >= 0 | BLS | ~6 month lag |
| month1_employment | INTEGER | ✓ | Employment in month 1 of quarter | `8234` | >= 0 | BLS | ~6 month lag |
| month2_employment | INTEGER | ✓ | Employment in month 2 of quarter | `8456` | >= 0 | BLS | ~6 month lag |
| month3_employment | INTEGER | ✓ | Employment in month 3 of quarter | `8512` | >= 0 | BLS | ~6 month lag |
| total_wages | FLOAT | ✓ | Total quarterly wages paid (may be confidential) | `45230000` | >= 0 (in dollars) | BLS | ~6 month lag |
| avg_weekly_wage | FLOAT | ✓ | Average weekly wage per worker | `687.50` | >= 0 | BLS | ~6 month lag |
| avg_annual_pay | FLOAT | ✓ | Annualized average wage | `35750` | >= 0 | BLS (computed) | ~6 month lag |
| region | VARCHAR | ✓ | Region key | `austin_tx` | One of `ref_regions.region_key` | Config | At insert |
| fetched_at | DATETIME | ✓ | When was this fetched | `2026-03-22 07:15:00` | ISO 8601 UTC | System time at fetch | At insert |

**Notes:**
- Data lag: ~6 months. E.g., 2025-Q3 is available in March 2026
- `establishments` is the key denominator for demand_pressure scoring
- Monthly employment values allow intra-quarter variance detection
- NULL values indicate data withheld by BLS for confidentiality

---

### jolts_data

**Purpose:** National job openings, quits, hires, and separations rates. One row per (metric, industry, month).
**Primary Key:** `id`
**Source:** BLS JOLTS API v2 (appended monthly)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | `730` | Auto-increment | System | Immutable |
| series_id | VARCHAR | ✗ | BLS series code | `JTS720000000000000QUR` | Format: JTS[industry]000000000000[metric] | BLS | At insert |
| series_description | VARCHAR | ✓ | Human-readable series name | `Accommodation & Food Services, Quits Rate` | Free text from BLS | BLS | At insert |
| metric | VARCHAR | ✗ | Which metric | `quits_rate` | `quits_rate`, `openings_rate`, `hires_rate`, `separations_rate` | BLS (mapped) | At insert |
| industry_code | VARCHAR | ✓ | NAICS industry code | `72` | `00` (all jobs) or 2-digit NAICS | BLS | At insert |
| year | INTEGER | ✗ | Year (YYYY) | `2025` | 2010–present | BLS | 2-month lag |
| month | INTEGER | ✗ | Month (1-12) | `12` | 1–12 | BLS | 2-month lag |
| value | FLOAT | ✗ | Rate (as percentage) | `2.5` | 0-10+ (e.g., 2.5 = 2.5% quit rate) | BLS (seasonally adjusted) | 2-month lag |
| fetched_at | DATETIME | ✓ | When was this fetched | `2026-03-22 06:15:00` | ISO 8601 UTC | System | At insert |

**Notes:**
- All values are seasonally adjusted (marked "SA" in BLS)
- `metric` values are monthly rates (e.g., 2.5% = 2.5% of workers quit in that month)
- Used primarily for `churn_signal` sub-score: high quit rates = normal postings, low quit rates = stress
- Industry code `00` = all jobs; `72` = Accommodation & Food Services

---

### laus_data

**Purpose:** County-level unemployment, labor force, and employment. One row per (county, month).
**Primary Key:** `id`
**Source:** BLS LAUS API v2 (appended monthly)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | `426` | Auto-increment | System | Immutable |
| fips_code | VARCHAR(5) | ✗ | County FIPS code | `48453` | One of 3 tracked: 48453 (Travis), 48491 (Williamson), 48209 (Hays) | BLS | At insert |
| area_title | VARCHAR | ✓ | County name | `Travis County, TX` | Free text | BLS | At insert |
| year | INTEGER | ✗ | Year (YYYY) | `2025` | 2010–present | BLS | 2-month lag |
| month | INTEGER | ✗ | Month (1-12) | `12` | 1–12 | BLS | 2-month lag |
| labor_force | INTEGER | ✓ | Total labor force (employed + unemployed) | `1045000` | >= 0 | BLS | 2-month lag |
| employed | INTEGER | ✓ | Number employed | `1010000` | >= 0, <= labor_force | BLS | 2-month lag |
| unemployed | INTEGER | ✓ | Number unemployed | `35000` | >= 0, = labor_force - employed | BLS | 2-month lag |
| unemployment_rate | FLOAT | ✓ | Unemployment rate (%) | `3.3` | 0-100 (e.g., 3.3 = 3.3% unemployed) | BLS | 2-month lag |
| region | VARCHAR | ✓ | Region key | `austin_tx` | One of `ref_regions.region_key` | Config | At insert |
| fetched_at | DATETIME | ✓ | When was this fetched | `2026-03-22 06:15:00` | ISO 8601 UTC | System | At insert |

**Notes:**
- Data is seasonally adjusted
- Unemployment rate = (unemployed / labor_force) × 100
- Used for baseline regional economic context; not directly in scoring

---

### oews_data

**Purpose:** Occupation-level wage percentiles by MSA. One row per (occupation, NAICS industry, year, MSA).
**Primary Key:** `id`
**Source:** BLS OEWS flat files (manual download, annual)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | — | Auto-increment | System | — |
| area_code | VARCHAR | ✗ | MSA area code | `12420` | `12420` (Austin-Round Rock-Georgetown) | BLS | Annual (May) |
| area_title | VARCHAR | ✓ | MSA name | `Austin-Round Rock-Georgetown, TX` | Free text | BLS | Annual |
| occ_code | VARCHAR(7) | ✗ | SOC occupation code | `35-3021` | One of 5 configured: 35-0000, 35-3023, 35-2021, 35-1012, 35-3021 | BLS | Annual |
| occ_title | VARCHAR | ✓ | Occupation name | `Food Preparation Workers` | Free text | BLS | Annual |
| naics_code | VARCHAR(6) | ✓ | Industry code (if available) | `722515` | Optional; may be NULL for cross-industry | BLS | Annual |
| employment | INTEGER | ✓ | Number employed in occupation | `3421` | >= 0 | BLS | Annual |
| wage_mean_hourly | FLOAT | ✓ | Mean hourly wage | `17.25` | >= 0 | BLS | Annual |
| wage_median_hourly | FLOAT | ✓ | Median (50th percentile) hourly wage | `16.85` | >= 0 | BLS | Annual |
| wage_10pct | FLOAT | ✓ | 10th percentile hourly wage | `12.50` | >= 0 | BLS | Annual |
| wage_25pct | FLOAT | ✓ | 25th percentile hourly wage | `14.10` | >= 0 | BLS | Annual |
| wage_75pct | FLOAT | ✓ | 75th percentile hourly wage | `19.50` | >= 0 | BLS | Annual |
| wage_90pct | FLOAT | ✓ | 90th percentile hourly wage | `22.00` | >= 0 | BLS | Annual |
| year | INTEGER | ✗ | Year (YYYY) | `2024` | 2000–present (published annually in May) | BLS | 12-month lag |
| region | VARCHAR | ✓ | Region key | `austin_tx` | One of `ref_regions.region_key` | Config | At insert |
| fetched_at | DATETIME | ✓ | When was this fetched | — | ISO 8601 UTC | System | — |

**Notes:**
- Data gap: No rows yet (table not populated). Must be manually downloaded from BLS and imported.
- Percentiles are used in wage_competitiveness: if chain pays less than median, gap increases
- Only available once per year (typically May publication for prior-year data)

---

### cbp_data

**Purpose:** ZIP-code-level establishment and employment counts. One row per (ZIP, NAICS, year).
**Primary Key:** `id`
**Source:** Census Bureau CBP API (manual setup required; annual)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | — | Auto-increment | System | — |
| zip_code | VARCHAR(5) | ✗ | ZIP code | `78701` | One of 25 configured Austin-area ZIPs | Census | Annual |
| naics_code | VARCHAR(6) | ✗ | Industry code | `722515` | One of 3: 722515, 722513, 722511 | Census | Annual |
| year | INTEGER | ✗ | Year (YYYY) | `2024` | 2010–present | Census | 18-month lag |
| establishments | INTEGER | ✓ | Number of active establishments | `8` | >= 0 (may be NULL if < 20 for privacy) | Census | 18-month lag |
| employment | INTEGER | ✓ | Total employment | `85` | >= 0 (may be withheld for privacy) | Census | 18-month lag |
| employment_noise_flag | VARCHAR(1) | ✓ | Data quality flag | `S` | `N` (normal), `S` (small), `D` (disclosure) | Census | 18-month lag |
| annual_payroll_k | FLOAT | ✓ | Total payroll (thousands of dollars) | `1250.5` | >= 0 | Census | 18-month lag |
| region | VARCHAR | ✓ | Region key | `austin_tx` | One of `ref_regions.region_key` | Config | At insert |
| fetched_at | DATETIME | ✓ | When was this fetched | — | ISO 8601 UTC | System | — |

**Notes:**
- Data gap: No rows yet (Census API key required). See section 10.2 in CLAUDE_AGENT_HANDOFF.md
- ZIP-level resolution allows hyperlocal staffing stress mapping (e.g., "Congress Ave Starbucks is in high-stress ZIP")
- Data lag: ~18 months (2024 data available mid-2026)
- Privacy suppression: If employment < 20, fields may be NULL or flagged

---

### labor_market_baseline

**Purpose:** Derived ground-truth baseline combining QCEW + JOLTS + OEWS + LAUS. One row per (region, NAICS).
**Primary Key:** `id`
**Source:** Computed by `backend/baseline.py` from ground-truth tables

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | `5` | Auto-increment | System | Immutable |
| region | VARCHAR | ✗ | Region key | `austin_tx` | One of `ref_regions.region_key` | Config | At compute |
| naics_code | VARCHAR(6) | ✗ | Industry code | `722515` | One of 5: 722515, 722513, 722511, 7225, 72 | Config | At compute |
| period_label | VARCHAR | ✗ | Time period (for clarity) | `2025-Q3` | Format `YYYY-QN` | Computed | At compute |
| establishment_count | INTEGER | ✓ | Total establishments in region/NAICS | `127` | >= 0 | QCEW | From latest QCEW quarter |
| total_employment | INTEGER | ✓ | Total employment across region/NAICS | `8400` | >= 0 | QCEW (quarterly average) | From latest QCEW quarter |
| avg_weekly_wage | FLOAT | ✓ | Average weekly wage (across all locations) | `687.50` | >= 0 | QCEW | From latest QCEW quarter |
| avg_employees_per_establishment | FLOAT | ✓ | Mean store size | `66.1` | >= 1 (computed: total_employment / establishment_count) | Derived | At compute |
| expected_quits_rate | FLOAT | ✓ | Monthly quit rate from JOLTS (%) | `2.5` | 0-10+ | JOLTS (latest 12-month avg) | From latest JOLTS |
| expected_openings_rate | FLOAT | ✓ | Monthly openings rate from JOLTS (%) | `3.2` | 0-10+ | JOLTS (latest 12-month avg) | From latest JOLTS |
| expected_monthly_separations | INTEGER | ✓ | Expected separations per month | `210` | >= 0 (computed: total_employment × expected_quits_rate / 100) | Derived | At compute |
| occupation_median_wage | FLOAT | ✓ | Median occupational hourly wage | `16.85` | >= 0 | OEWS (latest year, median of SOC codes) | From latest OEWS |
| occupation_employment | INTEGER | ✓ | Employment in tracked occupations | `3421` | >= 0 | OEWS (sum of tracked SOC codes) | From latest OEWS |
| unemployment_rate | FLOAT | ✓ | County unemployment rate (%) | `3.3` | 0-100 | LAUS (latest month, average of tracked counties) | From latest LAUS |
| labor_force | INTEGER | ✓ | Regional labor force size | `1045000` | >= 0 | LAUS (sum of tracked counties) | From latest LAUS |
| hiring_intensity_baseline | FLOAT | ✓ | Expected job posting rate (posts per 1000 employed) | `1.2` | >= 0 (computed: expected_monthly_separations / total_employment × 1000 × posting_rate_factor) | Derived | At compute |
| seasonal_index | FLOAT | ✓ | Seasonal adjustment factor | `1.15` | > 0 (>1 = peak season inflates, <1 = trough deflates) | Derived from quarterly QCEW variance | At compute |
| computed_at | DATETIME | ✓ | When was this baseline computed | `2026-03-22 04:00:00` | ISO 8601 UTC | System | At compute |

**Notes:**
- Recomputed weekly (Sunday 4am) after ground-truth sources are fetched
- All denominators for scoring formulas come from this table
- `seasonal_index` is computed from trailing 4 quarters of QCEW employment: index = current_Q_employment / 4Q_average
- If any ground-truth source is missing, all fields except `period_label` may be NULL (falls back to percentile-based scoring)

---

## Reference Tables

### ref_brands

**Purpose:** Brand/company master data. Defines what we track and how to find it in each scraper source.
**Primary Key:** `brand_key`

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| brand_key | VARCHAR | ✗ | Config identifier (must match `config/chains.yaml`) | `starbucks` | User-defined | Config | Never |
| display_name | VARCHAR | ✗ | Human-readable name | `Starbucks Coffee` | Free text | Config | Never |
| parent_company | VARCHAR | ✓ | Holding company | `Laxmi Mittal` | Free text | Web research | Quarterly |
| wikidata_id | VARCHAR | ✓ | Wikidata unique identifier | `Q37158` | Format `Q[0-9]+` | Wikipedia / Wikidata | Annual |
| naics_code | VARCHAR(6) | ✓ | Primary NAICS industry | `722515` | One of `ref_industry.naics_code` | BLS / Config | Never |
| internal_industry | VARCHAR | ✓ | Internal industry key | `coffee_shops` | One of `ref_industry.internal_key` | Config | Never |
| is_chain | BOOLEAN | ✓ | Is this a major chain vs. local? | `true` | true, false | Config | Never |
| is_publicly_traded | BOOLEAN | ✓ | Publicly listed company? | `true` | true, false | Web research | Annual |
| stock_ticker | VARCHAR | ✓ | Stock exchange ticker | `SBUX` | Format `[A-Z]+` | Web research | As needed |
| approx_us_locations | INTEGER | ✓ | Approximate store count | `16000` | >= 0 | Web research (AllThePlaces, company website) | Annual |
| careers_url | VARCHAR | ✓ | Careers page URL | `https://jobs.starbucks.com/` | Valid URL | Manual | As needed |
| glassdoor_id | VARCHAR | ✓ | Glassdoor company ID (if available) | `1879` | Numeric string | Glassdoor | As needed |
| indeed_query | VARCHAR | ✓ | Indeed jobs search query | `"starbucks"` | Search string (may use quotes) | Manual | As needed |
| atp_spider_names | TEXT | ✓ | AllThePlaces brand name variants (JSON array) | `["starbucks", "sbx", "s.bucks"]` | Valid JSON string array | AllThePlaces data | Quarterly |
| overture_name_patterns | TEXT | ✓ | Regex name patterns for Overture match (JSON array) | `["starbucks", "sbx.*coffee"]` | Valid JSON regex array | Manual | Quarterly |
| osm_tags | TEXT | ✓ | OpenStreetMap tag filters (JSON object) | `{"name": "Starbucks*", "brand": "starbucks"}` | Valid JSON object | Manual | Quarterly |
| avg_starting_wage | FLOAT | ✓ | Historical average starting wage | `18.50` | >= 0 | wage_index aggregate / web research | Quarterly |
| wage_source | VARCHAR | ✓ | Source of wage data | `jobspy` | Source name | Manual | Quarterly |
| typical_store_staff | INTEGER | ✓ | Expected number of employees per store | `7` | >= 1 | Company disclosure / estimates | Annual |
| union_presence | BOOLEAN | ✓ | Is union organizing present? | `false` | true, false | Manual / news monitoring | As needed |
| updated_at | DATETIME | ✓ | Last metadata update | `2026-03-22 09:00:00` | ISO 8601 UTC | System | Quarterly |

**Notes:**
- brand_key is immutable; if a chain changes name, create new row with old key marked inactive
- atp_spider_names and overture_name_patterns are critical for store discovery across scrapers
- typical_store_staff is used to estimate "understaffed" when actual headcount is unknown

---

### ref_industry

**Purpose:** NAICS industry hierarchy and sectoral characteristics.
**Primary Key:** `naics_code`

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| naics_code | VARCHAR(6) | ✗ | BLS NAICS code | `722515` | Valid BLS NAICS (2-6 digits) | BLS | Annual |
| naics_title | VARCHAR | ✗ | Official NAICS title | `Snack and Nonalcoholic Beverage Bars` | Free text | BLS | Annual |
| internal_key | VARCHAR | ✗ | Short human-readable alias | `coffee_shops` | User-defined, unique | Config | Never |
| parent_naics | VARCHAR(6) | ✓ | Broader category code | `7225` | Valid BLS NAICS (less specific) | BLS | Annual |
| sector | VARCHAR | ✓ | High-level sector name | `Accommodation & Food Services` | Free text | BLS | Annual |
| avg_hourly_wage_bls | FLOAT | ✓ | BLS average wage for industry | `17.50` | >= 0 | BLS CES / QCEW | Annual |
| avg_employees_per_location | FLOAT | ✓ | Typical store size | `7.5` | >= 1 | QCEW (establishment_count / employment) | Annual |
| seasonal_pattern | VARCHAR | ✓ | Typical hiring seasonality | `peak_summer` | `peak_summer`, `peak_holiday`, `steady`, `declining` | Manual observation | Annual |

**Notes:**
- Hierarchy: 2-digit sector (72), 3-digit subsector (722), 4-digit group (7225), 6-digit code (722515)
- avg_employees_per_location is used to estimate staffing stress (e.g., "if normal = 7.5, and we're seeing 2x postings, stress = high")
- seasonal_pattern informs seasonal adjustment in scoring

---

### ref_regions

**Purpose:** Geographic region definitions and demographic/economic baselines.
**Primary Key:** `region_key`

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| region_key | VARCHAR | ✗ | Config identifier | `austin_tx` | User-defined | Config | Never |
| display_name | VARCHAR | ✓ | Display name | `Austin-Round Rock-Georgetown MSA` | Free text | Config | Never |
| fips_code | VARCHAR | ✓ | FIPS code (state + county) | `48453` | 5-digit FIPS | BLS / Census | Never |
| center_lat | FLOAT | ✓ | Map center latitude | `30.2672` | -90 to 90 | Manual config | As needed |
| center_lng | FLOAT | ✓ | Map center longitude | `-97.7431` | -180 to 180 | Manual config | As needed |
| bbox_west | FLOAT | ✓ | Bounding box west (min longitude) | `-98.1` | -180 to 180 | Manual config | As needed |
| bbox_east | FLOAT | ✓ | Bounding box east (max longitude) | `-97.3` | -180 to 180 | Manual config | As needed |
| bbox_south | FLOAT | ✓ | Bounding box south (min latitude) | `29.8` | -90 to 90 | Manual config | As needed |
| bbox_north | FLOAT | ✓ | Bounding box north (max latitude) | `30.6` | -90 to 90 | Manual config | As needed |
| population | INTEGER | ✓ | Total population | `2450000` | >= 0 | Census ACS estimates | Annual |
| median_household_income | INTEGER | ✓ | Median household income | `72500` | >= 0 (in dollars) | Census ACS | Annual |
| unemployment_rate | FLOAT | ✓ | Current unemployment rate (%) | `3.3` | 0-100 | LAUS latest | Monthly |
| cost_of_living_index | FLOAT | ✓ | Cost-of-living index (100=national average) | `114.5` | > 0 | Council for Community & Economic Research | Quarterly |
| min_wage_state | FLOAT | ✓ | State minimum wage | `13.00` | >= 0 (in $/hr) | State government | As needed |
| min_wage_local | FLOAT | ✓ | City/local minimum wage (if higher) | `15.00` | >= min_wage_state | City government | As needed |
| living_wage_1adult | FLOAT | ✓ | Living wage for 1 adult (annual estimate) | `38000` | >= 0 (in $/yr) | MIT Living Wage Calculator | Annual |
| food_service_establishments | INTEGER | ✓ | Count of food service establishments | `2145` | >= 0 | QCEW aggregated | Annual |
| food_service_employees | INTEGER | ✓ | Employment in food service | `28400` | >= 0 | QCEW aggregated | Annual |
| retail_establishments | INTEGER | ✓ | Count of retail establishments | `5821` | >= 0 | QCEW aggregated | Annual |
| retail_employees | INTEGER | ✓ | Employment in retail | `62000` | >= 0 | QCEW aggregated | Annual |
| updated_at | DATETIME | ✓ | Last demographic update | `2026-03-22 09:00:00` | ISO 8601 UTC | System | Quarterly |

**Notes:**
- Bounding box defines the search area for all store discovery and signal collection
- min_wage comparisons help contextualize wage_competitiveness (chain wage vs. legal minimum)
- living_wage_1adult vs. chain starting wage is a hidden KPI (if chain pays < living wage, that's a story)

---

### ref_category_map

**Purpose:** Maps heterogeneous category systems (Overture, OSM, job boards) to internal industry codes.
**Primary Key:** (source_system, source_value, internal_industry)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| source_system | VARCHAR | ✗ | Upstream category system | `overture` | `overture`, `osm`, `naics`, `indeed`, `glassdoor` | Config | Never |
| source_value | VARCHAR | ✗ | Category value from upstream | `food_and_drink` | Free text (varies per system) | Upstream system | As needed |
| internal_industry | VARCHAR | ✗ | Maps to internal key | `food_service` | One of `ref_industry.internal_key` | Config | Never |
| confidence | FLOAT | ✓ | Mapping confidence (0-1) | `0.95` | 0-1 (1 = certain, <0.8 = ambiguous) | Manual assessment | As needed |

**Notes:**
- 1:1 mappings (one upstream category → one internal industry)
- Used by scrapers during ingest to classify discovered locations
- Low-confidence mappings (<0.8) should be reviewed quarterly

---

### api_sources

**Purpose:** Registry of external APIs with rate limits and authentication details.
**Primary Key:** `source_key`

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| source_key | VARCHAR | ✗ | Config identifier | `bls_api_v2` | User-defined (must match scraper code) | Config | Never |
| display_name | VARCHAR | ✗ | Human-readable name | `BLS Public Data API v2` | Free text | Config | Never |
| base_url | VARCHAR | ✓ | API base URL | `https://api.bls.gov/publicAPI/v2/` | Valid URL | Config | As needed |
| auth_type | VARCHAR | ✓ | Authentication method | `api_key` | `none`, `api_key`, `oauth`, `basic`, `bearer` | Config | Never |
| daily_limit | INTEGER | ✗ | Request quota per day | `500` | >= 0 (0 = unlimited) | API docs | As needed |
| min_delay_seconds | FLOAT | ✓ | Minimum delay between requests (pacing) | `0.2` | >= 0 | API docs / courtesy | As needed |
| reset_hour_utc | INTEGER | ✓ | Hour when daily limit resets (0-23 UTC) | `0` | 0-23 (24-hour UTC time) | API docs | Never |
| is_active | BOOLEAN | ✓ | Is this API currently monitored? | `true` | true, false | Config | As needed |
| notes | TEXT | ✓ | Documentation / gotchas | `Free tier has 500 req/day; v2 provides longer series history` | Free text | Config | As needed |
| created_at | DATETIME | ✓ | When this config was registered | `2026-01-15 10:00:00` | ISO 8601 UTC | System | Immutable |

**Notes:**
- Each scraper references a source_key to track rate limit usage
- min_delay_seconds is enforced by `backend.tracked_request` module
- reset_hour_utc is used to calculate whether daily_limit has reset (for quota tracking)

---

### api_endpoints

**Purpose:** Detailed adapter configurations and health metrics.
**Primary Key:** (adapter_name, source_key)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| adapter_name | VARCHAR | ✗ | Scraper adapter class name | `StarbucksCareersScraper` | Matches class in scrapers/ | Config | Never |
| scraper_module | VARCHAR | ✓ | File path to scraper | `scrapers.careers_api` | Python module path | Config | Never |
| source_key | VARCHAR | ✗ | API source identifier (foreign key to api_sources) | `starbucks_workday` | Must exist in `api_sources.source_key` | Config | Never |
| intent | VARCHAR | ✗ | What data does this collect? | `job_postings` | `job_postings`, `sentiment`, `reviews`, `establishment_count`, `wages`, `unemployment` | Config | Never |
| data_type | VARCHAR | ✗ | Type of observations collected | `listing` | Matches `signals.signal_type` | Config | Never |
| route_status | VARCHAR | ✗ | Current operational status | `active` | `active`, `deprecated`, `testing`, `failed`, `paused` | Runtime | Real-time |
| notes | TEXT | ✓ | Documentation | `Requires no auth; returns JSON with job postings and location details` | Free text | Config | As needed |
| industries_json | TEXT | ✓ | Which industries this scraper targets (JSON array) | `["coffee_shops", "food_service"]` | Valid JSON string array | Config | Never |
| brands_json | TEXT | ✓ | Which brands this scraper targets (JSON array) | `["starbucks", "dutch_bros"]` | Valid JSON string array matching `ref_brands.brand_key` | Config | Never |
| regions_json | TEXT | ✓ | Which regions this scraper covers (JSON array) | `["austin_tx"]` | Valid JSON string array matching `ref_regions.region_key` | Config | Never |
| base_url | VARCHAR | ✓ | Scraper-specific base URL | `https://jobs.starbucks.com/` | Valid URL (overrides api_sources.base_url if set) | Config | As needed |
| url_pattern | VARCHAR | ✓ | URL path pattern (may use placeholders) | `/search?q=barista&location={region}` | Free text with optional {placeholders} | Config | As needed |
| is_active | BOOLEAN | ✗ | Is this scraper enabled? | `true` | true, false | Config | Real-time |
| consecutive_failures | INTEGER | ✗ | How many times has this failed in a row? | `0` | >= 0 (auto-disabled if > 5) | Runtime | Real-time |
| success_count | INTEGER | ✗ | Total successful runs | `456` | >= 0 | Runtime counter | Real-time |
| failure_count | INTEGER | ✗ | Total failed runs | `3` | >= 0 | Runtime counter | Real-time |
| last_verified_at | DATETIME | ✓ | Last health check run | `2026-03-22 06:15:00` | ISO 8601 UTC | System (health checker) | Real-time |
| last_success_at | DATETIME | ✓ | Last successful data fetch | `2026-03-22 03:00:00` | ISO 8601 UTC | Scheduler | Real-time |
| last_failure_reason | VARCHAR | ✓ | Error message from last failure | `HTTP 429: Rate limit exceeded` | Free text (error string) | Scraper exception | Real-time |
| health_check_freshness_hours | FLOAT | ✓ | Alert if no data in > N hours | `12` | > 0 | Config | Never |
| created_at | DATETIME | ✓ | When this endpoint was registered | `2026-01-15 10:00:00` | ISO 8601 UTC | System | Immutable |
| updated_at | DATETIME | ✓ | Last config update | `2026-03-22 09:00:00` | ISO 8601 UTC | System | Real-time |

**Notes:**
- route_status auto-changes to `failed` if consecutive_failures > 5
- health_check_freshness_hours is used by pipeline/health.py to alert staleness
- consecutive_failures resets to 0 on success

---

### api_request_log

**Purpose:** Detailed HTTP telemetry. One row per external request.
**Primary Key:** `id`

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | `7` | Auto-increment | System | Immutable |
| source_key | VARCHAR | ✗ | Which API (foreign key to api_sources) | `bls_api_v2` | Must exist in `api_sources.source_key` | Scraper | At insert |
| request_type | VARCHAR | ✗ | Request category | `series_fetch` | `series_fetch`, `search`, `detail`, `list`, etc. (scraper-defined) | Scraper | At insert |
| url | VARCHAR | ✓ | Full URL (may be redacted if contains API key) | `https://api.bls.gov/publicAPI/v2/timeseries/data/` | Valid URL | Tracked request | At insert |
| method | VARCHAR | ✓ | HTTP method | `POST` | `GET`, `POST`, `PUT`, `DELETE`, etc. | Tracked request | At insert |
| status_code | INTEGER | ✓ | HTTP response status | `200` | 100-599 | HTTP response | At insert |
| success | BOOLEAN | ✗ | Did request succeed? | `true` | true, false (true = 2xx status) | Tracked request | At insert |
| error_message | VARCHAR | ✓ | Error message if failed | `Rate limit exceeded (429)` | Free text | HTTP response body / exception | At insert |
| latency_ms | INTEGER | ✓ | Request duration (milliseconds) | `345` | >= 0 | Measured at request time | At insert |
| response_bytes | INTEGER | ✓ | Response body size (bytes) | `12450` | >= 0 | HTTP response | At insert |
| data_items_returned | INTEGER | ✓ | Number of records returned | `24` | >= 0 | Scraper parsing | At insert |
| request_params_json | TEXT | ✓ | Request parameters (JSON, may be redacted) | `{"seriesid": ["SMU48124200000000001"], "startyear": 2024}` | Valid JSON object | Request payload | At insert |
| requested_at | DATETIME | ✗ | When request was made | `2026-03-22 10:30:45` | ISO 8601 UTC | System time | At insert |

**Notes:**
- Kept for 30 days then rolled off (logs table should not grow unbounded)
- Used to calculate rate_budgets daily rollup
- error_message is first 500 chars only (to avoid bloat)
- Sensitive info (API keys) should be redacted from url and request_params_json

---

### rate_budgets

**Purpose:** Daily API quota usage summary. One row per (source_key, date).
**Primary Key:** (source_key, date)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| source_key | VARCHAR | ✗ | API source (foreign key to api_sources) | `bls_api_v2` | Must exist in `api_sources.source_key` | Config | Never |
| date | VARCHAR | ✗ | Date (YYYY-MM-DD format, UTC) | `2026-03-22` | Valid ISO 8601 date | System | Daily |
| daily_limit | INTEGER | ✗ | Quota for this day (from api_sources) | `500` | >= 0 | Config | Never |
| used | INTEGER | ✓ | Requests used today | `87` | <= daily_limit | Aggregated from api_request_log | Real-time |
| succeeded | INTEGER | ✓ | Successful requests | `86` | <= used | Aggregated from api_request_log | Real-time |
| failed | INTEGER | ✓ | Failed requests | `1` | = used - succeeded | Aggregated from api_request_log | Real-time |
| total_latency_ms | INTEGER | ✓ | Sum of all request latencies (ms) | `29340` | >= 0 | Aggregated from api_request_log | Real-time |
| total_data_items | INTEGER | ✓ | Total records returned | `2145` | >= 0 | Aggregated from api_request_log | Real-time |
| total_bytes | INTEGER | ✓ | Total response bytes (MB) | `145` | >= 0 | Aggregated from api_request_log | Real-time |
| last_request_at | DATETIME | ✓ | Last request time today | `2026-03-22 23:55:00` | ISO 8601 UTC | Aggregated from api_request_log | Real-time |
| last_error | VARCHAR | ✓ | Last error message today | `Connection timeout` | Free text | Aggregated from api_request_log | Real-time |

**Notes:**
- Automatically computed at end of each day (11:59pm UTC) by aggregating api_request_log
- If used > daily_limit, next day's scraper runs should be paused for that source
- Alerts should fire if used > 0.9 × daily_limit

---

### source_freshness

**Purpose:** Data staleness tracking. Alerts when data hasn't updated.
**Primary Key:** (intent, region, source_key)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| intent | VARCHAR | ✗ | What type of data? | `job_postings` | `job_postings`, `sentiment`, `establishment_count`, `unemployment`, etc. | Config | Never |
| region | VARCHAR | ✗ | Which region? | `austin_tx` | One of `ref_regions.region_key` | Config | Never |
| brand | VARCHAR | ✓ | Which brand (if applicable)? | `starbucks` | One of `ref_brands.brand_key` (or NULL for regional data) | Config | As needed |
| industry | VARCHAR | ✓ | Which industry (if applicable)? | `coffee_shops` | One of `ref_industry.internal_key` (or NULL for brand-specific) | Config | As needed |
| source_key | VARCHAR | ✓ | Which API/scraper? | `careers_api` | One of `api_sources.source_key` | Config | Never |
| last_collected_at | DATETIME | ✗ | Last time data was successfully fetched | `2026-03-22 03:00:00` | ISO 8601 UTC | Scheduler / adapter | Real-time |
| records_collected | INTEGER | ✓ | How many records in last collection? | `24` | >= 0 | Scheduler / adapter | Real-time |
| status | VARCHAR | ✗ | Freshness status | `fresh` | `fresh`, `stale`, `missing`, `error` | Computed | Real-time |
| threshold_days | FLOAT | ✗ | Alert if no data in > N days | `3` | > 0 | Config | Never |
| notes | TEXT | ✓ | Status notes | `No new listings in 7 days; monitor for job market slowdown` | Free text | Manual | As needed |

**Notes:**
- Computed daily by `pipeline/health.py`
- Transitions to `stale` if last_collected_at > threshold_days ago
- Transitions to `missing` if never collected (last_collected_at = NULL)
- Transitions to `error` if last run had all failures

---

### snapshots

**Purpose:** Period scan summaries for dashboard history / trending.
**Primary Key:** `id`

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| id | INTEGER | ✗ | Record ID | `2` | Auto-increment | System | Immutable |
| region | VARCHAR | ✗ | Which region? | `austin_tx` | One of `ref_regions.region_key` | Config | Never |
| chain | VARCHAR | ✗ | Which chain? | `starbucks` | One of `ref_brands.brand_key` | Config | Never |
| source | VARCHAR | ✓ | Which source (or 'all')? | `all` | Source name or `all` | Config | Never |
| scanned_at | DATETIME | ✓ | When was this scan period? | `2026-03-16 04:00:00` | ISO 8601 UTC (typically Sunday night) | System | Weekly |
| store_count | INTEGER | ✓ | How many stores identified in this period? | `24` | >= 0 | Scanner | Weekly |
| signal_count | INTEGER | ✓ | How many raw signals collected? | `487` | >= 0 | Scanner | Weekly |
| summary_json | TEXT | ✓ | Arbitrary aggregates (JSON object) | `{"avg_score": 58.3, "critical_count": 4, ...}` | Valid JSON object | Scanner | Weekly |

**Notes:**
- Created automatically after each full scrape cycle (Sunday 4am after all jobs complete)
- Allows charting of "staffing stress trend over time"
- summary_json might include: avg_score, high_stress_count, critical_stores, by_source breakdown, etc.

---

### store_aliases

**Purpose:** Deduplication log. Maps duplicate store_num entries to canonical IDs.
**Primary Key:** (old_store_num, canonical_store_num)

| Column | Type | Nullable | Description | Example | Valid Values | Source | SLA |
|---|---|---|---|---|---|---|---|
| old_store_num | VARCHAR | ✗ | Duplicate store ID (from scraper) | `SB-AUSTIN-03347` | Store ID format | Collision detector | As needed |
| canonical_store_num | VARCHAR | ✗ | Canonical store ID to keep | `SB-03347` | Must exist in `stores.store_num` | Manual review | As needed |
| source_prefix | VARCHAR | ✓ | Which scraper created the duplicate? | `alltheplaces` | Scraper name | Collision detector | As needed |
| merged_at | DATETIME | ✓ | When was the merge performed? | `2026-03-15 12:30:00` | ISO 8601 UTC | Manual merge | As needed |

**Notes:**
- When a new store is discovered and matches an existing store (by lat/lng distance < 50m), create a merge record
- All signals on old_store_num should be re-tagged to canonical_store_num before deletion
- Currently unused (0 rows); future feature for multi-source store reconciliation

---

## Best Practices for Extending This Dictionary

**When adding a new table:**
1. Add entry to [Table Index](#table-index) at top
2. Create full section below with all columns documented
3. Include example values, valid ranges, source, and SLA
4. Document relationships (→ links, ← backlinks)
5. Add notes about NULL handling, constraints, refresh logic

**When adding a new column:**
1. Update the relevant table section here
2. Update corresponding SQLAlchemy model in `backend/database.py`
3. Add config to `config/chains.yaml` if tunable
4. Document in the column table with all 9 attributes

**When documenting scrapers:**
1. Add entry to `api_sources` with auth type and daily limit
2. Add entry to `api_endpoints` with route_status and health thresholds
3. Update the signals table "Signal Types & Value Ranges" section
4. Add test case for happy path + error cases

---

## Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-03-22 | Initial comprehensive dictionary covering all 22 tables |
