# ADR-0005: Immutable Menu snapshots and scoped selection

**Status:** Accepted
**Date:** 2026-09-17
**Accepted:** 2026-09-17 by project owner Fortune, in this session: “Accept ADR-0005 design”.
**Extends:** [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md)
**Implements:** [Plan 0002 Step 5](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/plans/0002-identity-foundation-before-menu.md#step-5---featdb-add-menu-graph-against-identity-contracts)

## Context

Bronze provenance and Identity exist through Step 4; Menu persistence does not.
The original Menu proposal mixed current eligibility with immutable integrity,
required factual Evidence on synthetic/inherited rows, and could invalidate a
pin during ordinary supersession or expose old prices after withdrawal. Its
Subject-dependent revision key also allowed ambiguous history after remapping.

The owner accepted immutable snapshots, explicit support and inheritance,
persistent pins, withdrawal/restoration, accepted-claim history, and a narrow
first implementation in the [readiness reassessment](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-readiness-reassessment.md#accepted-review-defaults-and-remaining-technical-work).
Those defaults are settled. This ADR records their accepted concrete semantics;
it does not reopen them or rewrite ADR-0004's acceptance history.

## Decision

Store complete immutable Menu interpretation aggregates, each scoped to an
eligible Organization or Establishment and supported by immutable Bronze input.
Select location prices only from that location's claims; retain shared content
and prices with their Organization scope and provenance explicit.

The [reconciled proposal](../plans/0002-step-5-menu-schema-proposal.md) defines
columns, operation shapes, time rules, enforcement and focused tests. The
following decisions are normative; examples in the
[reconciliation record](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-menu-design-reconciliation.md#input-and-selection-examples)
are the human review surface.

1. **Nine Menu tables, one immutable page aggregate.** Currency, page, section,
   item, variant, modifier, applicability, price observation and typed Evidence
   links live in `menu`. Parent/target FKs enforce same-page membership, restrictive
   deletion and typed scope. Inserts are atomic; UPDATE/DELETE/TRUNCATE and late
   membership are rejected. No draft Menu rows or mutable price columns.
2. **Support reflects what was asserted.** Pages, factual replacements,
   suppressions, applicability and prices need direct same-version or matching-
   Capture Evidence. An inherited node is an explicit base reference with no
   copied factual payload. A synthetic Unsectioned grouping derives support
   from its directly supported items. Neither pretends to be a local source
   assertion. Constraints prove support shape/ownership; semantic truth still
   needs supported input and review.
3. **Inherit, full replacement, suppression.** A local source can supply only
   a price using inherited references and mapped ancestors. Replacement supplies
   a complete typed row; optional NULL clears. Suppression hides the base target
   and descendants. Base child/parent correspondence is mandatory; movement
   requires suppression plus a supported addition. No matching by name.
4. **Pins survive ordinary supersession.** Pin exactly one committed published
   Organization page belonging to the Establishment's operator. Observation or
   correction successors do not rebase or invalidate it. Stream withdrawal or
   invalid current Identity mapping/scope blocks dependent current content.
   Restoration enables new pins; pre-withdrawal pins need an explicit new local
   snapshot. Only independent supported local additions survive an unresolved
   base in a current result.
5. **Streams outlive assignments.** Stream identity is Source Record, root key,
   interpretation kind, excluding Subject/version/event. Every page advances
   a single committed predecessor chain and stream revision. Version-specific
   interpretation revision is unique without Subject too. Remap requires a new
   eligible acceptance/event and cannot restart counters, fork history, or move
   old facts. Ordinary observations advance to later Bronze observation time;
   explicit corrections can revisit older input. Exact replay compares the
   whole aggregate and returns its old IDs without new writes, even after remap.
6. **Withdrawal is a stream tombstone.** The Evidence-backed tombstone has no
   graph or base. No older page becomes current. Only an explicit supported
   restoration successor can republish; it supplies a complete aggregate.
   A withdrawal also prevents implicit reuse of pre-withdrawal base pins.
7. **Admission differs from deferred integrity.** Every new page/member/link
   passes live Identity eligibility, exact resolution, pending-lineage and base
   validity checks at insertion. Deferred checks enforce immutable graph/support/
   revision correspondence only. A complete accepted aggregate followed by an
   ordered retirement/remap in the same transaction remains history; later Menu
   insertions fail. No final live check erases that earlier acceptance.
8. **Providers own policy and locks.** Identity expands the union of local/base
   dependencies, acquires batch locks in stable order, and owns SQL/Python
   eligibility policy. Pending unapplied lineage inputs cannot pass stale
   currentness checks. Promotion shares the feature predicate but must not
   require prior eligibility. Bronze owns immutable version/Evidence lookups.
   Menu imports published contracts only. Step 5 takes already committed Bronze
   and resolution input; mixed persist/resolve/Menu orchestration is deferred.
9. **History means accepted claims.** Current selection uses live Identity and
   operating availability. History uses immutable accepted scope/event, knowledge
   cutoff K, optional observation cutoff O, and effective instant E, without
   reconstructing past mutable Identity state. K is server admission time on
   committed rows, not a commit-time audit log. Select the stream head at K
   before observation/context filtering; filtering never revives a predecessor.
   Tombstones visible by K still apply when their observation time exceeds O.
   Pinned factual content retains its own observation time and support.
10. **Exact contexts and stable correspondence.** Compute applicability by
    intersecting local and mapped base ancestor restrictions before comparison.
    Rank exact effective tuples; overlapping unequal tuples remain distinct.
    Unspecified channel is not a wildcard. Stable source-native IDs include
    typed parent paths; fallback positional locators are version-local. Explicit
    typed links to the same pinned base can establish correspondence across
    sources; different bases or equal names cannot.
11. **Price scope is never inferred.** Local contenders rank by interpretation
    kind (`jsonld > dom > pdf > llm`), observation time, confidence, then canonical
    business key. Content uses page confidence; prices use price confidence.
    Shared prices are separate Organization claims, not local contenders.
    Absent local price returns derived unknown without invented Evidence;
    explicit unknown/unavailable retains its actual supporting observation.
    USD integer minor units, exact UTC windows and individual modifiers are the
    initial scope. No currency conversion, recurring schedules or choice groups.

## Alternatives considered

These explain the accepted direction; they are not requests to reopen it.

| Alternative | Benefit | Reason not selected |
|---|---|---|
| Mutable graph and price rows | Less duplicated structure | Loses accepted interpretation history and makes exact replay ambiguous. |
| Require direct Evidence on every physical row | Uniform link-count check | Misrepresents inherited references and synthetic grouping as source facts. |
| Per-field implicit inheritance or automatic rebasing | Smaller local payload | NULL becomes ambiguous and later shared edits silently change local history. |
| Scope-dependent streams or newest eligible predecessor fallback | Simple current lookup | Remaps fork revision identity; withdrawal or failed filters resurrect older claims. |
| Live eligibility checked again at deferred commit | One final guard | Rejects valid earlier acceptance followed by an ordered Identity change. |
| Reconstruct all historical Identity state now | Broader historical query | Mutable readiness/operating edits lack the required historical contract; outside Step 5. |
| Shared or sibling price fallback | More apparently priced locations | Invents location prices the source did not assert. |

## Consequences

Every selected fact can expose its scope, observation time and Evidence without
attributing Organization content to a local source. Replay and corrections are
explicit, and withdrawals cannot reveal obsolete prices. Raw SQL must obey the
same admission and aggregate invariants as commands. Provider boundaries remain
owned and testable without changing matching policy.

Costs include repeated snapshot structure, explicit parent references for local
price-only changes, two revision counters, and explicit rebasing after withdrawal.
Conservative correspondence yields unknown/unresolved results when continuity
is unsupported. Complete stream successors replace that stream's ordinary
candidate; omitted facts are absent, not an assertion of unavailability. Current
queries traverse lifecycle and pin dependencies. No scale claim is made before
measurement on real samples.

Implementation requires one narrow provider prerequisite revision and then one
Menu revision, with generated upgrade/downgrade SQL reviewed separately. Each
expensive rule maps to M01–M14 in the proposal. Native PostgreSQL foundation
validation is not validation of future Menu behavior. CI PostGIS image validation
is still outstanding after Docker socket denial; skipped tests are not acceptance.
No models, contracts, migrations, extraction, ML, Gold, API, runtime dependency
or deployment changes are part of this decision-record work.

## Review and implementation boundary

Owner acceptance covers this design and its reconciled proposal. The current
request authorizes only the narrow provider prerequisite after strict CI-image
PostGIS validation passes. Concrete migration SQL remains separately reviewable;
Menu implementation and application-data execution are not authorized here.
See the [provider gate record](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-provider-prerequisite-gates.md)
for the acceptance and remaining access limitation.

Review the concrete node shapes, lifecycle/time examples and enforcement matrix.
Acceptance of this ADR records the design; it does not approve unseen migration
SQL or application-data execution. The next implementation unit is the narrow
provider prerequisite, after design acceptance and the pre-implementation image
validation gate. Its Python/SQL parity, pending-lineage order, lock races and
provider preservation must be demonstrated before Menu depends on it.

## Implementation notes (2026-09-28)

- The text says provider and Menu work wait on CI-image PostGIS validation; both have merged
  (revisions `b72e6a90c431` provider, `d83f0a21c592` Menu; `packages/helios_core/domains/menu/`).

## Amendment 1 (2026-10-03, proposed): commit-time integrity check cost

**Status:** Proposed. Waits for owner review; no migration is written until it is
accepted. Evidence:
[2026-10-03-menu-write-commit-cost.md](../reviews/2026-10-03-menu-write-commit-cost.md).

**Problem.** ADR-0013 Amendment 8 item 6 found a 1,000-row page taking at least
1 h 25 min to commit. Two costs multiply. `ct_menu_integrity` runs the whole-page
`menu.check_aggregate` once per inserted row. Each check walks every node's path with
`menu.node_path`, which joins every Menu node in the database (`menu.nodes(NULL)`).
Measured on the current schema, commit time is quadratic in page size (406 rows:
226 s) and also grows with the stored corpus (a 10-item page: 2.5 s → 6.5 s as
stored nodes go from 11 to 2,042). A full extraction pass would slow down with every
page it wrote.

**Proposal.** One Menu migration, with no table or column change and no data
rewrite:

1. **Keyed path walk.** A new `menu.node(kind, id)` reads one node by primary key.
   `menu.node_path` keeps its signature and rows but follows parent and base edges
   through it, instead of joining `menu.nodes(NULL)`. This also speeds the selector's
   `_path_applicability_ids`.
2. **Check each page once per aggregate state.** A `BEFORE INSERT` trigger on the eight
   Menu tables bumps a transaction-local generation counter. `menu.check_integrity`
   skips a page already checked at the current generation, and records the
   generation after a successful check.

Measured with both (prototype SQL on disposable databases): commit is linear in page
size (406 rows: 0.66 s, ~340× faster) and flat in the corpus (0.08 s at 11 and at
10,122 stored nodes). The existing Menu, Gold and menu-API suites (339 tests) pass
unchanged against the patched schema. Either change alone falls short: the keyed walk
alone is still quadratic, and the once-per-state check alone still grows ×10 at 10k
stored nodes.

**Why the skipped checks are redundant.** Decision 7 is unchanged: the same
`check_aggregate` still runs at commit over the complete aggregate. A check is only
skipped when nothing in Menu was inserted since that page's last successful check in
the same transaction. A page's aggregate can't change any other way:

- every Menu table rejects `UPDATE`, `DELETE` and `TRUNCATE`;
- members can be inserted only in their page's own transaction (`admit_member`);
- a base pin must be a committed page (`admit_scope`).

A savepoint rollback restores the earlier counter value, so a rollback can only cause
an extra check, never skip one. `persist_menu`'s explicit pre-commit check is kept, so
callers still get the error before commit.

**Trade-off for the owner.** The memo is a custom setting
(`helios_menu.checked_<page>`), so a session that deliberately sets it can skip that
page's commit check. That is no new capability for Helios today: the app connects as
`helios`, the bootstrap superuser and owner of the Menu tables, which can already
disable the trigger. It would matter if a less-trusted role were ever given `INSERT`
on Menu. That role's grants would then need this considered.

**Alternatives not proposed.**

- Rewrite `check_aggregate` as set-based SQL: a larger review surface, not needed by
  the measurements.
- Drop the deferred triggers and rely on `persist_menu`: rejected by this ADR's
  Consequences (raw SQL must obey the same aggregate invariants).
- A single deferred trigger on `menu_page` only: `SET CONSTRAINTS … IMMEDIATE` would
  let later member inserts go unchecked.

**Owner questions.**

1. Accept both changes as one migration?
2. Accept the memo trade-off above?
3. Tests to add with the migration. `SET CONSTRAINTS ALL IMMEDIATE` then a later
   member insert is still rejected. A violation inserted after a savepoint rollback is
   still rejected. `check_aggregate` runs once per page at commit (counted with
   `pg_stat_user_functions` under `track_functions = 'pl'`). Old and new
   `node_path` give identical rows on the existing fixtures, including base pins and a
   cycle. The migration's upgrade and downgrade SQL is snapshotted under
   `docs/reviews/sql/`.
4. After merge: owner-run RUN-A-01 re-times the large page on a disposable clone of
   the laptop database.

## References

- [Detailed Menu proposal](../plans/0002-step-5-menu-schema-proposal.md)
- [Examples, verification and next-work prompt](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-menu-design-reconciliation.md)
- [Original readiness reassessment](https://github.com/First-Helios/First-Helios/blob/dde2dc31ea18585d3559f6e8741c10af260761fc/docs/reviews/0002-step-5-readiness-reassessment.md)
- [Plan 0002](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/plans/0002-identity-foundation-before-menu.md)
- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md)
- [RFC-0001](../rfc/0001-menu-pricing-first.md)
