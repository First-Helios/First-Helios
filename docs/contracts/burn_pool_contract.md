# Data Contract: burn_pool

> **Table:** `burn_pool`
> **Layer:** Operational
> **Owner:** Data Engineering
> **Created:** 2026-04-05
> **Status:** Active (FH-0)

---

## Purpose

Monthly aggregate of burned SpiritPool sessions. Tracks signal volume that has been anonymized via the burn mechanism. Records have a 1-year TTL enforced by a daily maintenance job. No per-session burn records — only monthly counts.

## Consumers

| Consumer | Usage | Dependency Level |
|----------|-------|-----------------|
| Dashboard | Monthly burn trends, burn rate metrics | Soft |
| Transparency metrics | Burn volume visible to contributors | Soft |

## Schema Contract

| Column | Type | Nullable | Constraint |
|--------|------|----------|------------|
| id | INTEGER | No | PK, auto-increment |
| month_key | VARCHAR | No | Format: 'YYYY-MM' |
| signal_count | INTEGER | No | Incremented on each burn |
| burned_at | DATETIME | No | Timestamp of burn operation |
| expires_at | DATETIME | No | burned_at + 1 year |

## Expiry Rules

1. `expires_at` = `burned_at` + 1 year
2. Daily maintenance job: `DELETE FROM burn_pool WHERE expires_at < NOW()`
3. After expiry, burn records are permanently deleted — no archive
4. The maintenance job is scheduled via `config/scheduler.yaml`

## Aggregation Semantics

- One row per burn operation (not per month)
- `month_key` groups burns by calendar month for trend analysis
- `signal_count` reflects the number of signals associated with the burned session
- Multiple rows can exist for the same `month_key` (one per burn operation)

## What Can Break

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Maintenance job fails to run | Expired records accumulate | Monitor job runs in meta_job_runs |
| Burn for session with zero signals | signal_count = 0 row created | Acceptable — still records the burn event |

## Freshness SLA

- No freshness requirement — rows created only when burns occur
- Monitor monthly burn volume as a health metric

## Privacy Constraints

- No PII in this table by design
- No session_token stored — only aggregate counts
- After expiry + deletion, no trace of the burn remains
