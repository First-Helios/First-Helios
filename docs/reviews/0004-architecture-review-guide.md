# Review guide: ADR-0004 and Plan 0002

Use this guide before accepting
[ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md) or
authorizing any schema work from
[Plan 0002](../plans/0002-identity-foundation-before-menu.md).

Acceptance approves an architecture and implementation sequence. It does
**not** approve the future model or migration diffs; CLAUDE.md requires those
to stop for separate human review.

## 1. Review in this order

1. **Confirm current code reality**
   - `packages/helios_core/db/models/venue.py`
   - `alembic/versions/a466cf4bc4e0_venue_identity_schema_and_three_layer_.py`
   - `test/test_schema_layout.py`
   - `test/test_venue_identity_schema.py`
2. **Read the decisions being amended**
   - [ADR-0003](../adr/0003-three-layer-schema.md)
   - [RFC-0001 Section D2](../rfc/0001-menu-pricing-first.md#d2-data-model-canonical-schema)
   - [Plan 0001 Steps 1-5](../plans/0001-map-and-menu-collection.md#3-the-sequence)
3. **Review the proposal**
   - [ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md)
   - [Context diagram](../diagrams/0004-modular-monolith-context.md)
   - [Logical ERD](../diagrams/0004-identity-provenance-erd.md)
4. **Review execution safety**
   - [Plan 0002 supersession map](../plans/0002-identity-foundation-before-menu.md#1-exact-supersession-of-plan-0001)
   - [Pre-menu gate](../plans/0002-identity-foundation-before-menu.md#3-must-be-done-before-the-menu-schema)
   - [Migration strategy](../plans/0002-identity-foundation-before-menu.md#7-legacy-migration-strategy-and-parity-gates)
   - [Fitness tests](../plans/0002-identity-foundation-before-menu.md#8-architecture-fitness-tests)

Do not review the proposal as a greenfield design. The migration must preserve
every valid state allowed by the current constraints, including null values,
shared sites, duplicate names, and non-empty tables.

## 2. Architecture decision checklist

Record an explicit yes, no, or requested change for each item.

### Lifecycle and ownership

- [ ] Bronze is durable source history, not a disposable staging area.
- [ ] Identity is durable Silver because human decisions cannot be recreated
      by replay.
- [ ] Vertical Silver data is owned by a named domain schema, beginning with
      `menu`; there is no catch-all `canonical` or `silver` owner.
- [ ] Gold contains only consumer-facing, rebuildable projections.
- [ ] Identity and provenance are shared; vertical facts are not.

### Identity grains

- [ ] Place means a physical location independent of its operator.
- [ ] Organization means a brand/operating identity independent of location.
- [ ] Establishment means an Organization operating at a Place for an
      effective interval.
- [ ] Subject is only a typed identity/lineage handle, not an entity bag,
      EAV store, or substitute for typed tables.
- [ ] A chain-wide menu may scope to Organization and a location-specific
      menu may scope to Establishment; neither scopes to Place.
- [ ] Conservative duplicate Place or provisional Organization rows are
      preferable to unsupported automatic merges during migration.

### Resolution and lineage

- [ ] A Source Record may remain unresolved indefinitely without creating a
      placeholder Subject.
- [ ] Assign, remap, and unassign append events with explicit nullability and
      current-target preconditions.
- [ ] The current-resolution projection is internal Identity state updated in
      the same locked transaction, not a Gold dependency.
- [ ] Merge records all inputs and one output, including a survivor in both
      roles when applicable.
- [ ] Split creates new outputs, retires the ambiguous predecessor, and does
      not clone vertical facts.
- [ ] Retirement is distinct from an Establishment closing.
- [ ] Confidence describes the decision method, while Evidence or human
      Adjudication records why the decision was made.
- [ ] Events, adjudications, Evidence links, and change members form one
      append-only audit aggregate.

### Boundaries and scope

- [ ] The schema FK matrix has no Bronze-to-Silver, Identity-to-vertical,
      cross-vertical, or authoritative-to-Gold dependency.
- [ ] The import graph permits one explicit all-model Alembic registry and no
      other upward dependency.
- [ ] `helios_parsing` remains pure and ORM-free.
- [ ] No internal HTTP, message broker, distributed transaction, graph
      database, or microservice is introduced.
- [ ] No EAV table, generic offering, generic cross-vertical fact, or future
      vertical implementation is introduced.

## 3. Walk the failure scenarios

Do not approve from entity names alone. Trace these scenarios through both
the ADR and ERD:

| Scenario | What the reviewer should be able to explain |
|----------|---------------------------------------------|
| Unresolved Overture row | Which Bronze rows exist and why no Subject or menu row is required |
| Incorrect assignment | Why remap appends history, how concurrent assignments serialize, and what becomes current |
| Duplicate identities | How A+B -> A is represented without losing A's input role |
| Split identity | Why old facts remain historical and are excluded from current Gold until reclassified |
| Human correction | How Adjudication satisfies the audit requirement without fabricating source Evidence |
| Shared first-party URL | Why one Endpoint can produce several Source Records and resolve to several Subjects |
| Closed restaurant | Why Establishment status changes while Place remains usable |
| Lost Gold table | Which source layers rebuild it and which refresh metadata is excluded from equality checks |
| Legacy backfill | Where every current scalar value, timestamp, fingerprint, site link, and raw JSON payload lands |
| Unsafe downgrade | Why downgrade aborts if post-backfill rows exist instead of deleting them |

If any scenario requires an unmentioned nullable FK, direct row rewrite, or
manual cleanup outside the plan, request changes before acceptance.

## 4. Migration review checklist

- [ ] Expansion is additive; no current table is renamed, altered, or dropped
      in the backfill PR.
- [ ] Brand mappings run before Venue mappings, and Venue mappings before
      aliases, sources, and site links.
- [ ] Unbranded Venues receive one provisional Organization each.
- [ ] Legacy discovery timestamps remain provenance metadata and do not
      become Establishment validity dates.
- [ ] Name fingerprints remain non-unique match inputs.
- [ ] `brand.website` and `site_identity` become Bronze Endpoint/source
      history rather than Organization attributes.
- [ ] Every legacy table has deterministic keys and null-safe parity queries.
- [ ] No fuzzy match, proximity match, URL guess, or address merge occurs
      during backfill.
- [ ] Immutability triggers activate only after deterministic backfill and
      parity checks, before application writes.
- [ ] The old `canonical` tables are database-enforced read-only during the
      observation window.
- [ ] Legacy contraction is a later PR with backup, restore rehearsal,
      attached parity report, and separate approval.

## 5. Fitness-test review checklist

Before approving an implementation PR, require:

- [ ] one failing test per constraint and event-transition invariant;
- [ ] metadata tests for table ownership and FK direction;
- [ ] AST tests for package imports and parser isolation;
- [ ] raw-SQL tests proving complete decision aggregates and Bronze identities
      reject mutation;
- [ ] a fixture that actually fires deferred constraints using
      `SET CONSTRAINTS ALL IMMEDIATE` or a real commit;
- [ ] concurrent resolution and Subject-change tests;
- [ ] a non-empty legacy migration fixture covering every current
      relationship and nullable scalar;
- [ ] upgrade, parity, downgrade, and re-upgrade coverage;
- [ ] a Gold rebuild comparison over deterministic business columns; and
- [ ] full `make ci`.

## 6. Record the review outcome

Use one of these outcomes:

- **Changes requested:** list the ADR section, disputed invariant, and desired
  replacement. Do not begin Plan 0002 Step 1.
- **Rejected:** record which current decision remains in force. ADR-0003 and
  Plan 0001 continue to govern.
- **Accepted:** make a documentation-only bookkeeping change:
  1. set ADR-0004 to `Accepted` with date and owner;
  2. set ADR-0003 to `Superseded by ADR-0004`;
  3. set Plan 0002 to `Approved`;
  4. mark Plan 0001 as partially superseded using Plan 0002's Section 1 map;
  5. replace the proposal callouts in RFC-0001 and ROADMAP.md; and
  6. keep schema implementation out of that acceptance commit.

After acceptance, the next implementation unit is **Plan 0002 Step 1:
Bronze provenance foundation**. Its model and migration diff still require a
new human review before merge.

## 7. Suggested sign-off record

```text
Decision: Accepted | Changes requested | Rejected
Reviewer:
Date:

Lifecycle and ownership:
Identity grains:
Resolution and lineage:
Dependency directions:
Migration safety:
Scope control:

Required changes or accepted risks:

Authorization:
- Documentation decision only.
- No schema implementation is approved by this sign-off.
```
