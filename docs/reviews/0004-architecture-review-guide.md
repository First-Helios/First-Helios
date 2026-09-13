# Review guide: ADR-0004 and Plan 0002

**Decision:** Accepted
**Reviewer:** Fortune
**Date:** 2026-09-12

This guide records the review of
[ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md) and
[Plan 0002](../plans/0002-identity-foundation-before-menu.md). Acceptance
approves the architecture and implementation sequence. It does **not**
approve future model or migration diffs; CLAUDE.md requires those to stop for
separate human review.

The bracketed annotations below preserve the owner's original review notes.
Where shorthand was ambiguous, the following accepted interpretation is
controlling:

| Topic | Accepted interpretation |
|-------|-------------------------|
| Menu scope | Organization scope can provide shared menu content, but Establishment facts must support location-specific prices and deterministic override precedence. |
| Identity matching | Deduplication uses typed feature clustering; a name fingerprint alone is never enough. |
| Unresolved records | An append-only `Open` event admits a record to identity resolution and creates explicit indexed `unresolved` state; `resolved` and `needs_review` remain equally visible. |
| Provisional identities | Subjects without meaningful identity features remain provisional and are blocked from downstream vertical writes. |
| Source links | Evidence retains the public Source Endpoint chain so a later API can return the original source URL on demand. |
| Event and FK design | Open/assign/remap/unassign, merge membership, and the ADR FK matrix are accepted as proposed after technical review. |
| Migration | Current application data is disposable pre-production scaffold data. Use a reviewed clean reset; do not spend effort on legacy backfill, compatibility, backup, or long-term preservation. |
| Tests | Protect every high-cost database and architecture invariant with a focused failing case, while avoiding speculative test infrastructure unrelated to the accepted scope. |

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
   - [Migration strategy](../plans/0002-identity-foundation-before-menu.md#7-clean-reset-migration-strategy-and-gates)
   - [Fitness tests](../plans/0002-identity-foundation-before-menu.md#8-architecture-fitness-tests)

The proposal was reviewed against the real current schema rather than as a
greenfield design. The owner then explicitly chose a clean reset: current
constraints still determine safe drop order and migration tests, but current
application rows do not need preservation.

## 2. Architecture decision checklist

Record an explicit yes, no, or requested change for each item.

### Lifecycle and ownership

- [Yes] Bronze is durable source history, not a disposable staging area.
- [Yes] Identity is durable Silver because human decisions cannot be recreated
      by replay.
- [Yes] Vertical Silver data is owned by a named domain schema, beginning with
      `menu`; there is no catch-all `canonical` or `silver` owner.
- [Yes] Gold contains only consumer-facing, rebuildable projections.
- [Yes] Identity and provenance are shared; vertical facts are not.

### Identity grains

- [Yes] Place means a physical location independent of its operator.
- [Yes] Organization means a brand/operating identity independent of location.
- [Yes] Establishment means an Organization operating at a Place for an
      effective interval.
- [Yes] Subject is only a typed identity/lineage handle, not an entity bag,
      EAV store, or substitute for typed tables.
- [Yes, but it can also varry. This is a problem to address when it arrives but should be held in consideration on the arachtectual level that for example, two mcdonalds will have different prices but the same menu] A chain-wide menu may scope to Organization and a location-specific
      menu may scope to Establishment; neither scopes to Place.
- [Yes, as in the case of duplicate we should have proper grain on identity features to determine de-duplication protocall based on feature clustering] Conservative duplicate Place or provisional Organization rows are
      preferable to unsupported automatic merges during migration.

### Resolution and lineage

- [yes, with a proper flag to indicate this so that unresolved indefinitely(unresolved by default but tagged as resolved) does not get lost] A Source Record may remain unresolved indefinitely without creating a
      placeholder Subject.
- [unsure, defer to your best judgement] Assign, remap, and unassign append events with explicit nullability and
      current-target preconditions.
- [Yes] The current-resolution projection is internal Identity state updated in
      the same locked transaction, not a Gold dependency.
- [Unsure] Merge records all inputs and one output, including a survivor in both
      roles when applicable.
- [True] Split creates new outputs, retires the ambiguous predecessor, and does
      not clone vertical facts.
- [True] Retirement is distinct from an Establishment closing.
- [True] Confidence describes the decision method, while Evidence or human
      Adjudication records why the decision was made.
- [True] Events, adjudications, Evidence links, and change members form one
      append-only audit aggregate.

### Boundaries and scope

- [Unsure] The schema FK matrix has no Bronze-to-Silver, Identity-to-vertical,
      cross-vertical, or authoritative-to-Gold dependency.
- [Yes] The import graph permits one explicit all-model Alembic registry and no
      other upward dependency.
- [True] `helios_parsing` remains pure and ORM-free.
- [True] No internal HTTP, message broker, distributed transaction, graph
      database, or microservice is introduced.
- [True] No EAV table, generic offering, generic cross-vertical fact, or future
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
| Clean reset | Why current rows are intentionally discarded and how the migration makes that loss explicit |
| Unsafe environment | Why discovering valuable data stops execution instead of silently switching to a partial backfill |

If any scenario requires an unmentioned nullable FK, direct row rewrite, or
manual cleanup outside the plan, request changes before acceptance.

## 4. Migration review checklist

- [x] The migration PR reports row counts from every superseded table before
      destructive execution.
- [x] Bronze and Identity foundations land before application writes use
      them.
- [x] The reset removes all six current identity tables and obsolete
      `raw` / `canonical` / `mart` schemas.
- [x] No legacy backfill, compatibility view, dual write, or long-term
      preservation path is built.
- [x] Immutability constraints are active before new application writes.
- [x] Upgrade tests seed every old table and prove the data is intentionally
      absent afterward.
- [x] Downgrade and re-upgrade prove structural behavior only; deleted rows
      are not recoverable.
- [x] Discovery starts fresh under the new model, with explicit resolution
      state and Subject-readiness gates.
- [x] If valuable data is discovered before execution, the migration stops
      and returns for a new owner decision.

## 5. Fitness-test review checklist

Before approving an implementation PR, require:

- [If this is a best practice, then yes. Fitness testing is not my strong suite.] one failing test per constraint and event-transition invariant;
- [Yes] metadata tests for table ownership and FK direction;
- [Yes] AST tests for package imports and parser isolation;
- [Yes] raw-SQL tests proving complete decision aggregates and Bronze identities
      reject mutation;
- [Yes] a fixture that actually fires deferred constraints using
      `SET CONSTRAINTS ALL IMMEDIATE` or a real commit;
- [Yes] concurrent resolution and Subject-change tests;
- [Yes] a seeded old-schema fixture proving the accepted clean reset removes
      every superseded table and row;
- [Yes] upgrade, clean-reset result, downgrade, and re-upgrade coverage;
- [Yes] a Gold rebuild comparison over deterministic business columns; and
- [Again for all of the above Defer to best practices, this is not my area of expertise. Consider how early we are in the project and the fact things may change, better to not waste tokens with unneeded tests, but even better to not leave important things open to silently failing. I dont know the correct balance for this] full `make ci`.

## 6. Record the review outcome

**Accepted.** The bookkeeping commit:

1. [x] sets ADR-0004 to `Accepted` with date and owner;
2. [x] sets ADR-0003 to `Superseded by ADR-0004`;
3. [x] sets Plan 0002 to `Approved`;
4. [x] marks Plan 0001 partially superseded using Plan 0002 Section 1;
5. [x] replaces proposal callouts in RFC-0001 and ROADMAP.md; and
6. [x] contains no schema or runtime implementation.

After acceptance, the next implementation unit is **Plan 0002 Step 1:
Bronze provenance foundation**. Its model and migration diff still require a
new human review before merge.

## 7. Suggested sign-off record

```text
Decision: Accepted
Reviewer: Fortune
Date: 2026-09-12

Lifecycle and ownership: Accepted for the current solo-owned modular monolith.
Identity grains: Accepted with feature-cluster deduplication and scoped menu overrides.
Resolution and lineage: Accepted with explicit unresolved/current state.
Dependency directions: Accepted as proposed after technical review.
Migration safety: Clean reset authorized; legacy application data is disposable.
Scope control: No EAV, generic offering, future vertical, graph DB, or microservices.

Required changes or accepted risks:
- Establishment prices may differ from Organization-scoped shared menu content.
- Provisional identities must be blocked until they have meaningful features.
- Tests should protect silent, expensive failures without speculative scaffolding.

Authorization:
- Documentation decision only.
- No schema implementation is approved by this sign-off.
```
