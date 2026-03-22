# BLS Ground-Truth Schema — Complete Guide

**This document focuses exclusively on the 5 BLS/Census tables that serve as the authoritative source of truth for labor market scoring.**

---

## What is "Ground-Truth"?

**Ground-Truth** = Official government data from the Bureau of Labor Statistics (BLS) and U.S. Census Bureau.

- **Authoritative:** Published by federal agencies; the official record
- **Append-only:** New data is always appended; old data is never revised
- **Lagged:** Data arrives 2–18 months after the fact
- **Benchmarks:** Used as denominators in all scoring formulas

When scrapers can't get current data (job postings dry up, sentiment disappears), ground-truth baselines allow fallback to percentile-based scoring.

---

## The 5 Ground-Truth Tables

```
                    ┌─────────────────────────────┐
                    │   Labor Market Baseline     │
                    │  (Computed from all 5)      │
                    └──────────────┬──────────────┘
                                   │
                  ┌────────────────┼────────────────┐
                  │                │                │
                  ▼                ▼                ▼
        ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
        │  QCEW Data   │  │ JOLTS Data   │  │ LAUS Data    │
        │(quarterly)   │  │(monthly)     │  │(monthly)     │
        │              │  │              │  │              │
        │Establish-    │  │Job Openings  │  │Unemploy-     │
        │ments: 127    │  │Quits: 2.5%   │  │ment Rate:3.3%│
        │Employment:   │  │Hires: 3.1%   │  │Labor Force:  │
        │8,400         │  │Separations:3%│  │1,045,000     │
        └──────────────┘  └──────────────┘  └──────────────┘
              │                 │                  │
              └─────────────────┼──────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
    ┌─────────────┐       ┌─────────────┐      ┌──────────────┐
    │ OEWS Data   │       │ CBP Data    │      │ Used By:     │
    │  (annual)   │       │  (annual)   │      │              │
    │             │       │             │      │Scoring       │
    │Wages:       │       │Establish:   │      │Engine        │
    │ $16.85/hr   │       │34 per ZIP   │      │              │
    │(median)     │       │Employment:  │      │demand_       │
    │             │       │456          │      │pressure      │
    └─────────────┘       └─────────────┘      │wage_comp     │
                                                │churn_signal  │
                                                └──────────────┘
```

### 1. QCEW (Quarterly Census of Employment & Wages)

**What it is:** County-level counts of how many employers (establishments) and employees exist, by industry.

**Frequency:** Quarterly (Q1, Q2, Q3, Q4)
**Data lag:** ~6 months (Q3 data available the following March)
**Coverage:** 5 Austin-area counties × 5 industry codes = 25 records per quarter

**Key columns:**
- `establishments` — How many Starbucks-like locations exist in Travis County?
- `month1/2/3_employment` — How many people worked in food service in Jan, Feb, Mar?
- `avg_weekly_wage` — Average weekly paycheck in this industry/county

**Used for:**
- **demand_pressure** — Postings per store / regional norm
- **seasonal_index** — Quarter-over-quarter employment variance

**Example row:**
```
Travis County, Q3 2025, Snack Bars (722515)
Establishments: 127
Month 1 employment: 8,234
Month 2 employment: 8,456
Month 3 employment: 8,512
Avg weekly wage: $687.50
```

---

### 2. JOLTS (Job Openings & Labor Turnover Survey)

**What it is:** National-level rates of how many jobs open up and how many people quit, by industry.

**Frequency:** Monthly
**Data lag:** ~2 months (Dec data available early Mar)
**Coverage:** National + 1 industry (Accommodation & Food) = 8 series IDs

**Key columns:**
- `quits_rate` — What % of workers quit each month?
- `openings_rate` — What % of jobs are unfilled?
- `hires_rate` — What % of jobs are newly filled?
- `separations_rate` — What % of jobs end (quits + layoffs)?

**Used for:**
- **churn_signal** — If 2% of workers quit normally, and we see 2x the postings, that's stress
- **baseline** — "Expected separations" = employment × quits_rate / 100

**Example row:**
```
Dec 2025, Accommodation & Food Services (NAICS 72)
Quits rate: 2.5% (seasonally adjusted)
Openings rate: 3.2%
Hires rate: 3.1%
Separations rate: 3.3%
```

---

### 3. LAUS (Local Area Unemployment Statistics)

**What it is:** County-level unemployment rates, labor force size, and employment figures.

**Frequency:** Monthly
**Data lag:** ~2 months
**Coverage:** 3 Austin-area counties × 12 months × 15+ years = 540+ records

**Key columns:**
- `unemployment_rate` — What % of the labor force is jobless?
- `labor_force` — How many people are in the labor market?
- `employed` — How many have jobs?
- `unemployed` — How many are looking for jobs?

**Used for:**
- **baseline context** — Regional economic health
- **wage_competitiveness** — "Is the chain paying below market when unemployment is 3.3%?"

**Example row:**
```
Travis County, Dec 2025
Labor force: 1,045,000
Employed: 1,010,000
Unemployed: 35,000
Unemployment rate: 3.3%
```

---

### 4. OEWS (Occupational Employment & Wage Statistics)

**What it is:** Occupational-level wage data (10th, 25th, 50th, 75th, 90th percentile) for specific job titles in specific regions.

**Frequency:** Annual (published May each year for prior-year data)
**Data lag:** ~12 months (2024 data published May 2025, available 2026)
**Coverage:** Austin MSA (area 12420) × 5 occupation codes = 5 records/year

**Key columns:**
- `wage_median_hourly` — 50th percentile (middle wage)
- `wage_10pct`, `wage_25pct`, `wage_75pct`, `wage_90pct` — Percentile wages
- `employment` — How many in this job in the Austin area?

**Used for:**
- **wage_competitiveness** — "Starbucks pays $18.50/hr; median for baristas is $16.85. Gap = +$1.65 (above market!) = no stress"

**Example row:**
```
Austin-Round Rock-Georgetown MSA, 2024
SOC 35-3021 (Food Preparation Workers)
Employment: 3,421
Wage 10th percentile: $12.50/hr
Wage 25th percentile: $14.10/hr
Wage median (50th): $16.85/hr
Wage 75th percentile: $19.50/hr
Wage 90th percentile: $22.00/hr
```

**Status:** ⚠️ **NOT YET IMPORTED** — Requires manual download from BLS website and import script

---

### 5. CBP (County Business Patterns)

**What it is:** ZIP-code-level counts of establishments and employment by industry.

**Frequency:** Annual
**Data lag:** ~18 months (2024 data available mid-2026)
**Coverage:** 25 Austin-area ZIPs × 3 industry codes × 15+ years = 1,000+ records

**Key columns:**
- `establishments` — How many Starbucks-like locations in ZIP 78701?
- `employment` — Total people employed in those locations
- `annual_payroll_k` — Total payroll in thousands

**Used for:**
- **hyperlocal context** — "Congress Ave (78701) has 8 food service establishments"
- **density** — "Downtown has higher employment density than suburbs"

**Example row:**
```
ZIP 78701 (Downtown), 2024
NAICS 722515 (Snack Bars)
Establishments: 8
Employment: 85
Annual payroll: $1,250,500
```

**Status:** ⚠️ **NOT YET IMPORTED** — Requires Census API key (free, ~24h signup)

---

## How They Work Together: labor_market_baseline

The **labor_market_baseline** table is **computed** from all 5 ground-truth tables. It's the bridge between raw government data and scoring logic.

**Baseline computation** (weekly, Sunday 4am):
```python
# For each region + NAICS code:
baseline = {
    "establishment_count": qcew.establishments,                  # From QCEW
    "total_employment": qcew.avg_employment_across_months,      # From QCEW
    "avg_weekly_wage": qcew.avg_weekly_wage,                    # From QCEW
    "expected_quits_rate": jolts.quits_rate_12m_avg,            # From JOLTS
    "expected_monthly_separations": total_employment * expected_quits_rate / 100,  # Computed
    "occupation_median_wage": oews.wage_median_hourly,          # From OEWS
    "unemployment_rate": laus.unemployment_rate_region_avg,     # From LAUS
    "seasonal_index": current_q_employment / 4q_average,        # From QCEW
}
```

Then the **scoring engine** uses this baseline:
```python
# demand_pressure = (store_postings / regional_per_establishment) × 50
regional_per_establishment = baseline["total_postings"] / baseline["establishment_count"]

# wage_competitiveness = 50 + gap_pct
gap = (baseline["occupation_median_wage"] - chain_wage) / baseline["occupation_median_wage"] × 100

# churn_signal = (store_postings / expected_separations) × 50
expected_separations = baseline["expected_monthly_separations"]
```

---

## Data Lag Timeline

```
                                    TODAY
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────┐
│ WHAT'S AVAILABLE NOW (March 2026)                           │
│                                                             │
│ QCEW:  Q3 2025 ✓ (6 months lag)                            │
│ JOLTS: Dec 2025 ✓ (2 months lag)                           │
│ LAUS:  Dec 2025 ✓ (2 months lag)                           │
│ OEWS:  2024 ✓ (12 months lag)                              │
│ CBP:   2024 ✓ (18 months lag)                              │
│                                                             │
│ Next arrivals:                                              │
│ ├─ QCEW 2026-Q1 (April 2026)                               │
│ ├─ JOLTS Jan 2026 (early May 2026)                         │
│ └─ LAUS Jan 2026 (early May 2026)                          │
└─────────────────────────────────────────────────────────────┘

LESSON: Scoring uses months-old data. That's fine — government
        labor markets move slowly. But check timestamps to know
        whether you're comparing June staffing stress against
        December employment baselines.
```

---

## Refresh Schedule (Automated)

In `backend/scheduler.py`:

| Job ID | Schedule | What it fetches |
|---|---|---|
| `qcew` | 1st of month, 7am | Latest quarter from BLS QCEW CSV API |
| `bls` | Monday 6am | Latest JOLTS + LAUS from BLS API v2 |
| `baseline_recompute` | Sunday 4am | Combines all 5 into labor_market_baseline |

**Manual (not yet automated):**
| Source | Action | Where |
|---|---|---|
| OEWS | Download annual flat file from BLS | https://www.bls.gov/oes/tables.htm |
| CBP | Request Census API key + run adapter | https://api.census.gov/data/key_signup.html |

---

## Common Questions

### Q: Why is OEWS data empty?
**A:** The adapter doesn't exist yet. OEWS publishes flat Excel files (not an API), so we need a manual import script. See CLAUDE_AGENT_HANDOFF.md section 10.3.

### Q: My scores are in fallback mode (percentile-based). Why?
**A:** One or more ground-truth sources haven't been fetched yet. Check:
1. Is `labor_market_baseline` table populated? (Should have 5 rows minimum)
2. What's the latest timestamp in each ground-truth table?
3. Check `api_endpoints.last_success_at` for each BLS job

### Q: Can I use older data if current data hasn't arrived?
**A:** Yes! The baseline table keeps historical data. If QCEW Q3 2025 is the latest, it's used for baseline. When Q4 2025 arrives (April 2026), the baseline updates.

**Exception:** JOLTS and LAUS are monthly series; an old month is outdated. If Dec 2025 data is missing, use Nov 2025.

### Q: What if I'm missing some ground-truth data?
**A:** The scoring engine **redistributes weights**. Example:
- Normal weights: 35% demand_pressure, 25% wage_competitiveness, 25% churn_signal, 15% qualitative
- If churn_signal can't compute (no JOLTS data), weights become: 44% demand_pressure, 31% wage_competitiveness, 0% churn_signal, 25% qualitative

### Q: How do I know if my baseline is stale?
**A:** Check the `labor_market_baseline.computed_at` column. If it's >7 days old, that's suspicious. Run:
```bash
sqlite3 data/tracker.db "SELECT * FROM labor_market_baseline ORDER BY computed_at DESC LIMIT 1;"
```

---

## Integration with Scoring

```
┌────────────────────────────────────────────┐
│  SCORING ENGINE (backend/scoring/engine.py)│
└────────────────────┬───────────────────────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
         ▼           ▼           ▼
    ┌─────────────────────────────────────┐
    │  labor_market_baseline (ONE QUERY)   │  ◄── Fetched once per compute
    │  • establishment_count               │
    │  • expected_quits_rate               │
    │  • occupation_median_wage            │
    │  • unemployment_rate                 │
    │  • seasonal_index                    │
    └─────────────────────────────────────┘
         │           │           │
    ┌────┴──┐   ┌────┴──┐   ┌────┴──┐
    │        │   │       │   │       │
    ▼        ▼   ▼       ▼   ▼       ▼
demand_     wage_      churn_    seasonal
pressure    competitiveness  signal   adjustment
(35%)       (25%)       (25%)     (implicit)
```

Each sub-score formula references baseline columns:
- **demand_pressure:** Uses `establishment_count`
- **wage_competitiveness:** Uses `occupation_median_wage`
- **churn_signal:** Uses `expected_monthly_separations` (derived from employment × quits_rate)
- **qualitative:** Independent (no baseline needed)

---

## File References

- **Config:** [config/chains.yaml](../config/chains.yaml) — Series IDs, county FIPs, NAICS codes
- **Database models:** [backend/database.py](../backend/database.py) — All 5 table schemas
- **Baseline computation:** [backend/baseline.py](../backend/baseline.py) — How baseline is computed
- **Scoring engine:** [backend/scoring/engine.py](../backend/scoring/engine.py) — How baseline is used
- **Scheduler:** [backend/scheduler.py](../backend/scheduler.py) — Refresh schedule
- **Full dictionary:** [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md) and [DATA_DICTIONARY_COLUMNS.md](./DATA_DICTIONARY_COLUMNS.md)

---

## Next Steps

**To get all BLS data flowing:**

1. ✅ QCEW + JOLTS + LAUS — Already configured and automated
   ```bash
   python scrapers/qcew_adapter.py --region austin_tx
   python scrapers/bls_adapter.py --region austin_tx
   python -c "from backend.baseline import compute_baselines; compute_baselines('austin_tx')"
   ```

2. ⚠️ OEWS — Manual download required
   - Download from https://www.bls.gov/oes/tables.htm
   - Need an import script (priority medium)

3. ⚠️ CBP — Census API key required
   - Sign up at https://api.census.gov/data/key_signup.html
   - Takes ~24 hours
   - Set `export CBP_API_KEY=your_key_here`
   - Then: `python scrapers/cbp_adapter.py --region austin_tx`

Once all 5 tables are populated and baseline is computed, **scoring activates in full ground-truth mode** (no fallback to percentiles).
