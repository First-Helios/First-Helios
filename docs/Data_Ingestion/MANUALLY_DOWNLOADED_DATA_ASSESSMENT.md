# Manually Downloaded Data Assessment

**Date:** 2026-03-22
**Location:** `/data/Manually_downloaded_data/` (571 MB)
**Status:** Analyzed and categorized

---

## Summary

You have 2 premium data sources downloaded:

| Source | Type | File Count | Coverage | Usefulness | Action Required |
|---|---|---|---|---|---|
| **OEWS (2024)** | National wage data | 8 XLSX files | National (area code 99 only) | ❌ Not suited for Austin MSA | **Download Austin-specific file** |
| **Revelio Labs** | Alternative labor stats | 7 CSV files | National + all states, 2021-2026 | ✅ Excellent for benchmarking | **Create ingestion tables + logic** |

---

## 1. OEWS Wage Data

### What You Downloaded
8 Excel files covering national occupational employment and wage statistics for 2024:
- `nat3d_M2024_dl.xlsx` — National 3-digit NAICS by occupation (national only, area code 99)
- `nat4d_M2024_dl.xlsx` — 4-digit NAICS
- `nat5d_6d_M2024_dl.xlsx` — 5-6 digit NAICS
- Plus owner-based variants

**Data Structure:**
- Columns: AREA, OCC_CODE, OCC_TITLE, TOT_EMP, H_MEDIAN, H_PCT10-90, A_MEDIAN, A_PCT10-90, etc.
- Format: Flat file with percentile wages (10th, 25th, median, 75th, 90th)
- Coverage: National aggregate only (area code 99)
- Year: 2024 (published May 2025)

### Problem
**These files contain NATIONAL data, not Austin MSA data.** The Austin-Round Rock-Georgetown MSA (area code 12420) occupational wages are NOT in these downloads.

### Solution
❌ **Current download is not useful for Austin-specific scoring.**

Download the Austin MSA-specific file instead:
```
https://www.bls.gov/oes/current/oes_12420.htm
→ Look for "Download XLS" link for detailed wage data
```

Or via direct URL pattern:
```
https://www.bls.gov/oes/2024/may/oes_12420.xlsx
```

**Action:** Replace the national files with Austin MSA file and re-ingest.

### Why This Matters
- `wage_competitiveness` sub-score needs **Austin-specific** occupation median wages
- National median (e.g., $16.85/hr for food prep) ≠ Austin median (may be $18.50/hr)
- Using national data would **understate** Austin staffing stress if Austin pays below-national but above-local

---

## 2. Revelio Labs Data

### What You Downloaded

Premium alternative labor statistics from [Revelio Labs](https://www.reveliolabs.com/):

| Dataset | File | Rows | Date Range | Granularity |
|---|---|---|---|---|
| **Employment** | employment_all_granularities.csv | 1.18M | 2021-01 to 2026-02 | Monthly, state, occupation (SOC 2d), industry (NAICS 2d) |
| **Job Openings** | postings_by_sector_occupation_state.csv | 1.06M | 2022-01 to 2026-02 | Monthly, state, occupation, industry |
| **Hiring & Attrition** | hiring_and_attrition_...csv | 1.18M | 2021-01 to 2026-02 | Hiring rate, attrition rate (NSA + SA) |
| **Salaries** | salaries_all_granularities.csv | 1.20M | 2022-01 to 2026-02 | Salary NSA, salary SA by state/industry/occupation |
| **Mass Layoff Notices** | layoffs_by_state.csv | 2,433 | 2021-01 to 2026-02 | By state: WARN Act filings |
| **Mass Layoff Notices** | layoffs_by_naics.csv | 1,005 | 2021-01 to 2026-02 | By industry |
| **Mass Layoff Notices** | total_layoffs.csv | 62 | National total | National aggregates |

### Data Quality
✅ **EXCELLENT** — Revelio Labs uses proprietary web scraping of job postings + WARN Act filings.

- **Employment data:** Monthly, 51 states + DC, 22 occupation groups, 17 industry groups
- **Job openings:** Real-time postings from 50+ job boards, deduplicated
- **Hiring/attrition:** Proprietary calculation from LinkedIn + Revelio panel
- **Salaries:** Scraped from job postings (real-time market data)
- **Layoffs:** WARN Act filings (official, leading indicator)

### Usefulness for Project

**Compare to existing BLS sources:**

| Metric | BLS Source | Revelio Source | Advantage |
|---|---|---|---|
| **Hiring rate** | JOLTS (national, 2mo lag) | Revelio (state-level, real-time) | **Revelio: More granular, more current** |
| **Attrition rate** | JOLTS quits % | Revelio attrition % | **Revelio: Includes layoffs, more direct** |
| **Job postings** | None (we scrape) | Revelio (aggregated) | **Revelio: Validated benchmark** |
| **Salaries** | OEWS annual | Revelio monthly | **Revelio: More current, posting-based** |
| **Layoff signal** | None | Revelio WARN filings | **Revelio: Early warning system** |

### Recommended Integration

Create 2 new tables in database:

#### Table: `revelio_labor_metrics`
```
id, month, state, naics2d_code, naics2d_name,
soc2d_code, soc2d_name,
employment_nsa, employment_sa,
hiring_rate_nsa, hiring_rate_sa,
attrition_rate_nsa, attrition_rate_sa,
salary_nsa, salary_sa,
fetched_at
```

**Usage:**
- Filter to Texas, NAICS 72 (Accommodation & Food)
- Track hiring/attrition over time
- Compare to JOLTS for validation
- Detect seasonal patterns

#### Table: `revelio_layoff_notices`
```
id, month, state, naics2d_code,
num_employees_notified, num_notices_issued, num_employees_laidoff,
fetched_at
```

**Usage:**
- Early warning: Mass layoffs → turnover spike expected
- Regional labor market shocks
- Industry sensitivity analysis

---

## Implementation Checklist

### OEWS Data

- [ ] **Download Austin MSA file:** https://www.bls.gov/oes/current/oes_12420.htm
  - Look for "Download XLS" or "Download CSV" with detailed percentile wages
  - Save to `/data/Manually_downloaded_data/OEWS_Austin_MSA_2024/`

- [ ] **Update ingestion script** to parse Austin-specific file format
  - Filter to SOC codes 35-0000, 35-3023, 35-2021, 35-1012, 35-3021 (food service roles)
  - Extract: area_code, occ_code, occ_title, employment, wage_median_hourly, wage_10pct-90pct

- [ ] **Test:** `python scrapers/manual_ingest.py --oews`
  - Verify oews_data table populated with Austin records
  - Spot-check: "Food Preparation Workers" (35-2021) median wage ~$16-18/hr

- [ ] **Update documentation:** Add to DATA_DICTIONARY_COLUMNS.md
  - Mark oews_data as "POPULATED (Austin MSA 2024)" instead of "EMPTY"

### Revelio Labs Data

- [ ] **Create database tables:**
  ```bash
  # Add to backend/database.py:
  class RevelioLaborMetrics(Base):
      __tablename__ = "revelio_labor_metrics"
      # Fields above

  class RevelioLayoffNotices(Base):
      __tablename__ = "revelio_layoff_notices"
      # Fields above
  ```

- [ ] **Create ingestion script** (`scrapers/revelio_ingest.py`)
  - Parse each CSV
  - Filter to Texas (state == 'Texas')
  - Ingest all months (2021-02 present)
  - Note: Data is monthly, not quarterly like QCEW

- [ ] **Add to scheduler** (`backend/scheduler.py`)
  - Job: `revelio_update` — Manual trigger (data doesn't update monthly)
  - Or: Quarterly review (compare patterns to JOLTS/QCEW)

- [ ] **Update baseline computation** (`backend/baseline.py`)
  - Add Revelio metrics as optional alternative to JOLTS for attrition rate
  - If JOLTS is stale (>2mo), use Revelio as fallback

- [ ] **Update documentation:**
  - Add Revelio tables to DATA_DICTIONARY_TABLES.md (new "ALTERNATIVE LABOR STATS" schema)
  - Update BLS_GROUND_TRUTH_GUIDE.md with comparison table

---

## Data Gaps Analysis

### What You Have Now

**Ground-Truth (Government):**
- ✅ QCEW (county employment) — quarterly
- ✅ JOLTS (national turnover) — monthly
- ✅ LAUS (county unemployment) — monthly
- ❌ OEWS (MSA occupation wages) — **missing Austin file** (you have national only)
- ❌ CBP (ZIP-level establishments) — needs Census API key

**Alternative (Private):**
- ✅ Revelio Labs (5 datasets) — national + state-level, 2021-present
- ❌ JobSpy (job boards) — automated via scrapers
- ❌ Reddit/Google Maps (sentiment) — automated via scrapers

### What You Still Need

For complete "heartbeat of the city" coverage:

#### High Priority

1. **Austin MSA OEWS file** (Occupation wages)
   - **Why:** Essential for wage_competitiveness scoring
   - **Effort:** 5 min download + 30 min ingestion script
   - **Impact:** Unlocks ground-truth wage benchmarking
   - **Get from:** https://www.bls.gov/oes/current/oes_12420.htm

2. **Census CBP API Key** (ZIP-level establishments)
   - **Why:** Hyperlocal staffing stress (Congress Ave vs. suburbs)
   - **Effort:** 24h signup, 1 command to run adapter
   - **Impact:** Enables targeting
   - **Get from:** https://api.census.gov/data/key_signup.html

#### Medium Priority

3. **Census ACS (American Community Survey)** — Education, income, population by ZIP
   - **Why:** Socioeconomic context (do poor ZIPs have different staffing stress?)
   - **Where:** Census API (same key as CBP)
   - **Effort:** Build new adapter
   - **Data:** Annual

4. **Google Maps Popular Times** API (if accessible)
   - **Why:** Store traffic/footfall patterns
   - **Where:** Google Places API (paid)
   - **Effort:** Requires commercial license
   - **Data:** Real-time

#### Low Priority (Nice to Have)

5. **Glassdoor / Indeed API** (if available)
   - **Why:** Company reviews, salary data, hiring trends
   - **Current:** Using JobSpy (aggregator) instead
   - **Effort:** Each API has different terms
   - **Data:** Real-time

6. **LinkedIn (via Revelio Labs existing data)**
   - **Why:** Employment flows, job search intensity
   - **Current:** Revelio Labs provides this (already have it!)
   - **Effort:** Already done
   - **Data:** Monthly

---

## Quick Wins (Do These First)

### 1. Download Austin OEWS File (5 min)
```bash
# Or manually download from:
https://www.bls.gov/oes/current/oes_12420.htm
# Save to: data/Manually_downloaded_data/OEWS_Austin_MSA_2024/
```

### 2. Ingest Revelio Labs (1 hour)
```bash
# Create revelio_ingest.py
# Run: python scrapers/revelio_ingest.py --all

# Result: 2 new tables with 1M+ rows each
# Validate: Texas NAICS 72 hiring/attrition rates make sense
```

### 3. Sign Up for Census API Key (5 min + 24h wait)
```bash
# Go to: https://api.census.gov/data/key_signup.html
# Paste key into .env: CBP_API_KEY=...
# Then: python scrapers/cbp_adapter.py --region austin_tx
```

### 4. Update Documentation (30 min)
- Mark OEWS as "POPULATED (Austin 2024)" in table dict
- Add Revelio tables to database schema
- Update BLS_GROUND_TRUTH_GUIDE.md with Revelio comparison

---

## File Organization

```
data/
├── tracker.db (main database)
├── Manually_downloaded_data/
│   ├── OEWS_wage_data/          ← NATIONAL DATA (replace with Austin MSA)
│   │   └── oesm24in4/
│   │       └── *.xlsx (national only)
│   └── revelioLabs/              ← ✅ USE THIS (all files)
│       ├── Employment.../
│       ├── Job Openings.../
│       ├── Hiring and Attrition.../
│       ├── Salaries.../
│       └── Mass-layoff Notices.../
```

---

## Summary: What's Ready vs. What's Needed

| Component | Status | Action |
|---|---|---|
| QCEW (county employment) | ✅ Populated | Run `python scrapers/qcew_adapter.py` |
| JOLTS (national turnover) | ✅ Populated | Run `python scrapers/bls_adapter.py` |
| LAUS (county unemployment) | ✅ Populated | Run `python scrapers/bls_adapter.py` |
| OEWS (MSA wages) | ❌ Wrong file | Download Austin MSA file, re-ingest |
| CBP (ZIP establishments) | ❌ Needs API key | Get free Census API key, run adapter |
| Revelio Labor Metrics | ✅ Downloaded | Create tables + ingestion script |
| Revelio Layoff Notices | ✅ Downloaded | Create table + ingestion script |
| **Baseline (computed)** | 🟡 Partial | Completes once OEWS + CBP done |
| **Scoring (engine)** | 🟡 Fallback mode | Activates once baseline complete |

**Current State:** Scoring works in percentile fallback mode. Once OEWS (Austin) + CBP are populated, scoring **activates full ground-truth mode** using real economic denominators.

---

## Sources

- [Austin-Round Rock MSA OEWS Data (2024)](https://www.bls.gov/oes/current/oes_12420.htm)
- [Revelio Labs Public Data Portal](https://www.reveliolabs.com/public-labor-statistics/)
- [BLS OEWS Download Page](https://www.bls.gov/oes/tables.htm)
- [Census API Key Signup](https://api.census.gov/data/key_signup.html)
