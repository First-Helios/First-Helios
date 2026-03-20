# ChainStaffingTracker

A public data intelligence platform that detects real staffing stress at chain employer locations — and surfaces where community job fairs will have maximum labor market impact(rentable area with high clustering of chain locations).

**Current focus:** Austin, TX. One city, done right, before scaling.

**What it produces:** A ranked list of chain store locations where local independent employers can show up with a permitted booth, a hiring sign, and a job offer — timed to when workers at that location have the most leverage.

---

## What This Is Not

- Not a browser extension or crowdsourcing tool (that phase is on hiatus)
- Not a real-time system — daily/weekly scraping is sufficient
- Not targeting any individual workers — store-level signals only
- Not doing anything that requires a login, bypasses a paywall, or scrapes private data

Everything here uses publicly accessible sources. The legal framework for this was deliberately designed before any code was written.

---

## How It Works

```
Public Sources (free, legal, no login required)
┌──────────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────────┐
│ Chain Careers    │ │ Indeed /    │ │ Reddit API   │ │ Google Maps  │
│ APIs             │ │ Glassdoor   │ │ (public)     │ │ + Yelp       │
│ (Starbucks etc.) │ │ via JobSpy  │ │ via PRAW     │ │ via Playwright│
└────────┬─────────┘ └──────┬──────┘ └──────┬───────┘ └──────┬───────┘
         └──────────────────┴───────────────┴────────────────┘
                                    │
                          Normalized ScraperSignal objects
                                    │
                             SQLite (tracker.db)
                      stores / signals / snapshots / scores / wage_index
                                    │
                    ┌───────────────┼────────────────┐
                    │               │                │
             Scoring Engine    Wage Index       Targeting Score
             (multi-source     (local vs        (where + when to
              composite)        chain pay)        host a job fair)
                    │               │                │
                         Flask API + Frontend
```

---

## Repository Structure

```
ChainStaffingTracker/
│
├── README.md                   ← you are here
├── AGENT.md                    ← instructions for AI coding agents
├── config/
│   ├── chains.yaml             ← chain targets, industries, regions, scoring weights
│   └── loader.py               ← typed config access for all modules
│
├── scrapers/
│   ├── base.py                 ← BaseScraper interface + ScraperSignal dataclass
│   ├── careers_api.py          ← Starbucks careers API (refactored from scrape.py)
│   ├── jobspy_adapter.py       ← Wraps python-jobspy → ScraperSignal output
│   ├── reddit_adapter.py       ← PRAW + keyword scoring → ScraperSignal output
│   ├── reviews_adapter.py      ← Google Maps (Playwright) + Yelp → ScraperSignal output
│   ├── bls_adapter.py          ← BLS API v1 (no key) → wage baseline context
│   └── geocoding.py            ← Nominatim + overrides
│
├── backend/
│   ├── database.py             ← SQLAlchemy models + init (tracker.db)
│   ├── ingest.py               ← ingest_signals() — writes ScraperSignals to DB
│   ├── scheduler.py            ← APScheduler job definitions
│   ├── scoring/
│   │   ├── engine.py           ← Composite score (multi-source weighted)
│   │   ├── careers.py          ← Careers API sub-score (age decay + baseline)
│   │   ├── sentiment.py        ← Reddit + review sentiment sub-score
│   │   └── wage.py             ← Wage gap sub-score (local vs chain)
│   └── targeting.py            ← TargetingScore — ranked job fair candidates
│
├── server.py                   ← Flask app (port 8765)
├── frontend/                   ← Existing Leaflet map SPA (dark theme, vanilla JS)
│   ├── index.html
│   ├── css/style.css
│   └── js/
│
├── scraper/                    ← LEGACY — do not delete, original scrape.py lives here
│   └── scrape.py               ← Still callable as CLI; internally delegates to scrapers/
│
├── spiritpool/                 ← Browser extension — ON HIATUS, do not modify
├── data/
│   ├── tracker.db              ← Primary SQLite DB (auto-created)
│   └── spiritpool.db           ← Extension DB — leave untouched
│
├── Data Analysis/
│   └── spiritpool_analysis.ipynb
│
├── RUNBOOK.md                  ← Start server, run scrapers, troubleshoot
└── .venv/                      ← Python virtual environment
```

---

## Third-Party Libraries Used (Don't Build What Exists)

This project deliberately delegates scraping to mature open-source tools rather than building from scratch. The custom work is in the scoring, targeting, and glue layers.

### `python-jobspy` — Job Board Scraping
**Replaces:** Writing custom Indeed/Glassdoor/LinkedIn Playwright scrapers  
**Install:** `pip install python-jobspy`  
**Repo:** https://github.com/speedyapply/JobSpy  
**License:** MIT  
**What it does:** Scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter, and Google Jobs concurrently. Returns a pandas DataFrame with title, company, location, salary (min/max/period), posting date, applicant count, urgency badges, and direct job URLs.

```python
from jobspy import scrape_jobs

jobs = scrape_jobs(
    site_name=["indeed", "glassdoor"],
    search_term="barista",
    location="Austin, TX",
    distance=25,
    hours_old=72,           # only fresh postings
    results_wanted=100,
    country_indeed="USA"
)
# Returns DataFrame — feed directly into jobspy_adapter.py
```

**Known limitations:** Capped at ~1000 results per search. LinkedIn rate-limits around page 10. For Austin-scoped daily runs neither limit is a real problem.

---

### `google-maps-scraper` (noworneverev) — Store Ratings + Status
**Replaces:** Writing a Google Maps Playwright scraper  
**Install:** `pip install google-maps-scraper` then `playwright install firefox`  
**Repo:** https://github.com/noworneverev/google-maps-scraper  
**License:** MIT  
**What it does:** Takes Google Maps URLs or search queries, extracts rating, review count, address, lat/lng, hours, `permanently_closed` flag, and category. Async batch processing with crash recovery.

```python
from gmaps_scraper import GoogleMapsScraper, ScrapeConfig
import asyncio

async def get_store_data(maps_url: str):
    config = ScrapeConfig(language="en", headless=True)
    async with GoogleMapsScraper(config) as scraper:
        result = await scraper.scrape(maps_url)
        if result.success:
            return result.place  # .rating, .review_count, .permanently_closed, .address
```

**Why this one over alternatives:** Pure Python, async, pip-installable, has crash recovery for batch jobs, confirmed working in 2025/2026. The `georgekhananaev/google-reviews-scraper-pro` is better for full review text extraction but requires SeleniumBase + Chrome; use it if you need review text sentiment, not just ratings.

---

### `google-reviews-scraper-pro` (georgekhananaev) — Review Text for Sentiment
**Replaces:** Writing a reviews DOM scraper  
**Repo:** https://github.com/georgekhananaev/google-reviews-scraper-pro  
**License:** MIT  
**When to use:** When you need the actual review text to keyword-scan for "understaffed", "slow", "skeleton crew". Not needed for just ratings/counts.  
**Config:** YAML file with list of business URLs. Writes to SQLite automatically.

```yaml
# config.yaml
headless: true
sort_by: "newest"
db_path: "data/reviews_raw.db"
businesses:
  - url: "https://maps.app.goo.gl/YOUR_STARBUCKS_URL"
    custom_params:
      company: "Starbucks"
      location: "Austin TX"
```

---

### `PRAW` — Reddit Sentiment
**Replaces:** Writing a Reddit scraper  
**Install:** `pip install praw`  
**Docs:** https://praw.readthedocs.io  
**What it does:** Official Reddit API wrapper. Pull posts + comments from subreddits by keyword, recency, or search. Free tier (read-only, no credentials) works via the public JSON API fallback.

**Subreddits to monitor:**
- `r/starbucks` — customer + worker mix
- `r/starbucksbaristas` — worker-only, higher signal
- `r/Austin` — local community service quality chatter

**Credentials:** Free app registration at reddit.com/prefs/apps. Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` env vars. Falls back to `requests` against `reddit.com/r/starbucks/search.json` if not configured.

---

### BLS Public Data API — Regional Wage Baseline
**Replaces:** Manual wage data research  
**No library needed** — raw `requests` calls  
**Docs:** https://www.bls.gov/developers/  
**Key:** V1 API requires no registration. V2 (free registration) allows 500 queries/day and 20 years of history.

```python
import requests

# Austin-Round Rock MSA average hourly wages, food service (no API key needed)
url = "https://api.bls.gov/publicAPI/v1/timeseries/data/SMU48121007072200001"
r = requests.get(url, headers={"User-Agent": "ChainStaffingTracker/1.0"}).json()
wage_series = r["Results"]["series"][0]["data"]
```

Series IDs for Austin food service wages are in `config/chains.yaml` under `bls_series`.

---

## Data Sources Summary

| Source | What It Gives You | Tool | Cost | Key Required |
|--------|-------------------|------|------|--------------|
| Chain careers APIs | Standing job postings, posting age | Custom (`careers_api.py`) | Free | No |
| Indeed / Glassdoor | Cross-posted listings, salary ranges, urgency badges, applicant counts | `python-jobspy` | Free | No |
| Google Maps | Store ratings, review counts, permanently_closed, lat/lng | `google-maps-scraper` | Free | No |
| Google Maps reviews | Review text for keyword sentiment scanning | `google-reviews-scraper-pro` | Free | No |
| Reddit | Worker/customer sentiment, staffing complaints, hiring event mentions | `PRAW` | Free | Optional (higher rate limits) |
| Yelp | Business ratings, review snippets | `requests` → Yelp Fusion API | Free (500/day) | Yes (free) |
| BLS | Regional wage averages, unemployment rate, labor market context | `requests` | Free | No (v1) |

---

## Scoring Model

Every store gets a composite score from 0–100 built from three independent sub-scores:

```
Composite = (careers_weight × careers_score)
          + (job_boards_weight × board_score)
          + (sentiment_weight × sentiment_score)

Weights (configurable in config/chains.yaml):
  careers_api:  40%
  job_boards:   35%
  sentiment:    25%
```

If a source has no data for a store, its weight is redistributed proportionally to available sources.

### Careers API Sub-Score (fixed from original broken model)

The original model produced 87% "critical" scores because it ignored the fact that 90% of Starbucks stores maintain exactly 2 standing requisitions at all times. Fixed with two changes:

**Age decay:** Fresh postings (< 7 days old) carry full weight. Postings 30–90 days old decay toward zero. Postings > 90 days = standing requisitions = no signal.

**Baseline-relative scoring:** A store's score is its percentile rank within the region — not its absolute listing count. A store with 2 listings is unremarkable if the regional median is 2. It's notable if the median is 1.

### Score Tiers

| Tier | Percentile | Meaning |
|------|-----------|---------|
| `critical` | Top 33% | High hiring pressure, maximum job fair ROI |
| `elevated` | Middle 33% | Moderate pressure, good secondary target |
| `adequate` | Bottom 33% | Normal staffing, low priority |

---

## Targeting Score

The targeting score answers: *"If we set up a community job fair here this week, how much would it matter?"*

```
Targeting Score = (staffing_stress × 0.40)
               + (wage_gap       × 0.30)
               + (isolation      × 0.20)
               + (local_density  × 0.10)
```

- **staffing_stress:** Composite score above — how hard is this location actually hiring right now
- **wage_gap:** How much more local employers pay for the same role (pulls from wage_index table)
- **isolation:** Distance to nearest same-chain store — isolated locations have captive labor pools
- **local_density:** Number of local (non-chain) employers within 2 miles actively hiring in the same industry

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scan/status` | Last scrape metadata |
| `POST` | `/api/scan` | Trigger scrape `{chain, region, force}` |
| `GET` | `/api/scores?region=austin_tx` | All store scores for region |
| `GET` | `/api/targeting?industry=coffee_cafe&region=austin_tx&limit=10` | Ranked job fair candidates |
| `GET` | `/api/wage-index?industry=coffee_cafe&region=austin_tx` | Local vs chain pay comparison |
| `GET` | `/api/scheduler/status` | Next scheduled run times + last run results |
| `GET` | `/api/spiritpool/stats` | SpiritPool extension stats (legacy, unchanged) |

---

## Quickstart

```bash
# 1. Clone and set up
git clone <your-repo>
cd ChainStaffingTracker
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install flask flask-sqlalchemy flask-cors requests tqdm playwright \
            pyyaml apscheduler python-jobspy praw nltk pandas \
            google-maps-scraper

playwright install firefox
playwright install chromium --with-deps

# 3. (Optional) Set environment variables for higher rate limits
export REDDIT_CLIENT_ID="your_id"
export REDDIT_CLIENT_SECRET="your_secret"
export YELP_API_KEY="your_key"          # free at yelp.com/developers
export BLS_API_KEY="your_key"           # free at bls.gov/developers

# 4. Start the server
python server.py --debug

# 5. Run your first scrape (Austin TX, Starbucks)
python scrapers/careers_api.py --region austin_tx
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx
python scrapers/reddit_adapter.py --region austin_tx

# 6. Check targeting output
curl "http://localhost:8765/api/targeting?industry=coffee_cafe&region=austin_tx&limit=10"
```

---

## Configuration

All chain targets, scoring weights, and region definitions live in `config/chains.yaml`. No hardcoded values anywhere in the codebase.

Key sections:
- `regions:` — geographic targets with center coordinates and radius
- `chains:` — chain definitions with careers API endpoints and target keywords
- `industries:` — industry taxonomy with local employer search terms
- `scoring.weights` — composite score weights per source
- `scoring.posting_age_decay` — fresh/stale thresholds for careers API scoring
- `bls_series` — series IDs for Austin-area wage baselines

---

## Important Constraints

**Do not touch `spiritpool/`** — the browser extension is on hiatus. The code is preserved for future use once this pipeline has proven its value to the community.

**Do not touch `data/spiritpool.db`** — the extension database is separate from `data/tracker.db` and must stay intact.

**Public data only** — no logins, no paywalls, no bypassing access controls. The legal defensibility of this project depends on this constraint being absolute.

**Austin TX only for now** — build it right for one city before adding regions. The config system supports multi-region; the pipeline focuses on one.

---

## Background: Why This Exists

Chain employers capture labor from local communities while wages, benefits, and profits flow out. Local independent employers often pay more and keep money in the community but lack the recruiting infrastructure to compete.

This platform gives community organizers a data-driven way to time and place job fairs — specifically at chain locations where workers have the most leverage and local alternatives pay the most. The legal and ethical framework was designed carefully: everything is public data, all actions are protected commercial speech and labor market competition, and the mission is explicitly constructive (building local employment) rather than punitive.

The browser extension (SpiritPool) that adds crowdsourced signal to this pipeline is on hold until the scraping pipeline proves the concept and the project earns community trust. Reputation first, then ask people to install something.
