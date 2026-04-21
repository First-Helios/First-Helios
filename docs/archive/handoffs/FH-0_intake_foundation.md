> **ARCHIVED 2026-04-21.** Phase complete. Canonical replacement: [../../architecture/HeliosDeployment/03_SPIRITPOOL_INTAKE_PIPELINE.md](../../architecture/HeliosDeployment/03_SPIRITPOOL_INTAKE_PIPELINE.md). Kept for schema/DDL history.

# FH-0: Intake Foundation

> **Trigger:** SpiritPool Phase 0 complete (M7 — session token & consent active)
> **Prerequisite:** Read `SPIRITPOOL_CONTEXT.md` first for full extension context.
> **Target repo:** `/home/fortune/CodeProjects/First-Helios/`

---

## Objective

Build the `POST /api/contribute` intake endpoint and the forward-compatible event storage schema so SpiritPool can begin flushing signals to First Helios.

---

## 1. What SpiritPool Will POST

```json
{
  "session_token": "string (UUID v4 now; 64-char hex in Second Helios — treat as opaque TEXT)",
  "epoch_id": "integer (consent version counter, starts at 1, increments on rotate)",
  "event_type": "string — one of: 'job_listing', 'salary_signal', 'business_review', 'event_listing'",
  "source": "string — 'indeed', 'linkedin', 'glassdoor', 'ziprecruiter', 'google_maps', 'google_jobs'",
  "domain": "string — 'jobs', 'events', 'business'",
  "payload": { "...structured extraction data — fields vary by source..." }
}
```

### Fields SpiritPool Never Sends

(Defence-in-depth — strip server-side anyway):
- `tabUrl` — full browser tab URL with session state
- `collectedAt` — client-side timestamp
- IP addresses

### Fields the Backend Sets Server-Side

- `collected_at` — server timestamp (`NOW()`)
- `event_id` — generated UUID (`gen_random_uuid()`)
- `pipeline_version` — integer, start at 1

---

## 2. Schema DDL

Forward-compatible across all three Helios eras. No migrations needed when SpiritPool upgrades to Second or Third Helios.

```sql
CREATE TABLE events (
  event_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_token    TEXT NOT NULL,            -- UUID now, hash_token later; never parse, never constrain length
  epoch_id         INTEGER NOT NULL,
  event_type       TEXT NOT NULL,
  payload          JSONB NOT NULL,
  source_type      TEXT NOT NULL DEFAULT 'extension',
  collected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  pipeline_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_events_session_epoch ON events(session_token, epoch_id);
CREATE INDEX idx_events_type_collected ON events(event_type, collected_at);

CREATE TABLE session_epochs (
  id               SERIAL PRIMARY KEY,
  contributor_id   INTEGER REFERENCES contributors(id),  -- nullable on burn
  session_token    TEXT NOT NULL UNIQUE,
  epoch_id         INTEGER NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  burned_at        TIMESTAMPTZ
);

CREATE TABLE burn_pool (
  id               SERIAL PRIMARY KEY,
  month_key        TEXT NOT NULL,            -- 'YYYY-MM'
  signal_count     INTEGER NOT NULL DEFAULT 0,
  burned_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at       TIMESTAMPTZ NOT NULL      -- burned_at + 1 year; auto-delete
);
-- Maintenance job: DELETE FROM burn_pool WHERE expires_at < NOW();

CREATE TABLE contributors (
  id               SERIAL PRIMARY KEY,
  uuid             TEXT NOT NULL UNIQUE,     -- per-install anonymous identity
  total_signals    INTEGER NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 3. Endpoint Spec

### `POST /api/contribute`

**Request body:** JSON matching the payload contract in §1.

**Processing order:**
1. Validate required fields: `session_token`, `epoch_id`, `event_type`, `source`, `domain`, `payload`
2. Strip `tabUrl` and `collectedAt` from payload if present (defence-in-depth)
3. Set server-side fields: `event_id`, `collected_at`, `pipeline_version`
4. Insert into `events` table
5. On first POST for a given `session_token`: create `session_epochs` row

**Responses:**
- `200` — success (event stored)
- `400` — `session_token` or `epoch_id` missing
- No detailed error bodies for auth failures (future eras will add cert-gated auth)

**IP handling:** Client IP must be stripped from request context before any handler runs. Never logged.

---

## 4. Hard Constraints

1. **`session_token` column is TEXT with no length or format constraints.** Must accept 36-char UUID (First Helios) and 64-char hex (Second Helios) without error. Never parse, validate, or assume format.

2. **`pipeline_version` tracks PII rule version.** Enables re-processing old events through future NER pipeline. Always set server-side.

3. **`consent_state` is NOT transmitted in payloads.** Do not create a consent column. It exists only in the extension.

4. **`payload` is JSONB.** Must store unknown fields from future eras without error. No schema enforcement on payload contents.

5. **No foreign key from `events` to `session_epochs`.** The relationship is via `session_token` text matching, not FK constraint. This allows burn (NULL contributor_id) without cascading.

---

## 5. Session Epochs & Burn

### First POST per token
When an event arrives with a `session_token` not yet in `session_epochs`:
- Create a new `session_epochs` row with `session_token`, `epoch_id`, `created_at = NOW()`
- If the extension has previously registered a contributor UUID, link `contributor_id`

### Burn endpoint
`POST /api/burn` (or equivalent):
- Input: `{ session_token, burned_at }`
- Set `session_epochs.contributor_id = NULL` for that token
- Increment `burn_pool` for current `month_key` (YYYY-MM format)
- Return 200

### Expiry maintenance
- Periodic job: `DELETE FROM burn_pool WHERE expires_at < NOW()`
- Frequency: daily is sufficient

---

## 6. Success Criteria

- [ ] SpiritPool can POST the payload from §1 and receive 200
- [ ] Event appears in `events` table with server-set `collected_at`, `event_id`, `pipeline_version`
- [ ] `session_epochs` row created on first POST per token
- [ ] `session_token` = 64-char hex (forward-compat test) stores without error
- [ ] `epoch_id` = large integer stores without error
- [ ] Unknown fields in `payload` JSONB store without error
- [ ] No IP addresses in any log or database row
- [ ] `tabUrl` and `collectedAt` stripped even if present in request

---

## 7. What Comes Next

After FH-0 is complete and SpiritPool can flush signals:
- **FH-1 (Backend Hardening)** — PII quarantine pipeline, full IP suppression audit, integration tests §8.1–8.5. Security gate before production.
- **FH-2 (Source Onboarding)** — Dedup keys and payload shapes for new content scripts as they ship.
