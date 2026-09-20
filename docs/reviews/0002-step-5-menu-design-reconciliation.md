# Step 5 Menu design reconciliation

**Date:** 2026-09-17
**Branch verified:** `Plan-0002-Step-5`
**Outcome:** Documentation reconciled; [ADR-0005](../adr/0005-immutable-menu-snapshots-and-selection.md)
is proposed for owner review. No Menu implementation or new design acceptance
is claimed. [The detailed proposal](../plans/0002-step-5-menu-schema-proposal.md)
is the implementation specification after review.

## Decisions recorded

The accepted defaults from the [readiness reassessment](0002-step-5-readiness-reassessment.md)
are preserved. This unit resolves the remaining technical details:

| Review issue | Concrete resolution | Proposal enforcement IDs |
|---|---|---|
| Admission versus deferred checks | Live guards on every new aggregate insert; immutable integrity only at deferred boundary. Earlier completed acceptance survives a later ordered scope change. | M01–M03 |
| Pending lineage and ownership | Identity checks unapplied input membership across the dependency union, owns batch ordering and eligibility policy; promotion uses the feature predicate without requiring prior eligible status. Bronze owns immutable provenance lookups. | M01–M02, M13 |
| Inherited node and parent shape | Inherit carries base and mapped parent references, no copied facts; direct local price has its own Evidence. Synthetic Unsectioned support traverses direct items. | M04–M05 |
| Base validity | Ordinary successors keep pins; withdrawal, stale mapping or retired scope blocks current dependencies. Restoration requires an explicit new pin to restored content. | M06, M08 |
| Stream/revision identity | Record/root/interpretation-kind stream; one predecessor chain and global stream revision, plus version revision uniqueness excluding Subject. Remap never restarts either counter. | M07 |
| Temporal meaning | Head at acceptance cutoff K first; observation cutoff O and effective instant E filter facts afterward without resurrection. History preserves accepted scope/event, not historical mutable Identity state. | M08, M12 |
| Correspondence | Genuine source-native IDs with stable typed parent paths, or explicit same-base links. Positional locators are version-local. | M11 |
| Applicability | Intersect local/base ancestor and target restrictions before exact context comparison. Unspecified is a distinct channel; operating state is a separate live availability filter. | M10 |

Routine choices made concrete include the single explicit stream chain, two
revision counters, no implicit revival of pre-withdrawal pins, an intentionally
narrow structural grouping shape, and no commit-time audit-log promise for K.
These choices implement the accepted semantics; their costs and alternatives
are recorded in ADR-0005. No source policy or matching policy is changed.

## Input and selection examples

These are illustrative fixtures, not claims about real restaurants or executed
Menu tests. Every money value is USD minor units. O is an Organization; A and B
are eligible sibling Establishments with the same operator and different Places.
All input versions/Evidence are already committed Bronze; each record is resolved
to the named Subject with an immutable event. `main` is the root. Context C is
`(dine_in, lunch, unbounded, unbounded)`, E is `2026-09-17T12:00:00Z`.

Evidence notation is a full path abbreviation: `eX(locator)` means
`selected fact -> menu.evidence_link -> bronze.evidence eX -> exact version vX
-> capture cX -> endpoint https://example.test/{O|A|B}/menu`.
An Evidence row targeting `cX` directly is equally legal when it is exactly vX's
Capture. Each eX includes its immutable excerpt hash. Inherited content uses
`local inherit reference -> typed base row -> eO -> vO -> cO -> O endpoint`;
it does not traverse the local price Evidence. Every directly declared context
also has Evidence for the lunch/dine-in assertion. Resolution history is reached
separately through `menu_page.resolution_event_id`, not substituted for Evidence.

Common inputs (all times UTC on 2026-09-17):

- O1: stream `(rO, main, jsonld)`, version vO1 observed **09:00**, accepted
  **09:01**, stream/version revision **1/1**. Source-native section `s-food`,
  item `i-burger`, name Burger, description Grilled beef; price **900**, C.
  Direct support eO1 at `/menu/sections/food/items/burger` and its `/price` field.
- A1: stream `(rA, main, dom)`, vA1 observed **09:10**, accepted **09:11**,
  revisions **1/1**, pin O1. Inherit section/item references with all factual
  payload NULL; local price **1050**, C, eA1 at `#burger .lunch-price`.
- B1 (when introduced): stream `(rB, main, dom)`, vB1 observed **09:20**,
  accepted **09:21**, revisions **1/1**, pin O1. Same inherited shape, local
  price **1200**, C, eB1 at `#burger .lunch-price`.

Each table result explicitly identifies the value, scope, observation time and
Evidence. K includes the described event unless another cutoff is stated.

| Case / input | Selected value and scope | Observation time and Evidence | Expected explanation |
|---|---|---|---|
| Unknown local price, K=09:15, before B1 | B: **unknown**; separate O claim **900** and shared Burger content | B price: **none / no local Evidence**. O: **09:00**, eO1 `/price`; content eO1 item path | No price row is invented. A1's 1050 cannot supply B, and O1's 900 stays Organization-scoped. |
| Sibling prices, K=09:25 | A **1050**, B **1200**; separate O **900** | A **09:10**, eA1; B **09:20**, eB1; O **09:00**, eO1 `/price` | Siblings can charge different prices. Local DOM remains the local value despite shared JSON-LD. |
| Price-only inheritance, A1 | A price **1050**; content **Burger / Grilled beef**, scope **O**, pinned O1 | Price **09:10**, eA1. Content **09:00**, inherit path to eO1 item | A did not assert the description. Inherit ancestors establish exact parent/target correspondence without copied facts. |
| Exact replay of A1 after 09:25 | A **1050**, same IDs and no new rows | Still **09:10**, eA1 (same Evidence set); accepted_at remains 09:11 | Retry timestamp does not create freshness. Different amount/Evidence under that key is a conflict. |
| Later observation A2: vA2 at 10:00, accepted 10:01, revisions 2/1, explicit A1 successor, same 1050 | A **1050**, now A2; content still O1 | Price **10:00**, eA2 `#burger .regular-price` plus declared-context Evidence; content **09:00**, eO1 | A new observation appends even when amount is unchanged. The initially accepted interpretation mislabeled the regular price as lunch; the next case corrects it. |
| Correction A3: vA2, accepted 10:10, revisions 3/2, successor A2, lunch price corrected to 1150 | K=10:05: A **1050**; K=10:15: A **1150** | Both **10:00**; earlier eA2 regular locator, corrected eA2-lunch `#burger .lunch-price` and lunch-context support | vA2 contains both source claims. The correction changes accepted interpretation and support, not Bronze or observation time. A2 remains inspectable as the prior accepted error. |
| Explicit local unknown A4: vA4 at 10:20, accepted 10:21, revisions 4/1, successor A3; source says market price | A **unknown**, no fallback; separate O **900** | A **10:20**, eA4 `#burger .market-price`; O **09:00**, eO1 | A real unknown observation has Evidence/time, unlike absence before B1. Unavailable has the same amount-NULL shape but a distinct source assertion. |
| Withdrawal A5: vA5 at 10:30, accepted 10:31, revisions 5/1, successor A4, Evidence-backed page tombstone | A local stream **withdrawn; no selected local value** (price result unknown due to withdrawal); shared O remains **900** separately | Tombstone **10:30**, eA5 `#notice` (“location menu withdrawn”); no local price observation; O **09:00**, eO1 | K=10:32 blocks A1–A4, even with O cutoff 10:20. K=10:25 still shows A4. No predecessor price reappears. |
| Restoration A6: vA6 at 10:40, accepted 10:41, revisions 6/1, explicit restoration of A5 with complete inherited graph/pin O1 and local 1175 | A **1175**; content **O1** | Price **10:40**, eA6 `#burger .lunch-price`; content **09:00**, eO1 | A fresh supported restoration is necessary; an ordinary observation after A5 is rejected. A5 remains immutable. |

Independent continuations below start from the stated common inputs, avoiding
an implicit combination of unrelated examples:

| Case / input | Selected value and scope | Observation time and Evidence | Expected explanation |
|---|---|---|---|
| O2 ordinary successor of O1, vO2 at 11:00 accepted 11:01, new description and price 950; A1 remains pinned O1 | A **1050**; pinned description **Grilled beef**, O1; latest standalone O claim **950** | A **09:10**, eA1; pinned content/optional pinned shared 900 **09:00**, eO1; standalone O2 **11:00**, eO2 | Ordinary supersession does not silently rebase A1. O2 and the O1 pinned view are explicitly different views. |
| O3 withdraws O stream at 11:10 / 11:11; then O4 explicitly restores it at 11:20 / 11:21 | A1: **unresolved base; no resolved local price** until explicit local rebase; O4 standalone **975** after restoration | A1's 1050 remains history at **09:10**, eA1; withdrawal **11:10**, eO3 notice; O4 **11:20**, eO4 price | O3 blocks the old pin; O4 does not revive it. A new local snapshot pinning O4 with locally supported price is needed. Historical K=11:05 still uses O1. Independent local additions can remain current. |
| Remap rA from A to B at 11:30; no new Menu page yet | Current A: **unknown (stale mapping)**; B does not acquire A's price. Accepted-history K=09:15 still A **1050** | Current A: no selected price/time/Evidence; excluded A1 remains **09:10**, eA1 with original assign event; B's independent B1, if present, remains **1200 / 09:20 / eB1** | Remap is not evidence of a new location price. Exact A1 replay is read-only. Remapping back still does not restore A1's original event. |
| Explicit corrected A-stream successor after that remap, accepted 11:31, vA1, stream/version revisions 2/2, scope B with current remap event | In corrected rA family: B **1050**, only if vA1 actually supports B; A has no current claim there | Still **09:10**, eA1 with corrected B resolution event; original A1 retains A scope/event | No counter reset. Cross-family B1 is not silently deduplicated with rA. If source support does not justify B, no successor may be accepted; input stays Bronze. |
| Retire A (or a required parent) at 11:40 after A1 acceptance | Current A: **no eligible local price**; accepted-history K=09:15: A **1050** | Current: no selected price/time/Evidence; historical **09:10**, eA1 plus original assign event | Retirement changes current eligibility, not the accepted observation. No split-output copying. Full A1 then retirement in one transaction retains history; retirement before A1 rejects admission. |

Additional exact-context and correspondence fixtures:

- A base section restricts C to `[11:00,14:00)` on the example day. Two local
  contenders declare `[10:00,15:00)` and `[11:00,14:00)` with matching labels;
  both effective contexts are `[11:00,14:00)` and rank together. A contender
  restricted to `[12:00,14:00)` stays a separate exact context. E=14:00 is
  outside all of them. Takeaway under the dine-in section fails integrity.
- Two captures each have “Burger” in position 2, with no native ID or base link.
  Their fallback locators include different versions: they cannot contribute
  prices to one another's selected content. A genuine `i-burger` under stable
  `s-food`, or links to the exact same O1 item, supplies correspondence.
- A head accepted at 12:01 with observation 12:00 is excluded by O=11:00;
  an older price is not revealed. Inspecting older accepted claims is explicit.
  A pin whose base exceeds O is unresolved at that cutoff. K filters accepted
  claims, not transaction commit times or past readiness edits.

## Verification and preservation

A newly initialized native PostgreSQL **16.14** cluster used explicit UTF-8,
private directory `/tmp/helios-menu-design.ltjyjy7x`, socket subdirectory `socket`,
port `55441`, role `helios`, and disposable database `helios_test`. No existing
cluster/script was assumed. The sandbox initially denied socket creation/access
and `uv` cache writes; the first `make ci` attempt stopped before tests. Repeating
with sandbox escalation allowed the required checks without changing guards or
Docker permissions.

```bash
export DATABASE_URL='postgresql+psycopg://helios@/helios_test?host=%2Ftmp%2Fhelios-menu-design.ltjyjy7x%2Fsocket&port=55441'
HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
```

| Check | Result |
|---|---|
| Strict `make ci` | **180 passed, 0 failed, 0 skipped**, 25.04s; all pre-commit hooks, mypy (39 files), and lockfile check passed |
| Migration/concurrency within that full suite | **1 migration round-trip test and 14 concurrency tests passed**, included in 180; no skips |
| Encoded-socket `alembic check` | Exit 0, **No new upgrade operations detected** |
| Local Markdown links | **7 edited/new documents, 100 local links, 33 heading fragments, 0 broken targets**; resolved relative targets and generated heading slugs |
| Design consistency review | All **14 enforcement mappings M01–M14** have concrete checks/tests; **14 lifecycle example rows** plus applicability/correspondence/cutoff fixtures reviewed against proposal and ADR |
| Documentation hooks and whitespace | Explicit pre-commit scan includes both new untracked Markdown files; `git diff --check` passes |
| Preservation | All pre-existing files outside five intentionally edited documentation files are byte-identical; original reassessment body and historical proposal record preserved |

Future Menu invariants are design obligations, not tests passed by this
change. Docker/PostGIS image `imresamu/postgis:16-3.4` remains **unverified** from
the prior socket-access denial and was not retried in this documentation unit.
Application image build/smoke, deployment, load, and future Menu behavior are
not verified. The new native cluster is stopped after verification; temporary
paths/logs are diagnostics, not prerequisites for the next session.

The initial tracked modifications and untracked hardening files were hashed
before edits. During this unit HEAD advanced externally from `96fec0d` to
`4eb9e94`; this agent issued no commit command. A comparison at that point
confirmed every pre-existing file except the intentionally edited proposal was
byte-identical. The agent did not switch branches, reset, clean, discard, commit,
push, merge or deploy. Historical ADR-0004 and acceptance/hardening records are
retained; the reassessment receives only a dated current-status pointer.
The ML notes remain byte-identical, SHA-256
`ac509f8b5db62599fb71db3a8b4681cbde5ba59c51b3240c2cc1eeeb4189db1c`.
The config and all code, tests, migrations, dependencies, CI and deployment files
are unchanged by this unit. README, ROADMAP and the Step 5 plan receive current
review links; future unwritten ADR topics are unnumbered so actual ADR-0005 does
not collide with a planned number. Existing numbered ADRs are untouched.

## Unresolved work and next unit

Owner review of proposed ADR-0005 and concrete schema/SQL remains separate from
accepted defaults. Future Menu triggers, races, selection and examples are not
implemented. Docker/PostGIS CI image validation remains a pre-implementation
gate; native success cannot close it. Mixed Bronze/resolution/Menu ingestion,
historical Identity reconstruction, extraction, ML, Gold and Step 6 stay deferred.

**One next work unit: prepare the narrow provider prerequisite for review, after
owner design acceptance and PostGIS validation.** Completion means published
Bronze immutable lookup DTOs/SQL helpers, Identity-owned batch admission and
shared feature predicate, one forward provider-function revision, focused
promotion/admission parity and pending-lineage/race tests, preserved foundation
data, reviewed upgrade/downgrade SQL, strict checks with zero database skips,
and a durable verification/handoff record. No Menu tables or writer in that unit.
If design acceptance or image validation is missing, close/report that gate
before starting the implementation diff; never imply it was accepted here.

Use configured `gpt-6-astra`, high reasoning, Default/implementation mode, one
agent and concise/low verbosity. `.codex/config.toml` was read and left unchanged;
this records the requested/configured choice, not a runtime model-switch claim.
Use this same chat for corrections to this design unit. Prefer a **new session**
for the provider prerequisite because design reconciliation is a completed work
boundary; repository records and the prompt below carry the needed context.

### Copyable next-work prompt

```text
Prepare Helios Plan 0002 Step 5's narrow provider prerequisite for review.
Use configured gpt-6-astra, high reasoning, Default/implementation mode,
one agent, concise reporting. Complete authorized edits and verification;
do not stop at a plan. This prompt authorizes the concrete provider diff
only after the design and image-validation gates below are satisfied.

Verify branch Plan-0002-Step-5; report mismatch before switching. Preserve
all tracked modifications and untracked files, including verification
hardening, Menu design docs, readiness reassessment, and
docs/HumanDevNotes/MLDataExtractionPlan.md. Do not reset, clean, discard, commit, push, merge,
or deploy. HEAD advanced externally to 4eb9e94 during design reconciliation;
recheck actual HEAD and file contents rather than assuming a clean tree.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
ADR-0004, docs/adr/0005-immutable-menu-snapshots-and-selection.md,
docs/plans/0002-identity-foundation-before-menu.md,
docs/plans/0002-step-5-menu-schema-proposal.md,
docs/reviews/0002-step-5-readiness-reassessment.md, and
docs/reviews/0002-step-5-menu-design-reconciliation.md. Never rely on prior
chat access. ADR-0005 is proposed until owner acceptance is recorded in this
session or repository; request only that missing design approval if needed.
Prepare concrete implementation/SQL for its separate final review; do not
request repeated permission for work this prompt and design acceptance allow.

First close outstanding strict CI PostGIS-image validation if accessible:
use the repository's CI image and a separately provisioned disposable *_test
DB, full make ci without skips, migration round trips, alembic check with no
drift. Prior native PostgreSQL 16.14 baseline: 180 passed, zero failures/skips,
including migration/concurrency; percent-encoded socket URLs worked. Docker
socket access was denied; native success is not PostGIS acceptance. Do not
assume temporary databases or scripts remain. If that gate is still blocked,
record the precise access limit and completed safe review/checks; do not claim
implementation readiness or change Docker permissions/deployment settings.

After those gates, implement only published Bronze immutable version/Evidence
lookups and Identity-owned batch scope guard, dependency expansion, lock order,
pending-lineage checks and shared feature predicate, with a narrow forward
provider-function migration after 91f4c2a7d6e8. Promotion must still work from
provisional; admission requires existing eligible readiness and exact current
Source Record/event mapping. Preserve matching/readiness policy. Prove Python/
SQL parity, both admission-versus-lineage orderings (including same transaction
and forced deferred constraints), race/retry behavior, and provider data/object
preservation across upgrade/downgrade/re-upgrade. Keep Bronze traversal owned
by Bronze and Identity policy/locks in Identity. No upward imports or provider
tables merely for Menu. Supply concrete SQL and focused tests for review.

Preserve the reconciled Menu contract: immutable snapshots; direct factual
Evidence plus structural/inherited support; inherit/full replacement/suppression;
pins surviving ordinary supersession; stream tombstones, explicit restoration
and rebasing after withdrawal; accepted-claim history with K/O/E cutoffs; stream
and version revision uniqueness across remaps; stable native/base correspondence;
effective contexts after ancestor intersection; no shared/sibling local-price
fallback; USD, exact contexts, individual modifiers and committed Bronze input.
Do not implement Menu models/contracts/writer, matching-policy changes, Gold,
APIs, extraction, ML, fuzzy matching, Step 6, runtime dependencies or deployment.
Do not modify applied migrations or historical acceptance records.

Run required make ci, focused checks and alembic check on disposable data;
skipped DB tests never establish acceptance. Review generated upgrade/downgrade
SQL; do not execute on application data. Record decisions, exact results and
unresolved work in the repo before handoff. Stop at the provider prerequisite
review boundary; do not begin Menu implementation.

End with (1) what changed and why in plain language; (2) verification counts
and remaining limits; (3) one next work unit and completion criteria;
(4) model/reasoning/mode/agent count/verbosity recommendation; (5) explicit
same-chat/new-session recommendation and reason; (6) a self-contained copyable
next-work prompt preserving this same completion-and-handoff requirement.
Continue the same chat for fixes within a unit; prefer a new session at a
distinct completed-work boundary. Never rely on prior conversation access.
```
