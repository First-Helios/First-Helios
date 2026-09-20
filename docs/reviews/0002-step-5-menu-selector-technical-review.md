# Step 5 pure Menu selection and ranking (read side) — technical review

**Date:** 2026-09-19. **Owner:** Fortune. **Branch:** `Plan-0002-Step-5`.
**Reviewed HEAD:** `02549a44f6da051288be3489127ed78d9a62c017` (the writer drift-fix
commit), on the provider acceptance base
`de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b`; branch and HEAD verified without
switching. The bounded Menu writer at revision `d83f0a21c592` and both Menu SQL
directions were accepted by Fortune "Accept as-is" on 2026-09-19 and are
**unchanged** here (hashes rechecked below).

**Disposition:** the read-side selector is a **review draft**. Green CI and this
record are **not** owner acceptance; this unit needs its own explicit owner
decision (see [§Owner disposition](#owner-disposition)).

## Scope of this unit

The pure current/accepted-history Menu selection and ranking unit — the **read**
complement of the accepted writer. It only reads already committed Menu
aggregates and returns deterministic selections. It performs no writes, commits,
extraction, ML, fuzzy matching, Gold projection, or API surface, and adds no
runtime dependency and **no migration** (it reuses the writer's `menu.node_path`
STABLE function for path/context traversal).

Two new files, both untracked before this unit:

- [Selector](../../packages/helios_core/domains/menu/selection.py)
  (`packages.helios_core.domains.menu.selection`) — request/result contracts and
  the `select_price` query. Imports only Menu ORM plus **published** Identity and
  Bronze *contracts* (never provider ORM), so it passes the ADR-0004 import
  boundary test.
- [Precedence tests](../../test/test_menu_precedence.py) — 22 focused tests over
  committed disposable data exercising the ADR-0005 example matrix and the
  extended applicability/correspondence/cutoff fixtures.

No accepted artifact was edited. The Menu writer, its migration, both concrete
SQL files, the provider revision, and the Identity/Bronze contracts are
byte-identical.

## What the selector does

`select_price(session, request)` selects, for one source-local family
`(source_record_id, root_key)` across interpretation kinds and one native-path
target, either the **current interpretation** (`knowledge_cutoff` absent) or the
**accepted-claim history** at `K`/`O`/`E` (`knowledge_cutoff` present). It
returns the selected content (with the scope that actually asserted it), the
local price value, and any separate Organization claims.

- **Current mode** re-admits the accepted head's own subject/record/event mapping
  through the published `require_resolved_scopes` guard and reads operating
  availability at `E` from the returned `ResolvedScope`. A broken mapping (remap,
  retirement, pending lineage, unmapped record) yields `unresolved_scope`; a
  closed or out-of-interval Establishment yields `not_operating`. Organizations
  are always operating.
- **History mode** picks the stream head at `K` (greatest visible stream
  revision, `accepted_at <= K`) **before** any observation/context/`E` filter, so
  a filtered head never revives a predecessor. A tombstone visible by `K` blocks
  every older page even when its observation time exceeds `O`.
- **Ranking:** interpretation kind (`jsonld > dom > pdf > llm`), then later
  observation time, then confidence (**page** confidence for content, **price**
  confidence for prices), then ascending canonical Bronze business key.
- **Applicability:** effective context is the intersection of the local and
  mapped-base ancestor restrictions plus the price's own context. Only exactly
  equal effective tuples compete; overlapping-but-unequal tuples stay distinct;
  `unspecified` is not a channel wildcard; `E` filters half-open window
  membership (end excluded).
- **Correspondence:** a target is identified by a stable `(kind, native_key)`
  path; an inherited reference resolves through its typed base link to the base
  node's identity, so JSON-LD/DOM claims and pinned siblings collapse to one
  target. A node with neither native key nor base link is version-local and does
  not match a stable-path target.
- **Scope never inferred:** an absent local price is a derived `absent` unknown
  with no invented Evidence and no shared/sibling fallback; an explicit
  `unknown`/`unavailable` price keeps its own observation and Evidence.
  Organization prices are surfaced separately as `pinned`/`head` claims and never
  become the local value. A pin whose base is withdrawn/filtered yields
  `unresolved_base`; independent local additions survive.

### Deliberate boundaries (for owner review)

- **One `unresolved_scope` reason.** The published Identity scope guard returns
  pass/fail, not *why* (remap vs. retire vs. pending). The selector reports the
  single boundary-respecting reason `unresolved_scope`; the specific identity
  cause stays an Identity-module concern. This is stricter than the matrix's
  explanatory labels but honours the ADR-0004 contract seam (verticals import
  identity **contracts**, never its ORM).
- **Operating availability:** `closed`, `valid_from > E`, or `E >= valid_to`
  withhold the current value; `open`/`unknown` within interval are available.
- **Organization claims** are derived from the selected content's pin. When the
  local head is a tombstone there is no pinned content, so the establishment
  query returns `withdrawn` with no Organization claim; the shared claim is still
  reachable by a **direct** Organization-scoped query (asserted in the tests).
- **Pending lineage** is applied by a deferred trigger at commit, so it is only
  observable inside its own transaction; that path is tested by selecting within
  the uncommitted session and rolling back.

## Verification (fresh disposable data, 2026-09-19)

Run on a **freshly provisioned** container — not reused. Every count is from
this run.

| Check | Evidence |
|---|---|
| Strict `make ci` | pre-commit (incl. the two new files) Passed; `mypy --strict` **Success, 58 source files**; `uv lock --check` clean (56 packages). Tests: **530 passed, 0 failed, 0 errors, 0 skipped**, **285.14s**, coverage **98%**. |
| New selector tests | **22** in `test_menu_precedence.py` (file coverage **100%**); total suite grew 508 → **530**. |
| Selector module coverage | `selection.py` **93%** (409 stmts, 29 uncovered — defensive `None` guards and write-time-only incompatible-context branches unreachable from valid committed data). |
| Concurrency (unchanged, all green) | test_menu_concurrency **48**, provider **39**, foundation **14** — both race orders, stronger-isolation rollback/revalidation, real deadlock retry, whole-transaction `40001`/`40P01` retry. The read selector adds no new concurrency scenarios (pure read over one consistent snapshot); integrated read/write races are deferred to final M01–M14 acceptance. |
| Drift & head | `alembic check`: **No new upgrade operations detected**; `heads`/`current` both **d83f0a21c592** (single head); **8** revision files (no migration added). |
| Accepted artifact preservation | All **6** accepted Menu artifact SHA-256 byte-identical (below); `docs/HumanDevNotes/MLDataExtractionPlan.md` = `ac509f8b…9db1c` unchanged. |
| Import boundary | `test_foundation_import_boundaries` passes: the selector imports Identity/Bronze **contracts** only, no provider ORM, no upward/cross-vertical import. |

Environment: `/snap/docker/current/bin/docker` (29.8.0) with sandbox escalation,
image `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4**, disposable `helios_selector_test` on a distinct
container/port `55443`. The task-owned container and its anonymous volume were
removed after the run; the developer stack container `helios-postgres` and volume
`infra_postgres_data` were not touched. No application data was used.

### Accepted Menu artifact hashes (unchanged)

| Artifact | SHA-256 |
|---|---|
| Revision d83f0a21c592 | `cc5cc345215511687ac16adf6c1a741ba83dff0903ed368f5a03d8ee45f3b153` |
| Concrete upgrade SQL | `55d4c4f36757e8ea188ca968984cdbc4de441f994fe546f6437d7db2c365f097` |
| Concrete downgrade SQL | `b3820db752de822ccebb3700b77498aab7f31983e72ca68e8a0a7019a63d6400` |
| Models | `c99ce3e10654e7799b7d1a3bf63aadf765de90bd86a1f74d2ba411f49e7942c0` |
| Contracts | `64610ca0fa3e1d42921d8981922b4552e72ca0956fbf00bbd0665eecd4ae7227` |
| Commands | `1205ce6ef428a987c8d524572ffbc68fe925663aba2b3d9675faa835d16286ae` |

## Limits

No Gold, API, extraction, ML, fuzzy matching, Step 6, new dependency,
application-data execution, deployment, or load benchmark. The selector is a pure
read contract/fixture specification, not a Gold projection or API. Mixed
Bronze/resolution/Menu ingestion and historical mutable-Identity reconstruction
remain deferred. Runtime results do not certify semantic source truth. Owner
acceptance of the selector is not recorded here.

## Owner disposition

The read-side selector (`selection.py`) and its tests are presented for an
explicit owner decision. Green CI and this review are **not** acceptance.

**Status: accepted by owner Fortune on 2026-09-19.** In this session, presented
the read-side selector and its 22 precedence tests against the hashes below,
with the fresh-data verification recorded above, and asked for a disposition.
Fortune's decision: **"Accept"** — accept the read-side selection/ranking unit at
the reviewed bytes. No correction or condition was requested.

This is a real supplied decision, not inferred from green tests or this review.
It accepts the two selector artifacts at their recorded SHA-256 values; those
bytes are unchanged. It does not authorize integrated M01–M14 acceptance,
application-data execution, Gold, APIs, extraction, ML, fuzzy matching, Step 6, a
new dependency, or any deployment. Future changes to these artifacts require
their own scoped review.

| Accepted selector artifact | SHA-256 |
|---|---|
| [Selector](../../packages/helios_core/domains/menu/selection.py) | `cdd4b62dee22cce62bd5676f6007379ded1d1a17938a5005f9b95c38280ad86d` |
| [Precedence tests](../../test/test_menu_precedence.py) | `b7dee1785420585ce942cb7f4a5899a6aaa575f3038c9aa8f30e1d96d364836f` |

## One next unit and completion criteria

**Integrated M01–M14 final acceptance and final owner SQL/selector review.**
Completion means: the accepted writer, both Menu SQL directions, and this
selector exercised together across the full ADR-0005 matrix and integrated
read/write race scenarios; strict fresh CI-image `make ci` with zero
failures/errors/skips; `alembic check` no drift; accepted-artifact and provider
preservation reconfirmed; and an explicit owner disposition against the reviewed
hashes. Do not begin it automatically.

## Recommendation

Configured **high reasoning, Default/implementation mode, one agent, concise
reporting**. Continue the **same chat** for fixes to this selector unit. Prefer a
**new session** for the distinct integrated-acceptance boundary, using the
repository and the self-contained prompt below rather than prior-chat access.

Step 5 remaining-work estimate after this unit: **one substantial unit** —
integrated M01–M14 acceptance and final SQL/selector owner review (review
findings can add a bounded correction pass). Most product collection/API work
remains beyond Step 5.

## Copyable next prompt

```text
Drive Helios Plan 0002 Step 5's integrated M01–M14 final acceptance of the
accepted Menu writer, both Menu SQL directions, and the read-side selector
together. Use configured high reasoning, Default/implementation mode, one agent,
concise reporting. Complete authorized verification and any bounded read-side
correction; do not stop at a plan or rely on prior chat access.

Verify branch Plan-0002-Step-5 and actual HEAD; report mismatch before switching.
Provider acceptance base de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b; bounded Menu
writer d83f0a21c592. Preserve every tracked modification and untracked file,
especially provider fixes/tests/SQL, the Menu implementation/migration/both SQL/
tests, the read-side selector (packages/helios_core/domains/menu/selection.py)
and test/test_menu_precedence.py, all reviews and acceptance/handoff/disposition
records (including docs/reviews/0002-step-5-menu-writer-technical-review.md and
docs/reviews/0002-step-5-menu-selector-technical-review.md), readiness
reassessment and docs/HumanDevNotes/MLDataExtractionPlan.md. No reset, clean,
discard, commit, push, merge, deploy or rewriting historical migrations/records.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/adr/0004 and 0005, Plan 0002, the reconciled Menu proposal and example
matrix, and all Step 5 review/handoff/disposition records. Fortune accepted
ADR-0005/proposal (2026-09-17), the corrected provider/code/both SQL directions
(2026-09-18), the bounded Menu writer + d83f0a21c592 + both Menu SQL directions
"Accept as-is" (2026-09-19), and the read-side selector
(selection.py SHA-256 cdd4b62dee22cce62bd5676f6007379ded1d1a17938a5005f9b95c38280ad86d,
test_menu_precedence.py SHA-256 b7dee1785420585ce942cb7f4a5899a6aaa575f3038c9aa8f30e1d96d364836f)
"Accept" (2026-09-19). Do not request those approvals again; all those artifacts
stay byte-identical. Only the final integrated M01–M14 disposition is still open;
green tests or this instruction are not acceptance.

Do not change the accepted writer, migration, SQL, or provider contracts; do not
add Gold, APIs, extraction, ML, fuzzy matching, Step 6 or new dependencies. The
selector must keep: current selection via live Identity + operating availability;
accepted-claim history with K/O/E and stream head at K before filtering (never
reviving a predecessor); tombstones visible by K applying past O; ranking by
kind>observation>confidence>canonical key with page confidence for content and
price confidence for prices; applicability by local/base ancestor intersection
with unspecified not a wildcard and overlapping-unequal tuples distinct;
Shared/Organization prices never inferred as local; absent local -> derived
unknown without invented Evidence; explicit unknown/unavailable keeping its
observation; pins through supersession, withdrawal/restoration/rebasing, stable
native/base correspondence and version-local fallback locators.

Use /snap/docker/current/bin/docker with sandbox escalation, imresamu/postgis:16-3.4
and fresh disposable *_test data; do not assume prior containers/logs remain. Run
strict make ci with zero failures/errors/skips, alembic check with no drift,
raw-SQL/Python integrity, forced deferred checks, real commits, both race orders
and whole-transaction 40001/40P01 retry, and integrated read/write scenarios
across the full ADR-0005 example matrix and extended replay fixtures. Keep both
writer SQL artifacts synchronized and byte-preserved; explicitly lint untracked
files. Skips never establish acceptance. No Docker permission/deployment changes
or application-data execution. Remove task-owned disposable resources. Record
exact counts and limits in the repo.

Present concrete artifacts for the owner and record only an actual supplied
decision. End with (1) changes and reasons; (2) exact verification counts and
limits; (3) one next unit and completion criteria; (4) model/reasoning/mode/
agent-count/verbosity recommendation; (5) explicit same-chat/new-session
recommendation and reason; (6) a self-contained copyable next prompt preserving
these same completion-and-handoff requirements; and an updated Step 5
remaining-work estimate. Continue the same chat for fixes within a unit; prefer a
new session at a distinct completed boundary. Never rely on prior chat access.
```
