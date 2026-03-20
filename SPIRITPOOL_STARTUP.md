# SpiritPool — Startup Guide

**Updated:** 2026-03-16  
**Component:** SpiritPool browser extension (Firefox, Chrome, Safari) + SQL backend  
**Purpose:** Getting local data collection into SQLite up and running

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.12+ | Ships with the `.venv/` |
| pip packages | see below | Already installed in `.venv/` |
| **Firefox** | 121+ | Load directly from `spiritpool/manifest.json` — no build step |
| **Chrome** | Any modern | Load `dist/chrome/` after running `build.sh` |
| **Safari** | macOS 14+ | Run `xcrun safari-web-extension-converter dist/safari/` after building |
| Node.js | Any | Optional — only needed for `node -c` syntax checks |
| Xcode | 15+ | Required for Safari only (wraps extension in a native app) |

### One-time venv setup (if starting fresh)

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker
python3 -m venv .venv
.venv/bin/pip install flask flask-sqlalchemy flask-cors requests tqdm playwright jupyter pandas matplotlib seaborn
```

---

## 1. Start the Backend Server

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker
.venv/bin/python server.py --debug
```

This does three things on startup:
1. Creates `data/spiritpool.db` (SQLite) if it doesn't exist
2. Runs `db.create_all()` to ensure all 5 tables are present
3. Serves the SpiritPool API at `http://localhost:8765/api/spiritpool/`

The DB file lives at: `data/spiritpool.db`

### Verify the server is running

```bash
curl http://localhost:8765/api/spiritpool/stats
# Expected: {"by_source":{},"observations_last_24h":0,"total_companies":0,"total_jobs":0,"total_observations":0}
```

---

## 2. Load the Extension

### Firefox (quickest — no build step)

1. Open Firefox → `about:debugging#/runtime/this-firefox`
2. Click **"Load Temporary Add-on…"**
3. Select `spiritpool/manifest.json`
4. Click the **SpiritPool** toolbar icon → **Grant Consent**

### Chrome

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker/spiritpool
./build.sh chrome
```

1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (toggle, top right)
3. Click **"Load unpacked"** → select `spiritpool/dist/chrome/`
4. Click the **SpiritPool** toolbar icon → **Grant Consent**

### Safari (macOS)

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker/spiritpool
./build.sh safari
xcrun safari-web-extension-converter dist/safari/ \
    --project-location spiritpool-safari-xcode \
    --app-name SpiritPool
```

1. Build and run the generated Xcode project (`Cmd+B` then `Cmd+R`)
2. In Safari → Settings → Extensions → enable **SpiritPool**
3. Grant access to allowlisted sites when prompted
4. Click the **SpiritPool** toolbar icon → **Grant Consent**

### Build all targets at once

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker/spiritpool
./build.sh          # produces dist/{firefox,chrome,safari}/
```

### Verify the extension loaded

Open the **Extension Console** (Firefox: about:debugging → Inspect; Chrome: chrome://extensions → service worker link):
- You should see: `[SpiritPool] Background service worker loaded.`

---

## 3. Collect Data

1. Navigate to `https://www.linkedin.com/jobs/search/?keywords=starbucks`
2. Open the browser Console (F12 → Console tab), filter by `[SP/LI]`
3. You should see within ~3 seconds:
   ```
   [SP/LI] Scan #1 summary: 53 total, 25 new, 0 already sent, 28 cross-strategy duplicates
   [SP/LI] ✅ Sent 25/25 new signals to cache
   ```
4. Signals are now in `browser.storage.local` under key `cache:linkedin.com`

### Trigger a flush to SQL

Flush happens automatically every 15 minutes via alarm, or immediately if the cache exceeds 500 signals.

**Option A — Popup button (easiest):**
1. Click the SpiritPool toolbar icon
2. Click **⚡ Flush Now**
3. The popup updates to show live server DB counts (jobs, observations, companies)

**Option B — Extension console:**
1. Open the Extension Console (Firefox: about:debugging → Inspect)
2. Run:
   ```js
   await flushAllDomains();
   ```
3. You should see:
   ```
   [SpiritPool] Flushing 25 signals for linkedin.com → backend...
   [SpiritPool] ✅ Flushed linkedin.com: 25 accepted, 25 new jobs
   ```

### Verify data landed in SQL

```bash
# Quick check via the API
curl http://localhost:8765/api/spiritpool/stats
curl http://localhost:8765/api/spiritpool/jobs | python3 -m json.tool | head -40

# Or inspect the DB directly
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/spiritpool.db')
for table in ['companies','jobs','observations','locations','contributors']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{table}: {count} rows')
conn.close()
"
```

---

## 4. API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/spiritpool/contribute` | Receive signal batch `{domain, signals[], contributorId}` |
| `GET`  | `/api/spiritpool/stats` | Aggregate counts (jobs, observations, by source) |
| `GET`  | `/api/spiritpool/jobs` | Paginated listing `?page=1&per_page=50&source=&company=&q=` |
| `GET`  | `/api/spiritpool/jobs/<id>` | Full job detail with observation history |

### Contribute payload shape

```json
{
  "domain": "linkedin.com",
  "contributorId": "a1b2c3d4-...",
  "signals": [
    {
      "source": "linkedin.com",
      "signalType": "listing",
      "company": "Starbucks",
      "jobTitle": "barista - Store# 12345",
      "location": "Seattle, WA",
      "salary": { "min": 16.5, "max": 21.0, "period": "hourly" },
      "postingDate": "2025-01-15T00:00:00Z",
      "applicantCount": 42,
      "badges": ["Easy Apply"],
      "url": "https://www.linkedin.com/jobs/view/4100123456",
      "observedAt": "2025-01-20T10:30:00Z",
      "jobId": "4100123456"
    }
  ]
}
```

---

## 5. Database Schema

SQLite file: `data/spiritpool.db`  
Switch to MS SQL Server: set `DATABASE_URL=mssql+pyodbc://user:pass@server/dbname?driver=ODBC+Driver+17+for+SQL+Server`

### Tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `companies` | Deduplicated company records | `name`, `name_normalised` (unique) |
| `locations` | Normalised location strings | `normalised` (unique), `city`, `state`, `is_remote` |
| `jobs` | Unique job postings | `source + source_job_id` (unique), `company_id` FK, `first_seen`, `last_seen` |
| `observations` | Point-in-time snapshots | `job_id` FK, `salary_min/max`, `applicant_count`, `badges`, `observed_at` |
| `contributors` | Anonymous extension installs | `uuid` (unique), `total_signals` |

### Key relationships

```
companies 1──N jobs 1──N observations N──1 locations
                                      N──1 contributors
```

The same job seen twice creates **1 job row + 2 observation rows** — this captures how salary, applicant count, and badges change over time.

---

## 6. Seed the Database (optional)

To populate the DB with test data without running the extension:

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker
.venv/bin/python backend/seed_test.py
```

This posts 8 realistic signals (LinkedIn + Indeed, Starbucks/Dutch Bros/Peet's) directly to the backend API and prints accepted/new counts.

---

## 7. Data Analysis Notebook

A pre-built Jupyter notebook queries the live SQLite DB and produces charts:

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker
.venv/bin/jupyter notebook "Data Analysis/spiritpool_analysis.ipynb"
```

Sections:
1. DB overview (row counts per table)
2. Jobs by source (bar chart)
3. Top companies (bar chart)
4. Observations over time (line chart)
5. Salary distribution (hourly + yearly histograms)
6. Top locations (bar chart)
7. Job freshness (first seen vs. last seen scatter)
8. Full jobs table

---

## 8. Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: flask_sqlalchemy` | `.venv/bin/pip install flask-sqlalchemy flask-cors` |
| Extension shows "consent not granted" | Click the SpiritPool toolbar icon → Grant Consent |
| Flush says "backend offline" | Make sure `server.py` is running on port 8765 |
| No signals extracted on LinkedIn | Ensure you're on `/jobs/search/` page, wait 3s for Ember hydration |
| DB file missing | Server creates it automatically on startup in `data/` |
| Port 8765 already in use | `fuser -k 8765/tcp` then restart server |
| Chrome extension not loading | Enable Developer mode in `chrome://extensions` |
| Safari extension not appearing | Run the Xcode project first, then check Safari → Settings → Extensions |
| `xcrun: invalid active developer path` | `xcode-select --install` |

---

## 9. File Map

```
ChainStaffingTracker/
├── server.py                          Flask server (scan API + SpiritPool API)
├── backend/
│   ├── __init__.py
│   ├── models.py                      SQLAlchemy models (5 tables)
│   ├── ingest.py                      Signal → normalised DB rows
│   ├── api.py                         REST endpoints (/api/spiritpool/*)
│   └── seed_test.py                   Seeds DB with realistic test data
├── data/
│   └── spiritpool.db                  SQLite database (auto-created)
├── Data Analysis/
│   └── spiritpool_analysis.ipynb      Jupyter notebook (8 query/viz sections)
├── spiritpool/
│   ├── manifest.json                  Firefox MV3 manifest (source of truth)
│   ├── manifest.chrome.json           Chrome MV3 manifest
│   ├── manifest.safari.json           Safari MV3 manifest
│   ├── build.sh                       Cross-browser build script → dist/
│   ├── background.js                  Service worker (cache + flush)
│   ├── compat/
│   │   └── browser-polyfill.js        browser.* → chrome.* shim for Chrome/Safari
│   ├── content/
│   │   ├── linkedin.js                LinkedIn scraper
│   │   ├── indeed.js                  Indeed scraper
│   │   ├── glassdoor.js               Glassdoor scraper
│   │   ├── google-maps.js             Google Maps scraper
│   │   └── starbucks-careers.js       Starbucks careers scraper
│   ├── shared/
│   │   ├── highlight.js               Visual fade on captured elements
│   │   ├── scanner.js                 MutationObserver DOM scanner
│   │   ├── parser.js                  DOM extraction utilities
│   │   ├── api.js                     Message passing client
│   │   ├── consent.js                 Consent state helpers
│   │   └── selectors.json             Per-domain CSS selector configs
│   ├── popup/                         Toolbar popup (stats, ⚡ Flush Now, server DB counts)
│   ├── options/                       Extension settings page
│   └── dist/                          Build output (gitignored)
│       ├── firefox/
│       ├── chrome/
│       └── safari/
├── RUNBOOK.md                         Server startup + scraper docs
├── SPIRITPOOL_STARTUP.md              ← THIS FILE
├── SPIRITPOOL_HANDOFF.md              Agent session handoff notes
└── HANDOFF.md                         Previous agent handoff (risk scoring)
```
