# Database Assessment & Data Collection Status
**Generated:** 2026-03-22 | **System:** ChainStaffingTracker v2.0 (Multi-Industry)

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Database Size** | 364 KB (23 empty operational tables) |
| **Reference Data** | ✅ 173 rows (brands, industries, regions, categories) |
| **API Sources Available** | 16 configured |
| **Scrapers Ready** | 8/8 available |
| **Data Downloaded** | 572 MB (Revelio Labs, OEWS, Texas wages) |
| **Data Ingested** | 0 rows (fresh start) |
| **Scheduler Jobs** | 12 registered |
| **System Status** | 🟢 Ready for data collection |

---

## SECTION 1: CORE LABOR DATA (Ground-Truth from Government)

### BLS Quarterly Census of Employment & Wages (QCEW)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `qcew_data` | 0 / 0 rows |
| **Coverage** | Austin-area counties | Travis, Williamson, Hays, Bastrop, Caldwell |
| **Granularity** | County × Industry × Ownership | NAICS 2-digit, private employment |
| **Recency** | Quarterly lag | Q3 2025 available |
| **Data Type** | Counts | Establishments, employment |
| **Configuration** | ✅ In chains.yaml | QCEW section configured |
| **Scraper** | ✅ qcew_adapter.py | Ready to run |
| **Scheduler Job** | ✅ qcew | Quarterly trigger |
| **Can Collect** | ✅ YES | Automated via BLS API |
| **Effort to Ingest** | 5 min | Schema already mapped |
| **Priority** | 🔴 **CRITICAL** | Baseline employment data |

**Data Fields (if collected):**
- county_fips, naics_code, ownership_code, period (YYYYQQ)
- establishments, employment, avg_annual_wages

---

### BLS Occupational Employment & Wages (OEWS)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `oews_data` | 0 / 638 rows expected |
| **Coverage** | Austin-Round Rock-San Marcos MSA | Area code 12420 |
| **Granularity** | MSA × SOC Occupation | All 638 occupations |
| **Recency** | May 2025 (latest annual) | Published May 2025 for May 2024 data |
| **Data Type** | Wages + percentiles | Hourly, annual, by percentile |
| **Configuration** | ✅ In chains.yaml | oews section configured |
| **Scraper** | ✅ oews_manual_ingest.py | Ready to run |
| **File Downloaded** | ❌ **NO** | Must download Austin file (not national) |
| **Download URL** | Link | https://www.bls.gov/oes/current/oes_12420.htm |
| **Can Collect** | ⚠️ YES (manual) | Must download Austin MSA file first |
| **Effort to Ingest** | 10 min | Schema ready, file format standard |
| **Priority** | 🔴 **CRITICAL** | Wage competitiveness scoring depends on it |

**Current Blocker:** Downloaded national OEWS (area code 99) — WRONG. Need Austin MSA (12420).
Human Note: the file name is /home/fortune/CodeProjects/First-Helios/data/Manually_downloaded_data/bls/(OEWS) Occupational Employment and Wage Statistics- Area: Austin-Round Rock-San Marcos, TX.ods its from austin.
**Data Fields (if collected):**
- soc_code, occupation_title, employment, mean_wage_hourly, wage_percentile_10/25/50/75/90

---

### BLS Job Openings & Labor Turnover (JOLTS)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `jolts_data` | 0 / 0 rows |
| **Coverage** | National aggregate | No state/MSA breakout |
| **Granularity** | Industry × Month | Manufacturing, education, food service, etc. |
| **Recency** | 2-month lag | January 2026 data released March 2026 |
| **Data Type** | Flows | Job openings, hires, separations, quits |
| **Configuration** | ✅ In chains.yaml | jolts section configured |
| **Scraper** | ✅ bls_adapter.py | Part of main BLS scraper |
| **Scheduler Job** | ✅ bls | Weekly trigger |
| **Can Collect** | ✅ YES | Automated via BLS API |
| **Effort to Ingest** | 5 min | Schema already mapped |
| **Priority** | 🟡 **HIGH** | Demand pressure scoring component |

**Data Fields (if collected):**
- naic_code, period (YYYYMM), job_openings, hires, quits, separations

---

### BLS Local Area Unemployment Statistics (LAUS)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `laus_data` | 0 / 0 rows |
| **Coverage** | County level | Travis, Williamson, Hays, Bastrop, Caldwell |
| **Granularity** | County × Month | Civilian labor force data |
| **Recency** | Monthly, ~1 week lag | February 2026 data available |
| **Data Type** | Rates & counts | Unemployment rate, labor force, employment |
| **Configuration** | ✅ In chains.yaml | laus section configured |
| **Scraper** | ✅ bls_adapter.py | Part of main BLS scraper |
| **Scheduler Job** | ✅ bls | Weekly trigger |
| **Can Collect** | ✅ YES | Automated via BLS API |
| **Effort to Ingest** | 5 min | Schema already mapped |
| **Priority** | 🟡 **HIGH** | Unemployment context & trend analysis |

**Data Fields (if collected):**
- county_fips, period (YYYYMM), unemployment_rate, labor_force, total_employment

---

### Census Bureau County Business Patterns (CBP)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `cbp_data` | 0 / 0 rows |
| **Coverage** | 25 Austin-area ZIP codes | Granular hyperlocal data |
| **Granularity** | ZIP × Industry | NAICS 6-digit |
| **Recency** | Annual (2024 data) | Released in December |
| **Data Type** | Counts | Establishments, employment by ZIP |
| **Configuration** | ✅ In chains.yaml | cbp section configured |
| **Scraper** | ✅ cbp_adapter.py | Ready to run |
| **Blocker** | ❌ **NO API KEY** | Must sign up: https://api.census.gov/data/key_signup.html |
| **Can Collect** | ⚠️ YES (with key) | Requires Census API registration |
| **Effort to Ingest** | 5 min (script ready) | Schema already mapped |
| **Priority** | 🟡 **HIGH** | Hyperlocal targeting & store baselines |

Human Note: Cencus API key is CBP_API_KEY in .env.
**Blocking Action:** Obtain Census API key (5 min signup).

**Data Fields (if collected):**
- zip_code, naics_code, establishments, employment

---

## SECTION 2: DOWNLOADED DATA (Ready to Ingest)

### Revelio Labs Employment Intelligence
| Attribute | Status | Details |
|-----------|--------|---------|
| **Source** | Revelio Labs | Proprietary employment data (Feb 2026 edition) |
| **Location** | `/data/Manually_downloaded_data/revelioLabs/` | 7 CSV files, 540 MB |
| **Files** | 7 datasets | See table below |
| **Total Rows** | ~1.2M | Time series across all files |
| **Coverage** | National (all states) | Can filter to Austin/Texas |
| **Recency** | February 2026 | Current month available |
| **Data Type** | Flows & stocks | Employment, hiring, attrition, salaries, layoffs |
| **Table(s)** | `revelio_employment`, `revelio_hiring`, `revelio_salaries`, `revelio_layoffs` | Not yet created |
| **Scraper** | None (manual download) | Need to create ingestion script |
| **Can Collect** | ✅ YES | Files already downloaded |
| **Effort to Ingest** | **1-2 hours** | Create 4 tables + parsing script |
| **Priority** | 🟡 **MEDIUM** | Alternative/supplementary labor data |
| **Value** | High granularity | State/industry/occupation breakouts; monthly detail |

**Files Ready to Ingest:**

| File | Rows | Key Granularities | Useful Columns |
|------|------|-------------------|-----------------|
| `employment_all_granularities.csv` | 1.18M | State, industry, occupation, 2021-2026 | month, employment_count, emp_change |
| `postings_by_sector_occupation_state.csv` | 1.06M | State, sector, SOC occupation, 2022-2026 | month, job_postings, posting_pct_change |
| `hiring_and_attrition_by_sector_occupation_state.csv` | 1.18M | State, sector, SOC, hiring/attrition NSA+SA | month, hiring_rate, attrition_rate |
| `salaries_all_granularities.csv` | 1.20M | State, industry, occupation, 2022-2026 | month, mean_salary, salary_growth_12mo |
| `layoffs_by_state.csv` | 2,433 | State, industry, 2020-2026 | month, layoff_count, cumulative_layoffs |
| `layoffs_by_naics.csv` | 1,005 | NAICS industry code, 2020-2026 | month, layoff_count |
| `total_layoffs.csv` | 62 | National aggregate, 2020-2026 | month, total_layoffs |

**Use Cases:**
- Trend validation against BLS
- Alternative wage growth measures
- Hiring rate comparisons
- Layoff early warnings

---

### Texas Wage Reference Data
| Attribute | Status | Details |
|-----------|--------|---------|
| **Location** | `/data/Manually_downloaded_data/texaswages/` | 4 CSV files, 612 KB |
| **Coverage** | Texas MSAs (7 major metros) | Houston, Dallas, Austin, San Antonio, etc. |
| **Granularity** | MSA × Industry | Industry mean wages by MSA |
| **Recency** | BLS source (2022-2023) | Utility data for reference |
| **Data Type** | Wage means | Hourly/annual by industry |
| **Table** | `ref_texas_wages` | Can create for reference/context |
| **Can Collect** | ✅ YES | Already downloaded |
| **Effort to Ingest** | 15 min | Reference table (no time series) |
| **Priority** | 🟢 **LOW** | Useful for context, not critical |

---

### BLS Manual Download Cache
| Attribute | Status | Details |
|-----------|--------|---------|
| **Location** | `/data/bls_cache/` | ~20 JSON files with series IDs |
| **Content** | Historical BLS data | QCEW, OES, employment series |
| **Purpose** | Quick lookup | Avoids repeated API calls |
| **Status** | ✅ Available | Can be used for backfill |
| **Effort** | 30 min | Schema mapping + ingestion script |
| **Priority** | 🟢 **LOW** | Backfill only, real-time fetch preferred |

---

## SECTION 3: OPERATIONAL DATA (Job Postings & Sentiment)

### JobSpy (Indeed + Glassdoor Aggregator)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `signals` (source='jobspy') | 0 rows (will grow with collections) |
| **Coverage** | Austin metro | Configurable search radius |
| **Granularity** | Individual job postings | Job title, company, posting date, salary |
| **Recency** | Real-time | Latest postings from Indeed/Glassdoor |
| **Data Type** | Job metadata | Title, URL, salary (when listed), posting age |
| **Scraper** | ✅ jobspy_adapter.py | Fully implemented |
| **Scheduler Job** | ✅ jobspy | Daily 4:00 AM |
| **Can Collect** | ✅ YES | No API key required |
| **Effort to Collect** | 0 (automatic) | Scheduled scraper running |
| **Priority** | 🟡 **HIGH** | Demand pressure signal |
| **Data Retention** | Rolling (postings age 1-90 days) | Older postings discarded |

**Signal Fields:**
- store_num (matched to chain_locations), signal_type='job_posting', value=posting_age_days
- metadata: job_title, url, salary_range, source_job_board

---

### Reddit (Sentiment Analysis)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `signals` (source='reddit') | 0 rows (will grow with collections) |
| **Coverage** | r/Austin + industry-specific subreddits | Mentions of employers, work conditions |
| **Granularity** | Individual posts/comments | Discussion threads about specific companies |
| **Recency** | Past 7 days (typical Reddit archiving) | Latest discussions |
| **Data Type** | Text sentiment | Positive/negative mentions of employers |
| **Scraper** | ✅ reddit_adapter.py | Fully implemented |
| **Scheduler Job** | ✅ reddit | Every 6 hours |
| **Can Collect** | ✅ YES | No authentication required (public API) |
| **Effort to Collect** | 0 (automatic) | Scheduled scraper running |
| **Priority** | 🟡 **HIGH** | Qualitative signal for sentiment scoring |
| **Data Retention** | 60 days | Older posts dropped |

**Signal Fields:**
- store_num (fuzzy-matched from post content), signal_type='sentiment', value=-1 to +1 (polarity)
- metadata: post_url, subreddit, post_title, author, score

---

### Google Maps Reviews
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `signals` (source='gmaps') | 0 rows (will grow with collections) |
| **Coverage** | Austin-area store locations | Linked to store_num via address matching |
| **Granularity** | Individual reviews | Customer ratings, text feedback |
| **Recency** | Recent reviews (1-30 days old preferred) | Full star rating history available |
| **Data Type** | Ratings + text sentiment | 1-5 stars + text review |
| **Scraper** | ✅ reviews_adapter.py | Playwright-based (handles SPA) |
| **Scheduler Job** | ✅ google_maps | Weekly Monday 5:00 AM |
| **Can Collect** | ⚠️ RISKY | Requires careful rate limiting, may trip anti-scraping |
| **Effort to Collect** | Automated | Scheduled, but may need tuning |
| **Priority** | 🟡 **MEDIUM** | Customer sentiment signal |
| **Data Retention** | Latest 100 reviews per location | Rotating window |

**Signal Fields:**
- store_num (address-matched), signal_type='review', value=star_rating (1-5)
- metadata: review_text, reviewer_name, review_date

---

## SECTION 4: STORE DISCOVERY (Location Data)

### AllThePlaces (Overture Maps)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `chain_locations` (source_discovery='alltheplaces') | 0 rows |
| **Coverage** | Austin metro (configurable bbox) | All POI types |
| **Granularity** | Individual locations | Name, address, lat/lng, category |
| **Recency** | Overture Maps release cycle | Updated quarterly |
| **Data Type** | POI metadata | Location coordinates, address, type |
| **GeoJSON Download** | ✅ `/data/overture_austin_places.geojson` | 106 MB file, ready to parse |
| **Scraper** | ✅ alltheplaces_adapter.py | GeoJSON parser |
| **Scheduler Job** | ✅ alltheplaces | Weekly Sunday 2:00 AM |
| **Can Collect** | ✅ YES | File already cached; can re-download |
| **Effort to Ingest** | 15 min | Parse GeoJSON, filter to target brands |
| **Priority** | 🟡 **HIGH** | Foundation for store location database |

**Data Fields:**
- store_num (auto-generated), brand_key (matched), chain (Starbucks/Dutch Bros/etc.)
- address, lat, lng, source_discovery='alltheplaces'

---

### OpenStreetMap (via Overpass API)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `chain_locations` (source_discovery='osm') | 0 rows |
| **Coverage** | Austin metro | Community-maintained map |
| **Granularity** | Individual locations | Amenity tags: cafe, restaurant, fast_food |
| **Recency** | Real-time (community updates) | Latest OSM data |
| **Data Type** | Tags + coordinates | OSM way/node metadata |
| **Scraper** | ✅ osm_adapter.py | Overpass API query |
| **Scheduler Job** | ✅ osm | Weekly Wednesday 4:00 AM |
| **Can Collect** | ✅ YES | Free, no authentication |
| **Effort to Collect** | Automated | Scheduled scraper running |
| **Priority** | 🟡 **HIGH** | Supplement corporate discovery |

**Data Fields:**
- store_num (auto-generated), brand_key (matched from name/tags), lat/lng

---

### Overture Maps (S3 Download)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `chain_locations` (source_discovery='overture') | 0 rows |
| **Coverage** | Austin metro | Commercial POI dataset |
| **Granularity** | Business locations | Companies, store names, categories |
| **Recency** | Quarterly release | Current release available |
| **Data Type** | POI + metadata | Location, business name, classifications |
| **Scraper** | ✅ overture_adapter.py | S3 parquet parser |
| **Scheduler Job** | ✅ overture | Weekly Tuesday 3:00 AM |
| **Can Collect** | ✅ YES | Public S3 bucket, no auth required |
| **Effort to Collect** | Automated | Scheduled scraper running |
| **Priority** | 🟡 **HIGH** | Authoritative POI source |

**Data Fields:**
- store_num, brand_key, lat/lng, address, business_category

---

## SECTION 5: LABOR DISTRESS SIGNALS

### WARN Act Notices (DOL)
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `signals` (source='warn') | 0 rows |
| **Coverage** | US-wide (can filter to Texas) | Mass layoff notifications |
| **Granularity** | Plant/facility level | Company, location, notice date, # affected |
| **Recency** | Real-time feeds | Warnings issued within days |
| **Data Type** | Layoff events | Notice date, effective date, count |
| **Scraper** | ✅ warn_adapter.py | DOL API scraper |
| **Scheduler Job** | Not yet registered | Can add to scheduler |
| **Can Collect** | ✅ YES | Public government data |
| **Effort to Collect** | Automated | Needs scheduler registration |
| **Priority** | 🟡 **MEDIUM** | Early warning signal for labor supply |

**Signal Fields:**
- store_num (geo-matched to locations), signal_type='warn_notice', value=workers_affected
- metadata: company_name, notice_date, effective_date, reason_code

---

### NLRB Union Activity
| Attribute | Status | Details |
|-----------|--------|---------|
| **Table** | `signals` (source='nlrb') | 0 rows |
| **Coverage** | US-wide (can filter to Texas) | Union organizing, strikes, petitions |
| **Granularity** | Facility/company level | Union name, action type, date |
| **Recency** | Weekly updates | Filings updated regularly |
| **Data Type** | Labor action metadata | Case type, status, parties |
| **Scraper** | ✅ nlrb_adapter.py | NLRB public database scraper |
| **Scheduler Job** | ✅ nlrb | Monthly trigger |
| **Can Collect** | ✅ YES | Public government data |
| **Effort to Collect** | Automated | Scheduled scraper running |
| **Priority** | 🟢 **LOW** | Operational labor signal (not Austin-specific) |

**Signal Fields:**
- store_num (matched to locations), signal_type='union_activity', value=engagement_level (1-5)
- metadata: case_type, union_name, case_status, filing_date

---

## SECTION 6: DATA COMPLETENESS MATRIX

### What We Can Collect (Immediately)

| Source | Type | Effort | Dependency | Status |
|--------|------|--------|-----------|--------|
| **BLS QCEW** | Ground-truth employment | 5 min | None | 🟡 Scheduler ready |
| **BLS JOLTS** | Ground-truth demand | 5 min | None | 🟡 Scheduler ready |
| **BLS LAUS** | Ground-truth unemployment | 5 min | None | 🟡 Scheduler ready |
| **OEWS Austin** | Ground-truth wages | 10 min | Download Austin file | ❌ **BLOCKED** |
| **Census CBP** | ZIP-level baseline | 5 min | Get Census API key | ⚠️ **BLOCKED** |
| **JobSpy** | Job postings | 0 min | None | ✅ **Running** |
| **Reddit** | Sentiment | 0 min | None | ✅ **Running** |
| **Google Maps** | Reviews | 0 min | None | ⚠️ Rate limits |
| **AllThePlaces** | Store discovery | 15 min | None | 🟡 GeoJSON cached |
| **OpenStreetMap** | Store discovery | 0 min | None | ✅ **Running** |
| **Overture Maps** | Store discovery | 0 min | None | ✅ **Running** |
| **WARN Act** | Layoff signals | 0 min | None | 🟡 Scheduler ready |
| **NLRB** | Union activity | 0 min | None | ✅ **Running** |

---

### What We Have Downloaded

| Source | Size | Status | Effort to Ingest |
|--------|------|--------|-----------------|
| **Revelio Labs** | 540 MB | ✅ Ready | 1-2 hours (create tables) |
| **OEWS National** | 32 MB | ❌ Wrong region | 0 (unusable) |
| **Texas Wages** | 612 KB | ✅ Reference | 15 min |
| **Overture GeoJSON** | 106 MB | ✅ Ready | 15 min |
| **BLS Cache** | ~5 MB | ✅ Cached | 30 min (optional backfill) |

---

## SECTION 7: CRITICAL PATH TO FIRST COMPLETE DATASET

### Phase 1: Immediate (Today) — 30 minutes
**Unlock:** OEWS Austin MSA data

1. Download OEWS Austin MSA file (area code 12420) from BLS
2. Run `python scripts/oews_manual_ingest.py` to ingest
3. Verify 638 occupations populated in `oews_data` table

**Impact:** Enables wage competitiveness scoring for all 638 Austin occupations

**Status:** ✅ **ACTION REQUIRED**

---

### Phase 2: Short-term (Today to Tomorrow) — 2-3 hours
**Unlock:** Revelio Labs alternative data + hyperlocal baseline

**2a. Revelio Labs Ingestion (1-2 hours)**
1. Create tables: `revelio_employment`, `revelio_hiring`, `revelio_salaries`, `revelio_layoffs`
2. Create ingestion script that loads 7 CSV files
3. Filter to Texas/Austin for dashboard
4. Run initial ingest

**Impact:** 1.2M additional labor data rows; monthly granularity; trends & flows

**Status:** 🟡 **READY TO START**

**2b. Census API Key (5 minutes)**
1. Sign up at https://api.census.gov/data/key_signup.html
2. Copy API key to environment
3. Test `cbp_adapter.py --test`

**Impact:** Unlocks ZIP-level establishment baselines (critical for targeting)

**Status:** 🟡 **READY TO START**

---

### Phase 3: Medium-term (Ongoing) — Automatic
**Unlock:** Real-time signals from job postings & sentiment

**3a. JobSpy (Daily)**
- Runs at 4:00 AM Austin time
- Collects job postings from Indeed/Glassdoor
- Populates `signals` table with posting ages

**3b. Reddit (Every 6 hours)**
- Runs on schedule
- Collects sentiment from r/Austin + industry subreddits
- Populates `signals` table with sentiment scores

**3c. Google Maps Reviews (Weekly)**
- Runs Monday 5:00 AM
- Collects reviews from all discovered store locations
- Populates `signals` table with review ratings

**3d. Store Discovery (Weekly)**
- AllThePlaces: Sunday 2 AM
- OpenStreetMap: Wednesday 4 AM
- Overture Maps: Tuesday 3 AM
- Populates `chain_locations` table with lat/lng

**Status:** ✅ **SCHEDULED & AUTOMATIC**

---

### Phase 4: Validation (Weekly)
**Run:** `scripts/system_health_dashboard.py`

Check:
1. Data freshness (last signal < 7 days old)
2. Table row counts increasing
3. No stale postings (age > 90 days)
4. Metadata lineage tracking

---

## SECTION 8: RECOMMENDED IMMEDIATE ACTIONS

### 🔴 BLOCKING (Must do today)

1. **Download OEWS Austin file** (5 min)
   ```bash
   # Manually download from:
   # https://www.bls.gov/oes/current/oes_12420.htm
   # Save to: data/Manually_downloaded_data/oews_austin/oes_12420.xlsx
   ```
   Then run:
   ```bash
   python scrapers/oews_manual_ingest.py data/Manually_downloaded_data/oews_austin/oes_12420.xlsx
   ```

2. **Get Census API Key** (5 min signup)
   ```bash
   # Go to: https://api.census.gov/data/key_signup.html
   # Save key to: export CENSUS_API_KEY=xxxxxxxxxxxxxxx
   ```
   Then test:
   ```bash
   python scrapers/cbp_adapter.py --test
   ```

### 🟡 HIGH-VALUE (Today/tomorrow)

3. **Ingest Revelio Labs** (1-2 hours)
   - Create ingestion script for 7 CSV files
   - Map to `revelio_*` tables
   - Filter to Austin/Texas for initial load

4. **Run store discovery** (30 min)
   ```bash
   # Parse cached GeoJSON
   python scrapers/alltheplaces_adapter.py --ingest
   ```

### 🟢 OPTIONAL (Can defer)

5. **Populate metadata** (30 min)
   ```bash
   python scripts/populate_metadata.py
   ```

6. **Run system health dashboard** (10 min)
   ```bash
   python scripts/system_health_dashboard.py
   ```

---

## SECTION 9: SUCCESS CRITERIA

After completing Phase 1-2, the system should have:

| Table | Target Rows | Purpose |
|-------|------------|---------|
| `ref_brands` | 17 ✅ | Brand master data |
| `ref_industry` | 49 ✅ | NAICS hierarchy |
| `oews_data` | **638** | Wage benchmarks |
| `cbp_data` | **~5,000** | ZIP-level baselines |
| `chain_locations` | **~500-1000** | Store locations |
| `signals` | **~10,000+** | Job postings + sentiment |
| `labor_market_baseline` | **~100** | Pre-computed metrics |
| `scores` | **~500-1000** | Store-level scores |

**Dashboard Ready:** API returns staffing stress scores by location

---

## SECTION 10: DATABASE FILE MANIFEST

| File Path | Size | Purpose | Status |
|-----------|------|---------|--------|
| `/data/tracker.db` | 364 KB | **Primary database** | 🟢 Active |
| `/data/tracker_pre_v2_20260323_023337.db` | 1.5 MB | Pre-reset backup | 📦 Archive |
| `/data/Manually_downloaded_data/revelioLabs/` | 540 MB | Revelio CSVs | 📦 Ready to ingest |
| `/data/Manually_downloaded_data/OEWS_wage_data/` | 32 MB | National OEWS (wrong region) | ❌ Unusable |
| `/data/Manually_downloaded_data/texaswages/` | 612 KB | Texas MSA reference | 📦 Can load |
| `/data/bls_cache/` | ~5 MB | BLS JSON cache | 📦 For lookup |
| `/data/overture_austin_places.geojson` | 106 MB | POI locations | 📦 Ready to parse |

---

## SECTION 11: NOTES & CAVEATS

### Known Limitations

1. **Regional scope:** Austin MSA only (no statewide/national comparison)
2. **Brand coverage:** 17 pre-configured chains (Starbucks, Dutch Bros as primary)
3. **OEWS lag:** Data is 12 months old (May 2024 data released May 2025)
4. **Revelio Labs:** Proprietary data (not government-sourced, but aggregated)
5. **Google Maps scraping:** May be rate-limited or blocked by anti-scraping

### Data Quality Assumptions

- **BLS data:** Authoritative but with 2-3 month publication lag
- **Revelio data:** Aggregated from job boards + payroll; good proxy but not ground-truth
- **Reddit/reviews:** Noisy but directionally informative
- **JobSpy:** Aggregates Indeed + Glassdoor (doesn't capture all postings)

### Future Enhancements

- LinkedIn scraping (requires OAuth)
- Glassdoor company reviews (requires scraping)
- Economic indicators (Fed data, census income distributions)
- Real estate data (rental trends, office space availability)
- Commute time analysis (API-based routing)

---

**Last Updated:** 2026-03-22 21:56 UTC
**System:** ChainStaffingTracker v2.0 (Fresh Start)
**Assessment By:** Claude Code with Explore Agent
