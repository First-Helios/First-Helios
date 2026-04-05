# Data Contract: session_epochs

> **Table:** `session_epochs`
> **Layer:** Operational
> **Owner:** Data Engineering
> **Created:** 2026-04-05
> **Status:** Active (FH-0)

---

## Purpose

Tracks SpiritPool session token lifecycle — creation, contributor linkage, and burn state. One row per unique `session_token`. Auto-created on first `POST /api/contribute` for a given token.

## Consumers

| Consumer | Usage | Dependency Level |
|----------|-------|-----------------|
| Burn endpoint | Sets contributor_id=NULL and burned_at on burn | Hard |
| Dashboard | Active session count, burn rate metrics | Soft |
| Transparency metrics | Session lifecycle visibility | Soft |

## Schema Contract

| Column | Type | Nullable | Constraint |
|--------|------|----------|------------|
| id | INTEGER | No | PK, auto-increment |
| session_token | TEXT | No | UNIQUE |
| epoch_id | INTEGER | No | Consent epoch at creation |
| contributor_id | INTEGER | Yes | FK contributors.id, NULL on burn |
| created_at | DATETIME | No | Server-set |
| burned_at | DATETIME | Yes | NULL while active, set on burn |

## Burn Semantics

1. `POST /api/burn` with a `session_token` triggers:
   - `contributor_id` set to `NULL` (deliberate data loss for privacy)
   - `burned_at` set to `NOW()`
2. Burn is **irreversible** — once contributor_id is NULL, the link is permanently severed
3. Multiple session tokens can exist for the same contributor (token rotation)
4. Burned sessions' events remain in `sp_events` but are no longer linkable to a contributor

## Contributor Linkage Rules

- `contributor_id` links to `contributors.id` via FK
- One contributor can have many session tokens (rotation over time)
- Setting `contributor_id = NULL` on burn is the primary privacy mechanism
- No FK from `sp_events` to `session_epochs` — relationship is text match on `session_token` only

## What Can Break

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Duplicate session_token | UNIQUE constraint violation | Extension generates UUID; collision probability negligible |
| Burn for non-existent token | No row to update | Return 200 anyway (idempotent) |
| Contributor deletes extension | Orphaned session_epochs | No cleanup needed — data remains anonymized |

## Freshness SLA

- No freshness requirement — rows created on-demand per new session token
- Monitor active session count as a health metric
