# Chain Staffing Tracker — Runbook

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.12+ | `.venv/` is pre-created |
| pip packages | see below | Already installed |
| Firefox / Chrome / Safari | Any modern | For the SpiritPool extension |
| Playwright browser | Chromium headless | One-time install for the scraper |
| Xcode (macOS) | 15+ | Only needed to package for Safari |

All Python deps live in `.venv/`. If starting fresh:

```bash
python3 -m venv .venv
.venv/bin/pip install flask flask-sqlalchemy flask-cors requests tqdm playwright jupyter pandas matplotlib seaborn
.venv/bin/playwright install chromium --with-deps
```

---

## Start the stack

```bash
cd /home/fortune/CodeProjects/ChainStaffingTracker
.venv/bin/python server.py
```

Opens at **http://127.0.0.1:8765**

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port N` | `8765` | Listening port |
| `--host H` | `127.0.0.1` | Bind address (`0.0.0.0` to expose on LAN) |
| `--debug` | off | Flask auto-reload on file save |

```bash
# Examples
.venv/bin/python server.py --port 9000
.venv/bin/python server.py --debug          # dev — auto-reloads on save
.venv/bin/python server.py --host 0.0.0.0   # expose to local network
```

---

## Restart the server

```bash
# Kill whatever is holding the port, then restart
fuser -k 8765/tcp
.venv/bin/python server.py
```

Or if you used `--debug` (reloader runs two processes):

```bash
pkill -f "server.py"
.venv/bin/python server.py --debug
```

---

## Run a manual scrape (CLI)

The browser UI triggers the scraper automatically, but you can also run it directly:

```bash
.venv/bin/python scraper/scrape.py --location "Austin, TX, US" --radius 25
```

### Scraper flags

| Flag | Default | Description |
|------|---------|-------------|
| `--location / -l` | `Seattle, WA, US` | City to scrape |
| `--radius / -r` | `25` | Radius in miles |
| `--out / -o` | `frontend/data/vacancies.json` | Output path |
| `--no-geocode` | off | Skip Nominatim (faster, no lat/lng) |
| `--merge` | off | Merge into existing file instead of overwrite |
| `--verbose / -v` | off | Debug logging |

Output is written to `frontend/data/vacancies.json`. The server reloads this automatically when the UI polls after a scan.

---

## Scan freshness

- **Stale threshold:** 7 days (set in `server.py → STALE_AFTER_DAYS`)
- The **⚡ Force** button in the header bypasses the cooldown (dev use)
- Log of the last scraper run: `scraper/last_scan.log`

---

## Project layout

```
ChainStaffingTracker/
├── server.py                   Flask server (scraper API + SpiritPool API)
├── backend/
│   ├── models.py               SQLAlchemy models (5 tables)
│   ├── ingest.py               Signal ingestion + dedup
│   ├── api.py                  SpiritPool REST endpoints
│   └── seed_test.py            Seed DB with test data
├── data/
│   └── spiritpool.db           SQLite database (auto-created on first start)
├── Data Analysis/
│   └── spiritpool_analysis.ipynb  Jupyter notebook — query + visualise DB
├── scraper/
│   ├── scrape.py               Careers scraper
│   ├── probe_api.py            API discovery tool (Playwright)
│   └── last_scan.log           Output of most recent scrape (auto-created)
├── spiritpool/
│   ├── manifest.json           Firefox MV3 manifest
│   ├── manifest.chrome.json    Chrome MV3 manifest
│   ├── manifest.safari.json    Safari MV3 manifest
│   ├── build.sh                Cross-browser build → dist/{firefox,chrome,safari}/
│   ├── background.js           Service worker
│   ├── compat/
│   │   └── browser-polyfill.js browser.* shim for Chrome/Safari
│   ├── content/                Per-site DOM parsers
│   ├── shared/                 Shared utilities (highlight, scanner, parser)
│   ├── popup/                  Toolbar popup UI
│   └── options/                Settings page
├── frontend/
│   ├── index.html
│   └── js/ css/ data/
└── .venv/                      Python virtual environment
```

---

## SpiritPool extension

### Load in Firefox (no build needed)

```bash
# Firefox → about:debugging → Load Temporary Add-on → spiritpool/manifest.json
```

### Load in Chrome or Safari

```bash
cd spiritpool/
./build.sh chrome    # → dist/chrome/  (load unpacked in chrome://extensions)
./build.sh safari    # → dist/safari/  (then xcrun safari-web-extension-converter)
./build.sh           # builds all three
```

### Verify the pipeline

```bash
# 1. Start server
.venv/bin/python server.py --debug

# 2. Load extension in browser, grant consent, browse a job site
# 3. Click ⚡ Flush Now in the popup
# 4. Check the DB
curl http://localhost:8765/api/spiritpool/stats

# Or seed with test data directly (no extension needed)
.venv/bin/python backend/seed_test.py
```

---

## API reference (internal)

### Scraper / frontend

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/scan/status` | Last scan metadata, stale flag |
| `POST` | `/api/scan` | Start scrape `{location, radius, force}` |
| `GET`  | `/api/scan/log` | Tail of `last_scan.log` (last 8 KB) |

### SpiritPool

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/spiritpool/contribute` | Ingest signal batch `{domain, signals[], contributorId}` |
| `GET`  | `/api/spiritpool/stats` | Aggregate counts (jobs, observations, by source) |
| `GET`  | `/api/spiritpool/jobs` | Paginated listing `?page=&source=&company=&q=` |
| `GET`  | `/api/spiritpool/jobs/<id>` | Full job detail with observation history |
