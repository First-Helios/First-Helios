# Plan 0002 Step 5: menu schema proposal

**Status:** Design accepted by owner on 2026-09-17 in
[ADR-0005](../adr/0005-immutable-menu-snapshots-and-selection.md).
Accepted review defaults are retained. No Menu schema or contract is implemented.
**Branch:** `Plan-0002-Step-5`. **Migration parent:** `91f4c2a7d6e8`.
**Provider update (2026-09-18):** The CI-image gate passed and provider revision
`b72e6a90c431` is prepared for [separate review](../reviews/0002-step-5-provider-prerequisite.md).
The migration parent above is the provider boundary; future Menu follows its
accepted revision. The specification and historical planning records are retained.
The original proposal baseline was `d1ff54cdae5d6fc59c385c77a4a89a1e91d8fc2f`
(Step 4 / PR #15); it is not a claim that today's working tree is clean.

Authority: [ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md),
[Plan 0002 Step 5](0002-identity-foundation-before-menu.md#step-5---featdb-add-menu-graph-against-identity-contracts),
[RFC-0001](../rfc/0001-menu-pricing-first.md), and the
[accepted defaults](../reviews/0002-step-5-readiness-reassessment.md#accepted-review-defaults-and-remaining-technical-work).
This document supplies the detailed design; ADR-0005 records its decisions.
The [reconciliation record](../reviews/0002-step-5-menu-design-reconciliation.md)
contains examples, verification, remaining gates, and the self-contained handoff.
Section 11 preserves historical planning text without granting it authority over
this reconciled specification.

Scope is persistence, admission, replay, and pure selection over already
persisted, committed Bronze input with resolved Identity. No extraction, ML,
fuzzy matching, matching-policy change, Gold, API, Step 6, new runtime dependency,
or deployment work. Schema and generated SQL remain separately reviewable.

## 1. Immutable snapshots and streams

A `menu_page` is one complete accepted interpretation of one Bronze version,
not a fetch. Its graph, prices, contexts, and support links form an immutable
aggregate inserted in one transaction. URL, payload, capture, hash, and replay
location stay in Bronze. All Menu tables reject UPDATE, DELETE, and TRUNCATE,
including no-op updates and support/catalog changes. Late child/link insertion
is forbidden. The command flushes and never commits; the caller owns commit.

A **stream** is `(source_record_id, root_key, source_kind)`, independent of
Subject, resolution event, and Bronze version. `source_kind` is interpretation
kind (`jsonld`, `dom`, `pdf`, `llm`), not Bronze Source kind. A stream has a
single append-only predecessor chain. Its first page is revision 1; every
subsequent page explicitly names the committed head and advances
`stream_revision` by one. No implicit supersession by arrival time. An ordinary
later observation is also an explicit successor: omission means no current
claim in that snapshot, never evidence of unavailability.

Organization pages supply shared content. An Establishment may pin one
published Organization page belonging to its operator. Ordinary observation
or correction supersession does not invalidate an existing pin. No rebasing,
name matching, sibling-price fallback, or Organization-to-local price copying.
A local price and the inherited description can have different scopes,
observation times, and Evidence paths; selection returns those separately.

## 2. Tables and relational shape

Schema `menu`, package `packages.helios_core.domains.menu`. Except `currency`,
each table has a surrogate BIGINT PK. Children carry non-null `page_id` and
`UNIQUE(id, page_id)` for composite FKs. Surrogate IDs never rank facts.
Column names below are the review contract; final SQL names must map to Section 9.

| Table | Columns and natural uniqueness |
|---|---|
| `currency` | `code VARCHAR(3)` PK, `minor_unit SMALLINT`; immutable catalog seeded with `USD, 2` only. |
| `menu_page` | `subject_id`, `subject_kind`, `source_record_id`, `source_record_version_id`, `resolution_event_id`, `root_key`, `source_kind`, `method`, `method_version`, `stream_revision`, `interpretation_revision`, `observed_at`, `accepted_at`, `confidence`, `operation`, `state`, nullable `base_organization_page_id`, nullable `supersedes_page_id`, server-stamped `created_transaction_id`. Unique `(source_record_id, root_key, source_kind, stream_revision)` and `(source_record_version_id, root_key, source_kind, interpretation_revision)`; partial unique non-null `supersedes_page_id`. Subject is absent from both revision keys. |
| `menu_section` | `page_id`, `section_key`, optional `source_native_key`, optional `parent_section_id`, `name`, `course`, `position`, optional `applicability_id`, optional `base_section_id`, `effect`, `support_kind`. Unique `(page_id, section_key)`. |
| `menu_item` | `page_id`, `item_key`, optional `source_native_key`, required `section_id`, `name`, `description`, `calories`, `dietary_tags TEXT[]`, `position`, optional `applicability_id`, optional `base_item_id`, `effect`, `support_kind`. Unique `(page_id, item_key)`. |
| `menu_variant` | `page_id`, `variant_key`, optional `source_native_key`, required `item_id`, `label`, `position`, optional `applicability_id`, optional `base_variant_id`, `effect`, `support_kind`. Unique `(page_id, item_id, variant_key)`. A size/portion; no invented default variant. |
| `menu_modifier` | `page_id`, `modifier_key`, optional `source_native_key`, exactly one of `item_id` / `section_id`, `label`, `required`, `position`, optional `applicability_id`, optional `base_modifier_id`, `effect`, `support_kind`. Unique `(page_id, modifier_key)`. Required means this individual modifier, not a choice group. |
| `menu_applicability` | `page_id`, `applicability_key`, `channel`, optional `service_period`, optional `valid_from` / `valid_to` TIMESTAMPTZ. Unique key within page and unique canonical declared context within page. |
| `price_observation` | `page_id`, `observation_key`, exactly one of `section_id` / `item_id` / `variant_id` / `modifier_id`, required `applicability_id`, `price_kind`, `price_state`, nullable `amount_minor BIGINT`, required `currency_code`, `confidence`. Unique `(page_id, observation_key)`; time/method inherited from page. |
| `evidence_link` | `page_id`, `evidence_id`, `page_target BOOLEAN`, nullable section/item/variant/modifier/applicability/price target IDs. `page_target::int + num_nonnulls(the six IDs) = 1`. Seven partial unique `(target, evidence_id)` indexes including `(page_id, evidence_id)` for page support. |

Factual columns in graph tables are nullable only to represent the explicit
inherit/suppress shapes below. CHECKs enforce required fields for replacements.
Every key/label is bounded, nonblank and trimmed when present; positions and
calories are nonnegative integers, dietary tags normalized/non-null/unique for
replacement items. Methods are nonblank. Confidence is finite NUMERIC(5,4)
in `[0,1]`. Page observation time equals Bronze's immutable observation time.

Every FK specifies `ON DELETE RESTRICT`, `ON UPDATE NO ACTION`; ORM has no delete
cascade. Allowed FKs: Menu to Menu, Identity, Bronze only. No provider references
Menu, no authoritative reference to Gold. Page `(subject_id, subject_kind)`
references Subject's matching composite key, with allowed kinds Organization or
Establishment only. Page references immutable resolution event and version,
never a current-state projection. An immutable provider lookup verifies that
`source_record_id` belongs to that version.

All parent, applicability, price-target and link-target relationships use
`(id, page_id)` FKs. Deferred checks reject section cycles. Typed base FKs
reference the correct table in precisely the pinned page; partial unique
`(page_id, base_*_id)` prevents duplicate overrides. Organization pages cannot
have bases. A base page is committed before local admission.

### Node shape, support, and parent mapping

| Shape | Stored payload | Support and meaning |
|---|---|---|
| `effect=replace`, `support_kind=direct` | Complete required typed content; optional NULL clears that field. Base optional. | At least one local Evidence link supporting the factual row; no per-field merging. Without a base link this is a local addition. |
| `effect=inherit`, `support_kind=inherited` | Required typed base link and local parent reference; all factual payload, position, native key, and applicability NULL. | Traverse the base row's support; do not copy its fields or claim local factual Evidence. Optional local Evidence may explain correspondence only. Local prices may target this reference. |
| `effect=suppress`, `support_kind=direct` | Required typed base link and mapped local parent; factual payload, position, native key, and applicability NULL. | Local Evidence explicitly supports suppression. Hides target and descendants, including prices; no local child/price may target a suppressed branch. |
| `effect=replace`, `support_kind=structural` | Section only: reserved `Unsectioned` key/name, position 0, no base/parent/course/native key/applicability. | Deterministic grouping of at least one directly supported local item. Support is through those child items; not an observed source heading. No direct Evidence is fabricated. |

Pages (including withdrawals), direct nodes, every declared applicability, and
every price require direct Evidence. Structural/inherited nodes require their
explicit support path instead. A missing local price produces a derived unknown
result, no fabricated `price_observation` or Evidence. An explicitly observed
unknown/unavailable price is a real supported price row.

Evidence must reference either the page's exact Bronze version or that version's
non-null Capture. Same URL/source/record without the right version/capture is
insufficient. Base Evidence remains on the base; it cannot satisfy a direct
local claim. Provider lookups establish ownership; the writer/reviewer must
establish semantic support. SQL cannot prove that an excerpt means a price.
No generic EAV support store or cross-version supplemental Evidence is added.

For every mapped child, its local parent must map to the base child's parent:
section parent to section parent (root to root), item section to base section,
variant item to base item, modifier to the same typed item/section parent.
Create inherit references up the complete parent path for price-only changes.
A replacement parent can retain its base correspondence. Moving a shared node
requires suppression at its original location and a new directly supported
local addition. Unmentioned base descendants remain inherited unless an
ancestor is suppressed. Structural sections cannot masquerade as base parents.

## 3. Provider boundary and admission

Proposed additions, not existing APIs:

- Bronze publishes frozen version/Evidence DTOs and immutable SQL lookup helpers
  for record, capture, observed time, and canonical source/Evidence keys. Bronze
  owns their traversal and validation. Menu imports only provenance contracts.
- Identity publishes a **batch** resolved-scope guard, with Subject/Source Record
  IDs and expected immutable resolution-event IDs as inputs. It expands all
  local/base Subject dependencies, acquires the complete lock set, and returns
  eligible typed scopes and Establishment parents. Menu does not discover
  parents, order provider locks, or copy readiness policy.
- Identity owns the corresponding SQL guard for raw-SQL admission and shared
  feature predicate. Python/SQL eligibility behavior must agree. Promotion uses
  that feature predicate without requiring the candidate to be already eligible;
  Menu admission additionally requires `readiness=eligible`. No resolver
  thresholds, matching rules, or readiness requirements change.

Menu BEFORE INSERT triggers on pages and all children/links call the provider
guard and reject late inserts against a page created in another transaction.
They also check the pinned base's live validity. DB stamps cannot be forged.
Exact existing-aggregate replay is a read-only return and needs no new admission.
New facts require an eligible current allowed Subject, eligible/current typed
parents, live readiness features, and this version's exact current resolved
Source Record/event mapping. Zero events, unresolved, needs-review, stale event,
provisional, retired, and incorrectly labeled eligible Subjects all fail.

Identity's guard checks pending unapplied lineage inputs in its expanded
Subject set, including a surviving merge input. It does not trust currentness
until a pending change has applied. A pending change with no input membership
cannot yet invalidate a named Subject; once membership is inserted, further
Menu inserts fail. A malformed incomplete change still fails Identity's own
commit checks. Test normal deferred application and forced application.

**Admission and deferred integrity are different.** All live eligibility,
resolution, base validity, and pending-lineage checks happen at each insertion.
Deferred Menu checks verify immutable support, version/event correspondence,
graph closure, contexts, base parent mapping, and revision shape only. They
must not re-evaluate live readiness/current mapping at commit. A complete Menu
aggregate admitted before an ordered retirement/remap remains history even
when that Identity change occurs later in the same transaction. Subsequent
Menu inserts fail; an incomplete aggregate then cannot commit. Changing the
scope first blocks all new acceptance. Cross-transaction races serialize or
abort and retry the whole transaction; no partial aggregate is accepted.

Closure is not retirement: historical observations can be admitted to an
otherwise eligible closed Establishment. Identity supplies its operating
interval/state for current selection; do not bake today's operating state into
immutable Menu integrity or promise historical operating-state reconstruction.

## 4. Stream lifecycle, replay, and base validity

| Operation | Required predecessor and result |
|---|---|
| `initial` | No stream predecessor; `stream_revision=1`, `interpretation_revision=1`, published. Only one initial page per stream. |
| `observation` | Published head, a previously unused Bronze version in this stream with strictly later `observed_at`; published full snapshot, interpretation revision 1. Same amount still appends. |
| `correction` | Published head; explicit successor with a complete corrected snapshot, published. Same version increments its interpretation revision; a different supported version is allowed for a deliberate correction, including an older observation. |
| `withdrawal` | Published head; withdrawn tombstone with direct page Evidence and no base, nodes, applicability, or prices. It blocks the whole stream, not just the predecessor. |
| `restoration` | Withdrawn head; explicit published successor with a complete newly supported aggregate. Ordinary observation/correction cannot bypass a tombstone. |

For every operation, interpretation revision is 1 for a version's first use in
that stream, otherwise its previous maximum plus one under the provider's
Source Record lock. Stream revision always increments the committed head by
one. Keys exclude Subject, so a remap cannot restart either counter or fork
history. Each successor has a strictly later DB-stamped `accepted_at` than its
predecessor (clock timestamp with a minimum one-microsecond increment). Neither
acceptance time nor surrogate IDs break business ranking ties. A Source Record
lock plus initial/revision/predecessor uniqueness serializes competing writers;
no unlocked `MAX + 1`. Only one page per stream per transaction; the predecessor
must be committed, not another uncommitted page in the same aggregate.

After an explicit Identity remap a correction can scope the successor to the
new eligible Subject and new resolution event, using the same supported Bronze
version if justified. It does not rewrite the old scope or copy prices to split
outputs. A remap alone creates no Menu page. Later remapping back does not make
an old event current: reacceptance requires an explicit successor. Exact replay
compares the complete canonical payload, membership, base/predecessor references,
revision, and sorted Evidence sets; a different Subject/event under an existing
key is a conflict. Same key/different amount, confidence, or Evidence also fails.
Exact replay returns existing IDs with zero inserts, even after retirement.

A pin is usable only if its Organization page was published and committed,
belongs to the Establishment's operator, and its original scope/event mapping
remains current and eligible for a current interpretation. It need not be the
stream head: ordinary successors leave pins intact, including new explicitly
chosen pins to superseded pages. A withdrawal later in that stream invalidates
**all earlier pins** for current use. Restoration makes its new page pinnable;
it does not silently revive pre-withdrawal pins. Local rebasing is an explicit
new local snapshot. At admission, these conditions are checked for every new
page/member; at selection they are read again for current use. Deferred checks
only enforce the immutable relationship.

If a base becomes invalid, inherited facts, mapped replacements/suppressions,
and prices depending on those correspondences cannot form a current resolved
graph. Return an unresolved-base condition and only independent, directly
supported local additions with complete independent parent paths. An orphaned
local price is retained in history but not attached by name to a new base.
No fallback to another Organization version or a sibling location is permitted.

## 5. Money, applicability, and correspondence

Money uses exact integer minor units and currency FK, initially USD with
exponent 2. Currency regex `^[A-Z]{3}$`, exponent `0..4`, and catalog FK enforce
shape/support. Section/item/variant `price_kind=absolute` amounts are nonnegative;
modifier `price_kind=delta` may be negative or zero. `price_state` is priced,
unknown, or unavailable; amount exists exactly when priced. No float, conversion,
section-plus-item summation, or guessed variant upcharge. A variant's absolute
price replaces its item's price for that variant. Individual required modifiers
are supported; choice groups, bundles, tax/service-fee interpretation are deferred.

Declared applicability is direct factual support: channel `unspecified`,
`dine_in`, or `takeaway`; optional exact service-period label; half-open UTC
`[valid_from, valid_to)`. NULL bounds are unbounded; explicit infinity, empty
service labels, nonfinite times, and empty/reversed windows are rejected.
Unique canonical declared tuples use NULL-safe equality (e.g. a PostgreSQL 16
`NULLS NOT DISTINCT` unique constraint). An absent graph applicability means
no added restriction. It differs from an explicit `channel=unspecified`, which
is a separate exact context and cannot establish dine-in/takeaway applicability.

Compute **effective** context before matching or ranking: intersect all present
ancestor restrictions, target restriction, and the price's required context.
For mapped nodes also retain the restrictions along the pinned base path;
replacement cannot widen them. Non-null service labels must agree (NULL adds
no restriction); all present channels must agree (unspecified is not a wildcard).
Window intersection uses greatest lower bound and least upper bound. Empty or
incompatible intersections reject the aggregate. The canonical effective tuple
is `(channel, service_period-or-empty, from-or-minus-infinity, to-or-plus-infinity)`.
Rank only exactly equal effective tuples and currency. Two different declared
windows can intersect to the same effective context and then compete; unequal
effective tuples remain separate even if both contain the requested instant.
The effective instant filters window membership; it is not a specificity rule.

For example a section restricted to dine-in/lunch `[11:00Z,14:00Z)` makes an
item price declared `[10:00Z,15:00Z)` compete with a price declared
`[11:00Z,14:00Z)`, with the same labels. A takeaway price under that section
fails integrity. Identity's operating interval is a separate current-availability
filter at the requested instant; mutable operating edits do not change the
canonical Menu context or retroactively invalidate accepted claims.

Keys use versioned canonical structured tuples, never ambiguous concatenation.
Node keys identify rows in one snapshot. `source_native_key`, when supplied,
is a supported stable native ID within `(record, root, node type, parent native
path)`; partial unique indexes enforce one per page in that namespace. Source
kind is excluded from this correspondence namespace so JSON-LD/DOM claims can
compete when they carry the same genuine native IDs. All parents in that path
must have stable correspondence. A positional/document fallback locator includes
the immutable Bronze version and is **version-local**; equal names or positions
across versions do not prove continuity. Same-version corrections can reuse
that locator. Explicit typed links to the same pinned base establish shared
correspondence across sources/versions. Different pinned bases remain separate
unless a future approved mapping explicitly relates them; Step 5 adds none.
No free-form matching hints, fuzzy IDs, or cross-source name deduplication.

Observation keys contain typed target key, declared context, currency, and
source claim locator; amount/confidence are payload, not key material.
Canonical business tie keys use source namespace/external key, observed time,
content hash, immutable capture keys, node/claim locators, revision and Evidence
locators/hashes, excluding acceptance time and surrogate IDs. Exact business
key/payload duplicates are equivalent even if historical raw SQL created duplicate
Bronze versions; conflicting payload under an identical canonical key is an
explicit conflict, not a row-ID tie break. Normal replay reuses Bronze's version.

## 6. Time and deterministic selection

Two modes are explicit: **current interpretation** and **accepted-claim history**.
Inputs name the Subject, source-local family `(Source Record, root_key)` across
interpretation kinds or explicit pinned correspondence, exact effective context,
currency, and effective instant `E`. History additionally supplies acceptance
cutoff `K` and optional observation cutoff `O`. All timestamps use UTC.

| Time | Meaning and boundary |
|---|---|
| `observed_at` / `O` | Bronze observation time; factual page must have `observed_at <= O` if supplied. Inherited facts keep their base's own observation time and must also pass O. Never substitute acceptance time. |
| `accepted_at` / `K` | Server admission timestamp; only committed rows with `accepted_at <= K` are visible to history. Current reads use all committed rows in a consistent transaction snapshot. This is accepted-claim time, not a reconstructed commit log: a transaction committed later may become visible with an earlier admission timestamp. |
| Effective instant `E` | Must lie in the canonical effective window; half-open end excluded. Current availability also requires live operating eligibility from Identity. Observation/acceptance timestamps do not imply a service window. |

1. At `K`, find the greatest visible stream revision **before** factual filters.
   A tombstone blocks every older page; published head is the only ordinary
   candidate from that stream. Apply observation/context/Identity filters after
   lifecycle selection; a filtered head never reveals a predecessor. Lifecycle
   controls visible by K apply even if their observed time exceeds O. Increasing
   O cannot undo a withdrawal. Inspection of any stored page remains possible,
   labeled historical/superseded/withdrawn as appropriate.
2. Current mode requires live eligible scopes, original event mappings, no
   pending lineage, and operating availability at E. History preserves the
   originally accepted Subject/event, ignores today's eligibility/mapping and
   operating edits, and does not claim historical Identity-state reconstruction.
   Corrections visible only after K cannot erase an earlier accepted answer.
3. Rank published content candidates in the identified family by source kind
   `jsonld > dom > pdf > llm`, later observation, higher page confidence, then
   ascending canonical business key. No unrelated family/name equivalence.
4. For a local base pin, inspect that exact page separately from stream-head
   selection. Ordinary supersession does not exclude it. Apply the pin validity
   rules of Section 4; history evaluates withdrawals only up to K and does not
   consult today's Identity. Base acceptance/observation must pass K/O too.
   Overlay inherit, full replacements, suppressions, and independent additions.
5. Collect local price contenders from published stream heads in the same
   family whose native correspondence or exact base links relate them to the
   selected content. Suppressed targets have none. Compute each contender's
   effective context using its own full path and require equality with the
   selected target's requested context. Never borrow an ancestor restriction
   from a competing page to make a mismatched price fit. Rank within the local
   scope by kind, observation, price confidence, canonical key. Retain all
   contenders and flag contradictions; deterministic ranking is not proof of truth.
6. Return the local value (including explicit unknown/unavailable) with its
   Establishment, observed time and Evidence. If absent, return derived unknown
   with no local observation/Evidence. Organization prices may be shown separately
   as Organization claims, with their own contexts, times and Evidence. They
   never compete for or populate the local value; sibling prices are excluded.

A supported local DOM price therefore wins as the local value even with shared
JSON-LD content. Content selection never relabels shared factual scope as local.
This is a pure contract/fixture specification, not a Gold projection or API.

## 7. Locks, indexes, and transaction boundaries

Identity owns dependency expansion and stable **batch** lock ordering: maintenance
lock, full sorted union of Subjects/currentness/typed readiness inputs, then
sorted Source Records (including records needed to protect readiness proofs)
using `FOR NO KEY UPDATE` (compatible with Bronze FK key-share locks), followed
by revalidation under lock. Menu passes all local/base
scope requests at once and takes its stream/predecessor locks only afterward.
If dependency discovery changes under lock, fail and retry; do not append a
lower-order lock or call single-subject guards in an arbitrary loop. Raw-SQL
triggers use this same provider entrypoint. Arbitrarily composed multi-aggregate
raw SQL can still deadlock; rollback/retry preserves integrity, and bounded
concurrency tests must prove no stale acceptance or partial commit.

Step 4's writer can hold a Source Record before resolving Subjects. Step 5
therefore consumes **already committed Bronze and resolution input**. Mixed
Bronze-persist/resolve/Menu orchestration is unsupported until a provider-owned
preflight and dedicated race tests exist. Do not advertise it based on ADR-0004's
general ability to share transactions. Menu itself adds no broker/lock framework.

Index every FK not already covered by a leading PK/unique index: page version,
event, subject/root/observed time, base page; section parents, item sections,
variant items, modifier parents, applicability, typed base links; each price's
target/applicability/currency; Evidence ID and link targets. Stream revision and
version revision uniqueness support head/replay lookup; predecessor uniqueness
supports successor lookup; include stream/operation lookup for tombstones. Add
four typed native-key indexes, four base-target uniqueness indexes and seven
Evidence-link uniqueness indexes. Canonical NULL-safe contexts are unique per
page. Do not add duplicate indexes or an unconsumed projection.

## 8. Implementation sequence after design review

1. Close the outstanding CI PostGIS validation before implementation acceptance:
   strict full suite, migration round trip, and no metadata drift on the actual
   CI image. Native PostgreSQL results do not establish image acceptance.
2. Prepare the narrow provider prerequisite: published immutable Bronze lookup
   contracts and Identity batch guard/shared policy, plus a forward revision
   after `91f4c2a7d6e8` installing provider-owned functions. No history rewrite,
   matching-policy change, new provider table, or upward dependency. Prove
   promotion/admission policy parity and pending-lineage/locking behavior.
3. After that review, prepare one Menu revision creating its schema and nine
   tables, all constraints, functions, admission/immutability/deferred triggers,
   and USD seed atomically. Register models solely through the registry and
   schema owner map. Commands/contracts consume provider DTOs, never provider ORM.
4. Prepare pure selection, replay, and focused tests from Section 9. Include
   upgrade/downgrade SQL for owner review. Execute only on disposable test data
   within separately authorized implementation work. Commands never commit.
5. Downgrade removes Menu triggers/links/prices, modifiers/variants/items/sections,
   applicability, self/base references, pages, currency and owned functions/schema
   in dependency order without CASCADE. Provider prerequisite downgrade removes
   only its additions. Existing provider data and object signatures must remain
   unchanged. Re-upgrade recreates empty Menu plus USD; it cannot restore deleted
   Menu history. Review generated SQL separately from this design.

## 9. Enforcement and focused acceptance tests

These are **proposed** constraints/trigger names and tests, not verified Menu
behavior. Every deferred test forces `SET CONSTRAINTS ALL IMMEDIATE` in the
outer transaction and includes a real-commit case; savepoint `session.commit()`
alone is insufficient. BEFORE-trigger cases use raw SQL as well as commands.

| ID / invariant | Enforcement and phase | Focused proof after implementation |
|---|---|---|
| M01 scope, readiness, exact mapping, pending lineage | `trg_menu_admit` BEFORE every aggregate insert calls Identity batch SQL guard; kind CHECK/composite FK | `test_menu_schema`: Place/null/forged kind, provisional/feature-poor/self or parent retired, zero-event/unresolved/stale mapping fail. Provider tests: promotion succeeds from provisional with sufficient features; Python/SQL parity. |
| M02 admission order versus history | Same BEFORE guard; `ct_menu_integrity` must not repeat live checks | `test_menu_concurrency`: scope change then insert fails; complete insert then remap/retire in same transaction commits history; additional child fails; pending lineage input (including survivor/parent) rejects before deferred apply and after forced apply as appropriate. |
| M03 complete immutable aggregate | `trg_menu_stamp`, `trg_menu_member_transaction`, `trg_menu_immutable` on all nine tables; deferred support closure | `test_menu_schema`: forged stamp, late child/link, no-op UPDATE, DELETE, TRUNCATE fail; missing support fails at forced boundary/commit; rollback leaves no partial aggregate. |
| M04 direct, inherited, structural support | shape CHECKs and `ct_menu_support`; Bronze immutable lookup for each link and version/event chain | `test_menu_schema`: unsupported direct page/node/context/price, wrong version/capture/same URL fail; inherit with copied facts fails; price-only inherit and structural grouping through supported items pass. No inherited Evidence presented as local. |
| M05 same-page graph, cycles, base parents | composite restrictive FKs, base-target partial uniques, `ct_menu_graph` recursive cycle/type/base/parent check | `test_menu_schema`: cross-page parents/targets, section cycle, duplicate base link, wrong Organization, wrong parent/type fail. Deep section, variant, both modifier parent forms, full replacement/NULL clearing, suppression descendants and additions pass. |
| M06 pin validity separate from head | `trg_menu_admit` locks/checks base stream live; `ct_menu_graph` checks immutable base ownership only; pure selector reads lifecycle | `test_menu_precedence` and concurrency: ordinary observation/correction keeps pin; withdrawal invalidates old pins; restoration needs new pin; remap/retirement invalidates current inheritance while historical query retains it. Base change after complete acceptance does not abort history. |
| M07 one stream across remaps, revisions | `uq_menu_stream_revision`, `uq_menu_version_revision`, `uq_menu_successor`; `trg_menu_stream_admit` checks committed head under Source Record lock; `ct_menu_lifecycle` immutable operation/revision shape | `test_menu_replay`/concurrency: duplicate initial, fork, skipped revision, wrong stream, uncommitted predecessor fail; same-version correction/remap cannot reuse revision 1; concurrent successors produce one winner and explicit conflict/retry, no automatic intent rewrite. |
| M08 tombstone/restoration | state/operation CHECK plus `ct_menu_lifecycle`, no children/base for withdrawn page | `test_menu_precedence`/replay: withdrawal hides every predecessor; observation cannot bypass it; explicit restoration creates new supported graph; K before/after tombstone and O older than tombstone cannot resurrect content. |
| M09 exact money and row shape | `ck_menu_price_shape`, target XOR, currency FK/CHECK, finite confidence/time CHECKs | `test_menu_schema`: zero absolute, negative modifier delta pass; negative item, missing currency, unsupported code, overflow/fractional input, NaN, amount on unknown/unavailable fail; exact round trips. Strict DTO integer validation rejects coercion; SQL stores BIGINT only. |
| M10 applicability after intersection | NULL-safe unique declared context, interval/enumeration CHECKs, `ct_menu_context` on complete target/ancestor/base paths | `test_menu_schema`/precedence: duplicate NULL contexts, conflicting channels/periods and empty intersections fail; unequal declared but equal effective windows compete; unequal effective windows do not; unspecified never proves dine-in; E at end excluded. |
| M11 stable correspondence and replay | native-key partial uniques, `ct_menu_graph`; command canonical aggregate/Evidence comparison; selector typed correspondence | `test_menu_replay`/precedence: reordered duplicate positional nodes cannot reuse continuity across versions; stable native paths and same pinned targets can; matching names/different bases cannot. Exact/concurrent replay adds zero/one aggregate; changed payload/support conflicts. |
| M12 time, ranking, no price leakage | immutable observed-time provider check, DB admission stamp; pure selector contract (no SQL truth heuristic) | `test_menu_precedence`: all Section 10 examples; kinds/recency/confidence/tie; reversed ingestion order same business answer; correction changes only later K; current remap vs accepted history; local unknown and absent local both avoid shared/sibling fallback. |
| M13 race serialization and ownership | Identity maintenance/batch locks and Menu stream lock sequence; transaction retry | `test_menu_concurrency`: separate connections/barriers, both orderings for replay/correction, unassign/remap, merge/split/retire, feature/parent edits, base withdrawal, projection rebuild, Bronze FK inserts; bounded timeout; full rollback on serialization/deadlock. Mixed ingestion remains deferred. |
| M14 migrations and boundaries | restrictive FKs, registry/owner metadata and AST checks; two forward revisions | `test_menu_migration`/`test_schema_layout`: seeded provider preservation across both boundaries, Menu downgrade/re-upgrade inventory/function/index/trigger/seed equality, offline SQL review, no drift; forbidden ordinary/relative/private ORM imports, exact registry exception, parser isolation and no upward references. |

Use existing pytest/SQLAlchemy/stdlib only. All destructive/concurrency tests
require disposable `*_test` PostgreSQL, strict mode, and no non-test override.
Skipped tests never establish acceptance. Update migration tests' head inventory
without weakening provider preservation. Human review checks semantic Evidence
support; constraints guarantee provenance links and shape, not source truth.

## 10. Review examples and completion gate

The [concrete example matrix](../reviews/0002-step-5-menu-design-reconciliation.md#input-and-selection-examples)
is part of this specification: value, scope, observation time, Evidence, temporal
cutoffs, pin state and expected selected result are all explicit. Convert these
examples to focused tests only in authorized implementation work.

Design reconciliation ends with this proposal and proposed ADR, documented checks
and handoff. It does not grant model/migration implementation approval. The next
unit is the provider prerequisite review preparation described in the handoff,
after owner acceptance of ADR-0005. That acceptance is now recorded in the ADR;
PostGIS validation remains outstanding. The earlier reconciliation and planning
records below retain their historical verification and approval boundaries.

## 11. Historical planning record (not the current specification)

This table preserves the original recommendations. The accepted review
defaults in the linked reassessment take precedence; approval of those
defaults does not approve contradictory details in this unrevised document.

| Decision | Recommendation and consequence |
|---|---|
| Snapshot granularity | Immutable whole-page aggregates with Evidence per typed row. More storage and explicit rebasing, but no mutable content/history ambiguity or orphan price attachment. |
| Shared/local behavior | Pinned Organization base, explicit typed correspondence, full-row replacement/suppression, and no Organization-to-location price fallback. Approve before implementing precedence. |
| Provider seam | Approve the narrow public DTO/guard additions and Identity-owned SQL eligibility guard. Existing Python contracts alone cannot enforce the full raw-SQL admission invariant. No Identity table or matching-policy redesign. |
| Initial currency support | Seed USD only; schema supports currencies with other minor units when explicitly added. Confirm any additional required currencies before migration SQL is finalized. |
| Applicability/modifiers | Exact channel/service-period/UTC-window contexts and individual required modifiers. Defer recurring schedules, modifier choice groups, bundles, tax/service-fee interpretation, and currency conversion. Source input requiring unsupported semantics stays Bronze. |
| Corrections | Explicit one-successor supersession, supported withdrawal, and no disappearance-as-unavailability inference. No automatic scope reclassification after a split. |

Planning validation: baseline `make ci` completed successfully (34 tests
passed, 87 database tests skipped); all 25 existing architecture fitness tests
passed. This verifies the checked-out baseline, not the proposed schema.
Database acceptance and the proposed tests remain implementation gates.

Subsequent foundation validation on 2026-09-17 ran against a disposable
PostgreSQL 16 cluster: 121 passed, zero skipped; `alembic check` found no
schema/model drift. This verifies the existing foundation, not Menu, and
does not cover the proposed Menu concurrency cases. See the reassessment
for the separately reproduced database-URL portability defect.
