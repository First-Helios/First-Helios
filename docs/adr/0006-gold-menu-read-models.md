# ADR-0006: Gold menu read models — shape, materialization, and refresh

**Status:** Accepted
**Date:** 2026-09-19
**Accepted:** 2026-09-19 by project owner Fortune. Proposed defaults accepted;
the first unit materializes a **bounded input set**. The full-catalog refresh
follow-up was accepted on 2026-09-20. See [Owner decision](#owner-decision).
[Amendment 1](#amendment-1-2026-10-22-section-names-and-variant-only-item-names)
(section and item names) was accepted 2026-10-22 and built in session P8-3.
[Amendment 2](#amendment-2-2026-10-27-proposed-json-ld-precedence-per-dish)
(JSON-LD precedence per dish) is Proposed (P8-18).
**Extends:** [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md),
[ADR-0005](./0005-immutable-menu-snapshots-and-selection.md)
**Implements:** [Plan 0002 Step 6](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models)

## Context

Step 5 is complete. The immutable Menu writer (revision `d83f0a21c592`), both
concrete Menu SQL directions, and the pure read-side selector
(`packages/helios_core/domains/menu/selection.py`) received integrated M01–M14
final acceptance from the owner on 2026-09-19
([record](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-menu-integrated-m01-m14-acceptance.md)). Step 6
adds the first `gold` projection over accepted Menu/Identity/Bronze.

**What is already settled at the ADR level** (do not reopen):

- Gold is the `gold` schema, owned by `packages.helios_core.gold`, holding
  "rebuildable consumer read models and aggregates"
  ([ADR-0004 §1–2](./0004-modular-monolith-identity-and-lifecycle.md)).
- Gold is rebuildable from Bronze and Silver, may be truncated or replaced by
  its owning refresh task, and is never an authoritative write target
  (ADR-0004 §1). Identity correctness never depends on Gold (ADR-0004 §5).
- FK direction: `gold` may reference `gold`, `menu`, `identity`, `bronze`; no
  authoritative table references `gold`; observation/history FKs use
  `RESTRICT`/`NO ACTION` (ADR-0004 §7). Gold reads **published contracts**
  only.
- Gold excludes facts scoped only to a retired ambiguous predecessor from
  current views, while historical queries retain them (ADR-0004 §5).
- Derived read models are ordinary tables refreshed by an explicit task, **not
  materialized views** — the reasoning ADR-0003 recorded for `mart` and
  ADR-0004 carried forward as "truncated or replaced by its owning refresh
  task." Postgres cannot incrementally refresh a matview, and Alembic manages
  matviews poorly ([ADR-0003](./0003-three-layer-schema.md)).

**What is *not* settled, and is why this ADR exists.** No ADR fixes the concrete
Gold read-model shape or refresh contract:

- ADR-0005 explicitly excludes Gold: "No models, contracts, migrations,
  extraction, ML, Gold, API, runtime dependency or deployment changes are part
  of this decision-record work."
- Plan 0002 §4 lists "Gold menu projections and API-specific indexes" as
  explicitly deferred work, and Step 6 gives only a two-line sketch
  (current-menu and price-index tables, a proven full rebuild, refresh owned by
  the Gold module).
- RFC-0001 §D2 describes `current_menu` (latest accepted price per
  `(item, variant)`) and `price_index_*` (median entrée price per H3
  cell/course), but those columns predate ADR-0004/0005: they assume
  `venue_id`/`menu_item_id` in a `canonical`/`mart` split that no longer
  exists. The current model is immutable Menu **aggregates**, Subject-scoped
  content, and the accepted per-`(family, target)` `select_price` selector.
  RFC-0001's Gold columns do not map onto it unchanged.

Concrete decisions with real trade-offs remain open: the grain and columns of
the current-menu table; whether the first unit ships a price index at all (its
by-H3/course aggregation needs the deferred cross-venue item taxonomy per
RFC-0001 §D2/§D7, the `h3-pg`/PostGIS extension per ROADMAP §4.3, and Place
geospatial columns that do not exist yet); whether refresh is a full rebuild or
targeted-incremental (Plan Step 6 / scenario A11 / §8 fitness test require a
proven **full rebuild**, while ROADMAP Phase 6 wants refresh **targeted to the
Establishments that changed**); and whether Gold reuses the accepted pure
selector or reimplements selection precedence in SQL. Per CLAUDE.md, a new
schema pattern on the expensive-to-reverse models/migration path is proposed in
an ADR and stopped for owner review before implementation.

## Decision (proposed)

Ship the first `gold` projection as **current-menu only**, materialized as
ordinary Gold-owned tables that record the accepted `select_price` result for
each current eligible scope and target, rebuilt by a full deterministic refresh
that reads Bronze/Identity/Menu without mutating them. Defer the price index.

The following points are the proposed normative surface for owner review:

1. **First projection is current-menu only; the price index is deferred.**
   RFC-0001 §D2 says start with one view and add aggregates only when an API
   endpoint needs them; Plan Step 6 says Gold "can land with the API work that
   first consumes it." A price index by H3/course additionally depends on the
   deferred cross-venue item taxonomy, the `h3-pg`/PostGIS extension, and Place
   geospatial columns — none present. Introducing them here would be
   "for later" scaffolding and a new-extension dependency decision. The price
   index gets its own unit alongside the price-index API (ROADMAP Phase 7).

2. **Materialization is ordinary `gold` tables refreshed by a Gold-owned task,
   not materialized views** (ADR-0003 reasoning; ADR-0004 refresh ownership).

3. **The refresh contract is a full, deterministic rebuild.** Refresh recomputes
   the projection from Identity + Menu (+ Bronze for provenance columns) and
   replaces the Gold rows; it never writes to or changes an authoritative row.
   A full rebuild after deleting Gold reproduces identical business columns
   (Plan Step 6, scenario A11, §8 "Gold rebuildability"). **Targeted
   incremental refresh is deferred** as an optimization until freshness volume
   justifies it (ROADMAP Phase 6); it is not a correctness requirement and
   ships with the ingest pipeline, not here.

4. **Grain and columns of `gold.current_menu` (review surface).** One row per
   resolved current selection: `(scope_subject_id, scope_subject_kind, target
   identity, effective context, currency)`, carrying the selector's output —
   `amount_minor`, `currency_code`, `price_state` (`priced`/`unknown`/
   `unavailable`), local vs organization `scope`, `source_kind`, `observed_at`,
   `price_confidence`, `evidence_ids`, and the selected content
   (`name`, `description`, content `source_kind`/`observed_at`/`evidence_ids`),
   plus surfaced freshness (`as_of` and a staleness age derived from
   `observed_at`). Money stays integer minor units with a currency FK; no float.
   Facts scoped only to a retired ambiguous predecessor are excluded from the
   current table (ADR-0004 §5). The exact column list, keys, and whether
   separate Organization shared-price claims get their own rows are the owner
   review surface, not settled by this text.

5. **Gold reuses the accepted pure selector as the single definition of
   "current."** The refresh enumerates current eligible scopes and their targets
   and records the deterministic `select_price` result. Selection precedence,
   applicability intersection, tombstone/pin lifecycle, and no-inferred-price
   rules are **not** reimplemented in Gold SQL — one definition of precedence,
   already accepted and tested, avoids a second copy that can drift. Gold
   imports Menu/Identity/Bronze **contracts** only.

6. **Determinism and idempotence.** The business columns in point 4 are
   deterministic functions of committed Bronze/Identity/Menu; a refresh over
   unchanged sources yields byte-identical business columns. Refresh-run
   metadata (`refreshed_at`, any refresh-run surrogate id) is excluded from the
   rebuild-equality comparison (Plan Step 6).

7. **Ownership, imports, FKs, migration.** Schema `gold`; package
   `packages.helios_core.gold`; models registered **only** through
   `packages.helios_core.db.model_registry`; imports published contracts only,
   never provider or vertical ORM. FKs `gold → gold/menu/identity/bronze` with
   `RESTRICT`/`NO ACTION`; no authoritative table references `gold`. When
   implemented, exactly one forward migration after `d83f0a21c592` with
   hand-reviewed, synchronized concrete upgrade/downgrade SQL (no `CASCADE`,
   dependency order) and focused fitness/round-trip tests, per Plan §8.

8. **Explicit non-goals of this ADR and Step 6's first unit.** No API, no price
   index, no H3/geospatial, no `h3-pg`/PostGIS extension use, no cross-venue
   item taxonomy, no targeted incremental refresh, no scheduler, no extraction,
   ML, fuzzy matching, matching-policy change, new runtime dependency, or
   deployment. No change to any accepted Step 5 artifact.

## Alternatives considered

These explain the proposed direction; they are the owner's to accept or redirect.

| Alternative | Benefit | Reason not proposed |
|---|---|---|
| Materialized views for Gold | Declarative refresh, no refresh code | Full recompute per refresh, `ACCESS EXCLUSIVE` locking without `CONCURRENTLY` (which needs a unique index per view), and Alembic manages matviews poorly (ADR-0003). |
| Reimplement selection precedence in Gold SQL | Refresh is one set-based query; no per-target Python loop | Creates a second definition of "current" that can drift from the accepted, tested `select_price`; ADR-0005's precedence/lifecycle rules are intricate and were accepted as the read contract. |
| Ship the price index now | Matches RFC-0001's product framing | Needs deferred cross-venue taxonomy, the `h3-pg`/PostGIS extension, and Place geospatial columns; premature "for later" scaffolding and a separate dependency decision. |
| Targeted incremental refresh as the first contract | Cheaper steady-state refresh | Correctness contract is a proven full rebuild (Plan Step 6 / A11 / §8); targeted refresh is an optimization better sized with real ingest volume (ROADMAP Phase 6). |
| Keep current-menu as a Silver internal projection | No new schema | ADR-0004 reserves consumer-facing read models for Gold; Silver internal projections are implementation details of the authoritative module, and this table exists to serve the API. |

## Consequences

**Easier**

- One accepted definition of "current" (the selector) drives both ad-hoc reads
  and the materialized table.
- "Drop Gold, refresh" is a literal, testable operation; the rebuild-equality
  fitness test (Plan §8) has a clear business-column contract.
- Step 6 lands with no new extension or runtime dependency and no geospatial
  surface to review.

**Harder / accepted costs**

- A full rebuild that calls the pure selector per current scope/target is
  `O(scopes × targets)` selector calls. This is correctness-first; no scale
  claim is made before measurement on real samples. Targeted refresh is the
  named later optimization.
- The first unit refreshes a **bounded, caller-supplied input set** of scopes;
  enumerating "all current eligible scopes and targets" across the catalog is a
  deferred follow-up (see Owner decision), so this unit does not own that query.
- The retired-predecessor exclusion needs a join to Identity lineage/currentness
  at refresh time.
- Staleness is surfaced in the table (`as_of`), not hidden; the API contract for
  it lands with Phase 7.

## Owner decision

Owner Fortune accepted the proposed defaults on 2026-09-19 and answered the five
open questions:

1. **Current-menu only** — accepted; price index deferred to its own unit
   alongside the price-index API.
2. **Full deterministic rebuild** refresh — accepted; targeted incremental
   deferred.
3. **Selector reuse** over SQL reprojection — accepted.
4. `gold.current_menu` **grain/columns** as proposed in Decision point 4 —
   accepted; Organization shared-price claims are materialized in the same table
   with an explicit `scope` (`local`/`organization`), mirroring the selector's
   result (no separate table).
5. **Scope of enumeration — bounded input set (amendment).** The first unit
   projects a caller-supplied bounded input (one or more explicit scopes,
   e.g. an Establishment or Organization); enumerating the full current catalog
   from Identity + Menu is **deferred** to a follow-up alongside the ingest
   materialization refresh (ROADMAP Phase 6). Full-rebuild determinism and
   idempotence (points 3, 6) are proven over that bounded input.

Owner also confirmed (2026-09-19) that the superseded RFC-0001 §D2 Gold column
shape is **disposable** and must not be ported; the new iteration is designed
directly on immutable Menu aggregates and the accepted selector.

**Descriptor / aggregate-tag columns deferred (owner, 2026-09-19).** Projecting
`course`/`dietary_tags` — and, further out, canonical ingredient/cuisine/cultural
tags for cross-venue aggregation and comparison — was considered and **deferred**.
`course`/`dietary_tags` exist in Menu but are not reliably populated yet; canonical
cross-venue tags have no source data and require a controlled vocabulary (RFC-0001
§D2/§D7 defers cross-venue item taxonomy to a future RFC). The rule stands: Gold
projects source-faithful data that exists, and does not add columns for data we do
not have. When that data and taxonomy are real, they arrive as their own unit — a
Silver classification layer plus a Gold `canonical_tags` column kept **distinct**
from source-asserted `dietary_tags` (provenance), and a dedicated `price_index_*`
aggregate table that groups `gold.current_menu` by those tags. Aggregation is an
aggregate table over `current_menu`, not a reshaping of its per-target grain, so
this deferral costs no rework.

This is a real supplied decision, not inferred from tests or this document. It
authorizes the bounded Gold current-menu implementation unit; it does not
authorize the price index, the full-catalog refresh, an API, or any deployment.

**Full-catalog refresh follow-up accepted (owner, 2026-09-20).** The deferred
full-catalog enumeration was subsequently implemented and **accepted "Accept
as-is" by owner Fortune on 2026-09-20** (`refresh_full_catalog` /
`enumerate_current_requests`; price-driven grain; current-eligible-operating
exclusion; enumeration kept in the Menu domain), jointly with the bounded unit it
builds on. See the
[full-catalog review](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/reviews/0002-step-6-gold-full-catalog-refresh.md) and the
[Step 6 review](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/reviews/0002-step-6-gold-read-models.md). The price index, an
API, and deployment remain unauthorized and still require their own owner-accepted
ADR/decision.

**Refresh semantics clarified (owner decisions D5.1–D5.3, 2026-09-23; remediation
S7).** (1) Selection and enumeration check current eligibility with Identity's
read-only `current_resolved_scopes` (no locks, never aborts the transaction);
writers keep the locking `require_resolved_scopes` guard. (2) The bounded
`refresh_current_menu` replaces **every row of each requested scope** (subject),
not per family; a scope that no longer yields any request is named through
`subject_ids` so its stale rows are removed. (3) Requests with a knowledge or
observation cutoff are rejected: `gold.current_menu` holds current answers only.
In current mode only the requested subject's own stream heads count, and every
one of them must still be live.

## Amendment 1 (2026-10-22): section names and variant-only item names

**Status: Accepted 2026-10-22 by the owner, all four questions as recommended, and built in
session P8-3 (revision `c95d883737db`).** See
[Owner decision](#owner-decision-amendment-1) and [Build notes](#build-notes-amendment-1).
Proposed 2026-10-22 (session P8-1). It is [ADR-0019](./0019-public-v1-site.md) §5 build step 2.

### The gap

`gold.current_menu` has one row per priced target, and each row carries the selected content of
that target only (`content_name`, point 4). The menu endpoint names a node only from the node's
own row (`apps/api/routes/venues.py` `_shape_menu`). Two kinds of node never have a row of their
own:

- **Sections.** No section carries a section-level price on `helios_laptop`, so every wire
  section serves `name: null` (ADR-0019 F2).
- **Items priced only through their variants.** The item has no row, only its variants do, so
  the item serves `name: null`.

Silver has the names. Read-only on `helios_laptop` (2026-10-22, before the P5-33 rescore):

| Node | In Silver | Named in Silver | Note |
|---|---:|---:|---|
| Innermost sections of priced item/variant rows | 10,376 | 10,376 | 571 of them are the structural `Unsectioned` grouping, which never reaches Gold (ADR-0007 Amendment 1 §7). The other 9,805 are `direct`. |
| Items priced only through variants | 2,181 of 61,214 priced items | 2,181 | All `direct`. |
| Nested sections (`parent_section_id` set) | 0 of 18,139 | | The extractor writes no nesting today. |

So after this amendment every section and every item the menu endpoint serves would carry a
name, as far as these counts go.

**On real Gold rows** (P8-1 record
[2026-10-22-p8-1-gold-fill.md](../reviews/2026-10-22-p8-1-gold-fill.md) §5.4, after the P5-33
rescore and the first refresh): all 900 `has_menu` menus, fetched through the API, serve 9,286
sections, **every one `name: null`**, and 50,836 items, of which **1,866 are `name: null`**:
exactly the items priced only through variants. Gold holds 52,651 rows and no row has a null
`content_name`. Those 9,286 section names and 1,866 item names are what this amendment fills.

### Proposed shape

Two nullable columns on `gold.current_menu`, filled by the refresh:

| Column | Type | Value |
|---|---|---|
| `section_name` | `varchar(512)`, nullable | The selected content name of the innermost `section` node on the row's `target_path`. |
| `item_name` | `varchar(512)`, nullable | The selected content name of the `item` node on the row's `target_path`; null when the path has no item (a section-level price or a section modifier). |

- **Same rule on every row.** An item row's `item_name` equals its own `content_name`, and a
  section row's `section_name` equals its own `content_name`. The redundancy keeps the rule
  simple ("the name of the path's section and item"), and the wire reads one column per node
  kind.
- **Selected, not read raw.** Each name is `select_price(...).content.name` for the ancestor
  target: the same scope Subject, source record and root key, with `TargetRef(kind, prefix)` the
  path prefix up to that node. Inherit references, pinned bases and suppression therefore follow
  ADR-0005's rules exactly as they do for `content_name` (point 5: no second definition). A
  structural or suppressed node selects no content, so its name is null.
- **Grain unchanged.** No new row, no change to `uq_gold_current_menu`, `price_state` or any
  CHECK. `has_menu`, the price index and `_place` read nothing new.
- **Business columns.** Both columns are deterministic functions of committed Menu and join the
  rebuild-equality comparison (point 6).
- **No provenance columns for the names.** The wire carries no content provenance today, and the
  ancestor's Evidence is reachable by re-running the selector for that target. See Q3.

### The refresh change

- `packages/helios_core/gold/refresh.py`: for each request, compute the innermost section prefix
  and the item prefix of `request.target.native_path`, and look up each name through
  `select_price` for that prefix, cached per `(subject, record, root key, prefix)` within one
  refresh. Current-mode content selection reads no context, so the cache key leaves context out.
  On `helios_laptop` after the P5-33 rescore, this adds 9,286 section lookups and 1,866 item
  lookups to 52,651 target selections, about +21%. The first refresh took 6 min 46 s, so
  expect about 8 min 15 s.
- `packages/helios_core/gold/menu_read.py`: `CurrentMenuRow` gains `section_name` and
  `item_name`.
- No change to `enumeration.py`, `selection.py`, `catalog.py` or `price_index.py`.

### The wire change

No new field and no type change. `MenuSectionResponse.name` and `MenuItemResponse.name` are
already `str | None`:

- `_shape_menu` takes a section's name from `row.section_name` when the section has no row of
  its own, and an item's name from `row.item_name` when only its variants or modifiers are
  priced. A node's own row still wins, as today.
- The two docstrings that say "null ... Gold carries no section names yet" change to "null when
  the source names no section". The OpenAPI snapshot changes only in those descriptions.
  `test/test_openapi_contract.py` sees no breaking change.
- ROADMAP Phase 7 G-4's "until a Gold ancestor-name column lands" sentence is updated with the
  build.

### Migration

One revision after `68146a4c5fc5`: `ADD COLUMN section_name varchar(512)` and
`ADD COLUMN item_name varchar(512)` on `gold.current_menu`, both nullable with no default. That
is a catalog-only change in PostgreSQL: no table rewrite, no row touched. Existing rows read
null until the next `python -m apps.gold.refresh`. The downgrade drops both columns. The table
is a rebuildable projection (ADR-0004 §1), so a downgrade loses nothing that a refresh can't
rebuild. An upgrade of `helios_laptop` needs `68146a4c5fc5` first (P8-1 owner question).

### Tests and done-when

- Refresh: a section and a variant-only item get their names; an inherited name follows its
  base; a suppressed ancestor gives null; rebuild equality covers the new columns.
- Read and wire: `test_api_venue_menu.py` asserts the section and item names; the no-seq-scan
  test still holds; the snapshot is regenerated.
- Migration round trip (`test_gold_migration.py` pattern) and `alembic check`.
- *Done when* (ADR-0019 step 2): after a refresh on `helios_laptop`, the menu endpoint serves a
  non-null section `name` wherever Silver has one, and a non-null item `name` for every
  variant-only item.

### Alternatives

| Option | Why not proposed |
|---|---|
| `ancestor_names text[]`, parallel to `target_path` | General (nested sections, the `base` element), but the wire flattens nested sections and reads only two names. Silver has no nesting today. An array the API must index by path position is harder to read and test. |
| A node table `gold.current_menu_node` (one row per section/item, with content provenance) | The cleanest grain, but a second table, a second read query per menu and a second rebuild to keep in step, for two strings. Worth it only if node-level provenance reaches the wire. |
| Name-only rows in `current_menu` (`price_state = 'absent'`) | Changes the grain: `_place` and the index's `unpriced_count` would count them, and `has_menu` semantics would need a new filter. |
| Read names from Silver in the API | ADR-0008 §9: the menu endpoint reads Gold only. It would also skip inherit and suppression rules. |

### Owner questions

- **Q1. Shape.** Two columns, `section_name` and `item_name`, as above (recommended)? Or the
  `ancestor_names` array, or a node table?
- **Q2. Redundant on own rows.** Fill each column on every row, including the node's own row
  (recommended, one rule)? Or only where the node has no row of its own?
- **Q3. Name provenance.** No Evidence columns for the names (recommended; the wire has no
  content provenance)? Or add `section_content_page_id` / `item_content_page_id`?
- **Q4. Migration order.** This revision follows `68146a4c5fc5`, so `helios_laptop` (at
  `db40e9424cba`) needs that index migration applied first. Approve both upgrades on
  `helios_laptop` when step 2 is built?

### Owner decision (Amendment 1)

**Answered by the owner on 2026-10-22**, at the start of session P8-3:

- **Q1 shape:** two columns, `section_name` and `item_name`.
- **Q2:** fill every row, including the node's own row (one rule).
- **Q3:** no Evidence columns for the names.
- **Q4:** both `helios_laptop` upgrades approved (a `pg_dump` first, then `68146a4c5fc5`, then the
  new revision, then `python -m apps.gold.refresh`).

### Build notes (Amendment 1)

Built 2026-10-22, session P8-3, as proposed:

- **Migration `c95d883737db`** (after `68146a4c5fc5`): `ALTER TABLE gold.current_menu ADD COLUMN
  section_name VARCHAR(512), ADD COLUMN item_name VARCHAR(512)`; the downgrade drops both. The
  reviewed SQL is in `docs/reviews/sql/2026-10-22-p8-3-gold-names-{upgrade,downgrade}.sql`, pinned
  by `test/test_gold_names_migration.py`, whose populated round trip shows that no row is lost
  and that existing rows read null until the next refresh.
- **Refresh** (`gold/refresh.py`): a row's own node takes its own selected content name; an
  ancestor's name is `select_price(...).content.name` for `TargetRef(kind, path prefix)`,
  cached per `(subject, subject kind, record, root key, instant, prefix)` within one refresh.
  No change to `selection.py`, `enumeration.py`, `catalog.py` or `price_index.py`.
- **Wire** (`apps/api/routes/venues.py` `_shape_menu`): a section or item takes the first
  non-null `section_name` / `item_name` among its rows, else its own row's `content_name`. The
  OpenAPI snapshot changes only in the two docstrings.
- **Tests:** names on a section-level price, an item's own row and a variant-only item; names
  that follow a pinned base; a withdrawn base names nothing. The plan's "suppressed ancestor"
  case cannot occur: `menu.check_aggregate` rejects any child under a suppressed node.
- **`helios_laptop`** (owner Q4): `pg_dump` at 16:06:06Z
  (`var/laptop-run/helios_laptop-2026-10-22-pre-p8-3.dump`, main checkout, 29,100,799 bytes,
  sha256 `2d62469985688f4f3ba4bc57b10a7fd016453017c70feaf7623eeab0a1bbedbb`), then
  `alembic upgrade` to `68146a4c5fc5` and `c95d883737db` (16:06:14Z–16:06:15Z), then
  `python -m apps.gold.refresh` (16:06:19Z–16:14:05Z, **7 min 46 s**, about 5% over the
  15:30Z refresh's 7 min 22 s; the +21% estimate above counted lookups the cache saves).
  Same report as 15:30Z: 54,318 rows, 946 families, 267 cells.
- **Done-when, met.** In Gold, no row has a null `section_name` and no row with an item on its
  path has a null `item_name`; every name equals the Silver node's name on the row's content
  page (54,318 of 54,318 for both). Through the local API (read-only session), all 941
  `has_menu` menus serve **9,527 sections, none `name: null`** (9,527 before), and **52,396
  items, none `name: null`**, including all 1,984 variant-only items (1,984 null before).
- **Not exercised by real data.** No `helios_laptop` page rides a pinned base (0 of 3,666 pages;
  no inherit or suppress node). One base case is untested: a node with its own base link under
  an independent local section gets a `("base", …)`-prefixed path, but the local section's own
  canonical path has no such prefix, so the prefix lookup finds no node and `section_name` stays
  null. The wire already lists that row under a separate base-prefixed section, which is null
  today too. Raised in the P8-3 PR, not changed here.

## Amendment 2 (2026-10-27, proposed): JSON-LD precedence per dish

**Status: Proposed 2026-10-27 (session P8-18). Not built.** Record:
[2026-10-27-p8-18-site-data-fixes.md](../reviews/2026-10-27-p8-18-site-data-fixes.md) §2.
Owner decision (2026-10-27): "prefer JSON-LD when a page has it". This amendment is how.

### The gap

A page with schema.org menu data publishes two Menu streams in one family (`root_key = page`):
`jsonld` and `llm`. In current mode, enumeration takes every live stream head of the subject
(Owner decision D5.3). The selector's `jsonld > dom > pdf > llm` rank decides only between
claims on the **same target path**, and the two streams key their dishes differently (JSON-LD
native keys, llm block keys). So both are enumerated, and the same dish is two Gold rows.
Carmen's Hideaway (venue 8652) shows its tamales twice.

On `helios_laptop`, 152 records publish both streams (90 URLs):
- llm 8,914 priced items, jsonld 5,421.
- 4,701 of the llm's priced items repeat a priced jsonld dish by name. Of 4,118 such names,
  97.9 % carry the same price set; 74 overlap and 13 differ.
- **JSON-LD covers less than the llm on 73 of the 152 records**, and 66 of them have no
  JSON-LD price at all (Kerbey Lane: 2 jsonld items, 0 prices; llm 156 priced).

So whole-page precedence would empty real menus. That is the fork below.

### Proposed: per dish, with the llm stream's other dishes kept (option b)

In `enumerate_current_requests` (Menu domain, `enumeration.py`, beside the selector):

1. For one subject's heads in one family, when a live `jsonld` head exists, collect the
   **dish names** of its priced targets. A target's dish is its innermost `item` ancestor,
   or itself when it is an item. A name is the item's content name, normalized:
   - NFKC, lower case, "&" → "and";
   - the set of its words (order-free).

   This is the validator's `norm_tokens` rule, restated in the Menu domain, since
   `helios_core` does not import `helios_parsing`.
2. A priced target on that subject's `llm` head whose dish name is in that set is **not
   enumerated**. Every other llm target is enumerated as today.
3. Nothing else changes:
   - the selector, its rank and its lifecycle rules;
   - Menu data, since nothing is withdrawn or deleted;
   - the `gold.current_menu` columns, so there is no migration;
   - determinism and rebuild equality (point 6), because the rule is a function of
     committed Menu content.

   `gold.price_index` (ADR-0007) reads `current_menu`, so its medians lose the duplicates
   too.

Sized on the 152 records, priced item rows (the Gold-row proxy):

| Option | Priced rows | Notes |
|---|---|---|
| Today | 14,335 | 4,701 llm duplicates |
| (a) whole page: a live jsonld head hides the llm head | 5,421 | 36 records lose every price |
| **(b) per dish (proposed)** | **9,634** | about 326 near-duplicates remain (same price, names overlap but differ) |
| (c) jsonld when it has at least as many priced dishes, else llm | 8,972 | jsonld on 79 records |
| (d) whole page when jsonld has any price, else llm | 7,840 | jsonld on 86 records; 1,794 llm-only priced dishes lost there |

Carmen's under (b): 73 jsonld rows, plus 16 llm dishes with no jsonld name. Those are mostly
`split_listed` fragments ("Egg", "Potato"), which P8-19's title-slot veto (ADR-0021) removes.
Under (a)/(d) Carmen's shows only the 73.

**Tests when built.**
- Enumeration over a two-stream family: a same-name dish is jsonld only, an llm-only dish
  stays, a jsonld head without prices hides nothing, and a withdrawn jsonld head hides
  nothing.
- A name equal only after normalization.
- An Organization base page: the rule applies within each subject's own heads only.
- Rebuild equality, unchanged.

### Alternatives

- **(a), (c), (d):** see the table. (d) is the literal "prefer JSON-LD when the page has
  it" with a fallback, and drops 1,794 priced dishes that only the llm read.
- **Near-duplicate matching:** same price and a name-token overlap of at least 0.5. It
  would catch most of the 326, but it is fuzzy matching, which point 8 excludes.
- **Doing it in Gold SQL or the refresh:** a second definition of "current" (point 5).

### Owner questions (Amendment 2)

- **Q1. The fork.** Per dish with the llm stream's extras kept, (b) (recommended)? Or whole
  page when JSON-LD has a price, (d)?
- **Q2. The match.** Normalized-name equality only (recommended; about 326 near-duplicates
  stay)? Or also the near-duplicate rule above?
- **Q3. Where.** In `enumeration.py`, Menu domain (recommended: enumeration already defines
  the current catalog)? Or in the selector?
- **Q4. Applying it.** After the build, `python -m apps.gold.refresh` on `helios_laptop`,
  then the Pi's data refresh?

## Implementation notes (2026-09-28)

- Point 4 `as_of`: `gold.current_menu` has no `as_of` column; `effective_instant` plays that role,
  with `staleness_seconds` as the age (`packages/helios_core/gold/models.py`).
- Point 4 `price_state`: the text lists three values; `ck_gold_price_state` allows eight
  (`_PRICE_STATES` in `packages/helios_core/gold/models.py`; migration `5f3a9c1e7b24`).
- Owner decision 4: there is no `scope` column. Establishment rows carry `organization_claim_count`;
  Organization-scoped prices are separate rows with `subject_kind = 'organization'`.
- Context cites ROADMAP §4.3 for `h3-pg`; §4.3 no longer names it (H3 dropped per ADR-0009).

## References

- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) — Gold
  lifecycle, ownership, FK direction, retired-predecessor exclusion.
- [ADR-0005](./0005-immutable-menu-snapshots-and-selection.md) — immutable Menu
  snapshots and the selection semantics Gold projects.
- [ADR-0003](./0003-three-layer-schema.md) — why derived read models are
  refreshed tables, not matviews (superseded, reasoning retained).
- [Plan 0002 Step 6](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models)
  and §8 Gold rebuildability fitness test.
- [RFC-0001 §D2/§D6/§D7](../rfc/0001-menu-pricing-first.md) — current-menu and
  price-index intent, conflict resolution, deferred item taxonomy.
- ROADMAP §4.3 (data layer), Phase 6 (materialization refresh), Phase 7
  (price-index API).
- `packages/helios_core/domains/menu/selection.py` — the accepted `select_price`
  contract Gold reuses.
- [Integrated M01–M14 acceptance](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-menu-integrated-m01-m14-acceptance.md).
