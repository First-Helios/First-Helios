# ADR-0012: Venue lifecycle — re-observation, closure, re-homing, and readiness

**Status:** Proposed
**Date:** 2026-09-24
**Phase:** 4 (remediation of the 2026-09-22 review, session S12)
**Decides for:** R36, R98, R105, R106, and the Establishment half of R61; sets
what S13 implements
**Owner decisions:** D6.3 (draft an ADR, then stop), D6.4 (auto-promote an
Establishment when its Place and Organization are eligible)
([remediation checklist](../reviews/2026-09-22-remediation-checklist.md))

## Context

Discovery ([ADR-0009](./0009-venue-discovery-source-dedupe-and-schedule.md))
mints venues once and never touches them again. Four review findings follow
from that:

- **R36.** A POI that resolves by GERS id on a later run is only counted
  (`report.reused`). Name, address and coordinate changes never reach its
  Organization or Place, venues that close or leave Overture stay current
  forever, and dedupe compares new POIs against first-seen coordinates.
- **R98.** `/v1/venues` checks only the Establishment's currentness. After a
  merge or retirement of its Organization or Place it still shows the retired
  parent's name and coordinates.
- **R105.** No Establishment can ever be `eligible`, so no Establishment-scoped
  menu write is possible (see "Readiness today" below).
- **R106.** An Establishment's Organization and Place links are immutable in the
  database (trigger `protect_typed_grain_key`, SQLSTATE `55000`), so fixing
  R98 or a relocation means a new Establishment, not re-pointing.

S8 (#30) left one more piece here: an `eligible` Establishment is not demoted
when a parent drops back to `provisional` (R61, Establishment half).

### What the code does today

- **Shape.** Each minted POI gets its own Organization, Place and Establishment
  (1:1:1). Dedupe assigns a second Overture record to an existing
  Establishment and mints nothing, so an Establishment can hold several Overture
  records. Only a human `record_subject_change` can make two Establishments
  share a parent.
- **Mutability.** Typed-grain *features* are ordinary columns, updatable in
  place: `place.address/latitude/longitude`,
  `organization.canonical_name/name_fingerprint`,
  `establishment.operating_status/valid_to`. The trigger only guards subject id,
  kind, and the Establishment's two parent links. No Identity event records a
  feature update. Events exist only for resolutions (`resolution_event`) and
  Subject changes (`subject_change`), both with decision metadata and Evidence.
- **History in Bronze.** Every discovery run with a new `observed_at` appends a
  Version per POI it sees, stamped with the release (`capture.bundle_path`
  today, the release endpoint under ADR-0011). "Last release this POI was seen
  in" is already derivable. No new table is needed to detect absence.
- **Closure semantics exist.** ADR-0004 §2: closing a restaurant changes the
  Establishment's operating state and is *not* retirement. A Place is not
  retired because one Establishment at it closes. `operating_status` is one of
  `unknown/open/closed`. Menu selection already treats an Establishment as
  not operating when `operating_status = 'closed'` or `valid_to` has passed
  (`selection._operating_ok`). `/v1/venues` does not filter on either.
- **Readiness today.** `identity.subject_feature_ready`:
  - Place: address or coordinates present.
  - Organization: a name, **and** a current `resolved` Source Record pointing
    at the Organization itself.
  - Establishment: both parents have stored `readiness = 'eligible'` and both
    are feature-ready.

  Nothing calls `mark_subject_eligible`. Places are therefore never eligible.
  Organizations are refreshed automatically when a resolution changes, but
  discovery assigns Overture records to the *Establishment*. So an
  Organization becomes eligible only when `resolve_urls` assigns it a website
  record. The Establishment rule then fails on the Place every time.
- **Menu scope binding.** A menu page stores `(subject, source record,
  resolution event)`, and current-mode selection re-checks that mapping. A
  remap or merge away from an Establishment drops its pages from current views
  and keeps them for history (ADR-0004 §5). No Establishment is eligible today,
  so no Establishment-scoped menu data exists yet. Nothing below touches stored
  menu rows.

## Decision

A **lifecycle pass** in the discovery app (`apps/discovery`), built only from
existing Identity commands plus one readiness command. It is a deterministic
function of Bronze history: re-running it on the same Bronze rows gives the same
Identity state. Each area below lists options; ⭐ is the recommendation. The
owner picks per area when accepting (see "For review").

### 1. Audit trail for lifecycle changes

| | Option | Cost |
|---|---|---|
| ⭐ **A** | **Feature edits in place; Bronze is the audit.** Name-display, address and small coordinate edits update typed-grain columns. Every edit is a deterministic rule over the Bronze Version that caused it, which the run report names. Anything that changes *which* Subject a record belongs to goes through the existing evented commands (`remap_source_record`, `record_subject_change`), with Evidence and `actor_class="rule"`. | No schema change. Typed-grain columns hold the current value only; history lives in Bronze. |
| B | A new append-only `identity.subject_feature_change` event (old/new values, decision metadata, Evidence), with trigger protection. | Migration on an Identity table (⚠ path). Worth it once humans edit features by hand, because a rule could then overwrite a human edit silently. |
| C | Every change becomes a Subject change (new Place/Organization plus a merge). | Venue ids churn every month for cosmetic edits. |

Under A, "Evidence-backed" means: every Identity *decision* (remap, merge,
retire, mint) carries the triggering Version's Evidence. A feature edit is not
a decision. It is the current projection of the latest Bronze Version, the same
way minting copies the first one today.

### 2. Re-observed POIs (R36, first half)

This runs inline in `run_discovery`'s `resolved` branch, where the new POI is in
hand. It applies only when the Establishment is **discovery-owned**: its only
current Overture record is this one, and no other current Establishment that
is **not closed** shares its Organization or Place. Closed ones are ignored
because a relocation or rebrand below leaves the closed predecessor on the
shared parent, and that must not freeze the successor. Anything else is counted as `lifecycle_skipped` and
left alone (a deduped pair, or parents shared after a human merge). There is no
basis for picking a winner there.

| Change | ⭐ Rule | Alternative |
|---|---|---|
| Display name changes, **same fingerprint** (case, accents, punctuation) | Update `organization.canonical_name` in place. | — |
| **Fingerprint changes** | Treat as a **new business at the same Place**: close the old Establishment (§3 closure fields, `valid_to` = this release's date), mint a new Organization and Establishment on the *same* Place, and `remap_source_record` the Overture record to it. | Rename in place. Cheaper, but a new owner under the same GERS id then inherits the old venue's menu history. That is a wrong merge, which ADR-0009 §2 ranks as the expensive error. A cosmetic rebrand under option ⭐ costs one closed-and-reopened venue id, which is the cheap error. |
| Address text changes, coordinates within 50 m | Update `place.address` in place. | — |
| Coordinates move **≤ 50 m** | Update `place.latitude/longitude` in place (a correction). | — |
| Coordinates move **> 50 m** | **Relocation**: close the old Establishment, mint a new Place and a new Establishment on the *same* Organization, and remap the record. The old Place stays current (ADR-0004: a Place is not retired when an Establishment at it closes). | Update in place at any distance. Simpler, but moves a venue's history to a new location. |
| Categories, websites | Out of scope. Websites belong to `resolve_urls` (ADR-0010). | — |

50 m is ADR-0009's dedupe radius, so "same place" means the same thing in both
rules. It is a named constant. If Overture coordinates jitter by more than that
between releases, the first S13 run will show it as a burst of relocations (the
run report counts them) and the constant is raised.

### 3. Venues that disappear (R36, second half)

- **Close, never retire** (ADR-0004 §2): `operating_status = 'closed'`,
  `valid_to` = date of the first release the venue was missing from. Place,
  Organization and resolutions are unchanged.
- ⭐ **N = 2 consecutive releases** (D6.3's suggestion): one missed release is
  often an upstream conflation blip. Named constant.
- **"Missing" = no Overture Version for any of the Establishment's current
  Overture records in that release.** Computed from Bronze at the end of a
  discovery run. Only current, not-yet-closed Establishments with at least one
  current Overture record are considered. A venue with no Overture record (one
  created by hand or by another source) is never closed by Overture's silence.
- **Partial runs never close anything.** The pass runs only after the discovery
  iterator is fully consumed. It **refuses** (reports and changes nothing) when
  either of the last N releases saw fewer than **90 %** of the POIs the release
  before it saw (named constant). A crashed or bbox-limited run then can't
  close a venue that was simply not read.
- ⭐ **Reappearance reopens** the same Establishment: `operating_status` goes
  back to `unknown` and `valid_to` to NULL. The closure was only inferred, and
  Bronze keeps the gap. *Alternative:* mint a new Establishment, which gives a
  stricter history but churns ids on every upstream blip.
- `operating_status = 'open'` is never set from Overture presence. Presence is
  not a confirmation, so seen venues stay `unknown`.
- *Deferred:* Overture's own open/closed flag. Discovery doesn't read it today.
  Check whether the pinned release carries it before relying on it. It would
  close venues one release sooner than absence does.
- ⭐ **`/v1/venues` stops serving closed venues**: it excludes
  `operating_status = 'closed'` and a `valid_to` in the past. No query parameter
  until a consumer asks. *Alternative:* keep serving them with the status
  field, which leaves every client to filter. S13 adds an ADR-0008 note either
  way.

### 4. Retired or merged parents (R98, R106)

Parent links can't change, so the fix is a **new Establishment** that points at
the current parent. This is the "re-home".

- **Detect:** the lifecycle pass finds current Establishments whose Organization
  or Place is not current.
- **Parent merged** (exactly one current successor in `subject_lineage`): mint
  Establishment E′ on the successor (other parent unchanged, same
  `valid_from`, status and `valid_to`). Then `remap_source_record` each of E's
  records to E′, and after that record
  `record_subject_change(operation="merge", inputs=[E, E′], outputs=[E′])`.
  That merge is legal today (≥2 inputs, one of which survives). The order
  matters: remap needs a current target, and the merge needs every member
  current. S12 checked this sequence against a migrated database. E retires
  and redirects through lineage, so API clients holding E's id can follow it.
- **Parent retired without successor, or with several** (a split): retire E
  (`operation="retire"`) and leave its records for review. An Establishment
  whose operating identity or location was proven invalid is itself invalid.
- ⭐ **Also, defensively:** `/v1/venues` never serves an Establishment whose
  Organization or Place is not current, so a merge committed by raw SQL between
  two passes can't show a retired name. *Alternative:* resolve the parent
  through lineage at read time. That fixes only the display: the Establishment
  still fails readiness because its parent isn't current.
- Who merges parents today? Only a human with `record_subject_change`. ⭐ The
  lifecycle pass is the only re-homer, which keeps one code path. The
  alternative (re-home inside `record_subject_change`) widens a
  concurrency-sensitive command S8 just fixed.

### 5. Readiness (R105, D6.4, R61)

D6.4 alone does not unblock menus, because Places are never promoted. The
pass therefore handles all three kinds. Every step is idempotent and re-run on
each pass:

1. **Place:** promote with `mark_subject_eligible` when feature-ready
   (address or coordinates). Every discovered Place qualifies.
2. **Organization:** ⭐ **no policy change.** It stays eligible exactly when a
   resolved record points at it, which in practice means once `resolve_urls`
   assigns its website. Menus come from websites (Phase 5), so an Organization
   with no website has no menu to write yet. *Alternative:* also count records
   resolved to its Establishments. That changes the SQL predicate
   (`subject_feature_ready`), which needs a migration.
3. **Establishment (D6.4):** promote when both parents are eligible. The
   lifecycle pass sweeps for this. So does `resolve_urls` right after a
   website assignment makes an Organization eligible, which saves waiting a
   month.
4. **Demotion (R61):** ⭐ the same sweep sets a stored `eligible` back to
   `provisional` when the computed readiness is false. Writes are already safe
   today, because admission re-evaluates the parents; this keeps the stored
   value honest for readers. It needs one new Identity command,
   `refresh_subject_readiness(subject_id)` (lock order as documented in
   `identity/commands.py`; no schema change). The existing private
   Organization-only refresh stays as it is.

### 6. Where and when it runs

- §2 runs inline during `run_discovery`. §3–§5 run as
  `run_lifecycle(session, release=…)` after `run_discovery` completes, from the
  same `python -m apps.discovery` invocation, in batches that commit like
  discovery does.
- Every Identity decision uses `actor_class="rule"`, a method name per rule
  (`overture-lifecycle-relocate`, `-rebrand`, `-rehome`, `-retire`), and the
  Evidence of the Version that triggered it. Closure is triggered by absence,
  so it has no Version of its own and makes no Identity decision (§1 A). The
  run report lists every closed Establishment and the last release it was seen
  in.
- New report counters: `updated`, `relocated`, `rebranded`, `closed`,
  `reopened`, `rehomed`, `retired`, `promoted`, `demoted`, `lifecycle_skipped`.
- **Pi:** nothing runs before the Pi rebuild (ADR-0011 §8). The first real
  lifecycle pass needs two releases after the rebuild before any closure can
  fire.

## Alternatives considered

| Area | Option | Why not (default) |
|---|---|---|
| Audit | Event table for feature edits (§1 B) | Migration on Identity for edits that are fully re-derivable from Bronze today. Revisit when hand edits exist. |
| Audit | Everything as Subject changes (§1 C) | Venue ids churn monthly for cosmetic edits. |
| Rename | Always in place | A new business under an old GERS id inherits the old menu history (wrong merge). |
| Relocation | Always in place | History follows the brand to a new address; dedupe radius loses its meaning. |
| Closure | Retire instead of close | ADR-0004 §2: retirement means the identity was invalid. A closed restaurant was real, and its menu history should read as a closed venue's. |
| Closure | N = 1 | One upstream blip closes venues. Reopen churn. |
| R98 | Read-time lineage lookup in the API | Fixes display only; the Establishment still can't be eligible. |
| R98 | Re-home inside `record_subject_change` | Widens S8's concurrency-sensitive command. |
| R105 | Change the Organization readiness predicate | Migration; no menu source exists for website-less Organizations anyway. |

## Consequences

- Venues track Overture: renames, corrections and closures appear within one
  or two monthly releases, and dedupe compares against current coordinates.
- **Venue ids are stable for edits and change on relocation, rebrand and
  re-home.** The old id closes (relocation, rebrand) or redirects through
  lineage (re-home). API clients following ids must accept that.
- Menus unblock only for venues whose Organization has a website. That is the
  intended Phase 5 population.
- **Harder:** typed-grain columns hold the latest value only. "What was this
  venue's address in March?" is answered from Bronze, not Identity. If humans
  ever edit features, §1 B becomes necessary before the next automated pass,
  or the pass overwrites their edit.
- The lifecycle pass is new write traffic on Identity every month (roughly
  10k Subjects read, few written). It follows S8's lock order, and like the
  multi-command discovery batches S8 documented, it can still deadlock
  against a concurrent writer; a retry of the batch is the remedy.
- Deduped Establishments (two Overture records) and human-merged parents never
  auto-update. They are counted, not fixed.

## For review (owner)

Accept or change each ⭐:

1. §1 audit: **A** — in-place feature edits, Bronze as audit (no migration).
2. §2 fingerprint change = **new business** (close + mint), not rename in place.
3. §2 relocation threshold **50 m**, relocation = close + new Place + new
   Establishment.
4. §3 **N = 2** releases, **90 %** partial-run floor, **reopen** on
   reappearance.
5. §3 `/v1/venues` **hides closed venues**.
6. §4 re-home via merge `[E, E′] → E′` in the lifecycle pass; retire on a
   parent retired without a single successor; API hides Establishments with
   non-current parents.
7. §5 promote Places; Organization predicate unchanged; promote/demote
   Establishments in the sweep and after website assignment; new
   `refresh_subject_readiness` command.

On acceptance S13 implements exactly this, adds an amendment pointer to
ADR-0009 §2 (re-observation) and a note to ADR-0008 (§3/§4 venue filtering),
and writes the tests the checklist lists for S13. Those are: a re-observed POI
with a new address, a POI missing for N releases, an Organization merge seen
through `/v1/venues`, and Establishment promotion unblocking a Menu write. Add
to them: relocation, rebrand, reopen, a refused partial run, and demotion.

## References

- [2026-09-22 review](../reviews/2026-09-22-full-codebase-review.md) R36, R61,
  R98, R105, R106; [remediation checklist](../reviews/2026-09-22-remediation-checklist.md) D6.3, D6.4, S12, S13
- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) §2 (closure vs
  retirement), §5 (merge/split/retire semantics)
- [ADR-0009](./0009-venue-discovery-source-dedupe-and-schedule.md) §2 (dedupe
  radius), §3 (monthly schedule)
- [ADR-0011](./0011-provenance-endpoints-vs-identity-match-keys.md) §8 (Pi rebuild)
- Code: `apps/discovery/pipeline.py` (`run_discovery`),
  `packages/helios_core/identity/commands.py` (`mark_subject_eligible`,
  `_refresh_subject_readiness`, `record_subject_change`, `remap_source_record`),
  `alembic/versions/b72e6a90c431_add_provider_scope_contracts.py`
  (`subject_feature_ready`),
  `alembic/versions/91f4c2a7d6e8_fix_typed_grain_update_trigger.py` (parent
  immutability), `apps/api/routes/venues.py` (`_current_venue_select`),
  `packages/helios_core/domains/menu/selection.py` (`_operating_ok`)
