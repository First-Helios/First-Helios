# Data Ingestion Summary & Next Steps

**Date:** 2026-03-22 | **Updated:** 2026-03-24
**Status 2026-03-24:** OEWS Austin MSA ingested (638 occupations in `oews_data`). Mobility graph loaded (781 SOC nodes, 256,831 transition edges, 18,981 occupation aliases). Revelio tables remain unpopulated — still the key gap. See README.md for current data state.

---

---

## What Was Done

### ✅ Analysis Complete

1. **Examined manually downloaded data**
   - OEWS: 8 national Excel files (571 MB total)
   - Revelio Labs: 7 CSV files with employment, hiring, salary, layoff data
   - Total: ~1.2M rows of historical labor data (2021-2026)

2. **Created analysis & assessment documents**
   - [MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md](./MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md) — Data characteristics & gaps
   - [DATA_INGESTION_SUMMARY.md](./DATA_INGESTION_SUMMARY.md) — This file (action items)

3. **Created ingestion scripts** (ready to use)
   - `scrapers/manual_ingest.py` — OEWS ingestion (placeholder; needs Austin MSA file)
   - `scrapers/revelio_ingest.py` — Revelio Labs preview script (dry-run ready)

4. **Updated documentation**
   - DATA_DICTIONARY_TABLES.md — Added Revelio tables + alternative stats schema
   - .env.example — Added API key templates

---

## What Still Needs to Happen

### Phase 1: Database Schema (30 min)

**Create 2 new tables in `backend/database.py`:**

```python
class RevelioLaborMetrics(Base):
    """Monthly employment, hiring, attrition by state/industry/occupation."""
    __tablename__ = "revelio_labor_metrics"

    id = Column(Integer, primary_key=True)
    month = Column(String, nullable=False)  # YYYY-MM
    state = Column(String, nullable=False, index=True)
    soc2d_code = Column(String, nullable=False)  # Occupation code
    soc2d_name = Column(String, nullable=True)
    naics2d_code = Column(String, nullable=False)  # Industry code
    naics2d_name = Column(String, nullable=True)
    count_nsa = Column(Integer, nullable=True)  # Not seasonally adjusted
    count_sa = Column(Integer, nullable=True)   # Seasonally adjusted
    hiring_rate_nsa = Column(Float, nullable=True)
    hiring_rate_sa = Column(Float, nullable=True)
    attrition_rate_nsa = Column(Float, nullable=True)
    attrition_rate_sa = Column(Float, nullable=True)
    salary_nsa = Column(Float, nullable=True)
    salary_sa = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('month', 'state', 'soc2d_code', 'naics2d_code'),
        Index('idx_month_state_industry', 'month', 'state', 'naics2d_code'),
    )


class RevelioLayoffNotices(Base):
    """WARN Act mass layoff filings."""
    __tablename__ = "revelio_layoff_notices"

    id = Column(Integer, primary_key=True)
    month = Column(String, nullable=False)  # YYYY-MM
    state = Column(String, nullable=False, index=True)
    naics2d_code = Column(String, nullable=True)
    num_employees_notified = Column(Float, nullable=True)
    num_notices_issued = Column(Float, nullable=True)
    num_employees_laidoff = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('month', 'state', 'naics2d_code'),
        Index('idx_month_state', 'month', 'state'),
    )
```

---

### Phase 2: OEWS Austin MSA Download (5 min)

**Current problem:** Downloaded files are national-only (area code 99). Need Austin MSA file.

**Action:**
```bash
# Download Austin-Round Rock-Georgetown MSA (area code 12420) file
# From: https://www.bls.gov/oes/current/oes_12420.htm
# Or direct URL: https://www.bls.gov/oes/2024/may/oes_12420.xlsx

# Save to: data/Manually_downloaded_data/OEWS_Austin_MSA_2024/

# Then run:
python scrapers/manual_ingest.py --oews --region austin_tx
```

**Expected result:** oews_data table populated with ~500 rows of Austin occupation wages

---

### Phase 3: Revelio Labs Ingestion (1 hour)

**Uncomment and complete `scrapers/revelio_ingest.py`:**

```python
def ingest_labor_metrics(session: Session) -> int:
    """Actually ingest employment data (currently dry-run only)."""

    emp_file = DATA_DIR / "Employment — February 2026/employment_all_granularities.csv"
    df = pd.read_csv(emp_file)

    inserted = 0
    for _, row in df.iterrows():
        record = RevelioLaborMetrics(
            month=row['month'],
            state=row['state'],
            soc2d_code=row['soc2d_code'],
            soc2d_name=row['soc2d_name'],
            naics2d_code=row['naics2d_code'],
            naics2d_name=row['naics2d_name'],
            count_nsa=int(row['count_nsa']),
            count_sa=int(row['count_sa']),
            fetched_at=datetime.utcnow(),
        )
        session.add(record)
        inserted += 1

    # Also load hiring/attrition/salary from other CSVs
    # ... [similar pattern for hiring_and_attrition.csv, salaries.csv]

    session.commit()
    logger.info(f"Ingested {inserted} labor metric records")
    return inserted
```

**Then:**
```bash
python scrapers/revelio_ingest.py --labor-metrics --all
python scrapers/revelio_ingest.py --layoffs
```

**Expected results:**
- revelio_labor_metrics: 1.18M rows (national) or ~23K rows (Texas)
- revelio_layoff_notices: 2,433 rows (national)

---

### Phase 4: Census API Key (24h + 10 min)

**Already done?** Check if CBP_API_KEY is in `.env`

**If not:**
```bash
# 1. Sign up: https://api.census.gov/data/key_signup.html
# 2. Copy key
# 3. Add to .env:
export CBP_API_KEY=your_key_here

# 4. Run:
python scrapers/cbp_adapter.py --region austin_tx
```

**Expected result:** cbp_data table populated with ~750 rows (25 ZIPs × 3 NAICS × 12+ years)

---

### Phase 5: Baseline & Scoring Activation (15 min)

**Once OEWS (Austin) + CBP are populated:**

```bash
python -c "from backend.baseline import compute_baselines; compute_baselines('austin_tx')"
python -c "from backend.scoring.engine import compute_all_scores; compute_all_scores('austin_tx')"
```

**Result:**
- labor_market_baseline table: 5 rows (one per NAICS code)
- scores table: Updated with ground-truth scores (instead of percentile fallback)

---

## Timeline & Dependencies

```
Phase 1: Schema (30 min) ─────────────────┐
                                          │
         ├─→ Phase 2: OEWS (5 min) ─────┤
         │                               │
         │   Phase 3: Revelio (1 hr) ────┼──→ Phase 5: Baseline (15 min)
         │                               │
         └─→ Phase 4: Census Key (24h + 10 min)
```

**Shortest path (1 hour):**
1. Create schema (30 min)
2. Run Revelio ingestion (30 min)
3. Verify data in DB

**Full activation (24+ hours):**
1. Schema (30 min)
2. Revelio + OEWS (1 hour)
3. Census key signup (24 hours)
4. Run all adapters (30 min)
5. Compute baselines (5 min)

---

## Data Readiness Status

### Before Ingestion

| Component | Status | Impact |
|---|---|---|
| QCEW | ✅ Populated | Denominator for demand_pressure |
| JOLTS | ✅ Populated | Denominator for churn_signal |
| LAUS | ✅ Populated | Regional unemployment context |
| OEWS (Austin) | ❌ Missing | wage_competitiveness stuck at fallback |
| CBP (Austin ZIPs) | ❌ Needs API key | Targeting disabled (ZIP-level) |
| Revelio Labor Metrics | 🟡 Downloaded, not ingested | Optional benchmark only |
| **Scoring Mode** | 🟡 Fallback (percentile) | Uses regional ranking, not economic denom. |

### After Phase 1-3 (Minimum Viable)

| Component | Status | Impact |
|---|---|---|
| QCEW | ✅ Populated | demand_pressure active |
| JOLTS | ✅ Populated | churn_signal active |
| LAUS | ✅ Populated | unemployment context |
| OEWS (Austin) | ✅ Populated | **wage_competitiveness ACTIVE** |
| CBP (Austin ZIPs) | ❌ Still missing | Targeting disabled (county-level only) |
| Revelio Labor Metrics | ✅ Ingested | Alternative benchmark available |
| **Scoring Mode** | ✅ Ground-truth | Uses real economic denominators |

### After Phase 1-5 (Full Activation)

| Component | Status | Impact |
|---|---|---|
| All ground-truth tables | ✅ Fully populated | **All scoring components active** |
| Revelio data | ✅ Available | Validation + alternative metrics |
| **Scoring Mode** | ✅ Ground-truth + Revelio validation | Maximum accuracy |
| **Targeting** | ✅ Full (ZIP-level) | Hyperlocal staffing stress detection |

---

## Quick Start (If You Want to Start Immediately)

### Minimal (verify ingestion works, 1 hour)

```bash
# 1. Create schema
# Edit backend/database.py, add RevelioLaborMetrics + RevelioLayoffNotices classes

# 2. Ingest Revelio
source .venv/bin/activate
python scrapers/revelio_ingest.py --labor-metrics --region Texas

# 3. Check DB
sqlite3 data/tracker.db "SELECT * FROM revelio_labor_metrics LIMIT 5;"
```

### Immediate (activate ground-truth scoring, 1.5 hours)

```bash
# 1. Create schema (as above)
# 2. Download Austin OEWS file manually
# 3. Update scrapers/manual_ingest.py to parse it
# 4. Run: python scrapers/manual_ingest.py --oews --region austin_tx
# 5. Compute baseline: python -c "from backend.baseline import compute_baselines; compute_baselines('austin_tx')"
# 6. Rescore: python -c "from backend.scoring.engine import compute_all_scores; compute_all_scores('austin_tx')"
```

### Complete (wait for Census key, 24+ hours)

```bash
# 1-6 above
# 7. Wait for Census API key approval (24 hours)
# 8. python scrapers/cbp_adapter.py --region austin_tx
# 9. Recompute baseline + rescore
```

---

## Files Created/Modified

**New files:**
- `scrapers/manual_ingest.py` — OEWS ingestion template
- `scrapers/revelio_ingest.py` — Revelio Labs ingestion (dry-run ready)
- `docs/MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md` — Detailed analysis
- `docs/DATA_INGESTION_SUMMARY.md` — This file

**Modified files:**
- `docs/DATA_DICTIONARY_TABLES.md` — Added Revelio tables + alternative schema
- `.env.example` — Added API key templates

**Still need to modify:**
- `backend/database.py` — Add 2 new tables
- `scrapers/manual_ingest.py` — Complete OEWS parser (if downloading Austin file)
- `scrapers/revelio_ingest.py` — Uncomment actual ingestion code

---

## Recommendations

### If you want to activate scoring in ground-truth mode TODAY:

1. ✅ Download Austin OEWS file (5 min)
2. ✅ Create database schema (30 min)
3. ✅ Ingest OEWS (10 min)
4. ✅ Compute baselines (1 min)
5. ✅ Rescore (1 min)

**Total: ~45 minutes to activate ground-truth scoring**

### If you want complete city "heartbeat" (all data):

1. Do all of the above
2. Sign up for Census API key (5 min now + 24h wait)
3. Ingest Revelio Labs (30 min)
4. When Census key arrives, run CBP adapter (10 min)
5. Final baseline recompute (1 min)

**Total: 1.5 hours active work + 24h waiting for Census key**

### Strategic ordering:

**Week 1:**
- Day 1: Download Austin OEWS + create schema + ingest
- Day 1: Ingest Revelio Labs
- Day 2-7: Wait for Census API key + any other improvements

**Week 2:**
- When Census key arrives: Ingest CBP
- Final validation + documentation

---

## See Also

- [MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md](./MANUALLY_DOWNLOADED_DATA_ASSESSMENT.md) — Detailed data analysis
- [DATA_DICTIONARY_TABLES.md](./DATA_DICTIONARY_TABLES.md) — Table specifications
- [BLS_GROUND_TRUTH_GUIDE.md](./BLS_GROUND_TRUTH_GUIDE.md) — Government data details
- `.env.example` — API key setup
