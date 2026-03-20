# AGENT.md — Instructions for AI Coding Agents

This file tells you everything you need to know to work on ChainStaffingTracker without asking clarifying questions. Read it completely before writing any code.

---

## 0. Read These First

```bash
cat README.md                          # project overview, architecture, all third-party tools
cat RUNBOOK.md                         # how to start the server, run scrapers, troubleshoot
cat SPIRITPOOL_HANDOFF_SESSION3.md     # state of the codebase as of last session
```

Then inventory what actually exists on disk — do not trust docs alone:

```bash
find . -name "*.py" -not -path "./.venv/*" | sort
wc -l server.py backend/*.py scraper/*.py 2>/dev/null
head -80 scraper/scrape.py             # understand the existing scraper before touching it
cat config/chains.yaml 2>/dev/null || echo "CONFIG NOT YET CREATED"
```

---

## 1. Mission

Build a public data scraping pipeline that detects real staffing stress at chain employer locations in Austin TX, and outputs a ranked list of where community job fairs will have maximum labor market impact.

This is a community economic justice tool. Every technical decision should be evaluated against: *does this make the output more useful for someone deciding where and when to show up with a hiring booth?*

---

## 2. What Already Works — Do Not Break

| Component | Location | Status |
|-----------|----------|--------|
| Starbucks careers API scraper | `scraper/scrape.py` | Working — CLI must remain functional |
| Flask server | `server.py` (port 8765) | Stable |
| Leaflet map frontend | `frontend/` | Stable — do not modify CSS or JS |
| SpiritPool SQLite backend | `backend/` + `data/spiritpool.db` | Working — do not touch |
| Browser extension | `spiritpool/` | **ON HIATUS — do not modify** |

**The original scraper CLI must keep working after any refactoring:**
```bash
python scraper/scrape.py --location "Austin, TX, US" --radius 25  # must not break
```

---

## 3. What Is Broken and Must Be Fixed

**The scoring model produces 87% "critical" scores.** This is because the Starbucks careers API maintains exactly 2 standing postings per store (1 Barista + 1 Shift Supervisor) as standard practice — 90% uniformity means there is no real signal variation. The scoring model does not account for this. Fix is described in §8.

---

## 4. Do Not Build What Already Exists

This is the most important section. Before writing any scraper, check if a library already solves it.

### Job Board Scraping → `python-jobspy`
```bash
pip install python-jobspy
```
Do NOT write a custom Indeed, Glassdoor, or ZipRecruiter scraper. JobSpy handles all of them with one call and returns a clean pandas DataFrame. Your job is to write `scrapers/jobspy_adapter.py` that wraps JobSpy's output into `ScraperSignal` objects.

```python
from jobspy import scrape_jobs

# This is already solved. Wrap it, don't rewrite it.
df = scrape_jobs(
    site_name=["indeed", "glassdoor"],
    search_term="barista",
    location="Austin, TX",
    distance=25,
    hours_old=72,
    results_wanted=100,
    country_indeed="USA"
)
```

JobSpy returns these fields (use them all):
- `title`, `company`, `location` (city/state), `job_url`
- `min_amount`, `max_amount`, `interval` (hourly/yearly)
- `date_posted`, `is_remote`, `job_type`
- `company_industry`, `company_description` (Indeed-specific)

### Google Maps Store Data → `google-maps-scraper` (noworneverev)
```bash
pip install google-maps-scraper
playwright install firefox
```
Do NOT write a custom Google Maps Playwright scraper. This library handles it.

```python
from gmaps_scraper import GoogleMapsScraper, ScrapeConfig
import asyncio

async def scrape_store(maps_url: str):
    config = ScrapeConfig(language="en", headless=True)
    async with GoogleMapsScraper(config) as scraper:
        result = await scraper.scrape(maps_url)
        if result.success:
            return result.place
            # .name, .rating, .review_count, .address, .latitude, .longitude
            # .permanently_closed, .hours, .website, .phone
```

### Google Maps Review Text → `google-reviews-scraper-pro` (optional)
Only needed if you want to keyword-scan actual review text. Clone and configure separately:
```bash
git clone https://github.com/georgekhananaev/google-reviews-scraper-pro.git
```
Configure its `config.yaml` with Austin Starbucks URLs. Its SQLite output gets read by `scrapers/reviews_adapter.py`.

### Reddit Sentiment → `PRAW`
```bash
pip install praw
```
Do NOT scrape reddit.com HTML. PRAW is the official API wrapper.

```python
import praw

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent="ChainStaffingTracker/1.0"
)

# If no credentials, fall back to public JSON API:
# https://www.reddit.com/r/starbucks/search.json?q=understaffed&sort=new&limit=100
```

### BLS Wage Data → raw `requests` (no library needed)
```python
import requests

# V1 API — no registration required
url = "https://api.bls.gov/publicAPI/v1/timeseries/data/{SERIES_ID}"
r = requests.get(url, headers={"User-Agent": "ChainStaffingTracker/1.0"}).json()
data = r["Results"]["series"][0]["data"]  # list of {year, period, value}
```

Series IDs for Austin food service wages are in `config/chains.yaml`.

---

## 5. Architecture Rules

### Every scraper produces `ScraperSignal` objects
All scrapers must implement `BaseScraper` from `scrapers/base.py` and return `list[ScraperSignal]`. No scraper writes directly to the database. The `backend/ingest.py` function `ingest_signals()` handles all DB writes.

```python
@dataclass
class ScraperSignal:
    store_num:    str          # "SB-03347" or "REGIONAL-austin_tx" if no specific store
    chain:        str          # "starbucks", "dutch_bros", etc.
    source:       str          # "careers_api", "jobspy", "reddit", "google_maps"
    signal_type:  str          # "listing", "wage", "sentiment", "review_score"
    value:        float        # normalized 0-1 or raw numeric
    metadata:     dict         # source-specific full payload
    observed_at:  datetime
    # Optional fields
    wage_min:     float | None
    wage_max:     float | None
    wage_period:  str | None   # "hourly" or "yearly"
    role_title:   str | None
    source_url:   str | None
```

### Config drives everything
Nothing is hardcoded. All chain names, API endpoints, scoring weights, region coordinates, and BLS series IDs come from `config/chains.yaml` via `config/loader.py`. If you find yourself hardcoding "Austin" or "Starbucks" anywhere other than config, stop and fix it.

### Two separate databases
- `data/tracker.db` — the new pipeline (stores, signals, snapshots, scores, wage_index)
- `data/spiritpool.db` — the extension pipeline — **never write to this from new code**

### Fail gracefully, never crash the server
Every scraper's `scrape()` method must catch all exceptions internally and return an empty list on failure. Log the error clearly. The server must stay up even if every scraper is down.

```python
def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
    try:
        # ... scraping logic
        return signals
    except Exception as e:
        logging.error(f"[{self.name}] Failed for {region}: {e}")
        return []   # never raise
```

### Rate limiting is mandatory
Every scraper must have configurable delays between requests. Defaults:
- Careers APIs: 1 req/sec
- Job board scraping (JobSpy): let JobSpy handle it internally
- Google Maps: 3-5 second random delay between stores
- Reddit: 2 second delay between requests (30 req/min public limit)
- BLS: 1 req/sec (500/day limit on v2)

---

## 6. Database Schema

**File:** `backend/database.py`  
**DB file:** `data/tracker.db` (auto-created on first run)  
**ORM:** SQLAlchemy (already installed)

```python
# stores — one row per physical chain location
class Store(Base):
    store_num    # str PK — "SB-03347"
    chain        # str — "starbucks"
    industry     # str — "coffee_cafe"
    store_name   # str
    address      # str
    lat          # float
    lng          # float
    region       # str — "austin_tx"
    first_seen   # datetime
    last_seen    # datetime
    is_active    # bool default True

# signals — every raw observation from any source
class Signal(Base):
    id           # int PK autoincrement
    store_num    # str FK → stores
    source       # str — "careers_api", "jobspy", "reddit", "google_maps"
    signal_type  # str — "listing", "wage", "sentiment", "review_score"
    value        # float
    metadata     # JSON
    observed_at  # datetime
    created_at   # datetime default now

# snapshots — periodic scan summaries
class Snapshot(Base):
    id           # int PK
    region       # str
    chain        # str
    source       # str
    scanned_at   # datetime
    store_count  # int
    signal_count # int
    summary      # JSON — {"critical": N, "elevated": N, "adequate": N}

# scores — computed per store, updated after ingestion
class Score(Base):
    store_num    # str FK → stores  \
    score_type   # str               > composite PK
    value        # float 0-100
    tier         # str — "critical", "elevated", "adequate", "unknown"
    computed_at  # datetime

# wage_index — local vs chain pay comparison
class WageIndex(Base):
    id           # int PK
    employer     # str
    is_chain     # bool
    chain_key    # str nullable
    industry     # str
    role_title   # str
    wage_min     # float nullable
    wage_max     # float nullable
    wage_period  # str — "hourly" or "yearly"
    location     # str
    zip_code     # str nullable
    source       # str
    observed_at  # datetime
    source_url   # str nullable
```

---

## 7. Scoring Model — Fix the Broken One First

Before building anything new, fix the scoring model. This is Priority 1.

### Why it's broken
The careers API maintains exactly 2 standing postings per store as standard practice. 90% of stores have exactly 2. The original model treats any store with 2 listings as "critical" — producing 87% critical scores across the board. It's noise.

### Fix 1 — Posting age decay
A posting open for 90 days is a standing requisition. A posting opened 3 days ago is a real signal.

```python
def age_weight(days_old: int) -> float:
    FRESH = 7    # from config
    STALE = 90   # from config
    if days_old <= FRESH:
        return 1.0
    if days_old >= STALE:
        return 0.0
    return 1.0 - ((days_old - FRESH) / (STALE - FRESH))
```

### Fix 2 — Baseline-relative scoring
Score stores relative to regional norms, not absolutely.

```python
def baseline_relative_score(store_count: int, regional_counts: list[int]) -> float:
    if len(regional_counts) < 3:
        return 50.0  # not enough data — neutral
    percentile = sum(1 for c in regional_counts if c <= store_count) / len(regional_counts)
    return percentile * 100
```

### Acceptance test
After implementing both fixes, run a scrape on Austin TX and print the score distribution. It must NOT be 87% critical. If it is, the fix didn't work.

---

## 8. Targeting Score

`backend/targeting.py` — computes where a job fair would have maximum impact.

```python
@dataclass
class TargetingScore:
    store_num:             str
    chain:                 str
    industry:              str
    address:               str
    lat:                   float
    lng:                   float
    staffing_stress:       float    # 0-100: composite score
    wage_gap:              float    # 0-100: how much more locals pay
    isolation:             float    # 0-100: distance to nearest same-chain store
    local_alternatives:    float    # 0-100: density of local hirers within 2 miles
    targeting_score:       float    # weighted composite
    targeting_tier:        str      # "prime", "strong", "moderate"
    chain_avg_wage:        float | None
    local_avg_wage:        float | None
    wage_premium_pct:      float | None
    nearest_same_chain_mi: float
    recommended_timing:    list[str]
```

Weights: staffing_stress 40%, wage_gap 30%, isolation 20%, local_alternatives 10%.  
All weights configurable in `config/chains.yaml`.

---

## 9. Flask API Endpoints to Add

Add these to `server.py`. Do not modify existing endpoints.

```
GET  /api/scores?region=austin_tx&chain=starbucks
GET  /api/targeting?industry=coffee_cafe&region=austin_tx&limit=10
GET  /api/wage-index?industry=coffee_cafe&region=austin_tx
GET  /api/scheduler/status
```

---

## 10. Scheduler

`backend/scheduler.py` — APScheduler running inside Flask.

```python
from apscheduler.schedulers.background import BackgroundScheduler

# Careers API — daily at 3am
# JobSpy (Indeed + Glassdoor) — daily at 4am  
# Reddit — every 6 hours
# Google Maps reviews — weekly Monday 5am
# BLS — weekly (data only updates monthly anyway)
```

APScheduler is not yet installed:
```bash
pip install apscheduler
```
Add it to the install command in `RUNBOOK.md`.

---

## 11. Code Standards

**Python:**
- Type hints on all functions and class attributes
- Docstrings on all modules and classes (what it does, what it depends on, what calls it)
- `logging` module only — never `print()`
- Log format: `[ScraperName] message` — makes logs greppable
- All config from `config/loader.py` — zero hardcoded values
- `pathlib.Path` for all file paths — no string concatenation

**Error handling:**
- Scrapers return empty list on failure — never raise
- DB operations use try/except with rollback on failure
- HTTP calls have timeouts (default 30s) and retry logic (max 3 attempts, exponential backoff)

**Testing:**
- Every new scraper adapter needs a `test_` function that can run against live data
- Score distribution test: after running Austin scrape, assert not >50% in any single tier

**Git hygiene:**
- Never commit `data/*.db` files
- Never commit `.env` or files containing API keys
- `config/chains.yaml` is safe to commit (no secrets)

---

## 12. What NOT to Do

| Do Not | Why |
|--------|-----|
| Modify `spiritpool/` | Extension is on hiatus |
| Write to `data/spiritpool.db` | Extension DB must stay clean |
| Write a custom Indeed scraper | JobSpy already does this |
| Write a custom Google Maps scraper from scratch | `google-maps-scraper` already does this |
| Scrape any page requiring login | Legal constraint — public data only |
| Add ML/NLP libraries | Keyword matching is sufficient for v1 |
| Add npm or Node.js build steps | Frontend is vanilla JS |
| Change Flask port | Stays 8765 |
| Break `python scraper/scrape.py --location "Austin, TX, US"` | Legacy CLI must stay working |
| Hardcode "Austin" or "Starbucks" outside config | Config-driven means config-driven |
| Add user authentication | Not needed for v1 |
| Build for any region other than Austin TX | One city first |

---

## 13. Verification Sequence

Run this after completing your work:

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker

# Server starts clean
pkill -f "server.py" 2>/dev/null; sleep 1
python server.py --debug &
sleep 2

# Legacy scraper still works
python scraper/scrape.py --location "Austin, TX, US" --radius 25

# SpiritPool still untouched
curl -s http://localhost:8765/api/spiritpool/stats

# New scrapers run without crashing
python scrapers/careers_api.py --region austin_tx
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx
python scrapers/reddit_adapter.py --region austin_tx
python scrapers/reviews_adapter.py --chain starbucks --region austin_tx

# Score distribution is NOT 87% critical
curl -s "http://localhost:8765/api/scores?region=austin_tx" | python3 -c "
import sys, json
data = json.load(sys.stdin)
tiers = [s['tier'] for s in data.get('stores', [])]
from collections import Counter
print(Counter(tiers))
# Should show spread across tiers, not 87% critical
"

# Targeting and wage endpoints respond with real data
curl -s "http://localhost:8765/api/targeting?industry=coffee_cafe&region=austin_tx&limit=10" | python3 -m json.tool
curl -s "http://localhost:8765/api/wage-index?industry=coffee_cafe&region=austin_tx" | python3 -m json.tool

# DB has data in all tables
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
for t in ['stores','signals','snapshots','scores','wage_index']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n} rows')
conn.close()
"
```

---

## 14. Session Handoff

At the end of every session, create or update `HANDOFF_SESSION_N.md`:

1. Tasks completed (table: task, status, notes)
2. Tasks started but not finished and why
3. Score distribution after fixes (what % are critical/elevated/adequate)
4. Top 3 rows from `/api/targeting` output — paste actual JSON
5. DB row counts per table in `tracker.db`
6. Any new known issues discovered
7. Deviations from these instructions and why
8. Suggested next session priorities

Follow the format of `SPIRITPOOL_HANDOFF_SESSION3.md`.

---

## 15. Quick Reference

```bash
# Start server
python server.py --debug

# Run individual scrapers
python scrapers/careers_api.py --region austin_tx
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx --mode chain
python scrapers/jobspy_adapter.py --industry coffee_cafe --region austin_tx --mode wage
python scrapers/reddit_adapter.py --region austin_tx
python scrapers/reviews_adapter.py --chain starbucks --region austin_tx

# Check DB
python3 -c "
import sqlite3; conn = sqlite3.connect('data/tracker.db')
for t in ['stores','signals','snapshots','scores','wage_index']:
    print(t, conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
"

# Install all dependencies
pip install flask flask-sqlalchemy flask-cors requests tqdm playwright \
            pyyaml apscheduler python-jobspy praw nltk pandas google-maps-scraper
playwright install firefox
playwright install chromium --with-deps
```

---

*This file is the authoritative instruction set for agents working on this codebase. README.md explains what the project does. This file explains how to work on it. When in doubt, re-read §4 (don't build what exists) and §12 (what not to do).*
