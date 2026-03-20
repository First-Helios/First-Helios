# SpiritPool — Browser Extension

**Crowdsourced staffing intelligence for chain retail stores.**

SpiritPool is a cross-browser extension (Firefox, Chrome, Safari) that passively collects job listing metadata as you browse allowlisted sites (Indeed, LinkedIn, Glassdoor, Google Maps, Starbucks Careers). Data is stored locally in domain-separated caches and sent to the backend only when consent is granted and a flush is triggered.

## Supported Browsers

| Browser | Manifest Version | Status |
|---------|-----------------|--------|
| **Firefox** | MV3 (`background.scripts`) | Primary — source uses `browser.*` natively |
| **Chrome** | MV3 (`service_worker`) | Built via `build.sh` — polyfill maps `chrome.*` → `browser.*` |
| **Safari** | MV3 (`service_worker`) | Built via `build.sh` — wrap with `xcrun safari-web-extension-converter` |

## Architecture

```
spiritpool/
├── manifest.json              # Firefox MV3 manifest (source of truth)
├── manifest.chrome.json       # Chrome MV3 manifest
├── manifest.safari.json       # Safari MV3 manifest
├── build.sh                   # Cross-browser build script → dist/
├── background.js              # Service worker: signal queue, domain caches, consent
├── compat/
│   └── browser-polyfill.js    # Tiny shim: globalThis.browser = chrome
├── content/
│   ├── indeed.js              # DOM parser for Indeed job listings
│   ├── linkedin.js            # DOM parser for LinkedIn Jobs
│   ├── glassdoor.js           # DOM parser for Glassdoor
│   ├── google-maps.js         # DOM parser for Google Maps store pages
│   └── starbucks-careers.js   # DOM parser for apply.starbucks.com
├── popup/
│   ├── popup.html             # Extension popup (stats, toggles, consent)
│   ├── popup.css
│   └── popup.js
├── options/
│   ├── options.html           # Full settings page (privacy, data log, export)
│   └── options.js
├── shared/
│   ├── consent.js             # Consent state helpers
│   ├── highlight.js           # Visual feedback on captured elements
│   ├── parser.js              # Shared DOM extraction utilities
│   ├── scanner.js             # MutationObserver-based DOM scanner
│   ├── api.js                 # Message passing client (content → background)
│   └── selectors.json         # CSS selectors for each site
├── icons/
│   ├── icon-16.png
│   ├── icon-48.png
│   └── icon-128.png
└── dist/                      # Build output (gitignored)
    ├── firefox/
    ├── chrome/
    └── safari/
```

## How It Works

1. **User installs** the extension and grants consent via a first-run modal
2. **Content scripts** run on allowlisted sites, extracting structured job/store data from the DOM
3. **Signals** are sent to the background worker via `browser.runtime.sendMessage`
4. **Background worker** validates consent + per-site toggle, then stores signals in **domain-separated caches** (`browser.storage.local`)
5. **Popup** shows real-time stats (signals today, total, per-domain queue sizes)
6. **Options page** provides per-site toggles, data log transparency, JSON export, and cache management

## Data Storage

All data lives in `browser.storage.local` under domain-namespaced keys:

| Key | Contents |
|-----|----------|
| `cache:indeed.com` | `{ signals: [...], lastUpdate: ISO }` |
| `cache:linkedin.com` | `{ signals: [...], lastUpdate: ISO }` |
| `cache:glassdoor.com` | `{ signals: [...], lastUpdate: ISO }` |
| `cache:google.com/maps` | `{ signals: [...], lastUpdate: ISO }` |
| `cache:apply.starbucks.com` | `{ signals: [...], lastUpdate: ISO }` |
| `consent` | `{ given: bool, timestamp: ISO, version: 1 }` |
| `siteToggles` | `{ "indeed.com": true, ... }` |
| `stats` | `{ totalSignals, todaySignals, lastResetDate, lastFlush }` |

Domains are kept separate so disabling a site immediately clears only its data. Revoking consent clears everything.

## Loading in Firefox

1. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`
2. Click **"Load Temporary Add-on..."**
3. Select `spiritpool/manifest.json` (or `dist/firefox/manifest.json` after building)
4. The extension icon appears in the toolbar — click it to grant consent and start

## Loading in Chrome

1. Run `./build.sh chrome` from the `spiritpool/` directory
2. Open Chrome and navigate to `chrome://extensions`
3. Enable **Developer mode** (toggle in top right)
4. Click **"Load unpacked"** and select the `dist/chrome/` directory
5. The extension icon appears in the toolbar

## Loading in Safari (macOS)

1. Run `./build.sh safari` from the `spiritpool/` directory
2. Generate the Xcode project:
   ```bash
   xcrun safari-web-extension-converter dist/safari/ \
       --project-location spiritpool-safari-xcode \
       --app-name SpiritPool
   ```
3. Open the generated Xcode project and build it (`Cmd+B`)
4. In Safari → Settings → Extensions, enable **SpiritPool**
5. Grant the extension access to the allowlisted sites when prompted

## Building

```bash
cd spiritpool/

# Build all targets
./build.sh

# Build one target
./build.sh firefox
./build.sh chrome
./build.sh safari
```

Output goes to `dist/{firefox,chrome,safari}/` — each is a self-contained, loadable extension directory.

### How the build works

- **Firefox**: straight copy — `browser.*` is native
- **Chrome/Safari**: the polyfill (`compat/browser-polyfill.js`) is prepended to `background.js` and added first in every `content_scripts` entry via the platform manifest. This aliases `chrome.*` → `browser.*` so all source code is shared.

## What Gets Collected

| Site | Data Extracted |
|------|---------------|
| **Indeed** | Job title, company, location, salary, posting date, applicant count, urgency badges, job ID |
| **LinkedIn Jobs** | Job title, company, location, salary, applicant count, Easy Apply flag, repost indicator |
| **Glassdoor** | Job title, company, location, salary estimate, rating |
| **Google Maps** | Store name, address, rating, review count, popular times, closure flag, staffing-related review snippets |
| **Starbucks Careers** | Job title, store location, posting date, job ID, category |

## What Is NEVER Collected

- Passwords, cookies, or session tokens
- Browsing history beyond the 5 allowlisted sites
- Personal information (name, email, resume, applications)
- Data from non-allowlisted domains

## Future: Backend Integration

The background worker flushes cached signals to `POST /api/spiritpool/contribute` on the local backend (port 8765). Flushing happens automatically every 15 minutes, when the queue exceeds 500 signals, or manually via the "Flush Now" button in the popup.

## Development

Source code is shared across all platforms. Edit files in the `spiritpool/` root, then run `./build.sh` to produce loadable packages.

- Edit content scripts to adjust DOM selectors when sites change layouts
- Shared utilities in `shared/` reduce duplication across content scripts
- The popup and options pages share the same domain list for consistency
- The `compat/browser-polyfill.js` is a 4-line shim — no heavy dependencies
