> **ARCHIVED 2026-04-21.** Alpha-readiness gaps from 2026-04-05; most items resolved. Re-triage before acting on anything here.

> **Date:** 2026-04-05
> **Scope:** Changes needed in the SpiritPool extension repo (`/home/fortune/CodeProjects/SpiritPool/`) to reach alpha readiness with First-Helios backend.

---

## Context

First-Helios backend (Tiers 1-4 complete, 191+ tests) is alpha-ready. The extension still has two integration gaps that prevent the full pipeline from working end-to-end. These are extension-side fixes only — no backend changes needed.

The legacy dual-write path (`POST /api/spiritpool/contribute`) is the alpha data path. The new per-signal endpoint (`POST /api/contribute`) is ready for post-alpha migration.

---

## Gap 1: Burn Endpoint URL (HIGH)

**File:** `spiritpool/shared/session.js` line 222-224

**Problem:** `burnCurrentSession()` constructs the burn URL as `${url}/burn` where `url` defaults to `http://localhost:8765/api/spiritpool`. This hits `/api/spiritpool/burn` which does not exist. The burn endpoint is at `/api/burn`.

**Fix:**
```javascript
// BEFORE (line 222-224):
const { backendUrl } = await browser.storage.local.get('backendUrl');
const url = (backendUrl || 'http://localhost:8765/api/spiritpool').replace(/\/$/, '');
await fetch(`${url}/burn`, { ... });

// AFTER:
const { backendUrl } = await browser.storage.local.get('backendUrl');
const baseUrl = (backendUrl || 'http://localhost:8765').replace(/\/api\/spiritpool\/?$/, '');
await fetch(`${baseUrl}/api/burn`, { ... });
```

**Impact:** Burn mechanism currently fails silently (best-effort fetch). Fix makes burns work end-to-end.

---

## Gap 2: Ed25519 Public Key Null (MEDIUM — defer past alpha)

**File:** `spiritpool/config-verify.js` line 42

**Problem:** `PINNED_PUBLIC_KEY_RAW = null`. Remote config signature verification is dead — `verifyAndApplyConfig()` always rejects.

**Impact for alpha:** Low. Bundled selectors work as fallback. Remote config is a nice-to-have for fast iteration on new site support.

**Fix (post-alpha):** Generate Ed25519 keypair, inject public key into extension, set up signing pipeline for config updates.

---

## Post-Alpha: Migrate to Per-Signal Endpoint

**Current flow:**
```
sanitizeForTransmit(signal) → flushDomain() batches signals →
POST /api/spiritpool/contribute {domain, signals[], contributorId, region} →
spiritpool_routes.contribute() → ingest_job_posting() + _dual_write_to_sp_events()
```

**Target flow (post-alpha):**
```
sanitizeForTransmit(signal) → flushDomain() sends per-signal →
POST /api/contribute {session_token, epoch_id, event_type, source, domain, payload} →
contribute_routes.contribute() → direct to sp_events
```

**File:** `spiritpool/background.js` — `flushDomain()` function (lines 544-629)

**What changes:**
1. Instead of batching signals with `{domain, signals, contributorId, region}`, send each signal individually with the new schema
2. Map `session_token` and `epoch_id` (already attached by M4 sanitize.js) to top-level fields
3. Set `event_type` based on signal type (default `"job_listing"`)
4. Set `source` to domain slug (e.g., `"indeed"`)
5. Set `domain` to `"jobs"` (or appropriate domain category)
6. Wrap extraction data in `payload` dict
7. Change URL from `${backendUrl}/contribute` to base URL `/api/contribute`

**Why defer:** The legacy dual-write path works for alpha. The backend now preserves real M7 session_token and epoch_id through the legacy path, so session management is not lost.

---

## Session Token Note

As of this session, `_dual_write_to_sp_events()` in `spiritpool_routes.py` now preserves the real `session_token` and `epoch_id` from M7's `sanitizeForTransmit()` when present in the signal. Falls back to `legacy_{contributorId}` and `epoch_id=1` for pre-M7 extension versions. This means:

- Token rotation works through the legacy path
- Burns will match the correct session_token
- 64-char hex tokens (Second Helios) will flow through correctly
- Forward-compatibility is maintained

---

## Verification After Gap 1 Fix

```bash
# In SpiritPool repo: run existing tests
npm test

# Manual test:
# 1. Start First-Helios server (python server.py)
# 2. Load extension in browser
# 3. Browse a job board, let signals flush
# 4. Trigger burn from extension popup
# 5. Verify /api/burn receives the POST (check server logs)
# 6. Verify session_epochs row has burned_at set
```
