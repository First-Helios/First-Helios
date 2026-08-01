# ADR-0003: Three-layer schema (raw / canonical / mart)

**Status:** Accepted
**Date:** 2026-07-31
**Accepted:** 2026-08-01 by the project owner

## Context

[ROADMAP.md §4.3](../../ROADMAP.md#43-data-layer) has always specified a
`raw` / `canonical` / `mart` split inside a single Postgres database, but
nothing has implemented it: the one table that exists (`venue`, from PR #2)
sits in `public`, and `alembic/env.py`'s `include_object` filter is
schema-blind.

[RFC-0001](../rfc/0001-menu-pricing-first.md) makes the split urgent rather
than aspirational. Under a menu-price-index product:

- Captures are high-volume and cheap to re-derive (every fetch of every menu
  page, monthly, across ~1,000+ sites).
- The domain model is append-only and expensive to lose (`price_observation`
  is the atom of the entire system, and its history *is* the product).
- Read-serving shapes ("what does this venue's menu cost right now", "median
  entrée price in this H3 cell") are pure derivations that we will get wrong
  several times before we get them right.

Those three things have genuinely different durability, rebuild, and
migration-risk profiles. Mixing them in one namespace means every future
schema change has to be reasoned about against the most fragile possible
interpretation of what it touches.

The decision is needed **now** because Phase 1 lands the venue-identity and
menu-graph schemas (RFC-0001 work plan PRs 1–3), and relocating tables after
they hold data is materially harder than creating them in the right place.

## Decision

**One Postgres database, three Postgres schemas, distinguished by who writes
them and what happens when they are lost.**

| Layer | Contents | Written by | If dropped |
|-------|----------|------------|------------|
| `raw` | Capture index — one row per fetch (`url`, `status`, `content_hash`, `fetched_at`, `bundle_path`, `outcome`) plus `rejected_signals` dead-letter | Scraper | Rebuild by re-walking `var/replay/` on disk |
| `canonical` | Domain model — `brand`, `venue`, `venue_alias`, `venue_source`, `site_identity`, `menu_page`, `menu_section`, `menu_item`, `price_observation`, `menu_modifier` | Ingest pipeline only | Rebuild by replaying bundles (`helios backfill --all`) |
| `mart` | Derived read models — `current_menu`, price-index aggregates | Refresh task only | Rebuild from `canonical` in one command |

**Raw bytes stay on disk, not in Postgres.** `raw` indexes captures; the
HTML/PDF payloads live in `var/replay/` per ROADMAP §4.5. Postgres is for
querying captures, not storing megabytes of markup.

**Dependencies point one direction: `raw` → `canonical` → `mart`.** No
foreign key ever points from `canonical` into `mart`, and none from `raw`
into `canonical`. `mart` may reference `canonical` keys. This is what makes
each layer independently droppable, and it is enforceable by reading the
migration, which is the only enforcement mechanism a solo project gets.

**`mart` objects are ordinary tables refreshed by an explicit task**, not
materialized views. Postgres cannot incrementally refresh a matview;
`REFRESH MATERIALIZED VIEW` re-computes everything and takes an
`ACCESS EXCLUSIVE` lock unless `CONCURRENTLY` is used, which itself requires
a unique index and still does full recomputation. The ingest pipeline
already knows precisely which venues changed, so a targeted refresh is both
cheaper and simpler to reason about. This also ports V1's proven
`DealMaterialization` pattern (ROADMAP §3.2, process 9).

**The existing `venue` table moves from `public` to `canonical`** as part of
RFC-0001 PR 1. It is a bare scaffold with no production data — exactly the
case CLAUDE.md exempts from the stop-and-ask rule on altering existing
tables. Doing it now costs one line in a migration; doing it after Phase 5
costs a data migration.

**`alembic_version` stays in `public`.** It belongs to the migration tool,
not to any data layer, and pinning it to `public` keeps it findable
regardless of `search_path`.

**Alembic must become schema-aware.** `env.py` gets
`include_schemas=True` in both `context.configure` calls, and
`include_object` gains a schema allowlist (`{raw, canonical, mart}` plus
`public` for `alembic_version`). Without the allowlist, `include_schemas=True`
makes autogenerate reflect PostGIS/Tiger objects in `topology` and `tiger`
and emit `DROP` statements for them — the failure mode the current
schema-blind filter was written to prevent, reintroduced by the very flag
the split requires. Models declare their layer via
`__table_args__ = {"schema": "canonical"}`.

**No `search_path` reliance in application code.** Every model names its
schema explicitly. Implicit `search_path` resolution is how a table silently
gets created in the wrong namespace.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Single `public` schema, prefixed names** (`raw_capture`, `mart_current_menu`) | Zero Alembic changes; simplest possible setup | Naming convention is not a boundary — nothing stops a `canonical` FK into a `mart` table, and "drop and rebuild the derived layer" becomes a hand-written table list that will drift |
| **Separate databases per layer** | Hardest possible isolation; independent backup/restore | No cross-database joins or FKs in Postgres, so every `mart` refresh becomes application-side ETL against two connections; multiplies connection config, migration runs, and backup jobs for a project with one maintainer |
| **`raw` stores the HTML bytes too** | Single source of truth; no filesystem/DB consistency question | Postgres becomes a blob store for data with a 100% rebuild path from disk; TOAST bloat, slow backups, and the replay-bundle pattern already gives durable, diff-able, versionable captures |
| **`mart` as materialized views** | Refresh logic is declarative SQL; no refresh code to write | Full recomputation on every refresh regardless of how little changed; locking without `CONCURRENTLY`, and `CONCURRENTLY` needs a unique index on every view; Alembic manages matviews poorly (raw `op.execute` on both `upgrade` and `downgrade`) |
| **Defer the split until data volume justifies it** | Less work now; ROADMAP already deferred it once | The whole point is that the split is cheap before the tables exist and expensive after. Phase 1 is the last moment it is free |

## Consequences

**Easier**

- "Drop `canonical`, replay from bundles" and "drop `mart`, refresh" become
  literal, testable operations. ROADMAP Phase 6's done-when clause depends on
  the first; RFC-0001's mart design depends on the second.
- Blast radius is legible at review time: a migration touching only `mart` is
  near-zero-risk, one touching `canonical` gets the careful read. With no
  second reviewer (ROADMAP §6.0), a structural signal about which diffs are
  dangerous is worth real effort.
- Backup policy can differ per layer later (Phase 8) without re-architecting.
- The read path is index-tunable against denormalized tables without
  contorting the append-only observation model.

**Harder / accepted costs**

- Every model must declare `{"schema": ...}`; forgetting it puts a table in
  `public`. Mitigated by a test that asserts every mapped table has a
  non-null, allowlisted schema.
- `env.py` grows a schema allowlist that must be updated when a layer is
  added — a real footgun, since an unlisted schema's objects get silently
  ignored by autogenerate rather than erroring. Documented in the module
  docstring.
- Migrations must `CREATE SCHEMA IF NOT EXISTS` before the first table in
  each layer, and drop them on `downgrade`. One-time cost in the PR 1
  migration.
- Test fixtures must create all three schemas, not just call
  `create_all()` — the `Base.metadata.create_all()` used in test fixtures
  will fail on a missing schema rather than helpfully creating it.
- `raw` and `var/replay/` can disagree (a row whose bundle was deleted, or a
  bundle with no row). The capture index is the queryable view of the
  filesystem, and reconciliation is a maintenance script, not a constraint.

**Deferred**

- dbt stays out of scope (ROADMAP §4.3: revisit at ≥5 mart views).
- Per-layer retention/partitioning of `raw` — revisit when capture volume
  is measured, not before.

## References

- [RFC-0001](../rfc/0001-menu-pricing-first.md) — menu-and-pricing-first
  data collection; §D2 defines the tables per layer
- [ROADMAP.md §4.3](../../ROADMAP.md#43-data-layer) — the original
  three-layer sketch this ratifies
- [ROADMAP.md §5, Phase 1](../../ROADMAP.md#phase-1--domain-model--migrations)
  — the `include_schemas` + allowlist change called out as a deliverable
- [ADR-0002](./0002-containerization.md) — why the dev/CI database ships
  PostGIS, hence why the autogenerate filter exists at all
- V1 `core/database.py` — `DealMaterialization`, the refresh-task pattern
  `mart` inherits
