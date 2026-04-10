# Data Collection Guide — SpiritPool × First Helios

> How signals flow from a job board page into the database, how to configure collection, and how to use dev mode for pipeline debugging.

---

## 1. Signal Lifecycle (End-to-End)

```
┌─────────────────────────────────────────────────────────────────────┐
│ BROWSER (SpiritPool Extension)                                      │
│                                                                     │
│  LinkedIn page                                                      │
│    ↓                                                                │
│  content/linkedin.js → parseCard() extracts fields from DOM         │
│    ↓                                                                │
│  background.js → stamps collectedAt + tabUrl → encrypts (M3)       │
│    ↓                                                                │
│  cache:linkedin.com → encrypted AES-256-GCM blobs in storage       │
│    ↓  (flush every 10 min)                                          │
│  decrypt (M3) → sanitizeForTransmit (M4) → POST to backend         │
│                                                                     │
│  M4 sanitize:                                                       │
│    STRIP:  tabUrl, collectedAt, consent_state                       │
│    FUZZ:   salary ±5%, applicantCount ±5%, observedAt ±15min        │
│    ATTACH: session_token, epoch_id                                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ POST /api/spiritpool/contribute
                               │ {domain, signals[], contributorId, region}
┌──────────────────────────────▼──────────────────────────────────────┐
│ SERVER (First Helios — Flask on port 8765)                          │
│                                                                     │
│  strip_forbidden_fields() — defence-in-depth                        │
│    ↓                                                                │
│  _map_signal() → ScraperSignal (normalize wages, generate source)   │
│    ↓                                                                │
│  ingest_job_posting() → job_postings table (upsert)                 │
│    ↓                                                                │
│  _dual_write_to_sp_events() → PII scan                             │
│    ├─ clean → sp_events table                                       │
│    └─ PII detected → quarantine table                               │
│                                                                     │
│  If dev mode: _store_dev_capture() → dev_capture.raw_signals        │
└─────────────────────────────────────────────────────────────────────┘
```

### Field-level detail at each stage

| Field | Content Script | After M4 Sanitize | After Server Strip | In sp_events | In job_postings |
|-------|---------------|-------------------|-------------------|-------------|-----------------|
| company | Exact from DOM | Unchanged | Unchanged | In payload | raw_employer_name + normalized_name |
| jobTitle | Exact from DOM | Unchanged | Unchanged | In payload | role_title |
| salary.min | Exact from DOM | Fuzzed ±5% | Unchanged | In payload | wage_min (float) |
| location | Exact from DOM | Unchanged | Unchanged | In payload | raw_address + geocoded lat/lng |
| tabUrl | Tab URL | STRIPPED | Would be stripped again | Never stored | Never stored |
| collectedAt | Timestamp | STRIPPED | Would be stripped again | Never stored | Never stored |
| observedAt | Exact timestamp | Fuzzed ±15min | Unchanged | In payload | Not mapped |
| session_token | Not present | ATTACHED (UUID) | Unchanged | Column | Not mapped |

---

## 2. Production Mode (Helios Privacy Active)

In production mode, the privacy pipeline is fully active:

**What the extension sends:**
- Job metadata (company, title, location, salary, badges)
- Salary values fuzzed by ±5% to prevent exact-match linkability
- Temporal values fuzzed (observedAt ±15min, postingDate rounded to day)
- Session identity (session_token UUID, epoch_id integer)
- No tabUrl, no collectedAt, no consent_state

**What the server stores:**
- `sp_events`: Sanitized payload as JSONB, server-set collected_at timestamp
- `job_postings`: Normalized employer name, geocoded location, standardized wages
- `quarantine`: Any signal that tripped PII detection (email, phone, SSN, credit card)

**Privacy guarantees:**
- tabUrl is never stored anywhere — stripped by extension AND server
- collectedAt is never stored — server sets its own timestamp
- IP addresses are never logged — `_IPSuppressedRequest` returns `0.0.0.0`
- PII-containing signals go to quarantine, not production tables
- Session tokens are opaque — no reverse lookup to user identity

---

## 3. Dev Mode (Raw Comparison)

### Enabling dev mode

1. Open extension options page (right-click extension icon → Options)
2. Scroll to **Developer Settings** section
3. Toggle **Dev Capture Mode** on
4. The status indicator turns red: "Active — raw DOM data is being captured"

### What dev mode captures

When enabled, each signal includes three data layers:

| Layer | Contents | Stored In |
|-------|----------|-----------|
| Raw HTML | Full `outerHTML` of the job card DOM element | `dev_capture.raw_signals.raw_html` |
| Extracted | Pre-sanitization fields (exact parser output) | `dev_capture.raw_signals.extracted_fields` |
| Sanitized | Post-sanitization fields (fuzzed, stripped) | `dev_capture.raw_signals.sanitized_fields` |

### How it works

1. Content script captures `card.outerHTML` before sending signal to background
2. `sanitizeForTransmit()` deep-clones the signal before stripping/fuzzing
3. Both the pre-sanitization snapshot (`_dev_raw`) and the sanitized signal are sent to the server
4. Server extracts `_dev_raw` and stores it in `dev_capture.raw_signals`
5. The sanitized signal still flows through the normal production pipeline
6. Production tables (`sp_events`, `job_postings`) never see dev fields

### Using the notebook for A/B comparison

Open `notebooks/SpiritPoolDataAnalysis/sp_signal_explorer.ipynb` and run Section 10:

- **Salary fuzz verification**: Compare `extracted_fields.salary.min` vs `sanitized_fields.salary.min` — should differ by ≤5%
- **Time offset verification**: Compare `extracted_fields.observedAt` vs `sanitized_fields.observedAt` — should differ by ≤15 minutes
- **Field stripping verification**: `tabUrl` present in extracted, absent in sanitized
- **Raw HTML inspection**: View the actual DOM element to verify extraction accuracy

### Security notes

- Dev mode signals contain `tabUrl` (stored in `dev_capture` schema only)
- Never enable dev mode when collecting production/real-user data
- The `dev_capture` schema is completely separated from production tables
- Disable dev mode before deploying to production

---

## 4. Configuring Signal Collection

### Extension settings

| Setting | Where | Default |
|---------|-------|---------|
| Backend URL | Options → Developer Settings | `http://localhost:8765/api/spiritpool` |
| Region | Options → Developer Settings | `austin_tx` |
| Site toggles | Options → Site Collection | All enabled |
| Dev mode | Options → Developer Settings | Off |
| Flush interval | Hardcoded in background.js | 10 minutes |
| Max queue size | Hardcoded in background.js | 500 signals |

**For OrangePi deployment:** Set backend URL to `http://192.168.1.191/api/spiritpool`

### Server settings

| Setting | File | Value |
|---------|------|-------|
| Allowed domains | `postings/spiritpool_routes.py` | 16 job board domains |
| Max batch size | `postings/spiritpool_routes.py` | 50 signals per POST |
| PII patterns | `core/privacy.py` | email, phone, SSN, credit card |
| Forbidden fields | `core/privacy.py` | tabUrl, collectedAt, consent_state |
| CORS origins | `server.py` | chrome-extension://, moz-extension://, localhost:8765 |
| Port | `server.py` | 8765 (do not change) |

### OrangePi operations

```bash
# Check service status
sudo systemctl status helios helios-frontend nginx postgresql

# View API logs
sudo journalctl -u helios -f

# Check signal counts
psql -U helios -d helios -c "SELECT COUNT(*) FROM sp_events;"

# Check dev captures
psql -U helios -d helios -c "SELECT COUNT(*) FROM dev_capture.raw_signals;"

# Trigger manual code update
sudo systemctl start helios-update
```

---

## 5. Adding a New Job Board Source

### Step 1: Content script

Create `spiritpool/content/newsite.js` following the pattern in `indeed.js`:
- Use `document.querySelectorAll()` to find job cards
- Extract fields into a signal object: `company`, `jobTitle`, `location`, `salary`, etc.
- Send via `browser.runtime.sendMessage({ type: "spiritpool:signal", domain, signal })`
- In dev mode, attach `card.outerHTML` as `signal._dev_html`

### Step 2: Selectors

Add selectors to `spiritpool/shared/selectors.json` under the new domain key.

### Step 3: Manifest

Add the new site's URL pattern to `manifest.json` content scripts section.

### Step 4: Domain allowlist

Add the domain to `_ALLOWED_DOMAINS` in `postings/spiritpool_routes.py`.

### Step 5: Test with dev mode

1. Enable dev mode in extension options
2. Browse the new site
3. Check `dev_capture.raw_signals` for captures
4. Verify extracted fields match what's visible on the page
5. Run notebook Section 10 for A/B comparison
