# Step 5 provider prerequisite: gate verification

**Provider preparation update (2026-09-18):** Both pre-implementation gates
are satisfied. ADR-0005 acceptance is retained; strict validation on CI image
`imresamu/postgis:16-3.4` passed **180 tests with zero failures/skips** and
`alembic check` found no drift before provider edits. The narrow provider diff
and concrete SQL are prepared for [separate review](0002-step-5-provider-prerequisite.md),
which records the final implementation checks and continuing handoff. Menu
implementation has not started. The access/approval records and prompts below
are historical; use the linked provider review for the current next work unit.

**Latest access update (2026-09-18):** The quick Docker check succeeded with
allowed sandbox escalation using `/snap/docker/current/bin/docker`:
`docker info --format '{{.ServerVersion}}'` returned **29.8.0**, exit 0.
The same direct-binary check inside the sandbox still gets socket permission
denied. The earlier escalation attempt was blocked by an automatic approval
review usage limit; today's explicitly resumed attempt was allowed.

An escalated `docker image inspect imresamu/postgis:16-3.4` reached the daemon
but returned **No such image**, exit 1. No image was pulled, container started,
or database test executed in this quick check. Docker permissions and deployment
settings were not changed. Branch remains `Plan-0002-Step-5`; all existing work
is retained. The access blocker is resolved for escalated commands, while strict
CI-image validation remains outstanding. Earlier access-denial records below
are historical results.

**Next execution:** Continue this chat. Use the direct Docker binary with
sandbox escalation, pull the CI image, create a fresh disposable `*_test`
database, then run strict `make ci`, migration/concurrency coverage, and
`alembic check`. ADR-0005 is already accepted. Only after that gate passes,
prepare the authorized provider diff and SQL using the completion/handoff
requirements in the next-work prompt below. Do not repeat the design approval.

**Current update (2026-09-17, resumed attempt):** Owner Fortune accepted
ADR-0005 and its reconciled proposal in this session: “Accept ADR-0005 design”.
Acceptance is recorded in the ADR; do not request it again. Strict CI-image
PostGIS validation remains blocked by Docker socket access. Provider code,
migration SQL, and implementation readiness remain outstanding.

## Resumed verification and decisions

Branch `Plan-0002-Step-5` and HEAD
`238627adf5019e9d9b39a33296f22932979028e0` were reverified. The existing README
modification and untracked gate record were preserved. All **82** pre-existing
tracked/untracked files were hashed before edits. Required guidance and design
documents were reread; accepted product defaults and historical decisions were
not reopened.

The direct Docker command
`/snap/docker/current/bin/docker info --format '{{.ServerVersion}}'`
again returned exit 1 with permission denied at `unix:///var/run/docker.sock`,
both inside the sandbox and with allowed sandbox escalation. This is an OS/socket
failure, not an automatic approval-review rejection. No permissions or deployment
settings were changed. An authorized environment for running the CI image was
requested; none had been supplied at the time of this update. The snap-launcher
failure below is the earlier result, not a new launcher test.

A fresh native PostgreSQL **16.14** cluster used explicit UTF-8, role `helios`,
`/tmp/helios-provider-resume.56rhbbsc`, private socket subdirectory `socket`,
port `55445`, no TCP listener, and new database `helios_provider_resume_test`.
No prior cluster or database was reused. It was stopped after the checks.

```bash
export DATABASE_URL='postgresql+psycopg://helios@/helios_provider_resume_test?host=%2Ftmp%2Fhelios-provider-resume.56rhbbsc%2Fsocket&port=55445'
HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
uv run alembic heads
```

| Resumed check | Result |
|---|---|
| Strict native `make ci` | **180 passed, 0 failed, 0 skipped**, 29.09s; exit 0. |
| Included foundation coverage | **14** concurrency tests and **1** seeded migration round trip passed; no new provider behavior is covered. |
| Lint/hooks, types, lockfile | Passed; mypy checked **39 source files**. |
| Encoded-socket `alembic check` | Exit 0; **No new upgrade operations detected**. |
| Alembic head | Unchanged: `91f4c2a7d6e8 (head)`. |
| CI-image PostGIS tests | **0 executed**; the remaining implementation gate is open. |
| Documentation checks | Applicable hooks passed for all **6** edited documents, including this untracked record; **88** local link targets checked, zero broken; `git diff --check` passed. |
| Preservation | All **82** pre-existing tracked/untracked files checked; only the **6** intended documentation files changed. ML notes retain the hash recorded below. |

This resumed change records owner acceptance in ADR-0005, updates current
README/ROADMAP/proposal status, adds a dated Plan 0002 acceptance update, and
extends this gate record. Original design-review and readiness-reassessment
records remain unchanged. Code, tests, applied migrations, dependencies,
configuration, and the ML notes remain unchanged. The initial attempt below
retains its original verification and missing-approval state as history.

## Initial attempt before owner design acceptance

**Date:** 2026-09-17
**Branch:** `Plan-0002-Step-5`, verified without switching.
**Starting HEAD:** `238627adf5019e9d9b39a33296f22932979028e0`; working tree clean.
**Outcome:** Provider prerequisite preparation remains blocked before implementation.
No provider diff, new migration, or concrete provider SQL is ready for review.

## Decisions and authority

The request authorizes the narrow provider implementation only after owner
acceptance of [ADR-0005](../adr/0005-immutable-menu-snapshots-and-selection.md)
and strict validation on the repository's CI PostGIS image. Neither gate is
closed by this record. ADR-0005 remains Proposed: an owner approval question
was presented in this session, with no acceptance received when this record
was written. Accepted defaults are retained without reopening them.

The required guidance, ADR-0004, Plan 0002, detailed Menu proposal, readiness
reassessment, and design reconciliation were read. The existing provider seam
was inspected without edits: Identity currently publishes the single-subject
`require_eligible_subject` and feature-policy functions in `identity/contracts.py`;
promotion calls `subject_meets_readiness_policy` from `identity/commands.py`.
Bronze contracts own observation persistence and Source Record locks. Alembic
still has one head, `91f4c2a7d6e8`. This inventory is not proof of the proposed
batch guard, exact-event admission, pending-lineage, or Python/SQL parity.

No implementation was started while the gates remained open. Do not use this
native foundation result as provider or Menu acceptance. The requested SQL
review remains outstanding alongside the provider implementation itself.

## CI-image access result

The Tests service in `.github/workflows/ci.yml` specifies
`imresamu/postgis:16-3.4`, matching Compose. Current access attempts:

| Attempt | Result |
|---|---|
| `docker version` through the installed snap launcher | Exit 1; `snap-confine is packaged without necessary permissions and cannot continue`; required `cap_dac_override` is absent. |
| `/snap/docker/current/bin/docker info --format '{{.ServerVersion}}'` | Exit 1; permission denied connecting to `unix:///var/run/docker.sock`. |
| Same direct-binary command with sandbox escalation | Exit 1; the same Docker socket permission denial. Escalation was allowed; this was a daemon/socket access failure, not an automatic approval-review rejection. |

No container or CI-image test database could be provisioned through that socket.
There were **zero tests executed against the CI image**. Docker permissions,
group membership, daemon configuration, and deployment settings were not changed.
The application image build/smoke and deployment were not verified either.
An environment with authorized access to the CI image is still required.

## Completed safe verification

A newly initialized native PostgreSQL **16.14** cluster used explicit UTF-8,
role `helios`, private directory `/tmp/helios-provider-gate.57g_6zbx`, socket
subdirectory `socket`, port `55443`, and no TCP listener. Its newly created
database was `helios_provider_gate_test`. No old cluster or script was reused;
no application data was involved. Sandbox escalation allowed the private
database socket and existing tool-cache access without configuration changes.

Commands after provisioning that disposable database:

```bash
export DATABASE_URL='postgresql+psycopg://helios@/helios_provider_gate_test?host=%2Ftmp%2Fhelios-provider-gate.57g_6zbx%2Fsocket&port=55443'
HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
uv run alembic heads
```

| Check | Result |
|---|---|
| Strict native `make ci` | **180 passed, 0 failed, 0 skipped**, 25.93s; exit 0. |
| Existing migration/concurrency tests, included in 180 | **1** seeded upgrade/downgrade/re-upgrade test and **14** real-connection concurrency tests passed. These are foundation tests, not new provider tests. |
| Lint/hooks, types, lockfile | All hooks passed; mypy passed on **39 source files**; lockfile check passed. |
| Encoded-socket `alembic check` | Exit 0; **No new upgrade operations detected**. |
| Alembic head | `91f4c2a7d6e8 (head)`; no revision added. |
| Documentation verification | Explicit pre-commit scan of README and the new untracked record passed applicable hooks; **14 local links in 2 files**, zero broken targets; `git diff --check` passed. |

The isolated cluster is stopped after verification. Temporary paths/logs are
diagnostic only; provision fresh disposable data on resumption. This record
preserves the prior native baseline while adding a fresh independent result.
It does not close the strict PostGIS gate or establish implementation readiness.

## Preservation and scope

Only this new record and a README link are intended repository changes.
All **81 pre-existing files** were hashed before edits and checked at handoff;
README is the sole changed pre-existing file. The ML notes retain SHA-256
`ac509f8b5db62599fb71db3a8b4681cbde5ba59c51b3240c2cc1eeeb4189db1c`.
Verification hardening, Menu design documents, readiness reassessment,
historical acceptance records, applied migrations, code, tests, dependencies,
CI/deployment settings, and `.codex/config.toml` remain unchanged.
No reset, clean, discard, commit, push, merge, or deployment was performed.

## One next work unit and completion criteria

**Resume this provider prerequisite unit by closing its remaining PostGIS gate,
then prepare the authorized provider diff for separate review.** ADR-0005 owner
acceptance is recorded; do not request it again. Run strict `make ci`, migration
round trips, and drift checks on a fresh disposable `*_test` database using the
CI image. If access stays blocked, record that result without bypassing the gate.

After both gates pass, completion requires Bronze-owned immutable version and
Evidence lookups; Identity-owned batch scope admission, dependency expansion,
lock order, pending-lineage checks, and shared feature policy; one narrow forward
provider-function migration after `91f4c2a7d6e8`; Python/SQL parity, promotion
from provisional, both lineage/admission orderings including forced deferred
checks, bounded concurrency/retry tests, and provider data/object preservation
through upgrade/downgrade/re-upgrade. Supply concrete upgrade/downgrade SQL,
strict verification counts with no database skips, and the review handoff.
Stop there: Menu implementation remains a separate unit.

Use requested/configured `gpt-6-astra`, high reasoning, Default/implementation
mode, one agent, concise/low verbosity. Local config specifies that model and
disables agents; it was not edited. This is not a claim to have switched the
running model. **Continue the same chat** for the access follow-up:
this unit is blocked, not a completed provider review boundary. Prefer a new
session only once a distinct work unit is completed, or if environment access
requires it; the prompt below is self-contained either way.

## Copyable next-work prompt

```text
Resume Helios Plan 0002 Step 5's narrow provider prerequisite for review.
Use configured gpt-6-astra, high reasoning, Default/implementation mode,
one agent, concise reporting. Complete authorized edits and verification;
do not stop at a plan. Never rely on previous chat access.

Verify branch Plan-0002-Step-5; report mismatch before switching. Preserve
all tracked modifications and untracked files, especially verification
hardening, Menu design documents, readiness reassessment, the new provider
gate record, and docs/HumanDevNotes/MLDataExtractionPlan.md. Do not reset,
clean, discard, commit, push, merge, or deploy.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/adr/0004-modular-monolith-identity-and-lifecycle.md,
docs/adr/0005-immutable-menu-snapshots-and-selection.md,
docs/plans/0002-identity-foundation-before-menu.md,
docs/plans/0002-step-5-menu-schema-proposal.md,
docs/reviews/0002-step-5-readiness-reassessment.md,
docs/reviews/0002-step-5-menu-design-reconciliation.md, and
docs/reviews/0002-step-5-provider-prerequisite-gates.md.

ADR-0005 and its reconciled proposal were accepted by owner Fortune on
2026-09-17 with “Accept ADR-0005 design”, recorded in the ADR. Do not ask for
that approval again or reopen accepted defaults.
Close strict PostGIS validation using CI image imresamu/postgis:16-3.4 and
a fresh disposable *_test database: strict make ci with zero failures/skips,
migration/concurrency execution, and alembic check with no drift. Native
PostgreSQL 16.14 passed 180 tests, zero failures/skips, including 1 migration
round trip and 14 concurrency tests; encoded socket URLs and drift check
passed. Docker snap capability failure and direct-binary socket permission
denial persisted even with sandbox escalation. No provider code or SQL was
prepared. Do not assume temporary databases/scripts remain. If CI-image
access stays blocked, record the exact limitation and safe checks without
claiming readiness or changing Docker permissions/deployment settings.

After the remaining PostGIS gate passes, this prompt authorizes only the provider diff:
Bronze-owned immutable version/Evidence lookups; Identity-owned batch scope
guard, dependency expansion, lock ordering, pending-lineage checks and shared
feature predicate; one narrow forward provider-function migration after
91f4c2a7d6e8. Promotion must work from provisional; admission requires eligible
readiness and exact current Source Record/event mapping. Preserve matching
and readiness policy. Prove Python/SQL parity, both lineage/admission orderings,
forced deferred checks, concurrency/retry behavior, and provider preservation
through upgrade/downgrade/re-upgrade. Supply concrete SQL for separate review.

Preserve immutable snapshots, direct factual Evidence with structural/inherited
support, inherit/full replacement/suppression, pins surviving ordinary
supersession, withdrawal tombstones and explicit restoration/rebasing,
accepted-claim history and K/O/E cutoffs, revision uniqueness across remaps,
stable correspondence, and applicability after ancestor intersection.
Never infer local prices from Organization or sibling-location prices.
Keep USD, exact contexts, individual modifiers, and committed Bronze input.
No Menu implementation, matching-policy changes, Gold, APIs, extraction,
ML, fuzzy matching, Step 6, runtime dependencies, or deployment changes.
Do not modify applied migrations or historical acceptance records.

Run required checks on disposable data; skipped database tests never establish
acceptance. Record decisions, verification counts, and unresolved work in the
repository. Stop at the provider prerequisite review boundary.

End with (1) what changed and why; (2) verification counts and remaining limits;
(3) one next work unit and completion criteria; (4) recommended model,
reasoning, mode, agent count, verbosity; (5) explicit same-chat/new-session
recommendation and reason; (6) a self-contained copyable next-work prompt
preserving this same completion-and-handoff requirement. Continue the same
chat for fixes within a unit; prefer a new session at a distinct completed
boundary. Never rely on prior chat access.
```
