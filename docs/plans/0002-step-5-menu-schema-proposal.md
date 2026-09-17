# Plan 0002 Step 5: menu schema proposal

**Status:** Proposed; awaiting Fortune's approval. No schema implementation.
**Baseline:** `d1ff54cdae5d6fc59c385c77a4a89a1e91d8fc2f`, Step 4 / PR #15.
**Branch:** `Plan-0002-Step-5`, created from clean, freshly fetched `main`.
**Migration parent:** `91f4c2a7d6e8`, including the typed-grain trigger fix.

Authority: [ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md),
[Plan 0002, Step 5](0002-identity-foundation-before-menu.md#step-5---featdb-add-menu-graph-against-identity-contracts),
and [RFC-0001](../rfc/0001-menu-pricing-first.md), especially D1, D2, and D6.
ADR-0004 supersedes RFC-0001's nullable Venue root and free-text evidence.

This proposes menu persistence, write validation, and a pure precedence
contract. Gold, APIs, extraction, fuzzy matching, generic offerings, and
Step 6 are outside this change. No runtime dependency is needed.

## 1. Recommended shape

Use immutable, source-version-specific menu snapshots. A `menu_page` is an
accepted interpretation, not another fetch record. Its URL, capture, payload
hash, and replay location remain in Bronze. All graph members are inserted
with their page in one transaction and become immutable together. A later
observation or correction appends another snapshot. This intentionally
duplicates changed/confirmed menu structure across observations; it avoids
mutable item attributes and preserves what each source actually supported.

Organization snapshots supply shared content. An Establishment snapshot can
explicitly refine one Organization snapshot belonging to its own operator.
That base is pinned: a later Organization snapshot never silently changes
an already accepted local interpretation. Price history stays append-only,
and Organization prices are never promoted to Establishment prices.

## 2. Tables and keys

All tables below belong to schema `menu`, package
`packages.helios_core.domains.menu`. Except `currency`,
each has a surrogate `BIGINT` PK. Every graph member carries non-null
`page_id` and exposes `UNIQUE(id, page_id)` for same-page composite FKs.
Surrogate IDs are storage references, never semantic tie-breakers.

| Table | Proposed columns and natural uniqueness |
|---|---|
| `currency` | `code VARCHAR(3)` PK, `minor_unit SMALLINT`; immutable supported-currency catalog. Initially `USD, 2`, subject to approval. |
| `menu_page` | `subject_id`, `subject_kind`, `source_record_version_id`, `resolution_event_id`, `root_key`, `source_kind`, `method`, `method_version`, `interpretation_revision`, `observed_at`, `accepted_at`, `confidence`, `state`, nullable `base_organization_page_id`, nullable `supersedes_page_id`, DB-stamped `created_transaction_id`. Unique `(subject_id, source_record_version_id, root_key, source_kind, interpretation_revision)`. |
| `menu_section` | `page_id`, `section_key`, optional `parent_section_id`, `name`, optional `course`, `position`, optional `applicability_id`, optional `base_section_id`, `effect`. Unique `(page_id, section_key)`. |
| `menu_item` | `page_id`, `item_key`, required `section_id`, `name`, optional `description`, optional nonnegative integer `calories`, normalized `dietary_tags TEXT[]`, `position`, optional `applicability_id`, optional `base_item_id`, `effect`. Unique `(page_id, item_key)`. |
| `menu_variant` | `page_id`, `variant_key`, required `item_id`, `label`, `position`, optional `applicability_id`, optional `base_variant_id`, `effect`. Unique `(page_id, item_id, variant_key)`. A variant represents a size/portion; an unqualified item price needs no invented default variant. |
| `menu_modifier` | `page_id`, `modifier_key`, exactly one of `item_id` / `section_id`, `label`, `required BOOLEAN`, `position`, optional `applicability_id`, optional `base_modifier_id`, `effect`. Unique `(page_id, modifier_key)`. No mutable price column. Required means this individual modifier is required; choice groups are not implied. |
| `menu_applicability` | `page_id`, `applicability_key`, `channel`, optional `service_period`, optional `valid_from` / `valid_to` (`TIMESTAMPTZ`). Unique `(page_id, applicability_key)` and unique canonical context within a page. Reusable typed applicability, not arbitrary JSON. |
| `price_observation` | `page_id`, `observation_key`, exactly one of `section_id` / `item_id` / `variant_id` / `modifier_id`, required `applicability_id`, `price_kind`, `price_state`, nullable `amount_minor BIGINT`, required `currency_code`, `confidence`. Unique `(page_id, observation_key)`. Time and method come from the immutable page. |
| `evidence_link` | `page_id`, `evidence_id`, `page_target BOOLEAN`, nullable `section_id`, `item_id`, `variant_id`, `modifier_id`, `applicability_id`, `price_observation_id`. Exactly one target: `page_target::int + num_nonnulls(the six typed IDs) = 1`. Seven partial unique indexes prevent duplicate `(target, evidence_id)` links, including `(page_id, evidence_id)` for a page target. |

`evidence_link` uses seven enumerated, real FK targets. It is a menu-only
association, with no generic `entity_type/entity_id`, EAV, or shared fact
store. Every accepted page, section, item, variant, modifier, applicability,
and price must have **at least one** link. Evidence can support several rows;
it must actually support each accepted claim. This includes an unavailable
item, an unknown price, and a correction. An Identity adjudication alone
does not substitute for Bronze Evidence on a menu observation.

### FK directions and graph integrity

- Page `(subject_id, subject_kind)` references existing
  `identity.subject(id, kind)`; `CHECK subject_kind IN
  ('organization', 'establishment')`. Neither NULL scope nor Place is legal.
- Page references `bronze.source_record_version(id)` and the immutable
  `identity.resolution_event(id)` that justified acceptance. It does not FK
  to the rebuildable current-resolution projection. A deferred validator
  proves that the event is an assign/remap of this version's Source Record
  to this Subject, and is the current event when accepted.
- Every child references its page. Section parents, item sections, variant
  items, modifier parents, applicability references, price targets, and
  Evidence-link targets use `(id, page_id)` composite FKs. Accidental joins
  across snapshots must fail in SQL.
- Section parents form an acyclic same-page tree. Reject self-parenting and
  longer cycles using a deferred recursive check. Root sections have NULL
  parent; every item belongs to a real section. A supported synthetic
  "Unsectioned" section is allowed, with deterministic key and Evidence.
- A local page's base must be an Organization page for the Establishment's
  immutable `organization_subject_id`. Organization pages cannot have bases;
  one level of refinement is sufficient. No sibling/cross-Organization base.
- Typed `base_*_id` FKs must target the corresponding table in precisely
  that base page. A deferred validator checks the base page and parent
  correspondence. An override preserves its parent's correspondence;
  moving an inherited node is a suppression plus a new local node.
  Partial `UNIQUE(page_id, base_*_id)` permits at most one local override per
  shared node. These are explicit source-supported links, never name matches.
- Price currency references `menu.currency(code)`. Evidence IDs reference
  `bronze.evidence(id)`. No FK points from Identity/Bronze into Menu, or from
  Menu into Gold or a different vertical.
- Every FK explicitly uses `ON DELETE RESTRICT`, `ON UPDATE NO ACTION`.
  No cascade or `SET NULL` erases history. ORM relationships have no delete
  cascade. Retirement, split, and remap leave old snapshots untouched.

## 3. Acceptance and provenance

The current contracts are useful but incomplete for this schema:

- `identity.contracts.require_eligible_subject(..., allowed_kinds=...)`
  locks Subjects, their currentness, and typed features. Organization
  readiness requires name/fingerprint plus a current resolved source key;
  Establishment readiness recursively requires eligible, current parents.
  A bare `readiness='eligible'` check is insufficient.
- That function does not prove that this page's particular Source Record
  resolves to that Subject. An eligible Organization can coexist with an
  unresolved menu Source Record. Both checks are required.
- Bronze contracts persist observations and lock Source Records, but do not
  yet publish immutable version/Evidence lookup DTOs. Bronze versions are
  not SQL-unique by content hash. Menu must not invent that guarantee.

Propose small, provider-owned contract additions, explicitly subject to
approval:

1. Provenance publishes frozen version/Evidence references containing the
   IDs, Source Record, capture, observed time, and deterministic source keys
   needed for validation. Consumers never import its ORM or private helpers.
2. Identity publishes a resolved-scope guard returning `EligibleSubject`,
   the accepted resolution event, and Establishment parent IDs as needed.
   It composes eligibility with the version's exact Source Record mapping.
3. Identity owns a SQL eligibility/resolution guard usable by Menu's
   acceptance trigger. The existing Python eligibility entrypoint delegates
   to the same policy where practical; policy must not drift into Menu SQL.
   The helper has only Subject/Source Record arguments, no menu concepts or
   upward imports. Existing eligibility behavior remains the reference.

Reject a missing Subject, wrong kind, provisional readiness, absent/noncurrent
currentness, failed live typed-feature policy, ineligible/retired parents,
absent resolution, `unresolved`, `needs_review`, mismatched Subject, or stale
resolution event. A closed Establishment is not inherently a retired Subject:
historical acceptance can succeed if identity remains eligible. Applicability
must intersect its effective operating interval; never advertise historical
facts as current operating availability.

Each Evidence link must target either the page's exact Record Version or
that version's non-null Capture. Same source or same URL alone is not enough.
This preserves both legal Bronze Evidence forms, while preventing unrelated
evidence laundering. Supplemental Evidence outside that chain is deferred;
separate source claims receive separate accepted snapshots. A base row retains
its own Evidence; a local override needs its own page's supporting Evidence.

Database BEFORE triggers stamp transaction IDs, validate live eligibility and
exact resolution for every new page/member/link, and reject late member/link
inserts after the page transaction. Deferred constraint triggers check support
counts, graph closure, and Evidence ownership at the transaction boundary.
Eligibility is an admission invariant, not a permanent invariant on historical
rows: an ordered retirement/remap after acceptance, including later in the same
transaction, preserves accepted history but disqualifies it from current
selection. No further members may be accepted against an invalidated scope.
Identity's deferred lineage application must be accounted for: the provider
guard rejects a Subject/dependency with a pending unapplied change in which it
is an input, rather than reading an obsolete currentness projection. Test both
normal deferred execution and explicitly forced constraint execution.
Commit an entire page aggregate or none of it. Missing or rejected menu input
stays in Bronze; there is no draft/nullable menu placeholder.

All menu tables reject UPDATE, DELETE, and TRUNCATE in database triggers,
including no-op updates, link changes, and currency-unit changes. There is no
application-settable bypass. A frozen page cannot acquire prices or children
later; new acceptance means a new snapshot.

## 4. Money, applicability, and corrections

- Store exact integer **minor units**, not float money and not universally
  named "cents". Currency defines the exponent. `code` checks `^[A-Z]{3}$`;
  `minor_unit` checks `0..4`. The FK rejects unsupported codes, so a regex
  alone does not pretend to validate currency identity. No FX conversion or
  cross-currency ranking. Missing currency prevents accepting a numeric price.
- `price_kind IN ('absolute', 'delta')`. Section/item/variant prices must be
  absolute and nonnegative. Modifier prices must be deltas and may be negative
  or zero. Never automatically add a section price to an item price. A variant
  price replaces the item price for that variant; no guessed upcharge semantics.
- `price_state IN ('priced', 'unknown', 'unavailable')`; amount is non-null
  exactly for `priced`. Unknown/market price is not zero. An explicit local
  unknown/unavailable observation blocks a shared-price fallback.
- `source_kind IN ('jsonld', 'dom', 'pdf', 'llm')` describes interpretation,
  not Bronze Source kind. This stores the RFC vocabulary but authorizes no
  LLM/extraction work. Method/version are nonblank; confidence is finite exact
  `NUMERIC(5,4)` in `[0,1]`. Price confidence is per claim; page confidence
  describes content interpretation. Observation time must equal Bronze's time;
  acceptance time is server-stamped and not a replay key or precedence input.
- Applicability channels are `unspecified`, `dine_in`, and `takeaway`.
  Unspecified does not prove either specific channel. Optional service-period
  labels are trimmed, bounded source labels, not machine-inferred hours.
  Explicit validity windows are half-open `[valid_from, valid_to)`; if both
  bounds exist, end must exceed start. NULL bounds are unbounded within the
  stated context. No recurring hours, timezone inference, or overnight parser
  is introduced. Graph restrictions intersect along the ancestor path; an
  incompatible or empty intersection is rejected.
- Define the canonical context tuple as `(channel, service_period-or-empty,
  valid_from-or-minus-infinity, valid_to-or-plus-infinity)`. An expression
  unique index uses that tuple, with literal infinities/empty service labels
  forbidden as input. This prevents NULL uniqueness holes. Matching/ranking
  compares exact contexts; overlapping but unequal contexts remain separate
  claims. No unapproved "more specific" heuristic selects among them.
- Graph `effect IN ('replace', 'suppress')`. Suppression requires an explicit
  base target. Replace uses the full typed content row: a NULL description
  clears that description, not "inherit". Children without explicit overrides
  retain base content. Suppressed ancestors hide their descendants.
- Page `state IN ('published', 'withdrawn')`. A withdrawal has Evidence and
  supersedes an earlier page; it has no content/price children. Corrections
  and withdrawals use `supersedes_page_id`, with a partial unique index on
  non-null predecessors to reject competing successors. The predecessor must
  already be committed and share source Record, root key, and source kind.
  Same-version corrections increment interpretation revision by one; a changed
  scope is allowed only after explicit Identity remap and fresh validation.
  New-version observations start at revision 1 and may explicitly supersede
  an older version; arrival order alone does not imply correction.
- A superseded snapshot remains queryable but is not a current candidate.
  Omission from an ordinary later snapshot is not proof of unavailability;
  use explicit supported suppression/withdrawal. No automatic split fan-out,
  merge rewrite, or correction of previous prices.

## 5. Deterministic precedence contract

This is a pure selection specification and test fixture, not a Gold view or
API. Input is an Establishment, an explicit menu family/base correspondence,
an exact applicability context, currency, and as-of time. Unrelated root
families are separate menus; the caller cannot equate names across sources.

1. Validate current Identity eligibility and mapping before considering a
   snapshot for a current interpretation. Exclude superseded/withdrawn pages,
   stale assignments, retired/ambiguous predecessors, and nonmatching time or
   channel contexts. A closed Establishment or one outside its effective
   operating interval cannot assert current availability. Historical queries
   retain the original scope and event. As-of history evaluates only snapshots
   and supersessions visible by the requested observation/knowledge cutoff;
   a later correction must not erase an earlier historical answer.
2. Within an explicitly identified source-local root family, select an
   accepted snapshot using RFC-0001 order: source kind `jsonld > dom > pdf >
   llm`, then later Bronze `observed_at`, then higher page confidence.
   Break a remaining tie by ascending canonical source/version/root/revision
   key, never by sequence ID or database arrival order. Retain all contenders.
3. A selected local page with a base uses exactly that Organization snapshot.
   Do not silently rebase to a newer Organization snapshot. If the pinned base
   is no longer a current candidate, return the local standalone facts and
   an unresolved shared-base condition; do not reactivate withdrawn content.
   Without a local page, Organization content may be returned as shared
   content, with its Organization scope explicit.
4. Overlay local sections/items/variants/modifiers by explicit `base_*` links.
   Local replacements win for mapped nodes; suppressions hide mapped nodes
   and descendants; unrelated local nodes are additions. Same names alone
   neither override nor deduplicate anything.
5. For each exact target correspondence, applicability context, and currency,
   a local price claim wins over any Organization price claim, regardless of
   source-kind rank. Within that scope, rank price claims by source kind,
   observed time, price confidence, then canonical observation key. Distinct
   contexts/currencies are not collapsed. Equal-ranked contradictions remain
   stored; the final key makes selection repeatable, not more truthful.
   Content selection in step 2 does not discard competing price observations:
   evaluate active snapshots in the same family whose stable source-local
   target keys or explicit base links correspond to the selected content.
   A suppressed target has no eligible prices. Do not mix incompatible pinned
   bases or infer variant/modifier correspondence from a matching item name.
6. If no local price exists, the location price is **unknown**. Shared prices
   may be reported separately as Organization claims. They are not copied,
   multiplied across Establishments, or substituted as in-store location
   prices. A sibling Establishment is never a candidate.

Example: Organization O publishes Burger = USD 900. Establishment A explicitly
links its Burger to O's item and observes USD 1050; B has no local observation.
A's price is USD 1050; B's location price is unknown; O's USD 900 remains a
shared claim. A later supported local `unknown` replaces A's numeric claim
through an explicit superseding snapshot, without falling back to USD 900.

## 6. Natural keys and replay

Use versioned canonical encodings of structured tuples, not concatenated
labels with ambiguous separators. Keys are bounded, nonblank, trimmed text;
canonical serialization and normalization are frozen in `menu.contracts`.

- Root identity uses source namespace + external record key + source-local
  root key. Snapshot identity additionally uses the immutable Bronze version,
  Subject, source kind, and explicit interpretation revision from the table.
- Prefer stable source-native node IDs. Otherwise use a reproducible locator
  under the captured document, including section path and duplicate occurrence
  ordinal. Normalized name is a component/display aid, never sole identity.
  Reordering unnamed duplicate nodes can create new identities; that is safer
  than asserting unsupported continuity. Explicit base links establish shared
  correspondence across snapshots/sources.
- Observation keys combine typed target key, canonical applicability tuple,
  currency, and source claim locator. Amount/confidence are compared payload,
  not key material; changing them under the same key is an error. Separate
  contradictory source claims need distinct locators/keys.
- Canonical business tie keys use Bronze namespace/external key, UTC observed
  time, content hash, immutable capture provenance, normalized keys, revision,
  and Evidence locators/hashes. They exclude acceptance time and surrogate IDs.
  Identical business keys/payloads are equivalent even if a historical raw SQL
  Bronze insert created duplicate versions; normal replay must reuse the
  Bronze version supplied by its published persistence contract.
- A writer looks up the complete root natural key before creating children.
  Exact aggregate and sorted Evidence-set equality returns existing IDs and
  performs zero inserts. Same key with different payload/membership/Evidence
  raises an idempotency conflict; no `ON CONFLICT DO UPDATE` and no late links.
  Exact retry of historical data can return its existing immutable result
  after retirement/remap, but cannot accept any new row or mark it current.
- A corrected interpretation requires an explicit higher revision and
  predecessor; never allocate revisions via unlocked `MAX + 1`. A later Bronze
  observation appends even if its amount is unchanged. First/last seen are
  derivable MIN/MAX of observation history; no freshness UPDATE is needed.

## 7. Locks, checks, and indexes

Acceptance uses the Identity maintenance lock and its established stable
Subject-before-Source-Record ordering. Lock the union of local/base Subjects
and Establishment dependencies in sorted order before calling guards for
individual Subjects. Lock the required Bronze Source Records in sorted order,
then re-read resolution and typed readiness inputs under their protection.
Use Source Record `FOR NO KEY UPDATE`, compatible with Bronze FK key-share
locks. Root/child insertion and deferred validation run under these locks.
Concurrent correction also locks its predecessor; a unique predecessor key
is the final defense against branching.

The approved Step 4 persistence command can already hold a Source Record lock
before its resolver acquires Subjects. Do not claim arbitrary cross-module
composition is deadlock-free. Step 5's first writer consumes already persisted,
resolved Bronze; same-transaction composition needs a provider-owned lock-set
preflight and the mixed-workflow tests below. On serialization failure or
deadlock, roll back and retry the whole transaction; never swallow it and
commit a partial aggregate. No new broker or coordination service.

Named database checks cover all enums, nonblank bounded keys/labels, kind/FK
agreement, XOR targets, amount/state/kind consistency, currency units, finite
confidence/time values, interval order, nonnegative positions/calories, and
normalized non-null/nonblank unique dietary tags. Deferred validators cover
cross-row support, same-version Evidence, base ownership/parent correspondence,
section cycles, correction shape, and eligibility. Every trigger has a focused
failing test using raw SQL and an actual deferred-constraint boundary.

Index inventory (avoid duplicates where a PK/unique index already leads with
the same columns):

- All natural unique keys, seven Evidence-link partial unique keys, four
  base-target partial unique keys, and unique non-null supersession target.
- Page `(subject_id, root_key, observed_at DESC)`, `source_record_version_id`,
  `resolution_event_id`, and `base_organization_page_id`.
- Child FK lookup indexes for section parent, item section, variant item,
  both modifier parents, graph applicability, and each base target.
- Price partial target indexes `(target_id, applicability_id, currency_code)`
  for each of its four target columns; standalone applicability/currency
  indexes where needed for referenced-row checks.
- Evidence-link `evidence_id` plus child-target FK indexes not already
  covered by partial unique indexes. All page membership scans are indexed.

## 8. Migration and package sequence after approval

1. Review the provider contract additions and SQL guard as a narrow prerequisite
   revision after `91f4c2a7d6e8`. Add Identity-owned functions only; no existing
   history rewrite, table replacement, policy relaxation, or menu dependency.
   Prove Python/SQL guard parity before introducing menu writes.
2. A second revision creates `menu` and its first real tables atomically:
   currency, page, applicability, section, item, variant, modifier, prices,
   Evidence links. Add self/base references and all named constraints/indexes
   in dependency order; install every immutability and acceptance trigger in
   the same migration. Seed only approved supported currencies.
3. Add `SCHEMA_MENU`/ownership in `db/base.py`. Register every model solely
   through `db/model_registry.py`; Alembic's existing ownership allowlist then
   includes Menu. Add `domains/menu/{models,contracts,commands}.py` and minimal
   package initializers. Commands flush but never commit; the caller owns the
   transaction. Published DTOs contain IDs/values, not ORM instances.
4. Extend metadata, AST, database, replay, and migration tests. Generate both
   upgrade and downgrade SQL for owner review; run `alembic check` and full
   `make ci` against a disposable Postgres test database. The migration/SQL
   approval remains separate from approval of this proposal.
5. Downgrade removes Menu triggers, then Evidence links/prices, modifiers,
   variants/items/sections, applicability, page, currency, and functions;
   remove self/base FKs first where necessary. Drop schema without CASCADE.
   Downgrading the prerequisite then removes only its added provider functions.
   Bronze/Identity rows and existing functions/triggers must remain intact.
   A downgrade discards Menu history; it is not an operational data restore.
   Re-upgrade restores the same empty Menu structure and currency seed.

Package fitness rules permit Menu to import only Identity/provenance
**contracts** and DB foundation. No root-package ORM re-exports as a loophole.
Lower modules cannot import Menu, another vertical, Gold, or apps. The registry
is the sole exception. Check both `import` and `from ... import`, including
relative imports. SQL guards remain owned by their provider; no Identity SQL
function references Menu. No parser, Gold package, or API scaffolding.

## 9. Required validation

| Area | Concrete acceptance cases |
|---|---|
| Migration | Seed Bronze/Identity at `91f4c2a7d6e8`; upgrade both revisions; compare provider rows and pre-existing object signatures; seed a supported Menu aggregate; downgrade Menu only, then prerequisite; prove foundation data/structure unchanged; re-upgrade and compare constraints, indexes, triggers, functions, catalog seed, and metadata. Exercise each revision boundary and full history from base. |
| Scope/readiness | Accept eligible Organization/Establishment. Reject Place, forged kind, NULL/missing Subject, provisional or manually mislabeled eligible Subject, retired/split predecessor, retired/provisional/feature-poor parents, zero-event/unresolved/needs-review Record, wrong/stale mapping. Closed versus retired behavior is tested separately. |
| Provenance | Reject missing version, unrelated resolution event, zero Evidence on each accepted row type, missing Evidence, wrong version, wrong Capture, and same-URL/wrong-record Evidence. Accept exact-version Evidence and matching-Capture Evidence. Traverse to source URL when an Endpoint exists. |
| Graph | Reject cross-page parents/targets/applicability, section cycles, invalid target counts, sibling/wrong-Organization base, duplicate overrides, wrong typed base and parent mapping. Verify full replacement, explicit NULL clearing, suppression of descendants, local additions, pinned-base behavior, and no name-based matching. |
| Price/applicability | Zero absolute price, negative modifier delta, unsupported/invalid currency, non-integer/overflow boundary inputs, exact money round trips, unknown/unavailable state shapes, confidence boundaries and NaN, duplicate NULL contexts, reversed intervals, incompatible ancestor contexts, channel isolation, and different-currency isolation. |
| Precedence | A/B sibling example; local DOM beats shared JSON-LD for A; Organization amount never becomes B's price; within-scope kind/recency/confidence/tie order; reversed ingestion order produces identical business result; unmatched names and unequal contexts remain distinct; no shared fallback after local unknown. |
| Replay/correction | Exact replay changes no row count or payload; concurrent identical replay returns one aggregate; same key/different value or Evidence set fails; unchanged amount on a later observation appends; correction preserves predecessor; two concurrent corrections cannot fork; remap/split never rewrites or copies old prices. |
| Append-only | Raw SQL UPDATE/DELETE/TRUNCATE on every Menu table, including support links/catalog; late child/Evidence insert after commit; forged transaction stamp; no-op UPDATE; rollback leaves no half-accepted page. |
| Deferred checks | Force `SET CONSTRAINTS ALL IMMEDIATE` inside the outer fixture transaction; test insert ordering and actual commit in isolated connections. Retirement/unassign before acceptance rejects it, including pending deferred lineage; a later ordered change preserves earlier history but blocks subsequent facts and current selection. The existing savepoint fixture's `session.commit()` alone is insufficient. |
| Concurrency | Separate connections/barriers for replay, correction, remap/unassign, retirement/merge/split, readiness-feature edits, parent readiness loss, base/local acceptance, projection rebuild, and Bronze FK inserts. Both race orderings yield valid serialization or a full retry; no stale accepted scope, partial result, or unexplained hang. Include Step 4 persistence-to-menu composition before advertising that workflow as supported. |
| Architecture | Active ownership gains Menu only; exact Menu inventory; complete model registration; allowed FK matrix and restrictive deletion; forbidden-import failures including relative imports; parser isolation; commands never commit; authoritative tables never reference Gold; no JSON domain payload or identity food attributes. |

Focused files: `test_menu_schema.py`, `test_menu_precedence.py`,
`test_menu_replay.py`, `test_menu_concurrency.py`, `test_menu_migration.py`,
plus extensions to provider contract tests and `test_schema_layout.py`.
Use existing pytest/SQLAlchemy/stdlib patterns. Do not add a test framework.
Destructive/concurrency tests require an actual disposable `*_test` database
without `HELIOS_ALLOW_NONTEST_DB`. Skipped database tests do not satisfy the
implementation acceptance gate. Update old migration tests that assume only
Bronze/Identity exist at `head`, without weakening their preservation checks.

## 10. Owner decisions before implementation

These recommendations are proposed, not silently treated as approved:

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

Approval of this document authorizes preparing the model/contract/migration
diff and its tests, not executing a migration on application data. The owner
still reviews the concrete schema diff and generated SQL under Plan 0002's
Step 5 review gate.
