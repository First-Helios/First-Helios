# Data Contract: sp_events

> **Table:** `sp_events`
> **Layer:** Operational
> **Owner:** Data Engineering
> **Created:** 2026-04-05
> **Status:** Active (FH-0)

---

## Purpose

Forward-compatible signal storage for SpiritPool contributor data. Accepts job listings, salary signals, business reviews, and event listings via `POST /api/contribute`.

## Consumers

| Consumer | Usage | Dependency Level |
|----------|-------|-----------------|
| Scoring engine | Contributor signals feed staffing stress scores | Hard |
| Dashboard | Contributor volume, domain coverage metrics | Hard |
| Transparency metrics | Collection health visible to contributors | Hard |
| Legacy compatibility | Dual-write from /api/spiritpool/contribute | Soft |

## Schema Contract

| Column | Type | Nullable | Constraint |
|--------|------|----------|------------|
| event_id | VARCHAR (UUID) | No | PK, server-generated |
| session_token | TEXT | No | No length/format constraint |
| epoch_id | INTEGER | No | No upper bound |
| event_type | VARCHAR | No | One of: job_listing, salary_signal, business_review, event_listing |
| payload | JSONB | No | Must accept unknown fields |
| source_type | VARCHAR | No | Default 'extension' |
| collected_at | DATETIME | No | Server-set only, never from client |
| pipeline_version | INTEGER | No | Server-set, starts at 1 |

## Accuracy Source

- Data originates from SpiritPool browser extension content scripts
- Salary values are fuzzed ±5% at the extension level
- Timestamps (observedAt) are fuzzed ±15 min at the extension level
- `collected_at` is the authoritative server-side receipt timestamp

## Freshness SLA

| Metric | Warning | Critical |
|--------|---------|----------|
| Last event received | > 3 days | > 7 days |
| Pipeline version currency | pipeline_version < current | — |

## Coverage Scope

- Geographic: Austin TX MSA (initial), expandable
- Domains: jobs, events, business
- Sources: indeed, linkedin, glassdoor, ziprecruiter, google_maps, google_jobs

## What Can Break

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Extension not sending signals | Table goes stale | Monitor freshness SLA, alert at 3 days |
| PII in payloads | Events routed to quarantine instead | PII detection engine; 200 returned to client regardless |
| Unknown JSONB fields from future eras | None — schema is forward-compatible | payload column accepts arbitrary JSON |
| 64-char hex session tokens (Second Helios) | None — TEXT column has no length constraint | Tested in §8.5 |

## Fallback Strategy

- If sp_events ingestion fails, the extension receives 200 anyway (no retry storm)
- Failed inserts are logged in `meta_job_runs` as batch-level errors
- Scoring engine falls back to automated collector data if contributor signals are absent

## Privacy Constraints

- `tabUrl` and `collectedAt` are stripped before storage (defence-in-depth)
- No IP addresses stored anywhere in the record or logs
- `session_token` is opaque — never parse, validate format, or use to recover identity
- PII-flagged events go to `quarantine`, never to this table

## Deduplication

- No server-side dedup key defined (extension handles collection cadence)
- Indexed on `(session_token, epoch_id)` for efficient session-scoped queries
