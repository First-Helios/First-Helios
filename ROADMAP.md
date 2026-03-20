# Chain Staffing Tracker — Feature Roadmap

**Created:** 2026-03-15
**Purpose:** Long-term planning for a multi-source staffing intelligence platform

---

## 1. Project Vision

Build a system that estimates **real hiring pressure** at chain retail stores by fusing signals from multiple public sources — careers pages, job boards, social media, and customer reviews. The goal is not to count open listings (which are often standing requisitions) but to detect **when and where staffing stress is actually happening**.

### What We Know Today

After scanning 1,197 Starbucks stores across 8 US metros, we confirmed:

- The official careers API maintains **exactly 2 standing postings** per store (1 Barista + 1 Shift Supervisor) as standard practice
- **90% uniformity** — the data is effectively binary noise
- The only signal from this API is **temporal change** (when a store flips between 1 and 2 listings) and **posting age patterns**
- A single data source cannot produce meaningful hiring range estimates

**Implication:** We need multiple independent signals to triangulate actual staffing conditions.

---

## 2. Data Source Inventory

Each source has different strengths, access methods, and legal/ethical considerations.

### 2.1 Starbucks Careers API (Current — Implemented)

| Attribute | Detail |
|-----------|--------|
| **Endpoint** | `apply.starbucks.com/api/pcsx/search` |
| **Auth** | None |
| **Rate limit** | Moderate (1 req/s is safe) |
| **Signal quality** | Low — standing reqs, 2/store cap |
| **Useful signals** | Posting age, temporal flips (1↔2 listings), regional variation in single-listing rate |
| **Status** | ✅ Implemented, working |

### 2.2 Indeed / ZipRecruiter / Glassdoor

| Attribute | Detail |
|-----------|--------|
| **Access** | ~~Scraping (ToS-restricted)~~ → **Browser extension** (user-consented, see §2.8) |
| **Auth** | None needed — extension reads the page the user is already viewing |
| **Signal quality** | Medium-High — may have listings NOT on the official portal |
| **Useful signals** | Duplicate/cross-posted listings (urgency proxy), salary ranges, "urgently hiring" badges, number of applicants, posting freshness |
| **Legal risk** | **Low via extension** — user consents to share data from pages they visit. No bots, no ToS violation. |
| **Alternatives** | SerpAPI ($50/mo) as fallback if extension user base is insufficient |
| **Status** | ❌ Not implemented |

**Key question:** Do third-party boards have different listings than the official Starbucks portal, or just mirror them? This determines whether they add signal or just duplicate.

### 2.3 LinkedIn Jobs

| Attribute | Detail |
|-----------|--------|
| **Access** | ~~Scraping (heavy bot detection)~~ → **Browser extension** (user-consented, see §2.8) |
| **Auth** | None needed — user is already logged in; extension reads the rendered page |
| **Signal quality** | Medium — similar listings but has applicant count and "easy apply" metadata |
| **Useful signals** | Applicant count (high = available labor pool), reposting frequency, salary insights |
| **Legal risk** | **Low via extension** — no automated access to LinkedIn; user views page normally |
| **Status** | ❌ Not implemented |

### 2.4 Social Media — Reddit

| Attribute | Detail |
|-----------|--------|
| **Access** | Reddit API (free tier: 100 req/min with OAuth) |
| **Auth** | OAuth2 app credentials |
| **Subreddits** | r/starbucks, r/starbucksbaristas, r/starbuckspartners |
| **Signal quality** | High for sentiment, low for per-store granularity |
| **Useful signals** | "Short-staffed" complaint volume, regional hiring event mentions, wage discussion, turnover anecdotes, store-specific callouts |
| **Challenge** | Extracting store-level location from unstructured text |
| **Status** | ❌ Not implemented |

### 2.5 Social Media — X (Twitter)

| Attribute | Detail |
|-----------|--------|
| **Access** | X API v2 (Basic tier: $100/mo for search) |
| **Auth** | OAuth2 Bearer Token |
| **Signal quality** | Medium — customers complain publicly about wait times/closures |
| **Useful signals** | "This Starbucks is so understaffed" tweets (often geotagged or store-tagged), local hiring event promotions, store closure announcements |
| **Challenge** | Cost ($100/mo minimum for search), noise filtering, geolocation extraction |
| **Status** | ❌ Not implemented |

### 2.6 Google Maps / Yelp Reviews

| Attribute | Detail |
|-----------|--------|
| **Access** | Google Places API ($17/1K requests), Yelp Fusion API (free 5K/day), **or browser extension** (free, user-consented, see §2.8) |
| **Auth** | API key (direct) or none (extension) |
| **Signal quality** | Medium — customer-side signal, not hiring-side |
| **Useful signals** | Review sentiment about wait times, "always understaffed" mentions, sudden rating drops, "temporarily closed" flags, popular times data (proxy for demand) |
| **Legal/cost** | Google Places is paid; Yelp is ToS-restricted. Extension approach is free and avoids both issues. |
| **Status** | ❌ Not implemented |

### 2.7 Bureau of Labor Statistics (BLS) / Census

| Attribute | Detail |
|-----------|--------|
| **Access** | Free public APIs |
| **Signal quality** | Low granularity (metro-level, quarterly) but high reliability |
| **Useful signals** | Regional unemployment rate, food service sector employment trends, wage growth by MSA — contextualizes local labor market tightness |
| **Status** | ❌ Not implemented |

### 2.8 Browser Extension — Crowdsourced Data Collection

Instead of scraping job boards server-side (ToS violations, bot detection, legal risk), we provide a **browser extension that users voluntarily install**. Users consent to what data the extension collects, and it sends structured observations to our backend as they browse job sites naturally.

#### Why This Changes Everything

| Problem (Server-Side Scraping) | Solution (Extension) |
|------|------|
| Indeed ToS prohibits automated access | User is browsing normally — no bot, no automation |
| LinkedIn aggressive bot detection | Extension reads the already-rendered DOM in the user's authenticated session |
| Google Places API costs $17/1K requests | Extension reads the Google Maps page the user already loaded — free |
| Glassdoor API is deprecated | Extension parses the page directly |
| Need proxy rotation to avoid IP bans | Each user is a unique IP browsing at human speed |
| Rate limiting across sources | Distributed across N users — inherently rate-limited by human browsing speed |

#### Legal / Ethical Framework

The key legal distinction: **the user is the one accessing the website**, not our servers. The extension is a tool that helps the user share data they already have access to, with their explicit consent.

**Required consent layers:**

1. **Install-time disclosure** — Chrome Web Store listing clearly states what data is collected
2. **First-run consent modal** — On first activate, the extension shows:
   - Exactly which sites are observed (allowlist, not blanket surveillance)
   - What data is extracted (job title, salary range, store location — never passwords, PII, or browsing history)
   - That data is sent to our servers for aggregation
   - Link to privacy policy
   - Explicit opt-in checkbox (not pre-checked)
3. **Per-site toggle** — Users can enable/disable collection for individual sites
4. **Data transparency** — Extension popup shows what was sent and when

**What the extension NEVER collects:**
- Passwords, cookies, or session tokens
- Personal browsing history beyond the allowlisted job sites
- User PII (name, email, resume data)
- Any data from non-allowlisted domains

#### Prior Art

This model is well-established:

| Product | What Extension Collects | Users |
|---------|------------------------|-------|
| **Honey** (PayPal) | Coupon codes, prices, cart contents | 17M+ |
| **Glassdoor** | Salary data contributed by employees | Millions |
| **SimilarWeb** | Page visit telemetry (aggregated traffic data) | 10M+ |
| **Keepa** | Amazon product prices over time | 2M+ |
| **Wayback Machine** | Page snapshots on demand | Millions |

All operate legally with user consent. The common thread: **users volunteer data in exchange for a service** (for us: access to the staffing intelligence dashboard).

#### What the Extension Observes (Per Site)

**Indeed / ZipRecruiter / Glassdoor:**
```
When user views a job search results page:
  → Extract: job title, company, location, salary range, posting date,
             "urgently hiring" badge, applicant count, job ID
  → Ignore: user's resume, saved jobs, application history
```

**LinkedIn Jobs:**
```
When user views a job listing or search results:
  → Extract: job title, company, location, salary, applicant count,
             "Easy Apply" flag, posting date, repost indicator
  → Ignore: user profile, connections, messages, feed
```

**Google Maps (Starbucks store pages):**
```
When user views a Starbucks location on Google Maps:
  → Extract: store name, address, rating, review count, popular times,
             "temporarily closed" flag, recent review snippets
  → Ignore: user's location history, saved places, directions
```

**Starbucks Careers Page:**
```
When user views apply.starbucks.com job listings:
  → Extract: same data our server scraper gets, but from the user's browser
  → Benefit: supplements server-side scraping, fills gaps in coverage
```

#### Data Flow

```
User's Browser                           Our Backend
┌──────────────────────┐                 ┌──────────────────┐
│ Extension installed  │                 │                  │
│                      │                 │                  │
│ User browses Indeed  │                 │                  │
│ for "starbucks"      │                 │                  │
│          │           │                 │                  │
│  ┌───────▼────────┐  │   POST /api/    │  ┌────────────┐  │
│  │ Content Script  │──┼──contribute────►│  │ Ingestion  │  │
│  │ (DOM parser)    │  │   {signals[]}   │  │ Pipeline   │  │
│  └───────┬────────┘  │                 │  └─────┬──────┘  │
│          │           │                 │        │         │
│  ┌───────▼────────┐  │                 │  ┌─────▼──────┐  │
│  │ Popup UI       │  │                 │  │ SQLite DB  │  │
│  │ "Sent 3 jobs" │  │                 │  │ (signals)  │  │
│  └────────────────┘  │                 │  └────────────┘  │
└──────────────────────┘                 └──────────────────┘
```

#### Extension Architecture

```
extension/
├── manifest.json            # MV3 manifest (permissions, content scripts)
├── background.js            # Service worker: queue signals, batch POST to API
├── content/
│   ├── indeed.js            # Content script for indeed.com
│   ├── linkedin.js          # Content script for linkedin.com/jobs
│   ├── glassdoor.js         # Content script for glassdoor.com
│   ├── google-maps.js       # Content script for google.com/maps
│   └── starbucks-careers.js # Content script for apply.starbucks.com
├── popup/
│   ├── popup.html           # Extension popup UI
│   ├── popup.css
│   └── popup.js             # Shows contribution stats, consent toggle
├── options/
│   ├── options.html          # Per-site toggles, privacy settings
│   └── options.js
├── shared/
│   ├── consent.js            # Consent state management
│   ├── parser.js             # DOM extraction utilities shared across content scripts
│   └── api.js                # API client for POSTing signals to our backend
└── icons/
    ├── icon-16.png
    ├── icon-48.png
    └── icon-128.png
```

#### Chrome Web Store Requirements

- **Manifest V3** (required for new extensions since 2024)
- Must declare exact host permissions (not `<all_urls>`)
- Must have a clear privacy policy URL
- Must pass Chrome Web Store review (1-3 business days)
- Extension description must accurately describe all data collection
- Single-purpose policy: extension must do one thing (contribute job data)

#### Incentive Model — Why Users Install

Users need a reason to install. Options (not mutually exclusive):

1. **Free dashboard access** — Extension contributors get full access to the staffing intelligence dashboard (non-contributors see limited data)
2. **Contribution badges** — Gamification: "You've contributed 500 observations this month"
3. **Personal insights** — Show the user aggregated hiring trends for areas they're browsing (useful if they're job-hunting themselves)
4. **Altruism / transparency** — Some users install out of interest in labor market transparency (similar to Glassdoor's model)
5. **Research participation** — Frame it as open research into retail labor supply chains

#### Challenges & Mitigations

| Challenge | Mitigation |
|-----------|------------|
| Low initial user count = sparse data | Supplement with server-side careers API scraping (which is legal and already built). Extension data enriches, not replaces. |
| Data quality (users send bad data) | Schema validation on ingest. Require minimum fields. Cross-check against known store list. Dedup by (store, source, date). |
| DOM structure changes break parsers | Each content script is versioned. Extension auto-updates via Chrome Web Store. Ship parser updates without full extension review. |
| User privacy concerns | Aggressive data minimization. Open-source the extension code. Publish what's collected. Allow per-site opt-out. |
| Chrome Web Store rejection | Follow MV3 guidelines strictly. Minimal permissions. Clear privacy policy. No obfuscated code. |
| Gaming/spam (fake signal injection) | Rate limit per user. Anomaly detection on ingested signals. Require minimum browsing pattern (not just API calls). |

---

## 3. Feature Proposals — Grouped by Theme

### A. Scoring Model Redesign

The current weighted-sum model is provably useless (§2.3 of HANDOFF.md). Before adding sources, we need a model that can incorporate multiple signal types.

| Feature | Description | Depends On | Complexity |
|---------|-------------|------------|------------|
| **A1. Baseline-relative scoring** | Compute per-region norms (e.g. "90% have 2 listings"). Flag only deviations. Requires ≥3 snapshots per region. | History data | Medium |
| **A2. Posting age decay** | Weight listings by freshness. A 3-day-old posting contributes more signal than a 90-day standing req. Use `posted_ts` already captured. | None (data exists) | Low |
| **A3. Temporal velocity score** | Score = rate of change across snapshots. Stores that flip status frequently or gain/lose listings between scans score higher for instability. | ≥5 snapshots | Medium |
| **A4. Multi-source composite score** | Weighted fusion: careers API signal + job board signal + sentiment signal + review signal. Each source outputs a normalized 0–1 sub-score. | B-series, C-series | High |
| **A5. Hiring range estimation** | From salary data (Indeed/Glassdoor) + listing count + regional labor stats, estimate a plausible wage range that the store is offering. | B1, B3, 2.7 | High |

**Recommendation:** Start with **A1 + A2** (no new infrastructure needed — just algorithm changes on data we already have). Then A3 once we have enough history. A4/A5 come after additional sources are integrated.

### B. Additional Data Sources (Job Boards — via Extension)

| Feature | Description | Source | Complexity |
|---------|-------------|--------|------------|
| **B1. Indeed data via extension** | Extension content script extracts Starbucks listings from Indeed pages users browse. Compare listing counts with the official portal. No scraping, no ToS violation. | 2.2 + 2.8 | Medium |
| **B2. Cross-listing analysis** | Detect when a store posts on both the official site AND third-party boards — "cross-posting" is a possible urgency signal. | B1, existing | Medium |
| **B3. Salary range extraction** | Parse salary/wage data from board listings that include it. Track wage changes over time per region. | B1 | Low-Medium |
| **B4. Applicant count tracking** | Some boards show "X applicants" — low applicant counts on old postings suggest the store is struggling to attract candidates. | B1 | Low |

### C. Social Media & Sentiment

| Feature | Description | Source | Complexity |
|---------|-------------|--------|------------|
| **C1. Reddit sentiment pipeline** | Pull posts from Starbucks subreddits, classify as staffing-related, extract location when possible. | 2.4 | Medium-High |
| **C2. Keyword-based staffing signal** | Track volume of "short-staffed", "understaffed", "hiring event", "nobody wants to work" posts over time as a macro sentiment indicator. | 2.4/2.5 | Medium |
| **C3. Review sentiment analysis** | NLP on Google/Yelp reviews mentioning wait times, slow service, understaffed. Aggregate per store. | 2.6 | High |
| **C4. Store-level social mentions** | Match social posts to specific stores (address/store# mentions). Very noisy — may not be viable at scale. | C1, C2 | High |

### D. Infrastructure & Architecture

| Feature | Description | Why | Complexity |
|---------|-------------|-----|------------|
| **D1. SQLite database** | Replace JSON files with SQLite. Schema: `stores`, `snapshots`, `listings`, `signals`, `scores`. Enables proper querying, history retention, multi-region management. | JSON doesn't scale past ~5 regions or ~50 snapshots | Medium |
| **D2. Pluggable scraper architecture** | Abstract interface: `BaseScraper → StarbucksCareers, IndeedScraper, RedditScraper`. Each produces normalized `Signal` records. | Required before adding any new source | Medium |
| **D3. Scheduled scraping** | Cron/APScheduler — run each scraper at configurable intervals (e.g. careers API daily, Reddit weekly, reviews monthly). | Manual scanning doesn't scale | Low-Medium |
| **D4. Rate limit / backoff framework** | Centralized rate limiter per source. Exponential backoff. Optional proxy rotation for sources with aggressive bot detection. | Prevent bans, be a good citizen | Low |
| **D5. Multi-chain support** | Extend beyond Starbucks: configurable chain target (McDonald's, Chipotle, etc.). Each chain has its own careers API pattern. | Long-term value | High |
| **D6. Configuration system** | YAML/TOML config for API keys, scraper targets, schedule intervals, scoring weights. Currently everything is hardcoded. | Required for D3, D5, any API-key source | Low |

### E. Frontend & Visualization

| Feature | Description | Complexity |
|---------|-------------|------------|
| **E1. Per-store trend sparklines** | Tiny inline chart in the sidebar list and map popup showing a store's score trajectory over the last N scans. | Medium |
| **E2. Multi-region comparison** | Side-by-side or overlay view comparing staffing stress across regions (e.g. Austin vs Columbus). | Medium |
| **E3. Heatmap layer** | Color gradient overlay on the map showing staffing stress density, not just per-marker dots. | Medium |
| **E4. Signal source breakdown** | In the store detail popup, show which sources contributed to the composite score and how much each weighted. | Medium (requires A4) |
| **E5. Time-range filtering** | Slider or date picker to filter the trends chart to a specific time window. | Low |
| **E6. Export / API** | CSV/JSON export of current data. REST API for programmatic access to scores and history. | Low-Medium |
| **E7. Alerting system** | Configurable alerts: "notify me when region X exceeds threshold Y for Z consecutive scans." Email/webhook/browser notifications. | Medium-High |

### F. Browser Extension

| Feature | Description | Complexity |
|---------|-------------|------------|
| **F1. Extension scaffold (MV3)** | Manifest V3 skeleton: background service worker, popup UI, options page, consent flow. No content scripts yet. | Medium |
| **F2. Indeed content script** | DOM parser for Indeed job search results and detail pages. Extracts title, company, location, salary, posting date, applicant count, urgency badges. | Medium |
| **F3. LinkedIn content script** | DOM parser for LinkedIn Jobs. Extracts same fields + "Easy Apply" and repost indicators. | Medium |
| **F4. Google Maps content script** | DOM parser for Google Maps Starbucks pages. Extracts ratings, review count, popular times, closure flags, recent review text. | Medium-High |
| **F5. Starbucks Careers content script** | DOM parser for apply.starbucks.com. Supplements server-side scraper — same data, user-sourced. | Low |
| **F6. Signal batching & upload** | Background service worker queues extracted signals, batches them, POSTs to `/api/contribute` with retry logic. | Low-Medium |
| **F7. Popup dashboard** | Extension popup shows: sites enabled, signals sent today/total, last upload time, link to main dashboard. | Low |
| **F8. Consent & privacy system** | First-run modal, per-site toggles, data transparency log, privacy policy link. Required for Chrome Web Store. | Medium |
| **F9. Backend ingestion API** | New Flask endpoint `POST /api/contribute` — validates, deduplicates, and stores extension-sourced signals. Rate limiting per contributor. | Medium |
| **F10. Contributor identity** | Anonymous contributor IDs (no login required). Optional account linking for dashboard access incentive. | Low-Medium |

---

## 4. Proposed Implementation Phases

### Phase 0: Foundation (Current → Next)
**Goal:** Make existing data useful before adding complexity.

```
Priority  Feature   Effort    What
───────────────────────────────────────────────────────
   1      A2        2-3 hrs   Posting age decay scoring
   2      A1        4-6 hrs   Baseline-relative scoring (per-region norms)
   3      D1        6-8 hrs   SQLite database (replace JSON files)
   4      D6        2-3 hrs   Config file (YAML/TOML)
   5      E5        2-3 hrs   Time-range filter on trends chart
```

**Deliverable:** A scoring model that produces meaningful differentiation between stores, backed by a real database.

### Phase 1: Multi-Source Architecture
**Goal:** Build the plumbing for multiple data sources.

```
Priority  Feature   Effort     What
───────────────────────────────────────────────────────
   1      D2        6-8 hrs    Pluggable scraper interface
   2      D3        3-4 hrs    APScheduler for periodic runs
   3      D4        2-3 hrs    Rate limit / backoff framework
   4      A3        4-6 hrs    Temporal velocity scoring
   5      E1        4-5 hrs    Per-store trend sparklines
```

**Deliverable:** A system that can register N scrapers, run them on schedule, and store normalized signals in SQLite.

### Phase 2: Browser Extension + Job Board Data
**Goal:** Add a second independent hiring signal via crowdsourced extension data.

```
Priority  Feature   Effort     What
───────────────────────────────────────────────────────
   1      F1        6-8 hrs    Extension scaffold (MV3, consent, popup)
   2      F8        4-6 hrs    Consent & privacy system
   3      F2        6-8 hrs    Indeed content script
   4      F6+F9     6-8 hrs    Signal batching + backend ingestion API
   5      B3        3-4 hrs    Salary range extraction (from extension data)
   6      A4        8-12 hrs   Multi-source composite scoring
   7      E4        4-5 hrs    Signal source breakdown in UI
```

**Deliverable:** A Chrome extension that users install to contribute Indeed job data. Server ingests crowdsourced signals alongside careers API data. Two independent pipelines feed one composite score.

### Phase 3: Sentiment & Intelligence
**Goal:** Add qualitative signal from people talking about stores.

```
Priority  Feature   Effort     What
───────────────────────────────────────────────────────
   1      C1/C2     12-16 hrs  Reddit sentiment pipeline
   2      C3        12-16 hrs  Review sentiment (Google/Yelp)
   3      A5        8-12 hrs   Hiring range estimation model
   4      E3        6-8 hrs    Heatmap layer
   5      E7        8-12 hrs   Alerting system
```

**Deliverable:** Three-signal composite (careers + boards + sentiment) with hiring range estimates.

### Phase 4+: Scale & Expand
- **F3.** LinkedIn content script (extension)
- **F4.** Google Maps content script (reviews via extension)
- **D5.** Multi-chain support (McDonald's, Chipotle, Target, etc.)
- **E2.** Multi-region comparison views
- **E6.** Public API for programmatic access
- Integration with BLS/Census data for labor market context
- Predictive modeling (forecast staffing stress 2-4 weeks out)
- Extension for Firefox (WebExtensions API is compatible)
- Mobile browser extension (limited but possible on Firefox Android)

---

## 5. Architecture — Current vs Target

### Current Architecture

```
         ┌────────────────────┐
         │ Starbucks          │
         │ Careers API        │
         └────────┬───────────┘
                  │
         ┌────────▼───────────┐
         │ scraper/scrape.py  │
         │ (monolithic)       │
         └────────┬───────────┘
                  │ writes JSON
         ┌────────▼───────────┐
         │ frontend/data/     │
         │ vacancies.json     │
         │ history.json       │
         └────────┬───────────┘
                  │ serves static         ┌─────────────┐
         ┌────────▼───────────┐           │ Browser     │
         │ server.py (Flask)  │◄──────────│ (Leaflet    │
         │ scan API, history  │──────────►│  frontend)  │
         └────────────────────┘           └─────────────┘
```

**Problems:** Single scraper, JSON storage, no scheduling, monolithic scoring, no separation of data collection from scoring.

### Target Architecture (Phase 2+)

```
```
  SERVER-SIDE                              USER BROWSERS (Crowdsourced)
  (our infrastructure)                     (extension installed)

  ┌───────────┐  ┌───────────┐             ┌──────────────────────────┐
  │ Starbucks  │  │ Reddit    │             │ User browses Indeed,     │
  │ Careers    │  │ API       │             │ LinkedIn, Google Maps,   │
  │ (direct)   │  │ (direct)  │             │ Glassdoor, Starbucks.com │
  └─────┬──────┘  └─────┬─────┘             └────────────┬─────────────┘
        │               │                                │
  ┌─────▼──────┐  ┌─────▼─────┐              ┌───────────▼──────────┐
  │ Careers    │  │ Sentiment │              │ Browser Extension    │
  │ Scraper    │  │ Scraper   │              │ (MV3)                │
  └─────┬──────┘  └─────┬─────┘              │  ┌────────────────┐  │
        │               │                    │  │ Content Scripts │  │
        │               │                    │  │ indeed.js       │  │
        │               │                    │  │ linkedin.js     │  │
        │               │                    │  │ google-maps.js  │  │
        │               │                    │  │ starbucks.js    │  │
        │               │                    │  └───────┬────────┘  │
        │               │                    │          │           │
        │               │                    │  ┌───────▼────────┐  │
        │               │                    │  │ Service Worker  │  │
        │               │                    │  │ (batch + queue) │  │
        │               │                    │  └───────┬────────┘  │
        │               │                    └──────────┼───────────┘
        │               │                               │
        │    normalised signals          POST /api/contribute
        │               │                               │
        └───────┬───────┴───────────────────┬───────────┘
                │                           │
         ┌──────▼──────┐             ┌──────▼──────────┐
         │  Scheduler  │             │  SQLite DB      │
         │ (APScheduler│             │  stores         │
         │  / cron)    │             │  signals        │
         └─────────────┘             │  snapshots      │
                                     │  scores         │
                                     │  contributors   │
                                     └────┬────────────┘
                                          │
                                  ┌───────▼──────────┐
                                  │  Scoring Engine   │
                                  │  (multi-source    │
                                  │   composite)      │
                                  └───────┬──────────┘
                                          │
                                  ┌───────▼──────────┐         ┌──────────┐
                                  │  Flask API       │◄────────│ Frontend │
                                  │  /api/scores     │────────►│ (SPA)    │
                                  │  /api/signals    │         └──────────┘
                                  │  /api/trends     │
                                  │  /api/contribute │
                                  └──────────────────┘
```

---

## 6. Proposed Directory Structure (Target)

```
ChainStaffingTracker/
├── config.yaml                   # API keys, scraper schedules, scoring weights
├── server.py                     # Flask app (API + static serving)
├── ROADMAP.md                    # This file
├── HANDOFF.md                    # Agent handoff notes
├── RUNBOOK.md                    # Ops documentation
│
├── backend/
│   ├── __init__.py
│   ├── database.py               # SQLite schema, migrations, connection management
│   ├── scheduler.py              # APScheduler job definitions
│   └── scoring/
│       ├── __init__.py
│       ├── engine.py             # Composite scoring engine
│       ├── baseline.py           # Baseline-relative scoring (A1)
│       ├── temporal.py           # Temporal velocity scoring (A3)
│       └── hiring_range.py       # Hiring range estimation (A5)
│
├── scrapers/                     # Renamed from scraper/ — plural, multi-source
│   ├── __init__.py
│   ├── base.py                   # BaseScraper interface + Signal dataclass
│   ├── careers_api.py            # Starbucks careers API (refactored from scrape.py)
│   ├── reddit.py                 # Reddit sentiment pipeline (C1)
│   ├── geocoding.py              # Nominatim + overrides (extracted from scrape.py)
│   ├── geocode_overrides.json    # Manual coordinate overrides
│   └── explore_regions.py        # Research/probing tool
│
├── extension/                    # Chrome browser extension (MV3)
│   ├── manifest.json             # Permissions, content script declarations
│   ├── background.js             # Service worker: signal queue, batch upload
│   ├── content/
│   │   ├── indeed.js             # DOM parser for Indeed job pages
│   │   ├── linkedin.js           # DOM parser for LinkedIn Jobs
│   │   ├── glassdoor.js          # DOM parser for Glassdoor
│   │   ├── google-maps.js        # DOM parser for Google Maps store pages
│   │   └── starbucks-careers.js  # DOM parser for apply.starbucks.com
│   ├── popup/
│   │   ├── popup.html            # Contribution stats, site toggles
│   │   ├── popup.css
│   │   └── popup.js
│   ├── options/
│   │   ├── options.html          # Privacy settings, per-site consent
│   │   └── options.js
│   ├── shared/
│   │   ├── consent.js            # Consent state management
│   │   ├── parser.js             # Shared DOM extraction utilities
│   │   └── api.js                # Client for POST /api/contribute
│   └── icons/
│
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── app.js
│   │   ├── data.js
│   │   ├── map.js
│   │   ├── ui.js
│   │   ├── scan.js
│   │   └── trends.js
│   └── data/                     # Generated output (gitignored except samples)
│       ├── vacancies.json
│       └── history.json
│
├── data/                         # Database + persistent state
│   └── tracker.db                # SQLite database
│
└── tests/
    ├── test_scoring.py
    ├── test_scrapers.py
    └── fixtures/
        └── sample_careers_response.json
```

---

## 7. Database Schema (Phase 0 / D1)

Initial SQLite schema to replace JSON files:

```sql
-- Known store locations (OSM + geocoded career data)
CREATE TABLE stores (
    store_num    TEXT PRIMARY KEY,     -- "03347"
    store_name   TEXT NOT NULL,
    address      TEXT,
    lat          REAL,
    lng          REAL,
    region       TEXT,                 -- "Austin, TX, US"
    first_seen   TEXT,                 -- ISO8601
    last_seen    TEXT
);

-- Raw signals from any source
CREATE TABLE signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store_num    TEXT NOT NULL REFERENCES stores(store_num),
    source       TEXT NOT NULL,        -- "careers_api", "indeed", "reddit", "reviews"
    signal_type  TEXT NOT NULL,        -- "listing", "sentiment", "review_score", "wage"
    value        REAL,                 -- normalised numeric value
    metadata     TEXT,                 -- JSON blob for source-specific data
    observed_at  TEXT NOT NULL,        -- ISO8601 timestamp
    created_at   TEXT DEFAULT (datetime('now'))
);

-- Periodic snapshots (replaces history.json)
CREATE TABLE snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    region       TEXT NOT NULL,
    radius_mi    INTEGER,
    scanned_at   TEXT NOT NULL,
    summary      TEXT,                 -- JSON: {critical: N, low: N, ...}
    store_count  INTEGER
);

-- Computed scores (refreshed after each signal ingestion)
CREATE TABLE scores (
    store_num    TEXT NOT NULL REFERENCES stores(store_num),
    score_type   TEXT NOT NULL,        -- "composite", "careers", "sentiment", "temporal"
    value        REAL NOT NULL,
    level        TEXT,                 -- "critical", "low", "adequate", "unknown"
    computed_at  TEXT NOT NULL,
    PRIMARY KEY (store_num, score_type)
);

CREATE INDEX idx_signals_store ON signals(store_num, source, observed_at);
CREATE INDEX idx_signals_time  ON signals(observed_at);
CREATE INDEX idx_scores_level  ON scores(level);
```

---

## 8. Scraper Interface Contract (Phase 1 / D2)

```python
# scrapers/base.py — interface all scrapers implement

@dataclass
class Signal:
    """A single observation from any data source."""
    store_num:    str                  # store identifier
    source:       str                  # "careers_api", "indeed", "reddit"
    signal_type:  str                  # "listing", "sentiment", "wage", etc.
    value:        float                # normalised 0-1 or raw numeric
    metadata:     dict                 # source-specific payload
    observed_at:  datetime             # when this was observed

class BaseScraper(ABC):
    """Interface for all data source scrapers."""

    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this source."""

    @abstractmethod
    def scrape(self, region: str, radius_mi: int) -> list[Signal]:
        """
        Run a scrape for the given region.
        Returns a list of Signal objects (normalized).
        Must handle its own rate limiting and retries.
        """

    def schedule_interval(self) -> timedelta:
        """How often this scraper should run. Override per source."""
        return timedelta(days=1)
```

---

## 9. Key Design Decisions to Make

These are open questions that should be resolved before implementation begins for each phase.

### Before Phase 0 (Foundation)

1. **Scoring model shape:** Should the composite score be 0–100 (percentile), 0–1 (probability), or categorical (adequate/low/critical)? Percentile is more expressive; categorical is simpler for the UI.

2. **History retention policy:** How many snapshots per region to keep? Indefinite (disk grows linearly) or rolling window (e.g. 90 days)?

3. **Multi-region data model:** Separate DB tables per region, or one table with a `region` column? Single table is simpler but queries need filtering.

### Before Phase 1 (Multi-Source)

4. **Signal normalization:** How to make a "Reddit complaint volume" comparable to a "career listing count"? Options: z-scores, percentile ranks, or manual calibration weights.

5. **Scheduler choice:** APScheduler (in-process, simple) vs Celery (distributed, complex) vs plain cron (no dependencies). For a single-machine tool, APScheduler is likely sufficient.

6. **Scraper failure handling:** If one source is down, should the composite score degrade gracefully (use available sources) or refuse to score (require all sources)?

### Before Phase 2 (Extension + Job Boards)

7. **Extension access model:** Should the dashboard require an extension install (contributors-only) or be open to all with extension users getting enhanced data? Contributors-only drives installs but limits audience. Open access with a "contribute to see more" prompt is a middle ground.

8. **Deduplication:** The same listing may appear on the careers site AND Indeed (seen by extension users). Dedup strategy needed: (store # + role + date posted) or (job ID if available across platforms).

9. **Extension trust model:** How to handle potentially malicious signal submissions? Options: (a) validate against known store list (reject signals for non-existent stores), (b) require minimum browsing pattern per session (not just raw POSTs), (c) cross-validate across multiple contributors (consensus model), (d) contributor reputation score.

10. **Chrome Web Store review process:** Extensions collecting data require clear justification. Draft the privacy policy and store listing description before building. Plan for 1-3 day review cycles on each update.

### Before Phase 3 (Sentiment)

11. **NLP approach:** Rule-based keyword matching vs a lightweight classifier (e.g. DistilBERT). Keyword matching is transparent and fast; ML is more accurate but harder to debug and requires training data.

12. **Location extraction from social text:** Posts like "my store in downtown Austin" need entity resolution to map to a specific store. May not be feasible at high accuracy — acceptable to aggregate at city/region level instead?

---

## 10. What NOT to Build

Equally important is knowing what's out of scope to avoid wasted effort:

- **Real-time monitoring** — We don't need sub-minute data. Daily/weekly scraping is sufficient for staffing trends.
- **Internal HR data** — We only use publicly available data. No employee databases, no internal Starbucks systems.
- **Individual employee tracking** — We track store-level staffing, never individual people.
- **Automated decision-making** — This is an intelligence/visibility tool, not an automated hiring system.
- **Mobile app** — The web frontend is sufficient. No native iOS/Android.
- **ML-heavy prediction** — Until we have 6+ months of multi-source data, statistical models (rolling averages, z-scores) outperform ML on this problem.

---

## 11. Success Metrics

How to know the system is working:

| Metric | Current | Phase 0 Target | Phase 2 Target |
|--------|---------|-----------------|-----------------|
| Score distribution | 87% critical, 13% low | ≤30% in any one bucket | Normal-ish distribution |
| Data sources | 1 (careers API) | 1 (better scored) | 2–3 (careers + extension) |
| Extension contributors | 0 | 0 | 50+ active |
| Stores tracked | 109 (2 regions) | 500+ (5+ regions) | 2,000+ |
| Snapshot frequency | Manual | Daily (automated) | Daily |
| Actionable alerts | 0 (everything alerts) | Region-level deviations | Store-level anomalies |
| Hiring range estimate | None | None | ±$2/hr per region |

---

## 12. Current Codebase Inventory

For reference — what exists today and its condition:

| File | Lines | Status | Notes |
|------|-------|--------|-------|
| `server.py` | 311 | Stable | Flask app, scan API, history API |
| `scraper/scrape.py` | 651 | Working, needs refactor | Monolithic — scoring, geocoding, API, output all in one file |
| `scraper/explore_regions.py` | ~270 | Research tool | Multi-region probe, useful for validation |
| `scraper/geocode_overrides.json` | 15 entries | Stable | Manual coords for Nominatim-resistant addresses |
| `frontend/js/app.js` | 253 | Stable | Controller, search, vacancy reload |
| `frontend/js/data.js` | 378 | Stable | localStorage, haversine matching, caching |
| `frontend/js/map.js` | ~450 | Stable | Overpass fetch, Leaflet markers, popups |
| `frontend/js/ui.js` | 393 | Stable | Sidebar, stats, modal, toasts |
| `frontend/js/scan.js` | 266 | Stable | Scan panel, polling, region awareness |
| `frontend/js/trends.js` | 372 | Stable | Canvas chart, diff table, drill-down |
| `frontend/css/style.css` | 1221 | Stable | Dark theme, complete |
| `frontend/index.html` | 227 | Stable | SPA shell |
| **Total** | **~4,600** | | |

### Technical Debt

1. **`scrape.py` is monolithic** — scoring, geocoding, API access, and output serialization should be separate modules
2. **JSON file storage** — no indexing, no concurrent access safety, manual merge logic is fragile
3. **No tests** — zero test coverage
4. **Hardcoded constants** — API URLs, weights, thresholds, and paths are scattered across files
5. **`--merge` flag is brittle** — overwrites geocoded coords, no per-region timestamps, accumulates stale data
6. **Frontend has no build step** — fine for now, but limits ability to use TypeScript, bundling, or frameworks later
