# Data Engineering Handoff — First-Helios

**Date:** 2026-03-22 | **Updated:** 2026-03-24 — PostgreSQL migration complete; `ingest_layer.py` is now the single employer write path
**Focus:** Data digest structure, validation logic, ingestion pipelines, multi-industry analysis
**Status:** ✅ PostgreSQL (helios DB) active; Career Pathfinder data loaded (781 SOCs, 256k transitions, 18,981 aliases)
**Related:** [DATABASE_DESIGN_BEST_PRACTICES.md](./DATABASE_DESIGN_BEST_PRACTICES.md), [CONFIG_GENERATION_SUMMARY.md](./CONFIG_GENERATION_SUMMARY.md)

---

## 1. Data Architecture Overview

The system uses a **6-layer data architecture** that separates concerns and enables quality checking at each boundary.

```
┌─────────────────────────────────────────────────────────────────┐
│ External Sources (15+ APIs, web scraping)                       │
│ BLS QCEW/JOLTS/OEWS/LAUS, Census, Indeed, Glassdoor, Reddit,  │
│ Google Maps, Yelp, Starbucks/Dutch Bros careers APIs           │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ (scrapers/[source]_adapter.py)
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: RAW                                                    │
│ Raw observations from each source, normalized to ScraperSignal │
│ Tables: signals, wage_index, qcew_data, cbp_data,              │
│         jolts_data, oews_data, laus_data, chain_locations,     │
│         local_employers, brand_groups                          │
│                                                                  │
│ Employer write path: backend/normalizer.py → backend/ingest_layer.py  │
│ Signal write path:   backend/ingest.py (ingest_signals)        │
│                                                                  │
│ Validation Rules (in backend/ingest.py / ingest_layer.py):     │
│  ✓ Schema: columns exist with correct types                    │
│  ✓ Nullability: NOT NULL columns enforced                      │
│  ✓ Range: numeric values within valid_range_min/max            │
│  ✓ Uniqueness: store_num must exist in stores table            │
│  ✓ Freshness: value observed_at must be recent (within 30 days)│
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ (backend/ingest.py / ingest_layer.py)
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 2: SIGNALS (de-duplicated)                               │
│ Deduplicated signals with time-series integrity checks         │
│ Same tables as Layer 1 but marked as "cleaned"                │
│                                                                  │
│ Validation Rules (in backend/ingest.py):                       │
│  ✓ Time-monotonicity: observed_at increases within 48 hours    │
│  ✓ Duplicate detection: same (store, signal_type, value) → skip│
│  ✓ Outlier detection: 3σ from rolling 30-day mean → flag       │
│  ✓ Staleness: must have signal in last 7 days                  │
│  ✓ Completeness: key stores must have min 1 signal/month       │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ (backend/baseline.py compute_*)
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 3: DERIVED                                               │
│ Computed aggregates from Layers 1-2                            │
│ Tables: labor_market_baseline (combines QCEW+JOLTS+OEWS+LAUS) │
│                                                                  │
│ Validation Rules (in backend/baseline.py):                     │
│  ✓ Formula audit: baseline = (qcew_est+jolts_sep+oews_wage)/3  │
│  ✓ Referential integrity: all foreign keys exist              │
│  ✓ No unexpected nulls: all key columns populated              │
│  ✓ Consistency check: baseline[t] ≈ baseline[t-1] ±10%        │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ (backend/scoring/engine.py compute_scores)
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 4: BUSINESS LOGIC                                        │
│ Decision inputs (scores, targeting)                            │
│ Tables: scores, wage_index, snapshots                          │
│                                                                  │
│ Validation Rules (in backend/scoring/engine.py):               │
│  ✓ Score bounds: all sub-scores 0-100, composite 0-100         │
│  ✓ No nulls: critical fields populated (store_num, score_val)  │
│  ✓ Percentile ranks: must be 1-100, no duplicates              │
│  ✓ Weight distribution: sum to 100%                            │
│  ✓ Consistency: score unchanged if inputs unchanged            │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ (server.py /api/* endpoints)
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 5: REFERENCE (lookup tables)                             │
│ Master data (brands, industries, regions, categories)          │
│ Tables: ref_brands, ref_industry, ref_regions, ref_category_map│
│                                                                  │
│ Validation Rules (in backend/models/reference.py):             │
│  ✓ Uniqueness: no duplicate brand_id, industry_id, etc.        │
│  ✓ Referential integrity: no orphaned foreign keys             │
│  ✓ No unexpected changes: reference data is nearly static      │
│  ✓ Coverage: all stores have valid brand_id and region_id      │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ (SYSTEM INTELLIGENCE)
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 6: METADATA                                              │
│ System intelligence (audit trail, data lineage)                │
│ Tables: meta_table_catalog, meta_column_catalog,               │
│         meta_data_lineage, meta_job_runs, meta_api_calls       │
│                                                                  │
│ Validation Rules (in scripts/populate_metadata.py):            │
│  ✓ All tables documented: 100% meta_table_catalog coverage     │
│  ✓ All lineage tracked: every table has at least 1 upstream    │
│  ✓ Job runs logged: every scraper write logged to meta_job_runs│
│  ✓ API calls tracked: rate limits monitored in meta_api_calls  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1.5 Configuration: Data-Driven Approach

**IMPORTANT CHANGE (2026-03-22):** The system now supports **multi-industry analysis** instead of food-service-only.

### Why Configuration Generation Matters

**Problem:** Maintaining `config/chains.yaml` manually means config drifts from data.

**Solution:** Generate config from actual OEWS data using:
```bash
python scripts/generate_config_from_oews.py --output config/chains.yaml
```

This script:
1. Queries Austin OEWS database (638 occupations, 22 industry groups)
2. Extracts actual average wages per industry
3. Generates chains.yaml with all industries
4. Makes config idempotent (run again, get same output)

### Current Configuration

```yaml
target_industries: all  # Multi-industry analysis

industries:
  soc_11: "Management ($65.68/hr, 36 occupations)"
  soc_13: "Business & Finance ($37.19/hr, 29 occupations)"
  soc_15: "IT & Computer ($58.86/hr, 20 occupations)"
  soc_25: "Education ($25.95/hr, 56 occupations)"
  soc_29: "Healthcare ($18.94/hr, 52 occupations)"
  soc_35: "Food Service ($19.20/hr, 17 occupations)"  # ← Just one of 22
  # ... 16 more industries ...

qcew:
  fetch_all_industries: true  # ← All NAICS codes, not just 72

cbp:
  fetch_all_industries: true  # ← All ZIP/NAICS, not just 722515

oews:
  fetch_all_occupations: true  # ← All 638 occupations, not just SOC 35
```

### What This Means for Data Engineers

- **Adding industries:** Just ingest their OEWS data, regenerate config
- **Changing wages:** Config automatically reflects current OEWS wages
- **Adding regions:** Run script against that region's OEWS data
- **No manual editing:** Config is derived from data, not maintained separately

---

## 2. Layer 1: RAW Data Ingestion

### 2.1 Input Format: ScraperSignal

All external data is normalized to this dataclass (in `scrapers/base.py`):

```python
@dataclass
class ScraperSignal:
    source: str              # "starbucks_careers", "bls_qcew", "reddit", etc.
    signal_type: str         # "job_posting", "wage_data", "sentiment", "establishment_count"
    value: Any               # The actual data (int, float, str)
    observed_at: datetime    # When the source says it happened
    fetched_at: datetime     # When we retrieved it
    store_num: str           # Links to stores.store_num
    confidence: float        # 0.0-1.0 how confident we are
    raw_data: dict           # Full response from API (for debugging)
```

### 2.2 Sources and How They Map

| Source | Adapter | Signal Type | Value Type | Frequency | Coverage |
|--------|---------|-------------|-----------|-----------|----------|
| Starbucks Careers | `careers_api.py` | `job_posting` | count | daily | Food service chains |
| Indeed/Glassdoor | `jobspy_adapter.py` | `job_posting` | count | daily | **All industries** |
| Reddit | `reddit_adapter.py` | `sentiment_mention` | score -5 to +5 | daily | All industries |
| Google Maps | `reviews_adapter.py` | `rating` + `review_count` | float + int | daily | **All industries** |
| BLS QCEW | `qcew_adapter.py` | `establishment_count` | int | monthly | **All NAICS codes** (was NAICS 72 only) |
| BLS JOLTS | `bls_adapter.py` | `quits_rate` | float | monthly | **All industries** (was NAICS 72 only) |
| BLS OEWS | `bls_adapter.py` | `wage_percentile` | float | annual | **All 638 occupations** (was SOC 35 only) |
| BLS LAUS | `bls_adapter.py` | `unemployment_rate` | float | monthly | All areas |
| Census CBP | `cbp_adapter.py` | `establishment_count` | int | annual | **All NAICS codes, all ZIPs** (was NAICS 722515 only) |

**KEY CHANGE:** QCEW, OEWS, CBP now ingest **all industries**, not just food service. This enables:
- Comparative industry analysis (which sectors have highest staffing stress?)
- Multi-sector labor market insights
- Community economic development beyond food service

### 2.3 Raw Data Validation (backend/ingest.py)

```python
def validate_signal(signal: ScraperSignal) -> tuple[bool, str]:
    """
    Returns (is_valid, error_message)
    """
    # 1. Schema validation
    if not signal.store_num:
        return False, "store_num required"

    # 2. Type validation
    if signal.signal_type not in VALID_SIGNAL_TYPES:
        return False, f"Unknown signal type: {signal.signal_type}"

    # 3. Range validation (from meta_column_catalog.valid_range_min/max)
    col_meta = get_column_metadata(table='signals', column='value')
    if col_meta.valid_range_min and signal.value < col_meta.valid_range_min:
        return False, f"Value {signal.value} below min {col_meta.valid_range_min}"

    # 4. Freshness validation (from meta_column_catalog.sla_freshness_days)
    days_old = (datetime.utcnow() - signal.observed_at).days
    if days_old > col_meta.sla_freshness_days:
        return False, f"Signal {days_old} days old, SLA is {col_meta.sla_freshness_days}"

    # 5. Referential integrity (store must exist)
    if not session.query(Store).filter_by(store_num=signal.store_num).first():
        return False, f"store_num {signal.store_num} not found"

    return True, ""
```

### 2.4 Storing Raw Data

When a signal passes validation:

```python
def ingest_signal(signal: ScraperSignal, session):
    """Store validated signal, log job run"""

    # 1. Create Signal row
    row = Signal(
        store_num=signal.store_num,
        source=signal.source,
        signal_type=signal.signal_type,
        value=signal.value,
        observed_at=signal.observed_at,
        fetched_at=signal.fetched_at,
        confidence=signal.confidence,
        raw_data=signal.raw_data,  # Full JSON for debugging
        created_at=datetime.utcnow(),
    )
    session.add(row)

    # 2. Log to meta_job_runs (for audit trail)
    job_run.rows_inserted += 1

    # 3. Commit
    session.commit()
```

---

## 3. Layer 2: Signal Deduplication & Time-Series Validation

### 3.1 Duplicate Detection

After ingesting a batch of signals, deduplicate:

```python
def deduplicate_signals(store_num: str, signal_type: str, observed_at: date):
    """
    Group signals by (store_num, signal_type, observed_at).
    If >1 exists, keep the one with highest confidence.
    """
    duplicates = session.query(Signal).filter(
        Signal.store_num == store_num,
        Signal.signal_type == signal_type,
        Signal.observed_at.cast(Date) == observed_at,
    ).all()

    if len(duplicates) > 1:
        # Keep highest confidence, delete rest
        best = max(duplicates, key=lambda s: s.confidence)
        for dup in duplicates:
            if dup.id != best.id:
                session.delete(dup)
        session.commit()
```

### 3.2 Time-Series Integrity

For each (store_num, signal_type), check:

```python
def validate_signal_timeseries(store_num: str, signal_type: str):
    """
    Check that signals for this (store, type) are monotonically increasing in time.
    Allow 48-hour gaps (weekends, API downtime).
    Flag if >7 days without a signal.
    """
    signals = session.query(Signal).filter(
        Signal.store_num == store_num,
        Signal.signal_type == signal_type,
    ).order_by(Signal.observed_at).all()

    for i in range(1, len(signals)):
        prev = signals[i-1]
        curr = signals[i]
        gap = (curr.observed_at - prev.observed_at).days

        # Check for backfill (current timestamp before previous)
        if curr.observed_at < prev.observed_at:
            logger.warning(f"Backfill detected: {store_num} {signal_type}")

        # Check for excessive gaps (>7 days)
        if gap > 7:
            logger.warning(f"Stale data: {store_num} {signal_type} gap {gap} days")
            # Mark with staleness flag in signals table
            curr.data_quality_flag = 'stale'
```

### 3.3 Outlier Detection

For numeric signals, flag values >3σ from rolling mean:

```python
def detect_outliers(store_num: str, signal_type: str):
    """
    Use rolling 30-day statistics to flag anomalies.
    """
    signals = session.query(Signal.value).filter(
        Signal.store_num == store_num,
        Signal.signal_type == signal_type,
        Signal.created_at > datetime.utcnow() - timedelta(days=30),
    ).all()

    if len(signals) < 3:
        return  # Not enough data

    values = [s.value for s in signals if isinstance(s.value, (int, float))]
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)

    for signal in signals:
        if abs(signal.value - mean) > 3 * stdev:
            signal.data_quality_flag = 'outlier'
            logger.warning(f"Outlier: {store_num} {signal_type} = {signal.value} (mean {mean})")
```

---

## 4. Layer 3: Derived Tables (labor_market_baseline)

### 4.1 Purpose

**labor_market_baseline** is the foundation for all scoring. It combines 4 BLS ground-truth sources into a single authoritative labor market snapshot.

### 4.2 Composition

| Input Table | Column | Meaning | Frequency |
|-------------|--------|---------|-----------|
| qcew_data | establishments | Count of establishments **by industry** (county-level) | Quarterly, 6mo lag |
| jolts_data | quits_rate | % of workers quitting monthly **by industry** | Monthly, 2mo lag |
| oews_data | wage_percentiles | Occupation wages **across all industries** (MSA-level) | Annual |
| laus_data | unemployment_rate | % unemployment (county-level) | Monthly, 2mo lag |

**MULTI-INDUSTRY NOTE:** Previously these were filtered to food service only. Now:
- **QCEW** fetches all industries (NAICS codes), not just 72
- **JOLTS** fetches all industries, not just food service
- **OEWS** has 638 occupations loaded (all industries), not just SOC 35
- Baseline can be computed per-industry for comparative analysis

### 4.3 Computation (backend/baseline.py)

```python
def compute_labor_market_baseline(period: str):
    """
    Combine QCEW+JOLTS+OEWS+LAUS into single baseline row.
    Period format: "2026-Q1" or "2026-01"
    """

    baseline = LaborMarketBaseline()
    baseline.period = period
    baseline.computed_at = datetime.utcnow()

    # Get QCEW data (quarterly establishments)
    qcew = session.query(QcewData).filter(
        QcewData.period == period,
        QcewData.area_fips == '48439',  # Travis County
    ).first()
    if qcew:
        baseline.qcew_establishments = qcew.establishments
        baseline.qcew_avg_weekly_wage = qcew.avg_weekly_wage

    # Get JOLTS data (national quits rate by industry)
    jolts = session.query(JoltsData).filter(
        JoltsData.period == period,
        JoltsData.industry_code == '7225',  # Food service
    ).first()
    if jolts:
        baseline.jolts_quits_rate = jolts.quits_rate
        baseline.jolts_level = jolts.level_of_employment

    # Get OEWS data (MSA occupation wages)
    oews = session.query(OewsData).filter(
        OewsData.area_code == '12420',  # Austin MSA
        OewsData.occupation_code == '35-0000',  # Food service
    ).first()
    if oews:
        baseline.oews_wage_median = oews.wage_median
        baseline.oews_wage_75th = oews.wage_75th_percentile

    # Get LAUS data (county unemployment)
    laus = session.query(LausData).filter(
        LausData.period == period,
        LausData.county_fips == '48439',  # Travis County
    ).first()
    if laus:
        baseline.laus_unemployment_rate = laus.unemployment_rate

    # Compute composite baseline (simple average)
    baseline.composite_score = (
        (baseline.qcew_establishments or 0) +
        (baseline.jolts_quits_rate or 0) * 100 +
        (baseline.oews_wage_75th or 0)
    ) / 3

    session.add(baseline)
    session.commit()
```

### 4.4 Validation Rules

```python
def validate_baseline(baseline: LaborMarketBaseline) -> tuple[bool, str]:
    """Check baseline integrity"""

    # Check all required fields are populated
    if not baseline.qcew_establishments:
        return False, f"QCEW missing for {baseline.period}"

    if baseline.composite_score < 0:
        return False, f"Negative composite score: {baseline.composite_score}"

    # Check consistency with previous period (allow ±10% drift)
    prev_baseline = session.query(LaborMarketBaseline).filter(
        LaborMarketBaseline.period < baseline.period,
    ).order_by(LaborMarketBaseline.period.desc()).first()

    if prev_baseline:
        drift = abs(
            (baseline.composite_score - prev_baseline.composite_score) /
            prev_baseline.composite_score
        )
        if drift > 0.10:
            logger.warning(
                f"Baseline drift {drift:.1%} from {prev_baseline.period} to {baseline.period}"
            )

    return True, ""
```

---

## 5. Layer 4: Scoring (scores table)

### 5.1 Score Computation (backend/scoring/engine.py)

Every time a signal arrives, recompute all scores for that store:

```python
def compute_store_scores(store_num: str):
    """
    Composite score = w₁·demand + w₂·wage_gap + w₃·churn + w₄·sentiment
    """
    store = session.query(Store).filter_by(store_num=store_num).first()

    # 1. DEMAND PRESSURE (from job postings)
    demand_score = compute_demand_pressure(store_num)  # 0-100

    # 2. WAGE COMPETITIVENESS (from local vs. chain pay)
    wage_score = compute_wage_gap(store_num)  # 0-100

    # 3. CHURN SIGNAL (from JOLTS vs. job posting velocity)
    churn_score = compute_churn_signal(store_num)  # 0-100

    # 4. QUALITATIVE (Reddit + Google sentiment)
    sentiment_score = compute_sentiment(store_num)  # 0-100

    # Get weights from config (can redistribute if data missing)
    weights = get_scoring_weights()  # {demand: 0.35, wage: 0.25, churn: 0.25, sentiment: 0.15}

    # Handle missing data: redistribute weights
    available_scores = {
        'demand': demand_score if demand_score is not None else None,
        'wage': wage_score if wage_score is not None else None,
        'churn': churn_score if churn_score is not None else None,
        'sentiment': sentiment_score if sentiment_score is not None else None,
    }
    available_weights = sum(
        weights[k] for k, v in available_scores.items() if v is not None
    )
    if available_weights > 0:
        weights = {
            k: weights[k] / available_weights if available_scores[k] is not None else 0
            for k in weights
        }

    # Composite
    composite = (
        (weights.get('demand', 0) * (demand_score or 0)) +
        (weights.get('wage', 0) * (wage_score or 0)) +
        (weights.get('churn', 0) * (churn_score or 0)) +
        (weights.get('sentiment', 0) * (sentiment_score or 0))
    )

    # Seasonal adjustment (optional)
    if is_seasonal_adjustment_enabled():
        seasonal_index = get_seasonal_index(current_month=datetime.now().month)
        composite = composite / seasonal_index

    # Store result
    score = Score(
        store_num=store_num,
        composite_score=composite,
        demand_pressure_score=demand_score,
        wage_competitiveness_score=wage_score,
        churn_signal_score=churn_score,
        sentiment_score=sentiment_score,
        percentile_rank=compute_percentile_rank(store_num, composite),
        computed_at=datetime.utcnow(),
    )

    session.add(score)
    session.commit()

    # Log to metadata
    log_score_computation(store_num, composite, demand_score, wage_score, churn_score, sentiment_score)
```

### 5.2 Score Validation

```python
def validate_scores():
    """Check score integrity"""

    # All scores should be 0-100 or NULL
    bad_scores = session.query(Score).filter(
        (Score.composite_score < 0) | (Score.composite_score > 100)
    ).all()
    if bad_scores:
        logger.error(f"Found {len(bad_scores)} out-of-range scores")

    # Percentile ranks should be 1-100 with no gaps
    ranks = [s.percentile_rank for s in session.query(Score).all() if s.percentile_rank]
    if len(ranks) != len(set(ranks)):
        logger.warning("Duplicate percentile ranks detected")

    # Score should not change if inputs unchanged
    current_score = get_score(store_num='12345')
    previous_score = get_score_history(store_num='12345', n=2)[0]  # 2nd most recent
    if current_score == previous_score:
        logger.debug("Score unchanged (as expected)")
    else:
        logger.debug(f"Score changed from {previous_score} to {current_score}")
```

---

## 6. Layer 5: Reference Data

### 6.1 Reference Tables

These are lookup tables that rarely change:

| Table | Rows | Update Frequency | Example |
|-------|------|------------------|---------|
| ref_brands | 6 | Quarterly (when new brands added) | Starbucks, Dutch Bros, etc. |
| ref_industry | 11 | Annual (when industry taxonomy changes) | Food service, Retail, etc. |
| ref_regions | 1 | Per new geographic target | Austin, TX |
| ref_category_map | 168 | Annual | Google Maps category → industry mapping |

### 6.2 Validation Rules

```python
def validate_reference_data():
    """Check reference integrity"""

    # 1. No duplicate brand IDs
    brands = session.query(RefBrand).all()
    brand_ids = [b.brand_id for b in brands]
    if len(brand_ids) != len(set(brand_ids)):
        logger.error("Duplicate brand IDs found")

    # 2. No orphaned foreign keys (all stores have valid brand_id)
    orphans = session.query(Store).filter(
        ~Store.brand_id.in_(session.query(RefBrand.brand_id))
    ).all()
    if orphans:
        logger.error(f"Found {len(orphans)} stores with invalid brand_id")

    # 3. All categories map to valid industries
    bad_maps = session.query(RefCategoryMap).filter(
        ~RefCategoryMap.industry_id.in_(session.query(RefIndustry.industry_id))
    ).all()
    if bad_maps:
        logger.error(f"Found {len(bad_maps)} unmapped categories")

    # 4. Reference data stable (no unexpected changes)
    # Store checksums in meta_table_catalog
    current_checksum = hash_table('ref_brands')
    previous_checksum = get_table_checksum('ref_brands', days_ago=7)
    if current_checksum != previous_checksum:
        logger.warning("ref_brands changed in last 7 days")
```

---

## 7. Layer 6: Metadata Tables

### 7.1 Purpose

Metadata tables track the system itself, enabling humans to understand what data has been built and how it flows.

### 7.2 Five Metadata Tables

| Table | What It Answers | Example Query |
|-------|---|---|
| meta_table_catalog | What tables exist and why? | `SELECT table_name, purpose, sla_freshness_days FROM meta_table_catalog WHERE layer='raw'` |
| meta_column_catalog | What does each column mean? | `SELECT column_name, description, valid_range_min, valid_range_max FROM meta_column_catalog WHERE table_name='scores'` |
| meta_data_lineage | How does data flow from source to output? | `SELECT * FROM meta_data_lineage WHERE source_table='qcew_data'` |
| meta_job_runs | When did scrapers run and did they succeed? | `SELECT job_id, COUNT(*) as runs, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes FROM meta_job_runs GROUP BY job_id` |
| meta_api_calls | What are the API health metrics? | `SELECT api_source, AVG(latency_ms) as avg_latency, SUM(CASE WHEN success=false THEN 1 ELSE 0 END) as failures FROM meta_api_calls GROUP BY api_source` |

### 7.3 Populating Metadata

Every time an ingestion script runs, it must log:

```python
def log_scraper_run(job_id: str, rows_processed: int, rows_inserted: int, error: str = None):
    """Log job execution to metadata system"""

    job_run = MetaJobRun(
        job_id=job_id,
        job_type='scraper',
        status='success' if not error else 'failed',
        rows_processed=rows_processed,
        rows_inserted=rows_inserted,
        rows_skipped=rows_processed - rows_inserted,
        error_message=error,
        started_at=job_start_time,
        completed_at=datetime.utcnow(),
        duration_seconds=(datetime.utcnow() - job_start_time).total_seconds(),
        triggered_by='scheduler',
    )
    session.add(job_run)

    # Also log any API calls made
    for api_call in collect_api_calls():
        meta_api_call = MetaApiCall(
            api_source='bls_v2',
            endpoint='/timeseries/data',
            status_code=api_call.status_code,
            success=api_call.status_code == 200,
            rows_returned=api_call.row_count,
            latency_ms=api_call.latency_ms,
            error_message=api_call.error if not api_call.success else None,
            rate_limit_remaining=api_call.rate_limit_remaining,
            job_run_id=job_run.id,
        )
        session.add(meta_api_call)

    session.commit()
```

---

## 8. Common Debugging Scenarios

### 8.1 "A table is stale — what happened?"

```bash
# 1. Check the health dashboard
python scripts/system_health_dashboard.py

# 2. Query job run history
psql -d helios -c "
SELECT job_id, status, error_message, completed_at
FROM meta_job_runs
WHERE job_id = 'qcew_fetch'
ORDER BY completed_at DESC
LIMIT 10;
"

# 3. Check for recent API errors
psql -d helios -c "
SELECT api_source, COUNT(*) as errors, MAX(request_timestamp) as last_error
FROM meta_api_calls
WHERE success = 0
GROUP BY api_source
ORDER BY last_error DESC;
"

# 4. If API is fine, check network
curl -I https://api.bls.gov/publicAPI/v2/timeseries/data

# 5. If network is fine, manually run the job
python scrapers/qcew_adapter.py --verbose

# 6. If manual run fails, debug the adapter
# Add print statements, check that API_KEY env vars are set, etc.
```

### 8.2 "I see strange scores — validation failed"

```bash
# 1. Check score bounds
psql -d helios -c "
SELECT store_num, composite_score
FROM scores
WHERE composite_score < 0 OR composite_score > 100;
"

# 2. Check for nulls in key columns
psql -d helios -c "
SELECT COUNT(*) as null_count
FROM scores
WHERE store_num IS NULL OR composite_score IS NULL;
"

# 3. Check percentile ranks for gaps
psql -d helios -c "
SELECT percentile_rank, COUNT(*) as stores
FROM scores
GROUP BY percentile_rank
HAVING COUNT(*) > 1;
"

# 4. Check what inputs fed this score
psql -d helios -c "
SELECT * FROM meta_data_lineage
WHERE target_table = 'scores'
ORDER BY source_table;
"

# 5. Trace the lineage back to raw data
# Check: did the upstream data validation pass?
```

### 8.3 "Data looks duplicated — what went wrong?"

```bash
# 1. Check for exact duplicates
psql -d helios -c "
SELECT store_num, signal_type, observed_at, COUNT(*) as count
FROM signals
GROUP BY store_num, signal_type, observed_at
HAVING COUNT(*) > 1
LIMIT 20;
"

# 2. Run deduplication
python backend/ingest.py --deduplicate

# 3. Check confidence scores (should keep highest)
psql -d helios -c "
SELECT store_num, signal_type, observed_at, confidence
FROM signals
WHERE (store_num, signal_type, observed_at) IN (
  SELECT store_num, signal_type, observed_at
  FROM signals
  GROUP BY store_num, signal_type, observed_at
  HAVING COUNT(*) > 1
)
ORDER BY store_num, signal_type, observed_at;
"
```

### 8.4 "A signal is stale — staleness check failed"

```bash
# 1. Check gap between signals for specific store/type
psql -d helios -c "
SELECT store_num, signal_type, MAX(observed_at) as last_signal
FROM signals
GROUP BY store_num, signal_type
HAVING (julianday('now') - julianday(MAX(observed_at))) > 7;
"

# 2. Check data_quality_flag
psql -d helios -c "
SELECT store_num, signal_type, COUNT(*) as stale_signals
FROM signals
WHERE data_quality_flag = 'stale'
GROUP BY store_num, signal_type;
"

# 3. Manually trigger that scraper
# If it's a BLS fetch, check their data release schedule
# If it's Glassdoor/Indeed, check JobSpy is still working
# If it's Reddit, check PRAW credentials

# 4. Check when the source last updated
curl https://api.bls.gov/publicAPI/v2/timeseries/data \
  -d '{"seriesid":["QCEW..."], "startyear":2026, "endyear":2026}' \
  | jq '.Results.series[0].data[0]'
```

### 8.5 "Baseline computation failed"

```bash
# 1. Check all required inputs exist
psql -d helios -c "
SELECT
  CASE WHEN (SELECT COUNT(*) FROM qcew_data WHERE period = '2026-Q1') > 0 THEN '✓ QCEW' ELSE '✗ QCEW missing' END,
  CASE WHEN (SELECT COUNT(*) FROM jolts_data WHERE period LIKE '2026-01') > 0 THEN '✓ JOLTS' ELSE '✗ JOLTS missing' END,
  CASE WHEN (SELECT COUNT(*) FROM oews_data WHERE year = 2025) > 0 THEN '✓ OEWS' ELSE '✗ OEWS missing' END,
  CASE WHEN (SELECT COUNT(*) FROM laus_data WHERE period LIKE '2026-01') > 0 THEN '✓ LAUS' ELSE '✗ LAUS missing' END;
"

# 2. Check baseline computation result
psql -d helios -c "
SELECT period, composite_score, qcew_establishments, jolts_quits_rate, oews_wage_75th, laus_unemployment_rate
FROM labor_market_baseline
ORDER BY period DESC
LIMIT 5;
"

# 3. Check for consistency drift
psql -d helios -c "
SELECT period,
       composite_score,
       LAG(composite_score) OVER (ORDER BY period) as prev_score,
       ROUND(100.0 * (composite_score - LAG(composite_score) OVER (ORDER BY period)) / LAG(composite_score) OVER (ORDER BY period), 1) as pct_change
FROM labor_market_baseline
ORDER BY period DESC;
"

# 4. If drift > 10%, check what changed in source tables
psql -d helios -c "SELECT * FROM qcew_data WHERE period = '2026-Q1' LIMIT 5;"
```

---

## 9. Integration Points

### 9.1 How Scrapers Feed the System

```python
# In any scraper (e.g., scrapers/qcew_adapter.py):

def fetch_and_ingest(config):
    # 1. Fetch from external API
    api_response = requests.get(api_url)

    # 2. Normalize to ScraperSignal
    signals = []
    for record in api_response.json():
        signal = ScraperSignal(
            source='bls_qcew',
            signal_type='establishment_count',
            value=record['establishments'],
            observed_at=parse_date(record['period']),
            fetched_at=datetime.utcnow(),
            store_num=record['county_code'],  # Actually county, but same pattern
            confidence=0.95,  # BLS is authoritative
            raw_data=record,
        )
        signals.append(signal)

    # 3. Ingest through pipeline
    engine = init_db()
    session = get_session(engine)

    for signal in signals:
        is_valid, error = validate_signal(signal)
        if is_valid:
            ingest_signal(signal, session)
        else:
            logger.warning(f"Invalid signal: {error}")

    # 4. Log job execution
    log_scraper_run('qcew_fetch', len(signals), session.query(QcewData).count(), error=None)
```

### 9.2 How Scores Feed the API

```python
# In server.py:

@app.route('/api/scores')
def get_scores():
    """Fetch latest scores for all stores"""
    session = get_session()

    # Get latest score for each store
    scores = session.query(Score).distinct(Score.store_num).order_by(
        Score.store_num, Score.computed_at.desc()
    ).all()

    return {
        'generated_at': datetime.utcnow().isoformat(),
        'scores': [
            {
                'store_num': score.store_num,
                'composite_score': score.composite_score,
                'percentile_rank': score.percentile_rank,
                'demand_pressure': score.demand_pressure_score,
                'wage_gap': score.wage_competitiveness_score,
                'churn_signal': score.churn_signal_score,
                'sentiment': score.sentiment_score,
                'computed_at': score.computed_at.isoformat(),
            }
            for score in scores
        ]
    }
```

### 9.3 How Metadata System Gets Populated

Every one of the above should trigger metadata logging:

```python
def wrapper_for_any_data_operation(operation_name: str):
    """Wrap any data operation to log to metadata"""
    job_start = datetime.utcnow()
    try:
        result = perform_operation()
        log_job_run(
            job_id=operation_name,
            status='success',
            rows_processed=result.row_count,
            rows_inserted=result.inserted_count,
        )
        return result
    except Exception as e:
        log_job_run(
            job_id=operation_name,
            status='failed',
            rows_processed=0,
            rows_inserted=0,
            error_message=str(e),
        )
        raise
```

---

## 10. Data Flow Diagram (Text)

```
BLS QCEW API (quarterly)
    ↓
scrapers/qcew_adapter.py
    ↓ (ScraperSignal)
validate_signal() [RAW validation]
    ↓
ingest_signal() → qcew_data table [LAYER 1: RAW]
    ↓
deduplicate_signals() [LAYER 2: SIGNALS]
    ↓
validate_signal_timeseries() ← checks for gaps, backfills, outliers
    ↓
backend/baseline.py
    ↓ (combines QCEW+JOLTS+OEWS+LAUS)
compute_labor_market_baseline() [LAYER 3: DERIVED]
    ↓
labor_market_baseline table
    ↓
backend/scoring/engine.py
    ↓ (uses baseline as input)
compute_store_scores() [LAYER 4: BUSINESS LOGIC]
    ↓
scores table
    ↓
server.py /api/scores
    ↓
frontend/js/app.js
    ↓
Leaflet map (user sees colored pins)
```

---

## 11. Running a Complete Data Validation Cycle

```bash
#!/bin/bash
# Complete validation cycle (run weekly)

set -e

echo "=== LAYER 1: Raw Data Validation ==="
python -c "from backend.ingest import validate_all_signals; validate_all_signals()"

echo "=== LAYER 2: Signal Deduplication & Time-Series ==="
python -c "from backend.ingest import deduplicate_signals, validate_timeseries; \
           deduplicate_signals(); validate_timeseries()"

echo "=== LAYER 3: Baseline Computation ==="
python -c "from backend.baseline import compute_all_baselines; compute_all_baselines()"

echo "=== LAYER 4: Scoring ==="
python -c "from backend.scoring.engine import compute_all_scores; compute_all_scores()"

echo "=== LAYER 5: Reference Data Check ==="
python -c "from backend.models.reference import validate_reference_data; validate_reference_data()"

echo "=== LAYER 6: Metadata & Health Check ==="
python scripts/system_health_dashboard.py

echo "✅ All validations passed"
```

---

## 12. Key Files Reference

| File | Purpose | When to Read |
|------|---------|--------------|
| `backend/ingest.py` | Raw → Signals layer validation | Troubleshooting data quality |
| `backend/baseline.py` | Signals → Derived layer computation | Baseline issues |
| `backend/scoring/engine.py` | Derived → Business Logic layer | Score issues |
| `backend/database.py` | Table definitions + metadata | Schema questions |
| `backend/metadata.py` | Metadata table models | Audit trail |
| `scripts/populate_metadata.py` | Populates metadata system | Understanding all tables |
| `scripts/system_health_dashboard.py` | Weekly health check | Data staleness |
| `scrapers/base.py` | ScraperSignal dataclass | Adding new sources |
| `config/loader.py` | Configuration access | Tuning parameters |
| **`scripts/generate_config_from_oews.py`** | **Generate config from OEWS data** | **Regenerating config with new industries** |
| `config/chains.yaml` | Configuration (auto-generated) | Understanding available industries |

---

## 12.5 Configuration Generation (Data-Driven Approach)

### The Philosophy

> **Don't maintain config separately from data. Generate config from data.**

Instead of manually editing `config/chains.yaml`, generate it from the Austin-Round Rock-San Marcos, TX MSA OEWS database:

```bash
python scripts/generate_config_from_oews.py --output config/chains.yaml
```

### Data Source and Scope

- **File:** `data/reference/bls/Occupational Employment and Wage Statistics- Area: Austin-Round Rock-San Marcos, TX.ods`
- **Coverage:** Austin-Round Rock-San Marcos, TX MSA **only** (BLS area code 12420)
- **Not:** Texas statewide, national, or any other region

### Required Environment Variables

| Env Var | Purpose | Where Set |
|---------|---------|-----------|
| `CBP_API_KEY` | Census Bureau API key for County Business Patterns data | `.env` |
| `BLS_API_KEY` | BLS v2 API key for QCEW/JOLTS/OEWS/LAUS | `.env` |

These are loaded automatically via `config/loader.py` — no code changes needed to use them.

### How It Works

1. **Queries OEWS database** for all 638 Austin-Round Rock-San Marcos, TX MSA occupations (area code 12420)
2. **Groups by industry** (22 SOC groups)
3. **Extracts actual wages** per industry from database
4. **Generates YAML** with all industries, wages, and search terms
5. **Preserves chains** (Starbucks, Dutch Bros) from existing config

### What Gets Generated

```yaml
target_industries: all  # Multi-industry analysis enabled

industries:
  soc_11:
    display_name: "Management"
    avg_wage_hourly: 65.68  # From actual OEWS data
    occupations_in_austin: 36

qcew:
  fetch_all_industries: true  # Fetch ALL NAICS, not just 72

cbp:
  fetch_all_industries: true  # Fetch ALL NAICS/ZIP combinations

oews:
  fetch_all_occupations: true  # Fetch all 638 occupations
```

### Why This Matters

- **Single source of truth:** OEWS database
- **Reproducible:** Run script, get identical config
- **No drift:** Config always matches data
- **Scalable:** Add new regions by running script
- **Multi-industry ready:** All 22 industries automatically included

### When to Regenerate

Run this command when:
- Adding new OEWS data for a region
- Updating OEWS occupations
- Wages change significantly
- Adding new industries
- Any time you want config to match current data

---

## 13. Next Steps for New Data Engineers

### Initial Setup
1. **Read this document** (you are here)
2. **Read [CLAUDE_DATA_ENGINEER.md](./CLAUDE_DATA_ENGINEER.md)** for operational procedures
3. **Read [DATABASE_DESIGN_BEST_PRACTICES.md](./DATABASE_DESIGN_BEST_PRACTICES.md)** for architectural rationale
4. **Read [CONFIG_GENERATION_SUMMARY.md](./CONFIG_GENERATION_SUMMARY.md)** to understand data-driven config

### Ongoing Operations
5. **Run health dashboard weekly:** `python scripts/system_health_dashboard.py`
6. **Regenerate config when OEWS changes:** `python scripts/generate_config_from_oews.py`
7. **Add a data source:** Follow the 6-step checklist in CLAUDE_DATA_ENGINEER.md
8. **Monitor metadata system:** Query `meta_*` tables to track data lineage
9. **Monthly audit:** Follow procedures in CLAUDE_DATA_ENGINEER.md#monthly-audit-procedure

### Understanding Multi-Industry Analysis

The system now analyzes **all 22 industries** in the Austin-Round Rock-San Marcos, TX MSA (638 occupations), not just food service:
- **Highest wage:** Management ($65.68/hr, 36 occupations)
- **Largest sector:** Manufacturing (59 occupations)
- **Food service:** Just one of 22 industries ($19.20/hr, 17 occupations)

OEWS data scope: **Austin-Round Rock-San Marcos, TX MSA only** (BLS area code 12420).

This enables:
- Comparative labor market analysis across sectors
- Identifying high-stress industries beyond food service
- Community economic development insights

