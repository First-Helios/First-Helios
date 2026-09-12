# Plan 0002: Identity foundation before menu schema

**Status:** Proposed - blocked on ADR-0004 acceptance
**Implements:** [ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md)
**Supersedes on approval:** Affected portions of
[Plan 0001](./0001-map-and-menu-collection.md), listed in Section 1

This is an implementation plan, not authorization to change the schema.
Every PR under `alembic/versions/**` or `packages/**/db/models/**` remains a
CLAUDE.md stop-and-review point.

## 0. Ground truth at proposal time

Current `main` contains two migrations. The latest migration:

- creates empty `raw` and `mart` schemas;
- moves `public.venue` to `canonical.venue` without dropping its rows;
- creates `canonical.brand`, `venue_alias`, `venue_source`,
  `site_identity`, and `venue_site`;
- requires every `venue_source` to resolve immediately to one Venue;
- cascades deletion of a Venue into its aliases, source links, and site
  links; and
- adds metadata tests that require exactly `raw`, `canonical`, and `mart`.

There are no menu, capture-index, rejected-signal, or Gold/Mart tables.
There is no identity resolver, discovery ingest, or public venue read path.
The migration strategy below assumes the existing tables are non-empty even
if development databases happen to contain no rows.

## 1. Exact supersession of Plan 0001

Plan 0001 remains the historical record for the work already merged and the
product milestones that do not conflict with ADR-0004.

| Plan 0001 portion | Disposition under this plan |
|-------------------|-----------------------------|
| Section 0 decisions D-1 through D-3 | Unchanged: API remains after seeding; DuckDB and the configured Travis/Williamson bounding box remain approved |
| Section 1 code snapshot | Replaced by Section 0 above |
| Section 2 dependency budget | Unchanged; this plan adds no dependency |
| Step 1 venue identity schema | Completed historical work; its resulting schema is the migration source, not the target architecture |
| Step 2 menu graph schema | Superseded and paused until the pre-menu gate in Section 3 passes |
| Step 3 raw/mart layers | Superseded by Bronze and Gold lifecycle semantics plus bounded-context schemas |
| Step 4 venue seeding | Coverage goals retained; persistence changes from `venue_source -> venue` to Bronze source records plus append-only Identity resolution |
| Step 5 website and menu-URL resolution | Discovery behavior retained; a website is Bronze provenance and may remain unresolved or resolve to Organization/Establishment |
| Steps 6 through 8 | Product intent and ordering retained; names and FKs must use the new module contracts |
| Section 4 deferred work and Section 5 milestone | Unchanged |

RFC-0001 remains authoritative for the menus-first product and source policy.
ADR-0004 governs architecture where RFC-0001 assumed `raw`, `canonical`, and
`mart` ownership.

## 2. Decisions fixed by ADR-0004

The implementation PRs must not reopen these choices:

1. Helios is a modular monolith with one database and migration history.
2. Bronze is source-faithful and permits unresolved Source Records.
3. Silver is split into shared `identity` and named vertical schemas; there
   is no generic `silver`/`canonical` owner.
4. Gold alone is freely rebuildable. Bronze evidence and Identity decisions
   are durable.
5. Subject is a typed identity handle, not EAV. Place, Organization, and
   Establishment remain separate grains.
6. Source resolution, remap, unassign, merge, split, and retirement history
   is append-only.
7. Menu facts are owned by `menu`; only identity and provenance are shared.
8. Package imports and FKs follow the dependency matrices in ADR-0004.

## 3. Must be done before the menu schema

The menu model must not be proposed or implemented until all of the following
are true:

1. The owner accepts ADR-0004 and this plan.
2. The Bronze source, Source Record, immutable version, and Evidence grains
   have approved names and constraints.
3. The Subject, Place, Organization, and Establishment grains have approved
   keys, effective-time rules, and deletion behavior.
4. Resolution and Subject-change event tables enforce append-only history,
   confidence bounds, evidence links, valid operation shapes, and acyclic
   lineage.
5. The current `Brand`, `Venue`, and `VenueSource` rows have an approved,
   deterministic backfill mapping with no lossy automatic deduplication.
6. Architecture fitness tests enforce schema, FK, import, append-only, and
   typed-grain boundaries.
7. The menu dependency seam is fixed:
   - a menu root may scope to Organization or Establishment;
   - it may not scope to Place;
   - the root references the immutable Bronze Source Record Version from
     which it was derived;
   - each accepted observation links to one or more immutable Bronze
     Evidence rows;
   - unresolved input remains Bronze and does not require a placeholder menu
     row; and
   - menu-specific observations live only in `menu`.
8. An upgrade against a non-empty legacy fixture passes the parity checks in
   Section 7, and the owner reviews the generated SQL twice.

The old `canonical` tables do not have to be physically dropped before the
menu PR. They do have to be read-only compatibility data, with new writes
using Bronze and Identity. Keeping them through a short cutover window is
safer than combining backfill, cutover, and destructive contraction.

## 4. Deferred work

The following is explicitly **not** a prerequisite for the menu schema:

- fuzzy/probabilistic identity matching and calibrated thresholds before the
  discovery phase that owns the duplicate-rate milestone;
- merge/split/remap CLI commands or a human review UI;
- bulk correction of legacy identities beyond deterministic backfill;
- legal-entity, franchise, parent/subsidiary, or brand-hierarchy modeling;
- retention or partitioning policy for Bronze payload versions;
- Gold menu projections and API-specific indexes;
- cross-venue menu-item taxonomy;
- any second vertical;
- a generic offering, generic observation, or EAV model;
- a graph database, microservices, message broker, or distributed events; or
- dropping the legacy tables after cutover.

The event model and constraints are required before menu because later facts
will depend on stable identity semantics. Operator tooling around those
events is deferred until real correction volume justifies it.

## 5. Proposed implementation sequence after approval

Each step is a separate review-sized PR with green `make ci`. Steps that
touch models or migrations stop for owner review.

### Step 1 - `feat(db): add Bronze provenance foundation`

- Add `bronze` only when its first tables land.
- Add typed models for Source, Source Endpoint, Source Record, Source Record
  Version, Capture, and Evidence.
- Keep source payload JSON only on immutable Bronze versions.
- Permit Source Records with no Identity row or resolution event.
- Enforce deterministic source namespace plus external-key uniqueness.
- Make Source namespace keys, Endpoint identities, Source Record
  `(source_id, external_key)` keys, Captures, Versions, and Evidence immutable
  by contract. The database immutability triggers activate after the legacy
  backfill in Step 3, before any application write path uses these tables.
- Extend Alembic's allowlist and replace the "exactly three layers" test with
  ownership-aware checks.
- Move all-model Alembic registration to
  `packages.helios_core.db.model_registry` as the single import-direction
  exception, and update CLAUDE.md's registration instruction in the same PR.
- Do not remove `raw`, `canonical`, or `mart` in this step.

### Step 2 - `feat(db): add shared identity foundation`

- Add `identity.subject`, `place`, `organization`, and `establishment` with a
  shared-PK typed-grain pattern.
- Add typed names/aliases without arbitrary attribute rows.
- Add append-only `resolution_event`, optional human adjudication, and
  Evidence links.
- Add append-only `subject_change`, typed input/output members, and Evidence
  links.
- Add rebuildable `identity.current_resolution` and Subject-lineage
  projections. Serialize resolution transitions by locking the Source Record
  and updating the projection in the same transaction as event insertion.
- Enforce:
  - one typed grain per Subject;
  - `(subject_id, subject_kind)` composite FKs and constant-kind checks on
    typed grains;
  - Organization and Place references on every Establishment;
  - valid assign/remap/unassign transitions;
  - merge/split/retire cardinalities and same-kind inputs/outputs;
  - stable-order member locking and current-input validation for concurrent
    Subject changes;
  - no lineage cycles;
  - confidence in `[0, 1]`;
  - method version, actor class, decision time, and effective time on every
    resolution and Subject change;
  - at least one Bronze Evidence link or append-only human adjudication per
    decision; and
  - no hard delete of a referenced Subject.

Implementation may use deferred constraint triggers where a row-level
`CHECK` cannot enforce event cardinality. The migration must name and test
each such invariant.

### Step 3 - `feat(db): backfill legacy venue identity`

Use an additive migration and a deterministic migration actor/method. Do not
merge records by fuzzy name, proximity, URL, or address during backfill.

The mapping is:

| Current row | Target |
|-------------|--------|
| `brand` | One Organization Subject with organization kind `brand`; preserve name, non-unique match fingerprint, and timestamps with a legacy Evidence record |
| `venue` | One Place Subject plus one Establishment Subject; raw/normalized address, coordinates, and H3 move to Place, while name and operating status describe the Establishment. Discovery `first_seen_at`/`last_seen_at` remain provenance metadata and do not become business `valid_from`/`valid_to`. |
| branded `venue` | Establishment points to the Organization produced from its Brand |
| unbranded `venue` | Create one provisional Organization per Venue from its name; never merge two such Organizations during migration |
| `venue_alias` | A typed name on the Establishment Subject, preserving alias fingerprint, source, and timestamps |
| `venue_source` | A Bronze Source Record keyed by `(source, external_id)`, one immutable version containing `raw_identity` and seen/timestamp metadata, and an initial assign event to the Establishment Subject |
| `brand.website` | A first-party-web Source Endpoint plus a legacy Source Record keyed by Brand ID and assigned to the Brand's Organization Subject; do not duplicate the URL as an Organization attribute |
| `site_identity` | A first-party-web Source Endpoint keyed by canonical URL plus a `site:<id>:endpoint-state` Source Record Version preserving original URL and liveness fields |
| `venue_site` | One legacy Source Record per `(site_identity_id, venue_id)` link, assigned to the Establishment Subject with the original resolution method as Evidence; multiple records may share one Endpoint |

Create a reserved legacy source namespace such as `helios-v2-legacy` for
facts that have no original `venue_source` row. That namespace makes
migration-derived claims explicit instead of presenting them as Overture or
OSM observations.

The migration stores deterministic legacy keys (`brand:<id>`,
`brand:<id>:website`, `venue:<id>:place`,
`venue:<id>:establishment`, `site:<id>:endpoint-state`, and
`site:<site_id>:venue:<venue_id>`) in Bronze, so every old row and both
Venue-derived Subjects have a durable crosswalk without requiring a
permanent application compatibility table.

Venue and alias name fingerprints remain non-unique matching inputs on their
typed Subject names. Every legacy scalar value is also retained in the
migration Source Record Version so parity does not depend on a normalized
target preserving source spelling or timestamp semantics.

After inserts and parity checks, Step 3 activates database immutability
triggers for Source namespace keys, Endpoint identities, Source Record
identity columns, Captures, Versions, Evidence, resolution events,
adjudications, event-Evidence links, Subject changes, change members, and
change-Evidence links. Its downgrade drops those triggers before removing
only the deterministic backfill rows; the earlier foundation revisions then
remain downgradeable without a bypass flag. The downgrade aborts rather than
delete anything if it finds rows not owned by the deterministic migration
actor/namespace.

### Step 4 - `refactor(db): cut writes to Bronze and Identity`

- Replace the current Venue/Brand ORM write surface with module-owned
  provenance and identity commands.
- Keep old `canonical` tables read-only for parity inspection, enforced by
  database guards that Step 4's downgrade removes.
- Provide deterministic resolution for exact external-key, canonical-URL, and
  legacy-crosswalk matches. New discovery writes create Bronze records first,
  then append Identity decisions only when those rules resolve them.
- Make unresolved candidates observable and retryable rather than rejected.
- Run the architecture fitness suite from Section 8.

There is no dual-write period: no current production feature requires it,
and dual write would create two competing identity authorities. The old
tables are a frozen comparison source only.

Fuzzy and probabilistic matching remains in Plan 0001's discovery step, where
the hand-labeled duplicate-rate metric is measured. It is deferred from this
pre-menu foundation, not removed from the product plan.

### Step 5 - `feat(db): add menu graph against identity contracts`

This is the replacement for Plan 0001 Step 2 and starts only after the gate
in Section 3.

- Create `menu` with the first real menu table; do not pre-create an empty
  vertical schema.
- Keep the typed menu graph required by RFC-0001.
- Scope the menu root to an Organization or Establishment Subject with an
  explicit allowed-kind invariant.
- Link the menu root to its immutable Bronze Source Record Version and each
  accepted observation to one or more immutable Bronze Evidence rows.
- Leave unresolvable extraction output in Bronze rather than manufacturing a
  fake Subject or nullable half-canonical menu.
- Keep money, item, modifier, applicability, and price history semantics
  inside `menu`; do not add a shared offering model.

The exact menu tables and constraints remain the subject of that schema PR.

### Step 6 - `feat(db): add Gold menu read models`

- Create `gold` only with its first real projection.
- Build current-menu and price-index tables from Identity plus Menu.
- Prove a full rebuild without mutating Bronze, Identity, or Menu. Compare
  deterministic business columns; exclude refresh-run metadata such as
  `refreshed_at`.
- Keep refresh ownership in the Gold module.

This replaces Plan 0001 Step 3's Mart portion and can land with the API work
that first consumes it.

### Step 7 - `refactor(db): contract legacy schemas`

After at least one cutover cycle and explicit owner approval:

- take and verify a backup;
- rerun all parity queries;
- remove obsolete ORM registrations;
- drop the migrated `canonical` tables;
- drop empty `raw` and `mart`;
- remove transitional schema allowlist entries.

This destructive contraction must not share a PR with backfill or the menu
schema. If any legacy row lacks a target or preserved unresolved record, the
step is blocked.

## 6. Architecture acceptance scenarios

These scenarios define behavior, not a particular service API.

| # | Given | When | Then |
|---|-------|------|------|
| A1 | An Overture record has not matched any identity | Its capture and record version are ingested | Bronze commits successfully, no placeholder Subject is created, and the record appears in the unresolved set |
| A2 | An unresolved Source Record has address and name Evidence | A resolver assigns it to an Establishment at confidence `0.86` | One assign event and its Evidence links append; the current projection points to that Establishment |
| A3 | A Source Record currently points to Establishment A | Better Evidence supports Establishment B | A remap event names A and B; A's event remains unchanged; current resolution points to B |
| A4 | A Source Record was assigned incorrectly and no replacement is known | An unassign decision is recorded | The earlier assignment remains queryable and the record returns to unresolved |
| A5 | Two same-kind Subjects are proven duplicates | A merge selects one survivor | Both histories remain; the loser retires through lineage; existing facts are not rewritten; current lookup reaches the survivor |
| A6 | One Establishment Subject represented two real locations | A split is adjudicated | Two or more new Establishments are created, the predecessor retires as ambiguous, and no old menu fact is copied automatically |
| A7 | A restaurant stops operating at an address | Its closure is recorded | The Establishment closes while the Place remains current and reusable |
| A8 | One first-party site emits a chain-wide menu-scope Source Record | Its scope is resolved | The record resolves to the Organization; a chain menu may use that Organization Subject |
| A9 | A first-party page emits a location-specific Source Record | Its scope is resolved | The record resolves to that Establishment; location-specific menu facts do not leak to sibling Establishments |
| A10 | One endpoint is linked to multiple legacy Venues | Legacy data is backfilled | Each link becomes its own evidenced Source Record and assignment; the shared URL is not forced to resolve to one Subject |
| A11 | A Gold current-menu table is lost | The refresh command runs | Gold is reconstructed from Identity and Menu without changing their rows |
| A12 | A legacy database contains every current table with rows | The additive migration runs | Every row has a deterministic target or preserved unresolved representation, with parity queries returning zero unexplained rows |

## 7. Legacy migration strategy and parity gates

The migration follows **expand -> backfill -> cut over -> observe ->
contract**.

### Expand

- Create Bronze and Identity tables alongside `canonical`.
- Add no FK from a legacy table into the new schemas.
- Keep all existing constraints active.
- Seed the migration Source and method metadata deterministically.

### Backfill

- Process Brands before Venues, Venues before aliases/source/site links.
- Use stable ordering and idempotent keys so rerunning produces no duplicate
  Subjects, versions, or events.
- Preserve timestamps and original payloads.
- Make no fuzzy identity decisions.
- Write an explicit migration Evidence row for every value derived only from
  legacy canonical columns.

### Cut over

- Stop writes through legacy ORM models.
- Route collection to Bronze first and Identity second.
- Keep legacy tables available read-only for parity and rollback analysis.
- Do not create compatibility views that hide which model a caller uses.

### Observe

At minimum, run these parity checks against a seeded non-empty fixture and a
copy of any real development data:

| Check | Required result |
|-------|-----------------|
| Brand -> Organization mapping | Exactly one target Organization per Brand |
| Organization fingerprints | Values preserved as non-unique match inputs; duplicate fingerprints do not merge or fail |
| Brand website preservation | Every non-null website becomes or reuses a first-party-web Endpoint, with a Brand-keyed Source Record assigned to the Brand Organization |
| Venue -> Place mapping | Exactly one target Place per Venue |
| Venue -> Establishment mapping | Exactly one target Establishment per Venue |
| Establishment operator | Exactly one Organization, using Brand when present and a per-Venue provisional Organization otherwise |
| Venue scalar preservation | Name/fingerprint, raw and normalized address, coordinates, H3, status, and all timestamps compare null-safely to their typed target or migration Version |
| VenueSource preservation | Same row count and same `(source, external_id)` keys |
| VenueSource scalar preservation | Raw identity plus first/last-seen and created/updated timestamps compare null-safely; canonicalized JSON hashes match |
| Initial resolutions | Exactly one migration assign event per VenueSource |
| Alias preservation | Same count, text, fingerprint, source, timestamps, and owning legacy Venue |
| Site preservation | Every SiteIdentity becomes a Source Endpoint plus one Version preserving canonical/original URL, liveness status, verification time, and row timestamps |
| VenueSite preservation | Same pair count and resolution method/timestamps; one evidenced Source Record and initial assignment per pair |
| Coordinates and H3 | Exact value equality, including null pairs |
| Unexplained legacy rows | Zero |

### Contract

The contract migration is independently reversible only from its verified
backup once new writes begin. It therefore needs explicit owner approval,
the parity report attached to its PR, and a restore rehearsal. A successful
backfill is not permission to drop the old tables in the same migration.

## 8. Architecture fitness tests

Use existing pytest, SQLAlchemy metadata, and the Python standard library.
Do not add an architecture-test dependency.

| Fitness test | Mechanism | Required failure |
|--------------|-----------|------------------|
| Every table has one owner | Inspect `Base.metadata`; schema must map to exactly one module | Missing, `public`, unknown, or multiply owned schema |
| Schema FK direction | Inspect every `ForeignKey`; compare with ADR-0004's matrix | Bronze -> Identity/Menu/Gold, Identity -> Menu/Gold, cross-vertical, or authoritative -> Gold |
| No destructive provenance cascade | Inspect `ondelete` for Evidence, Source Record Version, resolution, and observations | Cascade can erase a source version, Evidence, decision, Subject history, or vertical observation |
| Package import direction | Parse first-party imports with `ast`; allow only `packages.helios_core.db.model_registry` to import every model for Alembic | Lower/shared module imports a vertical, Gold, or app; one vertical imports another; any other registry exception appears |
| Parser isolation | Inspect imports under `packages/helios_parsing` | Import from SQLAlchemy or any Helios ORM module |
| Subject typed-grain invariant | Composite-FK tests plus a deferred-invariant fixture | Subject has zero or multiple typed rows after commit, or row kind disagrees with subtype |
| Menu scope kind | Database constraint test in the future menu PR | A menu root references Place or an unapproved Subject kind |
| Unresolved is valid | Insert Source Record and Version without resolution | Insert fails or creates a placeholder identity |
| Decision aggregate append-only | Raw SQL `UPDATE` and `DELETE` against events, adjudications, Evidence links, and Subject-change members | Any statement succeeds |
| Bronze identity immutable | Raw SQL changes a Source namespace, Endpoint identity, or Source Record key, or updates/deletes a Capture, Version, or Evidence | Any statement succeeds |
| Resolution transition validity | Database/service transaction tests | Remap/unassign does not name current source; assign overwrites an existing mapping |
| Subject-change shape | Constraint-trigger tests | Invalid merge/split/retire member cardinality or mixed Subject kinds commit |
| Lineage acyclicity | Transaction test | A Subject becomes its own successor directly or transitively |
| Confidence bounds | Constraint tests at below `0`, above `1`, and boundaries | Out-of-range value commits or valid boundary fails |
| Evidence required | Transaction test | Decision commits without immutable Evidence/manual adjudication |
| Gold rebuildability | Seed Bronze/Identity/Menu, delete Gold, run refresh, and compare business columns | Gold differs from its pre-delete deterministic result or source layers change |
| Migration parity | Seed every legacy relationship and run Alembic upgrade | Any Section 7 parity query is non-zero |

Temporary migration schemas may be allowlisted only through an explicitly
named transition set with a test that identifies the contract step that
removes them. The final test must not freeze a universal schema count:
bounded contexts, not the number three, are the invariant.

There is no application-settable append-only bypass. Step 3 installs the
triggers only after its deterministic inserts and drops them first on
downgrade. Later corrections append events; any future data-fix migration
that proposes disabling immutability is a separate owner-review gate and must
prove that it restores every trigger before commit. A global
`session_replication_role` bypass is not permitted.

The current savepoint-based `session` fixture cannot prove deferred
constraint behavior by calling `session.commit()`. Deferred-invariant tests
must use a dedicated fixture that executes `SET CONSTRAINTS ALL IMMEDIATE`
inside the outer transaction, or performs a real commit with isolated
cleanup. Every deferred trigger gets a failing case through that fixture.

## 9. Human review gates

Stop for owner review at:

1. ADR-0004 and this plan.
2. Bronze model and migration SQL.
3. Identity model, event constraints, and migration SQL.
4. Legacy backfill SQL and parity report.
5. Menu model and migration SQL.
6. Any destructive legacy contract migration.

Use the
[ADR-0004 human review guide](../reviews/0004-architecture-review-guide.md)
for the decision checklist, failure-scenario walkthrough, and sign-off
record.

No proposed schema in this plan is implemented by the documentation PR.
