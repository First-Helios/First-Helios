# Agent Handoff — Risk Scoring & Data Analysis/Cleanup

**Date:** 2026-03-15  
**Focus:** Vacancy risk scoring model, data quality, geocoding, and trend analysis  
**Stack:** Python 3.12 + Flask backend, vanilla JS/HTML/CSS frontend, Leaflet maps

---

## 1. Project Overview

A full-stack Starbucks staffing tracker that scrapes the public careers API, scores stores by vacancy risk, plots them on a map, and tracks trends over time.

```
server.py              – Flask dev server (port 8765), scan API, history API
scraper/scrape.py      – Careers API scraper, vacancy scoring, geocoding, history append
frontend/index.html    – SPA shell (Leaflet map, sidebar, scan panel, trends drawer)
frontend/js/data.js    – localStorage persistence, vacancy index, haversine matching, cache
frontend/js/map.js     – Overpass API fetch, markers, popups with vacancy data
frontend/js/ui.js      – Sidebar list, stats card, filters, toasts, report modal
frontend/js/scan.js    – Scan-on-demand panel, region-aware status, polling
frontend/js/trends.js  – Canvas line-chart, changes diff table, store drill-down
frontend/js/app.js     – Bootstrap, region loading, vacancy reload orchestration
frontend/css/style.css – Full dark theme, all components styled (1221 lines)
frontend/data/vacancies.json  – Current vacancy snapshot (merged Austin + Columbus)
frontend/data/history.json    – Append-only scan timeline (5 snapshots)
RUNBOOK.md             – Startup/restart/CLI docs
```

**Line counts:** scraper 590, server 310, frontend JS 1993, CSS 1221, HTML 227 = ~4340 total

---

## 2. Current Risk Scoring Model — Problems

### 2.1 The Scoring Algorithm (scraper/scrape.py lines 60–75)

```
ROLE_WEIGHTS:
  barista               → 1.0
  shift supervisor      → 2.0
  assistant store mgr   → 1.0
  store manager         → 0.5
  other                 → 0.5

THRESHOLDS:
  score > 2.0  → critical
  score > 0.0  → low
  score == 0   → unknown
```

### 2.2 Known Issues with Current Scoring

**Issue 1: Almost every store is "critical"**  
Current data (Austin + Columbus combined, 109 stores):
- **95 critical** (87%), **14 low** (13%), **0 unknown**
- Score range: 1.0–3.0
- 95 stores have exactly 2 listings (1 Barista + 1 Shift Supervisor = score 3.0)
- 14 stores have exactly 1 listing (score 1.0 or 2.0)

The API appears to cap listings at ~2 per store (likely 1 Barista + 1 Shift Supervisor as standard always-open postings). This means the scoring model produces a binary output: almost everything is "critical" because 1.0 + 2.0 = 3.0 > 2.0 threshold.

### 2.3 Multi-Region Exploration (2026-03-16) — CONFIRMED

Ran `scraper/explore_regions.py` across **8 major US metros** (1,197 stores total).
Results saved in `scraper/exploration_results.json`.

```
Region                    Stores  Critical%  Std Pair%  MaxLC  Roles
───────────────────────────────────────────────────────────────────
Seattle, WA, US              122      89.3%      89.3%      2      2
Chicago, IL, US              156      91.0%      91.0%      2      2
New York, NY, US             291      90.4%      90.4%      2      2
Los Angeles, CA, US          310      89.0%      89.0%      2      2
Denver, CO, US               118      88.1%      88.1%      2      2
Miami, FL, US                 69      89.9%      89.9%      2      2
Atlanta, GA, US               43      90.7%      90.7%      2      2
Dallas, TX, US                88      93.2%      93.2%      2      2
───────────────────────────────────────────────────────────────────
TOTAL                       1197      90.0%      90.0%
```

**Key findings:**
1. **No store anywhere has more than 2 listings.** The 2-listing cap is universal.
2. **Exactly 90.0%** of stores have the standard {Barista:1, Shift Supervisor:1} pair.
3. **Only 2 role types** observed across all 1,197 stores — zero ASM/SM postings.
4. The remaining **10%** have 1 listing (either Barista-only or Shift-Supervisor-only).
5. **Posting ages** range 1.9–89.9 days; medians vary 17–78 days by region.
6. The "critical" designation is **binary noise**: it simply means the store has 2 standing reqs instead of 1.

**Conclusion:** The current risk scoring model is provably useless at national scale. The "critical" label conveys zero information about actual staffing stress. The only meaningful signals are:
- **1-listing stores** (10%) — possibly recently filled one position, or new store ramping up
- **Temporal changes** — when a store flips between 1 and 2 listings across scans
- **Posting age** — whether listings refresh (re-posted) or sit stale for 90 days

**Issue 2: Weights need rethinking**  
- Shift Supervisor at 2.0 dominates the score. Having one Shift Supervisor posting (very common, likely a standing requisition) immediately pushes score to 2.0 before any other role is counted.
- The metric doesn't differentiate between "posting exists as routine hiring" vs "urgent vacancy."

**Issue 3: No temporal signal in scoring**  
- `latest_posting` timestamp is captured but not used in score calculation.
- A 6-month-old posting has the same weight as one posted today.
- The `posted_ts` field from the API could drive a "posting age decay" factor.

**Issue 4: No relative/percentile scoring**  
- Scores are absolute, not relative to the region. If every store in Austin always has 2 postings, that's the baseline — the interesting signal is stores that deviate.

### 2.3 What the User Wants

Direct quote: *"Currently it seems no store has more than two openings. This is likely intentional and the insights we need are in how the critical openings move over time."*

The user understands the per-snapshot data is coarse. The real value is **longitudinal trend analysis**: which stores gain/lose postings between scans, and whether critical status flows to new areas over time.

---

## 3. Data Quality Issues

### 3.1 Geocoding

The scraper uses Nominatim (free OSM geocoder) with a two-pass strategy:
1. Try the raw address from the careers API
2. If that fails, clean the address (`_clean_address()` in scrape.py lines 317–345) and retry

**Current geocoding rates:**
- Columbus, OH: **47/56 geocoded (84%)**
- Austin, TX: **47/53 geocoded (88%)** ← but these lost coords after --merge re-scraped without geocode for the Austin entries

**Currently in vacancies.json:** Austin stores have `lat: null` (0/53 geocoded) because the Columbus scan used `--merge` and the Austin entries weren't re-geocoded.

**9 previously-ungeocodable Columbus stores** — all had shopping center names that Nominatim couldn't resolve. **All 9 now resolved (2026-03-16):**

| Store | Method | Coordinates |
|---|---|---|
| #02465 FIESTA LANE | Improved `_clean_address()` strips "Festival Square" | 40.006, -83.046 |
| #13861 UPPER ARLINGTON | Strips "The Shoppes at Tremont" | 40.023, -83.060 |
| #10288 PARKWAY CENTRE | Strips "Parkway Centre" | 39.879, -83.041 |
| #02431 MILL RUN | Strips "Market at Mill Run" | 40.028, -83.116 |
| #02574 MARKET AT EASTON | Strips "Market at Easton" | 40.051, -82.919 |
| #11881 MARKET AT EAST BROAD | Strips "The Market at East Broad" | 39.981, -82.834 |
| #20129 PICKERINGTON PLAZA | Strips "Shoppes at Hunter's Run" | 39.929, -82.787 |
| #61853 HAMILTON QUARTER | Override (`geocode_overrides.json`) | 40.076, -82.854 |
| #02455 5TH AVE & GRANDVIEW | Override (`geocode_overrides.json`) | 39.988, -83.035 |

**Improvements applied to `scraper/scrape.py`:**
1. `_clean_address()` now catches Square, Centre, Shoppes, Quarter, Crossing, Run, Outlets, Town Center patterns
2. New "Market at X" / "The Market at X" stripping rule
3. Short-token rule reduced from 4→3 chars to preserve state names like "Ohio"
4. New 3rd geocoding pass: minimal address (street + city + state + country)
5. New `geocode_overrides.json` fallback for permanently ungeocodable addresses

**Columbus geocoding: 56/56 (100%)** — up from 47/56 (84%).

### 3.2 OSM-to-Vacancy Matching

Frontend `data.js` uses haversine matching (≤ 0.35 km) between OSM Starbucks locations and geocoded vacancy stores. Current match rate for Columbus: **47 of 77 OSM locations matched** (the 30 unmatched are stores without geocoded vacancy data, or vice versa).

### 3.3 Merge Artifact

The scraper's `--merge` flag (used by the server) accumulates stores across regions into one file. Currently vacancies.json contains 109 stores (53 Austin + 56 Columbus). The Austin stores have `lat: null` because the last scrape was Columbus-only with `--merge`.

**The `--merge` behavior needs review:**
- Pro: Supports multi-region tracking
- Con: Stale region data sits alongside fresh data with no per-region timestamp
- Con: Re-scraping one region doesn't re-geocode the other region's stores

### 3.4 Role Name Parsing

The job title regex (`scrape.py` line 210):
```python
r"(?P<role>.+?)\s*-\s*Store#\s*(?P<num>\d+),\s*(?P<name>.+)"
```
Then the `department` field from the API is used as the `open_roles` key (not the parsed role).

Currently only 2 role names appear: **"Shift Supervisor" (104) and "Barista" (100)**. No ASM or SM postings observed. This is consistent with the hypothesis that these are standing requisitions.

---

## 4. History & Trends System

### 4.1 History Format (frontend/data/history.json)

```json
[
  {
    "ts": "2026-03-01T12:00:00+00:00",
    "loc": "Austin, TX, US",
    "rad": 25,
    "summary": { "critical": 48, "low": 5, "unknown": 0, "total": 53 },
    "stores": {
      "19801": { "n": "3RD & LAVACA", "l": "c", "s": 3.0, "lc": 2, "r": {"Shift Supervisor":1,"Barista":1} },
      ...
    }
  },
  ...
]
```

Compact format: `l` = level initial (c/l/u), `s` = score, `lc` = listing count, `r` = open roles.

Currently 5 snapshots: 3 synthetic (seeded for testing, March 1/5/9), 1 real Austin (March 15), 1 real Columbus (March 16).

### 4.2 Trends Frontend (frontend/js/trends.js, 371 lines)

- **Canvas line chart**: Plots critical/low/total store counts per snapshot
- **Changes table**: Diffs last two snapshots, shows stores that changed level (escalation/de-escalation)
- **Store drill-down**: Click a row → expand full scan-by-scan timeline for that store
- **Endpoint**: `GET /api/history?location=X&last=N`

### 4.3 What's Missing in Trends

- No time-range filtering (UI shows all snapshots)
- No per-store trend sparklines on the map or sidebar
- No export functionality
- No multi-region comparison view
- The chart only shows aggregate counts, not individual store trajectories
- No statistical analysis (moving average, rate of change, clustering)

---

## 5. API Reference

### Starbucks Careers API

```
GET https://apply.starbucks.com/api/pcsx/search
  ?domain=starbucks.com
  &query=
  &location=Columbus, OH
  &start=0            (pagination offset)
  &num=100            (ignored; API returns 10/page)
  &sort_by=distance
  &filter_distance=25 (miles)
  &filter_worklocation_option=onsite
```

No auth required. Returns `{ status: 200, data: { positions: [...], totalPositions: N } }`.

**Key constraint:** The API returns max 10 results per page regardless of `num` param. Pagination auto-detects this.

### Server API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/scan/status` | GET | Scan state + last-scan metadata + stale flag |
| `/api/scan` | POST | Start scrape: `{location, radius, force}` |
| `/api/scan/log` | GET | Last 8KB of scraper log |
| `/api/history` | GET | Scan history array; `?location=`, `?last=N` |

The scan is region-aware: requesting a different region bypasses the 7-day cooldown.

---

## 6. Recommended Next Steps (Priority Order)

### 6.1 Rethink the Scoring Model

The current model is nearly useless — 87% critical tells you nothing. Options:

**A. Baseline-relative scoring:**
- Compute a per-region baseline (e.g., "85% of Columbus stores always have 2 postings")
- Flag only stores that deviate from baseline (extra postings, unusual roles like SM/ASM)
- This requires ≥3 snapshots to establish a baseline

**B. Temporal decay scoring:**
- Weight recent postings higher than old ones
- A Barista posting that's been open 6 months is a standing req; one posted yesterday might indicate a sudden departure
- The `posted_ts` (Unix timestamp) field is already captured

**C. Role-anomaly scoring:**
- If every store has {Barista, Shift Supervisor}, that's noise
- The signal is when a store posts for ASM/SM (rare) or when a store has ≥3 unique roles open
- Possibly flag stores that *don't* have the expected 2 postings (might indicate recently filled = better staffing)

**D. Change-velocity scoring (longitudinal):**
- Score = how frequently a store's status changes between snapshots
- A store that flips critical↔low every scan is volatile (potentially problematic)
- A store that's been critical for 10 consecutive scans is chronically understaffed

### 6.2 Fix Data Quality

1. **Geocoding improvement**: For the ~12-16% ungeocodable addresses, consider:
   - Fallback to Google Maps Geocoding API (paid but more robust)
   - Manual geocode table for known-bad addresses (add a `geocode_overrides.json`)
   - Parse the shopping center name out more aggressively in `_clean_address()`

2. **Merge strategy**: The `--merge` flag mixes regions without per-region freshness. Consider:
   - Separate files per region (`vacancies_columbus_oh.json`)
   - Or add a `region` + `scanned_at` field per store in the merged file
   - Frontend should load only the region that matches the current map view

3. **Austin geocode loss**: The current vacancies.json has 53 Austin stores with `lat: null` because `--merge` overwrote them without re-geocoding. Fix: the merge logic should preserve existing geocoded coords if the new data lacks them.

### 6.3 Enhance Trend Analysis

1. **Diff intelligence**: Beyond "changed from low → critical", compute:
   - How many scans a store has been at current level (streak length)
   - Which stores are newly appearing vs disappearing from the vacancy list
   - Regional heat — are critical stores clustered geographically?

2. **Statistical features**:
   - Rolling average of critical store count (3-scan or 7-day window)
   - Rate of change (is the region getting better or worse?)
   - Correlation between posting age and vacancy level

3. **Alerting**: When a store crosses a threshold for N consecutive scans, flag it as "chronic."

---

## 7. File-by-File Guide for Key Changes

| File | Lines | What to change for scoring |
|---|---|---|
| `scraper/scrape.py` L60-75 | Role weights + thresholds | Adjust or replace the scoring model |
| `scraper/scrape.py` L258-292 | `aggregate_by_store()` | Where scores are computed per store |
| `scraper/scrape.py` L440-480 | `append_history_snapshot()` | What gets recorded in history |
| `frontend/js/data.js` L162-200 | `getStatus()` | Frontend status computation (community + vacancy fallback) |
| `frontend/js/data.js` L55-86 | `buildVacancyIndex()` | Haversine matching OSM↔vacancy |
| `frontend/js/trends.js` L1-371 | Entire file | Canvas chart, diff table, drill-down |
| `frontend/js/map.js` L160-220 | Popup rendering | How vacancy info displays in map popups |
| `frontend/js/ui.js` L200-250 | Sidebar list items | Vacancy badge rendering |

---

## 8. Running the Stack

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker
source .venv/bin/activate
python server.py                    # http://localhost:8765

# Manual scrape (bypass server)
python scraper/scrape.py --location "Columbus, OH" --radius 25
python scraper/scrape.py --location "Columbus, OH" --radius 25 --no-geocode  # fast, no coords
python scraper/scrape.py --location "Columbus, OH" --radius 25 --merge       # add to existing data
```

Python deps: `flask`, `requests`, `tqdm`, `playwright` (playwright only for probe_api.py, not needed for normal scraping).

---

## 9. Current Data Snapshot

```
vacancies.json: 109 stores (53 Austin + 56 Columbus)
  Austin:   0/53 geocoded (lost during merge), all critical or low
  Columbus: 56/56 geocoded (100%), previously 47/56 — 9 fixed via improved cleaning + overrides
  Roles:    Shift Supervisor (104), Barista (100) — only 2 role types observed
  Scores:   1.0–3.0 range, 95 stores at exactly 3.0
  Levels:   95 critical, 14 low, 0 unknown

history.json: 5 snapshots
  3 synthetic (Austin, March 1/5/9 — for testing)
  1 real Austin (March 15)
  1 real Columbus (March 16)
```

---

## 10. Key Insight for Next Agent

**CONFIRMED across 1,197 stores in 8 major metros** (see §2.3): the Starbucks careers API maintains exactly 2 standing postings (1 Barista + 1 Shift Supervisor) per store as standard practice. The max listing count is universally 2. No ASM/SM postings exist anywhere. The current risk score is provably binary noise.

**The only meaningful signals available from this API are:**
1. **1-listing vs 2-listing stores** (10% have only 1) — the interesting question is *why*
2. **Temporal flips** — when a store's listing count changes between scans (1→2 or 2→1)
3. **Posting age & refresh patterns** — listings range 2–90 days old; a re-posted listing signals activity
4. **Regional 1-listing rate variation** — Dallas has 6.8% single-listing stores vs Denver at 11.9%

The scoring model must be rebuilt around longitudinal change detection, not per-snapshot weighted sums.

### Exploration tooling

- `scraper/explore_regions.py` — reusable multi-region probe script
- `scraper/exploration_results.json` — raw data from the 8-metro scan (2026-03-16)
