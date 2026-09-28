# S13 implementation review — venue lifecycle

Implements accepted [ADR-0012](../adr/0012-venue-lifecycle.md), including R36,
R98, R105, R106 and Establishment readiness demotion from R61. Draft PR; merge
and Phase 5 acceptance remain pending. No Pi data or resolver was touched.

## Starting point and scope

`main` and `origin/main` were both `46d81d4`. PR #43 (Pi rebuild record) and
PR #44 (precision review, originally based on #43) were merged, with no open
PRs. Work uses `/home/fortune/CodeProjects/First-Helios-s13`, branch
`feat/s13-venue-lifecycle`. Existing worktrees were preserved.

This is lifecycle implementation, not retrospective correction. The precision
packet remains agent assessment: 23 supported duplicate pairs / 4 distinct /
16 unresolved; 20 corroborated geocodes / 3 supported errors / 22 unresolved.
Broad duplicate cleanup is deferred. The Pi URL-resolution gate remains closed
pending correction/adjudication and a passing confirmed precision audit. S6b is
not Pi-gating. Phase 5 remains closed until S13 merges and lifecycle acceptance
passes.

## Implementation and schema review

- Re-observation projects only the newest successful Bronze release. Same-instant
  content conflicts are reported, older backfills cannot undo newer projections,
  and exact replay does not repeat transitions. A per-record watermark records
  the applied Version. Every changed feature is traceable to the report's
  Version IDs and immutable Bronze data.
- Same-fingerprint display edits, address text corrections and coordinate changes
  within 50 m update the current projection. A changed fingerprint creates a new
  Organization; movement over 50 m creates a new Place. Both together create
  one successor Establishment. The predecessor closes, its parents remain
  historical identities, and existing Identity commands record the remap with
  Evidence and `actor_class="rule"`.
- Multiple current Overture records or shared active parents veto automatic
  feature transitions. Address changes without comparable coordinates are
  explicitly reported for review. Closed predecessors do not freeze successors.
- Re-homing follows parent lineage to its current terminal successors. A unique
  successor permits remaps followed by `[E, E′] → E′`; absent/ambiguous successors
  retire E. Triggering Version/parent-change Evidence supports the decision.
- Places and Establishments refresh readiness under Identity's existing lock
  order; Organization policy is unchanged. URL writes refresh readiness without
  waiting for another discovery release. Menu admission still requires Identity
  events committed in a prior transaction.
- Website remaps check the intended Organization before payload reuse. Only
  this GERS record's lifecycle ancestry may supply remaps. Existing own-site and
  every platform menu key need fresh successful verification. Changed websites
  can rediscover and verify a replacement menu. Failed, stale or disputed keys
  retain history. Cache freshness uses the server-recorded transition time,
  not the release date or the acquisition run's earlier decision time.
- Both venue routes exclude closed/expired Establishments and non-current
  parents. Detail requests for filtered IDs return 404; re-home lineage is
  retained, but there is no new redirect endpoint.

Migration `5a91ef3ff9d8` adds only the two discovery-owned tables explicitly
required by ADR-0012. It does not alter existing Bronze or Identity columns:

| Table | Purpose and guards |
|---|---|
| `bronze.discovery_release_completion` | Canonical release endpoint/instant; exact bbox, categories and filter-policy version plus coverage hash; row count; expected predecessor; server completion time. Identical retries collapse. Conflicting counts/predecessors persist and veto closure. |
| `bronze.discovery_lifecycle_state` | Append-only applied-Version watermarks and inferred closure/reopen origin, including first missing release. Bronze-only FKs preserve layer direction; Subject IDs are journal identifiers, not upward FKs. |

Both tables reject UPDATE, DELETE and TRUNCATE. All FKs use RESTRICT. Populated
downgrade refuses to destroy lifecycle history; an empty database supports
upgrade → downgrade → upgrade. The model registry imports these discovery-owned
ORM models through its existing all-model registration exception. The import
fitness rule allows exactly that models module, not general app imports.

Reviewed SQL: [upgrade](sql/2026-09-28-s13-lifecycle-upgrade.sql) and
[downgrade](sql/2026-09-28-s13-lifecycle-downgrade.sql). Snapshot tests normalize
trailing whitespace from Alembic's DDL formatter.

## Completion and operating procedure

The discovery CLI commits all observed rows only after exhausting its iterator,
then appends and commits the completion marker, then invokes `run_lifecycle`.
Intermediate batches still commit every 100 POIs. A failed iterator produces no
completion marker even when most rows have committed. A crash after sealing but
before lifecycle can be recovered by rerunning the identical release.

`--expected-predecessor <previous-release-path>` declares the immediately prior
published release. A baseline may omit it; that missing edge cannot establish
absence. Closure requires two strictly increasing linked completed releases
following a completed baseline, identical full Austin coverage/filter policy,
and the 90% count floor at both edges. Custom bbox/filter runs can supply
presence but cannot supply absence. Old completions cannot move the horizon
backwards. Presence from any current Overture record (including rejected input)
vetoes absence; rejected input cannot update features. A newer observation also
prevents an older closure pass from closing the venue.

Closure sets `closed` and the first missing release instant, retaining Subjects
and resolutions. Only a recorded inferred closure can reopen on newer successful
presence; manual or transition closures remain closed. Re-homing preserves an
inferred closure's origin. Batch commits cover parent handling, closure and
readiness; retry a whole batch after a database deadlock.

No historical completion markers are synthesized. In particular, the Pi rebuild
record does not become machine-verifiable survey completion merely because this
migration is installed. Establish a real completed baseline through a separately
authorized run before counting its two successors.

## Acceptance coverage

| Contract | Tests |
|---|---|
| Latest release, exact replay, same-instant conflict, combined transition, atomic rollback | `test_venue_lifecycle.py` |
| Shared record/parent refusal and missing-coordinate ambiguity | `test_venue_lifecycle.py` |
| Two missing releases, first-missing timestamp, reopen, manual closure, rejected presence | `test_venue_lifecycle.py` |
| Custom 95% coverage, missing marker, count anomaly/conflict, skipped/unknown predecessor, old horizon | `test_venue_lifecycle.py` |
| Actual crash after 95% of rows commit; exhausted CLI replay and readiness | `test_lifecycle_cli.py` |
| Organization/Place merge, retirement, split; HTTP/API visibility | `test_venue_lifecycle.py` |
| Unchanged/changed websites, every saved platform key, stale/failing verification, review protection | `test_lifecycle_urls.py`, `test_web_client.py` |
| Promotion admitting a committed Establishment Menu; old Menu current/history separation | `test_lifecycle_urls.py` |
| Readiness demotion and retired/missing Subjects | `test_venue_lifecycle.py` |
| Immutable completion/state, empty round trip, populated downgrade refusal, SQL snapshots | `test_lifecycle_migration.py` |

## Validation

Final results on the committed diff:

- `HELIOS_STRICT_DB_TESTS=1 make ci` on a freshly created database: lockfile,
  ruff check/format, mypy --strict (118 files) passed; pytest 1017 passed,
  1 skipped (pre-existing `packages/helios_parsing has not landed yet`), 93 %
  coverage. An earlier strict run caught one test passing Subject ID `-1`, which
  Identity's lock function rejects before lookup; the test now uses a missing
  positive ID.
- `alembic upgrade head` then `alembic check`: no new upgrade operations.
- `docker build -f infra/Dockerfile` and container `/healthz` smoke: OK.
All database validation uses separately provisioned disposable `*_test` databases
on a local `imresamu/postgis:16-3.4` container, with no application data. HTTP
verification tests use injected responses; no test crawls a live venue.

## Remaining limitations and rollback

- Duplicate/adjudication work and historical coordinate repairs remain separate.
  A movement over 50 m is conservatively treated as relocation, even if upstream
  coordinates were wrong; no automatic threshold widening or geocode correction.
- Shared-source venues and ambiguous lineage need review. Same-instant conflicting
  observations are preserved and reported; the first projection is not silently
  reversed when later conflicting evidence arrives.
- Completion trusts iterator exhaustion under the recorded query policy. It is
  not an upstream cryptographic completeness guarantee. Conflicting retry claims
  fail closed; correcting them needs a reviewed policy, not editing Bronze.
- Direct manual feature editing remains unsupported by the accepted Bronze-as-audit
  projection policy. A distinct human feature-event contract is still deferred.
- S6b's discovery of additional platform menus alongside own-site menus remains
  deferred. S13 verifies every platform record that already exists.
- Discovery serializes its lifecycle and URL batches with an advisory lock after
  the shared Identity-maintenance lock. Independent Identity commands may still
  deadlock with a multi-command batch; rollback/retry remains required. Production
  throughput has not been measured, and no live deployment has been attempted.
- Rollback: stop scheduling the new lifecycle path and revert application code.
  Retain appended Bronze and evented Identity history. Do not drop populated
  lifecycle tables or reverse remaps with raw SQL; use reviewed Identity commands
  with Evidence for any subsequently authorized corrective decisions.
