# Design Flaw: Food Service-Only Focus

**Date Identified:** 2026-03-22
**Severity:** HIGH — Limits market analysis to single industry
**Status:** OPEN — Needs refactoring

---

## Problem

The system was built with a **narrow focus on food service occupations (SOC 35-xxxx)** and Starbucks/Dutch Bros chain locations.

This constraint appears throughout:
- **Scrapers:** Filter for SOC 35-0000, 35-2021, 35-3023, etc.
- **Scoring:** Uses food-service-specific wage baselines
- **Configuration:** `chains.yaml` defines only coffee/café chains
- **Data ingestion:** OEWS/JOLTS/CBP ingestion filters to NAICS 722515 (food service)
- **Analysis:** Assumes all insights are about coffee shops and fast food

## Why This Is Wrong

1. **Labor market dynamics vary by industry**
   - Retail staffing stress ≠ food service staffing stress
   - Healthcare has different wage floors, turnover patterns, seasonality
   - Tech has different skill requirements and competition

2. **Community job fair targeting is too narrow**
   - Local independent employers span many industries
   - Retail, healthcare, professional services, construction all have hiring needs
   - Food service is only ~8% of total employment

3. **Ground-truth comparisons are skewed**
   - Using food-service-only wage baselines misses regional context
   - JOLTS data for food service alone doesn't show broader labor market health
   - Can't compare staffing stress across industries

4. **Missed opportunities**
   - Could identify other high-stress industries
   - Could benchmark different sectors against each other
   - Could inform broader community economic development

## Required Changes

### 1. **Config (config/chains.yaml)**
- [ ] Remove `chains:` section limiting to Starbucks/Dutch Bros
- [ ] Add `target_industries:` with all NAICS codes or mark as "all"
- [ ] Update `scoring.baseline` to use multi-industry baselines
- [ ] Remove SOC code filters from scrapers config

### 2. **Data Ingestion (scrapers/)**
- [ ] `qcew_adapter.py` — Remove NAICS 72 filter, fetch all industries
- [ ] `jolts_adapter.py` — Remove industry filtering
- [ ] `oews_adapter.py` — Fetch all occupations, not just 35-xxxx
- [ ] `cbp_adapter.py` — Remove NAICS filters

### 3. **Scoring (backend/scoring/)**
- [ ] `engine.py` — Remove food-service-specific assumptions
- [ ] `wage.py` — Use industry-relative wages, not food-service baselines
- [ ] `careers.py` — Count postings by industry, not just chain jobs

### 4. **Database (backend/database.py)**
- [ ] Remove industry filters from baseline computation
- [ ] Add `industry_id` or `naics_code` columns to scores table
- [ ] Compute scores per-industry, not globally

### 5. **Documentation**
- [ ] Update README to reflect multi-industry scope
- [ ] Update scoring documentation (currently food-service-only)
- [ ] Update data dictionary

### 6. **Analysis (frontend/)**
- [ ] Map should show ALL stores, not just chain coffee shops
- [ ] Score view should allow filtering/grouping by industry
- [ ] Add industry comparison view

---

## Impact on Current Work

**Short term:** Can still ingest all OEWS data (all industries) even if scoring only uses food service. This provides ground truth for future refactoring.

**Medium term:** Expand scoring to all industries using same framework.

**Long term:** Complete redesign to multi-industry labor market analysis.

---

## Notes

This limitation was acceptable for MVP (proof of concept with one industry) but needs immediate attention for production use. The underlying infrastructure (6-layer architecture, metadata system, validation rules) supports multi-industry naturally — it's only the configuration and filtering logic that needs change.

