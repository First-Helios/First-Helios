# SpiritPool — Session 3 Handoff Document

**Date:** 2026-03-16  
**Author:** Agent session #3  
**Focus:** Cross-browser support, Chrome debugging, popup UI features, tracking controls

---

## 1. What Was Done This Session

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Highlight visual feedback on captured DOM elements | ✅ Done | `shared/highlight.js` — subtle blue glow, 10s natural decay, smooth taper |
| 2 | Cross-browser build system (Chrome + Safari) | ✅ Done | `build.sh` → `dist/{firefox,chrome,safari}/` |
| 3 | Browser polyfill for Chrome/Safari | ✅ Done | `compat/browser-polyfill.js` — shims `chrome.*` → `browser.*` |
| 4 | Chrome MV3 manifest | ✅ Done | `manifest.chrome.json` — `service_worker` background |
| 5 | Safari MV3 manifest | ✅ Done | `manifest.safari.json` |
| 6 | Fix Chrome match pattern error | ✅ Done | `web_accessible_resources` uses `https://www.google.com/*` |
| 7 | Fix `browser is not defined` on Chrome | ✅ Done | Polyfill injected into popup, options, and content scripts |
| 8 | Fix Chrome async message handler | ✅ Done | `sendResponse` + `return true` pattern (Chrome ignores async listeners) |
| 9 | Documentation updates | ✅ Done | `SPIRITPOOL_STARTUP.md`, `RUNBOOK.md` |
| 10 | Auto-flush interval → 10 minutes | ✅ Done | Was 15 min |
| 11 | 🔥 Burn button (clear all caches) | ✅ Done | Red button in popup flush section |
| 12 | Manual tracking toggle with 24h auto-re-enable | ✅ Done | Pause/resume via toggle, auto-resumes after 24h |

---

## 2. Current Architecture

```
                          ┌──────────────────────────────┐
                          │  Content Scripts (5 sites)    │
                          │  indeed / linkedin / glassdoor│
                          │  google-maps / starbucks      │
                          └──────────┬───────────────────┘
                                     │ browser.runtime.sendMessage
                                     ▼
                          ┌──────────────────────────────┐
                          │  background.js (service wkr)  │
                          │  ┌────────────────────────┐  │
                          │  │ Signal gates:           │  │
                          │  │  1. Consent given?      │  │
                          │  │  2. Tracking paused?    │  │
                          │  │  3. Site enabled?       │  │
                          │  └────────────────────────┘  │
                          │  Domain-separated caches      │
                          │  10-min flush alarm           │
                          └──────────┬───────────────────┘
                                     │ POST /api/spiritpool/contribute
                                     ▼
                          ┌──────────────────────────────┐
                          │  server.py (Flask, port 8765) │
                          │  backend/ingest.py → dedup    │
                          │  data/spiritpool.db (SQLite)  │
                          └──────────────────────────────┘
```

### Browser Support

| Browser | Source | Load from | Background model |
|---------|--------|-----------|-----------------|
| Firefox | `spiritpool/` (source of truth) | `spiritpool/` as temp add-on | `background.scripts` array |
| Chrome  | Built by `build.sh` | `dist/chrome/` | `service_worker` (polyfill prepended) |
| Safari  | Built by `build.sh` | `dist/safari/` → Xcode converter | `service_worker` (polyfill prepended) |

---

## 3. File Map (Extension — 4,255 lines)

### Core

| File | Lines | Purpose |
|------|-------|---------|
| `background.js` | 427 | Service worker: signal queue, consent, flush, pause, message handler |
| `compat/browser-polyfill.js` | 24 | Chrome/Safari shim: `chrome.*` → `browser.*` |
| `build.sh` | 136 | Cross-browser build script |

### Popup

| File | Lines | Purpose |
|------|-------|---------|
| `popup/popup.html` | 110 | Consent gate, main UI (stats, toggles, flush, burn, tracking toggle) |
| `popup/popup.js` | 297 | Popup controller: init, showMain, bindEvents, backend stats |
| `popup/popup.css` | 444 | Dark theme, toggle switches, button styles, backend grid |

### Content Scripts

| File | Lines | Purpose |
|------|-------|---------|
| `content/linkedin.js` | 641 | 3 extraction strategies, SPA navigation detection, dedup |
| `content/indeed.js` | 254 | Indeed job card extraction, `TARGET_COMPANIES` filter |
| `content/google-maps.js` | 198 | Google Maps store ratings & reviews |
| `content/starbucks-careers.js` | 189 | Starbucks careers portal extraction |
| `content/glassdoor.js` | 166 | Glassdoor job listing extraction |

### Shared Libraries

| File | Lines | Purpose |
|------|-------|---------|
| `shared/scanner.js` | 804 | DOM scanning framework, MutationObserver, rescan timer |
| `shared/parser.js` | 198 | Signal parsing & normalisation |
| `shared/highlight.js` | 108 | Blue glow visual feedback on captured elements (10s decay) |
| `shared/api.js` | 82 | Shared API helpers |
| `shared/consent.js` | 47 | Consent state utilities |
| `shared/selectors.json` | — | CSS selectors for each site (web-accessible resource) |

### Manifests

| File | Purpose |
|------|---------|
| `manifest.json` | Firefox MV3 — `gecko` settings, `background.scripts` |
| `manifest.chrome.json` | Chrome MV3 — `service_worker`, polyfill in content_scripts |
| `manifest.safari.json` | Safari MV3 — same structure as Chrome |

### Options

| File | Lines | Purpose |
|------|-------|---------|
| `options/options.html` | ~298 | Settings page |
| `options/options.js` | 266 | Options controller |

---

## 4. File Map (Backend — 1,144 lines)

| File | Lines | Purpose |
|------|-------|---------|
| `server.py` | 332 | Flask app factory, SQLAlchemy init, CORS, blueprint registration |
| `backend/models.py` | 148 | ORM models: Company, Location, Job, Observation, Contributor |
| `backend/ingest.py` | 256 | Signal ingestion: company/location/job dedup, observation creation |
| `backend/api.py` | 187 | REST endpoints: contribute, stats, jobs list, job detail |
| `backend/seed_test.py` | 221 | Seed script with 8 realistic LinkedIn + Indeed signals |

---

## 5. Message Protocol (popup/content → background.js)

All messages use `browser.runtime.sendMessage({ type, ...params })`.

| Message Type | Direction | Params | Response |
|---|---|---|---|
| `spiritpool:signal` | content → bg | `{ domain, signal }` | `{ ok, queued }` or `{ ok: false, reason }` |
| `spiritpool:getStatus` | popup → bg | — | `{ consent, stats, siteToggles, caches, trackingPause }` |
| `spiritpool:grantConsent` | popup → bg | — | `{ ok: true }` |
| `spiritpool:revokeConsent` | popup → bg | — | `{ ok: true }` (also clears caches) |
| `spiritpool:toggleSite` | popup → bg | `{ domain, enabled }` | `{ ok: true }` |
| `spiritpool:getDomainCache` | popup → bg | `{ domain }` | `{ signals, lastUpdate }` |
| `spiritpool:clearDomainCache` | popup → bg | `{ domain }` | `{ ok: true }` |
| `spiritpool:flushAll` | popup → bg | — | `{ ok: true }` or `{ ok: false, reason }` |
| `spiritpool:pauseTracking` | popup → bg | — | `{ ok: true }` |
| `spiritpool:resumeTracking` | popup → bg | — | `{ ok: true }` |
| `spiritpool:getBackendStats` | popup → bg | — | `{ ok, stats }` or `{ ok: false, reason }` |

### Chrome Async Handler Pattern

Chrome MV3 does not support returning a Promise from `onMessage`. The handler uses:

```javascript
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender).then(sendResponse, (err) =>
    sendResponse({ ok: false, reason: err.message })
  );
  return true; // keep channel open
});
```

---

## 6. Storage Keys (browser.storage.local)

| Key | Shape | Purpose |
|-----|-------|---------|
| `consent` | `{ given: bool, timestamp: ISO, version: 1 }` | User consent state |
| `siteToggles` | `{ "indeed.com": bool, ... }` | Per-site enable/disable |
| `stats` | `{ totalSignals, todaySignals, lastResetDate, lastFlush }` | Running counters |
| `trackingPause` | `{ paused: bool, pausedAt: ISO\|null }` | Manual pause state |
| `cache:<domain>` | `{ signals: [...], lastUpdate: ISO }` | Per-domain signal queue |
| `contributorId` | UUID string | Stable install identifier |

### Tracking Pause Behaviour

- **Pause:** User flips toggle off → `trackingPause = { paused: true, pausedAt: now }`
- **Resume:** User flips toggle on → `trackingPause = { paused: false, pausedAt: null }`
- **Auto-resume:** On next signal check, if `Date.now() - pausedAt >= 24h`, auto-clears pause
- **Gate location:** `handleMessage()` → signal handler, between consent check and site toggle check
- Pause does NOT clear cached signals — only prevents new signals from being accepted
- Flush still works while paused (existing cached signals can be sent)

---

## 7. Build System

```bash
cd spiritpool/
./build.sh              # all three targets
./build.sh chrome       # just Chrome
./build.sh firefox      # just Firefox
./build.sh safari       # just Safari
```

**Output:** `spiritpool/dist/{firefox,chrome,safari}/`

**What the build does:**
1. **Firefox:** Straight copy of source files + `manifest.json`
2. **Chrome/Safari:** Copies shared dirs, uses platform manifest, **prepends** `compat/browser-polyfill.js` to `background.js` (since `service_worker` only allows one file), includes polyfill as first JS in all `content_scripts`

**Safari extra step:**
```bash
xcrun safari-web-extension-converter dist/safari/ \
    --project-location spiritpool-safari-xcode --app-name SpiritPool
```

---

## 8. Popup UI Layout

```
┌─────────────────────────────────────┐
│  🌊 SpiritPool          [Active]    │  ← header + status badge (green/orange)
├─────────────────────────────────────┤
│  Tracking          resumes in 23h   │  ← tracking toggle + countdown
│                              [━━●]  │    (countdown only when paused)
├─────────────────────────────────────┤
│   42        1,287        5          │  ← stats (today / all time / queued)
├─────────────────────────────────────┤
│  Monitored Sites                    │
│  Indeed          3 cached    [━━●]  │  ← per-site toggles
│  LinkedIn Jobs   12 cached   [━━●]  │
│  Glassdoor       0 cached    [━━●]  │
│  Google Maps     1 cached    [━━●]  │
│  Starbucks       0 cached    [━━●]  │
├─────────────────────────────────────┤
│  Cached Signals                     │
│  Indeed                  3 signals  │
│  LinkedIn Jobs          12 signals  │
│  Google Maps             1 signal   │
├─────────────────────────────────────┤
│  [⚡ Flush Now]  [🔥 Burn]          │  ← action buttons
├─────────────────────────────────────┤
│  Server Database                    │
│   56      180      23      12       │  ← backend stats grid
│  Jobs    Obs    Companies  Last24h  │
├─────────────────────────────────────┤
│  Settings              Revoke       │  ← footer links
└─────────────────────────────────────┘
```

---

## 9. Known Issues / Gotchas

| Issue | Details |
|-------|---------|
| **Firefox manifest has path in match pattern** | `host_permissions` includes `https://www.google.com/maps/*` — valid for Firefox but Chrome requires this to be `https://www.google.com/*` in `web_accessible_resources` (already fixed in chrome/safari manifests) |
| **Content scripts are partially tested** | Only `linkedin.js` confirmed on live DOM; others (`indeed.js`, `glassdoor.js`, `google-maps.js`, `starbucks-careers.js`) are scaffolds |
| **No auth on backend API** | Contributor UUID is self-generated, no validation |
| **No rate limiting** | Backend accepts unlimited POST /contribute calls |
| **SQLite concurrency** | Single-writer — fine for local dev, needs migration for multi-user |
| **Observation dedup gap** | Retried flushes could create duplicate observation rows; no unique constraint on `(job_id, contributor_id, observed_at)` |
| **linkedin.js is verbose** | Heavy `console.log` output, diagnostic counters — not production-ready |
| **Alarm minimum** | Firefox MV3 may enforce a minimum alarm period of 1 minute |
| **Icons are placeholder** | `icons/icon-{16,48,128}.png` may be missing or placeholder |
| **Pause doesn't stop flush** | By design — pausing prevents new signal capture but doesn't block flushing already-cached signals |

---

## 10. Environment State

```
Python:    3.12.3 (in .venv/)
Packages:  flask, flask-sqlalchemy, flask-cors, requests, tqdm, playwright,
           jupyter, pandas, matplotlib, seaborn
DB:        data/spiritpool.db (SQLite, ~200 KB, has seeded data)
Server:    server.py on port 8765
Extension: spiritpool/ (source), dist/{firefox,chrome,safari}/ (built)
Node:      Required only for syntax-checking JS during development
```

### Quick Start

```bash
# Start backend
cd /home/fortune/CodeProjects/ChainStaffingTracker
source .venv/bin/activate
python server.py --debug

# Build extensions
cd spiritpool/
./build.sh

# Load in browser
# Firefox: about:debugging → Load Temporary Add-on → spiritpool/manifest.json
# Chrome:  chrome://extensions → Developer mode → Load unpacked → dist/chrome/
# Safari:  xcrun safari-web-extension-converter dist/safari/ ...
```

---

## 11. Scaling Analysis — Extension Size & Remote Selectors

### Current Measurements (5 sites)

| Component | Size | Notes |
|---|---|---|
| 5 content scripts | **45 KB** (~9 KB avg/site) | Only matched site's script loads per page |
| `selectors.json` | **10.6 KB** (~2 KB/site) | Loaded once by `scanner.js` |
| Shared libs (scanner, parser, highlight) | **39 KB** | Fixed cost, site-agnostic |
| **Whole extension** | **165 KB** | Including manifests, popup, options, icons |

### Projected at 100+ Sites

| Component | Projected | Performance impact? |
|---|---|---|
| Content scripts | ~900 KB on disk | **None** — browsers only inject the script whose `matches` hits the current URL; the other 99 sit on disk |
| `selectors.json` | ~200 KB | Loaded once into memory. Negligible |
| Extension download (.zip) | ~1.1 MB uncompressed | JS compresses ~70% → **~350 KB** from store. Trivial (uBlock Origin ships 10+ MB) |
| Manifest `content_scripts` entries | 100 entries | Parsed once at install. No runtime cost |

**Verdict: Extension size is NOT a performance concern at any realistic site count.**

### Where Remote Selectors DO Make Sense — Deployment Velocity

The real scaling pain is not size but **update speed**:

| Problem | Bundled selectors | Remote selectors |
|---|---|---|
| Site changes layout (selectors break) | Push extension update → wait for store review (1-3 days) | Update JSON on server → **instant fix** |
| Add a new site | New manifest entry + content script + store review | Add selectors to DB → extension auto-discovers |
| A/B test extraction strategies | Impossible without code change | Swap selector sets server-side |
| Rollback a broken selector | Full extension rollback | Revert one JSON record |

### Recommended Hybrid Architecture (Future)

The existing `selectors.json` separation from JS logic is halfway there. Target architecture:

```
┌──────────────────────────────────────────────────────────┐
│  Extension (static, rarely updated)                       │
│  ├── scanner.js        — generic DOM extraction engine    │
│  ├── parser.js         — signal normalisation             │
│  ├── highlight.js      — visual feedback                  │
│  └── bootstrap.js      — ONE content script for ALL urls  │
│       1. Checks current URL against backend site list     │
│       2. Fetches selector config for this domain          │
│       3. Feeds config to scanner.js                       │
└──────────────┬───────────────────────────────────────────┘
               │ GET /api/spiritpool/selectors?domain=linkedin.com
               ▼
┌──────────────────────────────────────────────────────────┐
│  Backend                                                  │
│  └── /api/spiritpool/selectors                            │
│       Returns selector JSON for the requested domain      │
│       (cached in extension storage with 24h TTL)          │
└──────────────────────────────────────────────────────────┘
```

**What stays in the extension:** The extraction *engine* (`scanner.js` — generic DOM walking). Site-agnostic, rarely changes.

**What moves to the backend:** Per-site *configuration* (`selectors.json` entries + site-specific quirks). This is what breaks when sites update their HTML.

**Trade-offs:**
- Extension needs `host_permissions` for `<all_urls>` or a broad set
- First page load adds a network round-trip (mitigated by caching in `browser.storage.local` with 24h TTL)
- Offline browsing degrades gracefully to last-cached selectors

**When to migrate:** Not needed now. Implement when you're actively adding sites frequently and store review latency becomes a bottleneck.

---

## 12. Suggested Next Steps

1. **Test content scripts on live sites** — `indeed.js`, `glassdoor.js`, `google-maps.js`, `starbucks-careers.js` need live DOM validation
2. **Add observation dedup guard** — unique constraint on `(job_id, contributor_id, observed_at)` or check before insert
3. **Add API auth** — at minimum, validate contributor UUID format; ideally, add API key or token
4. **Rate limiting** — throttle `/contribute` endpoint per contributor
5. **Production DB migration** — switch from SQLite to PostgreSQL or MS SQL Server via `DATABASE_URL`
6. **Extension icons** — design proper 16/48/128px icons
7. **Clean up console logging** — remove verbose debug output from content scripts
8. **Automated tests** — integration test that starts server, posts signals, asserts DB state
9. **Pause countdown live update** — currently the remaining time shown in popup is static; could use `setInterval` to tick down while popup is open
10. **Badge icon overlay** — show paused/active state on the extension toolbar icon itself
11. **Remote selectors endpoint** — `GET /api/spiritpool/selectors?domain=` when store review latency becomes a bottleneck (see §11 above)

---

## 13. Files Changed This Session

| File | Change |
|------|--------|
| `spiritpool/background.js` | Tracking pause logic, `sendResponse` pattern, 10-min flush, message types |
| `spiritpool/popup/popup.html` | Tracking toggle section, burn button, polyfill script tag |
| `spiritpool/popup/popup.js` | Pause/resume wiring, burn handler, badge state, `formatRemaining()` |
| `spiritpool/popup/popup.css` | Tracking toggle styles, burn button styles, paused badge colour |
| `spiritpool/compat/browser-polyfill.js` | **New** — Chrome/Safari `browser.*` shim |
| `spiritpool/manifest.chrome.json` | **New** — Chrome MV3 manifest |
| `spiritpool/manifest.safari.json` | **New** — Safari MV3 manifest |
| `spiritpool/build.sh` | **New** — Cross-browser build script |
| `spiritpool/shared/highlight.js` | **New** — Visual feedback overlay on captured elements |
| `spiritpool/options/options.html` | Added polyfill script tag |
| `SPIRITPOOL_STARTUP.md` | Cross-browser instructions, file map, seed section |
| `RUNBOOK.md` | Chrome/Safari troubleshooting, build commands |
