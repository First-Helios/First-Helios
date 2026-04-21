> **ARCHIVED 2026-04-21.** Template is still valid reference for onboarding new sources; linked from the SpiritPool navigator. No active work pending.

# FH-2: New Source Onboarding

> **Trigger:** Each new SpiritPool Phase 3 content script that ships
> **Prerequisite:** FH-0 complete (intake endpoint live). Read `SPIRITPOOL_CONTEXT.md` for full context.
> **Target repo:** `/home/fortune/CodeProjects/First-Helios/`

---

## Objective

For each new content script SpiritPool adds, First Helios needs to accept the new `event_type` and `source` values and know the dedup key columns for that source. The `events.payload` JSONB column stores arbitrary shapes — **no code changes are required** to accept new sources. But dedup keys and expected field mappings must be documented so scoring and dashboard queries can reference them.

This document provides the onboarding template and the first batch of planned sources.

---

## 1. How It Works

When SpiritPool ships a new content script:
1. The script extracts structured data and POSTs through the existing pipeline
2. The `source` and `event_type` fields in the POST body identify the new data
3. `events.payload` JSONB stores the new shape without schema changes
4. **This FH-2 document gets updated** (or a new appendix added) with the source's dedup keys and payload shape so First Helios can build scoring queries and dashboard views

---

## 2. Source Onboarding Template

Copy this template for each new source:

```
────────────────────────────────────────────
Source:      [site name, e.g. "eventbrite"]
Script:      [filename, e.g. "eventbrite.js"]
event_type:  [e.g. "event_listing"]
domain:      [e.g. "events"]
Dedup keys:  [tuple for dedup, e.g. (source, payload->>'event_id')]

Payload shape:
{
  "field_1": "type — description",
  "field_2": "type — description",
  ...
}

Notes:
[Any source-specific quirks, rate limits, or extraction caveats]
────────────────────────────────────────────
```

---

## 3. Existing Sources (Phase 0–1, Already Active)

These are already flowing through the pipeline. Listed here for completeness and to document dedup strategies.

### indeed
- **event_type:** `job_listing`
- **domain:** `jobs`
- **Dedup keys:** `(source, payload->>'url')`
- **Key payload fields:** `jobTitle`, `company`, `location`, `salary`, `postingDate`, `applicantCount`, `badges`, `url`

### linkedin
- **event_type:** `job_listing`
- **domain:** `jobs`
- **Dedup keys:** `(source, payload->>'url')`
- **Key payload fields:** `jobTitle`, `company`, `location`, `salary`, `postingDate`, `applicantCount`, `badges`, `url`

### glassdoor
- **event_type:** `job_listing` / `salary_signal`
- **domain:** `jobs`
- **Dedup keys:** `(source, payload->>'url')`
- **Key payload fields:** `jobTitle`, `company`, `location`, `salary`, `postingDate`, `badges`, `url`

### ziprecruiter
- **event_type:** `job_listing`
- **domain:** `jobs`
- **Dedup keys:** `(source, payload->>'url')`
- **Key payload fields:** `jobTitle`, `company`, `location`, `salary`, `postingDate`, `badges`, `url`

### google_maps
- **event_type:** `business_review`
- **domain:** `business`
- **Dedup keys:** `(source, payload->>'place_id')` or `(source, payload->>'url')`
- **Key payload fields:** business name, category, rating, review count, location, url

### google_jobs
- **event_type:** `job_listing`
- **domain:** `jobs`
- **Dedup keys:** `(source, payload->>'url')`
- **Key payload fields:** `jobTitle`, `company`, `location`, `salary`, `postingDate`, `url`
- **Note:** Google Jobs uses obfuscated class names — extractor relies on structural heuristics, not stable selectors

---

## 4. Planned Sources (Phase 3)

### eventbrite
- **Script:** `eventbrite.js`
- **event_type:** `event_listing`
- **domain:** `events`
- **Dedup keys:** `(source, payload->>'event_id')`
- **Payload shape:**
```json
{
  "event_name": "string",
  "date": "ISO datetime",
  "venue": "string",
  "category": "string",
  "price": "number | null",
  "rsvp_count": "number | null",
  "url": "string (canonical event URL)"
}
```

### meetup
- **Script:** `meetup.js`
- **event_type:** `event_listing`
- **domain:** `events`
- **Dedup keys:** `(source, payload->>'event_id')`
- **Payload shape:**
```json
{
  "event_name": "string",
  "date": "ISO datetime",
  "venue": "string",
  "category": "string",
  "group_name": "string",
  "rsvp_count": "number | null",
  "url": "string (canonical event URL)"
}
```

### do512
- **Script:** `do512.js`
- **event_type:** `event_listing`
- **domain:** `events`
- **Dedup keys:** `(source, payload->>'event_url')`
- **Payload shape:**
```json
{
  "event_name": "string",
  "date": "ISO datetime",
  "venue": "string",
  "category": "string",
  "price": "number | null (often free)",
  "url": "string (canonical event URL)"
}
```
- **Note:** do512 is Austin-specific; dedup uses `event_url` rather than a numeric ID

---

## 5. Dedup Implementation Guidance

Dedup is a First Helios backend responsibility. Recommended approach:

```sql
-- Example: skip insert if duplicate exists within 24-hour window
INSERT INTO events (session_token, epoch_id, event_type, payload, source_type)
SELECT $1, $2, $3, $4, $5
WHERE NOT EXISTS (
  SELECT 1 FROM events
  WHERE source_type = $5
    AND event_type = $3
    AND payload->>'url' = $4->>'url'
    AND collected_at > NOW() - INTERVAL '24 hours'
);
```

Adjust the dedup key columns per source as documented above. The dedup window (24h) and strategy (skip vs. merge) are First Helios design decisions.

---

## 6. Adding Future Sources

When SpiritPool ships a new content script beyond Phase 3:
1. Copy the template from §2
2. Fill in source, event_type, domain, dedup keys, payload shape
3. Append to §4 (or create a new section)
4. Drop the updated document in `First-Helios/agentinbox/`
5. No schema migration needed — JSONB handles new shapes automatically
