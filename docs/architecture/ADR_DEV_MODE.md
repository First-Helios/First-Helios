# ADR: Dev Capture Mode — Raw Signal A/B Comparison

**Status:** Accepted
**Date:** 2026-04-06
**Context:** SpiritPool extension privacy pipeline prevents raw signal visibility

---

## Problem

The SpiritPool extension's privacy pipeline (`sanitizeForTransmit()` in M4) strips and fuzzes signals before they leave the browser. The server never sees:
- Exact salary values (fuzzed ±5%)
- Exact timestamps (observedAt fuzzed ±15min)
- Tab URLs (stripped entirely)
- Client-side collection timestamps (stripped entirely)

This is correct for production but makes it impossible to:
1. Verify that CSS selectors are extracting the right data from job cards
2. Confirm that fuzzing stays within specified ranges
3. Debug extraction failures by comparing DOM content to parsed fields
4. Build a ground truth dataset for improving extraction accuracy

## Decision

Implement a **dev capture mode** that sends both pre-sanitization and post-sanitization versions of each signal, along with the raw HTML of the source DOM element. Dev data is stored in a **separate PostgreSQL schema** (`dev_capture`) to prevent production data tainting.

## Alternatives Considered

| Option | Approach | Rejected Because |
|--------|----------|-----------------|
| Skip sanitization | Bypass `sanitizeForTransmit()` in dev mode | No A/B comparison — only see raw, not how pipeline transforms it |
| Separate endpoint | `POST /api/dev/raw-signal` for raw data | Adds API surface area; harder to correlate with production pipeline output |
| Extension-only logging | Log raw signals to separate extension storage | Not accessible from server-side notebook; can't join with database data |
| Inline `_dev_raw` in sp_events | Store dev data in production payload JSONB | Taints production tables with raw data including tabUrl |

## Architecture

```
Extension (dev mode on):
  Content script → capture card.outerHTML as _dev_html
  sanitize.js → deep-clone signal before strip/fuzz → attach as _dev_raw
  POST includes: sanitized signal + _dev_raw + _dev_mode flag

Server:
  Extract _dev_raw and _dev_mode from signal BEFORE production processing
  Store in dev_capture.raw_signals (separate schema)
  Continue normal pipeline with clean signal → sp_events + job_postings
```

**Data isolation:** `dev_capture` is a PostgreSQL schema-level boundary. Production queries never touch it. The `_dev_raw` and `_dev_mode` fields are stripped from signals before they enter the production pipeline.

## Privacy Implications

- Dev mode signals store `tabUrl` (in `dev_capture` schema only)
- This is an intentional privacy tradeoff for development
- Dev mode should never be enabled for production data collection
- The `dev_capture` schema should be periodically purged on production servers

## Files Changed

| File | Repo | Change |
|------|------|--------|
| `core/models/dev_capture.py` | First-Helios | New model: `RawSignalCapture` |
| `alembic/versions/c1a4f7e39b02_...` | First-Helios | Migration: create schema + table |
| `postings/spiritpool_routes.py` | First-Helios | Dev capture routing + field stripping |
| `spiritpool/shared/sanitize.js` | SpiritPool | Dual-payload when dev mode on |
| `spiritpool/content/linkedin.js` | SpiritPool | Capture outerHTML |
| `spiritpool/content/indeed.js` | SpiritPool | Capture outerHTML |
| `spiritpool/options/options.html` | SpiritPool | Dev mode toggle UI |
| `spiritpool/options/options.js` | SpiritPool | Wire toggle to storage |
