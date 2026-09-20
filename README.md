# Helios V2

A trustworthy, queryable price index of food in Austin — restaurant menus
and what they actually cost, rebuilt from scratch with professional rigor.

**Status (2026-09-18):** Bronze provenance and shared Identity are implemented
through Plan 0002 Step 4. Menu persistence has a reconciled [proposal](./docs/plans/0002-step-5-menu-schema-proposal.md)
and [accepted ADR-0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md).
The [provider prerequisite and concrete SQL](./docs/reviews/0002-step-5-provider-acceptance-and-menu-handoff.md)
are accepted by the owner after CI-image PostGIS validation; the API has
health endpoints only. Menu collection and the price-index product are not
implemented yet.

The [current reassessment](./docs/reviews/0002-step-5-readiness-reassessment.md)
records verified behavior, verification hardening before Menu, and the
next product demonstration.

The [provider prerequisite gate check](./docs/reviews/0002-step-5-provider-prerequisite-gates.md)
preserves the earlier access failures and now links the completed CI-image gate.
ADR-0005 owner acceptance is recorded. The provider diff and
[upgrade/downgrade SQL](./docs/reviews/0002-step-5-provider-prerequisite.md#migration-and-concrete-sql)
are now accepted; Menu implementation has not started.

The [provider technical review](./docs/reviews/0002-step-5-provider-review.md)
fixed stale-snapshot admission after remap/unassign. Final strict CI passed
278 tests with no failures/skips, including direct SQL preservation checks;
Alembic found no drift. Owner acceptance of the corrected provider and both SQL
directions is recorded in the [acceptance and Menu handoff](./docs/reviews/0002-step-5-provider-acceptance-and-menu-handoff.md).

The [owner-disposition packet](./docs/reviews/0002-step-5-provider-owner-disposition.md)
binds the corrected implementation and both SQL artifacts to exact hashes.
Fresh strict CI again passed 278 tests with zero failures/skips and no drift;
the disposable test container was removed. Fortune subsequently approved all
presented items on 2026-09-18. The provider unit is complete; the bounded Menu
persistence/writer handoff is ready for separate implementation authorization
in a new session.

**Update (2026-09-19):** the bounded Menu writer, revision `d83f0a21c592`, and
both concrete Menu SQL directions were accepted "Accept as-is"
([writer technical review](./docs/reviews/0002-step-5-menu-writer-technical-review.md)).
The [read-side selection/ranking unit](./docs/reviews/0002-step-5-menu-selector-technical-review.md)
is now implemented (`packages/helios_core/domains/menu/selection.py` and
`test/test_menu_precedence.py`, 22 focused tests) and was **accepted by the owner
on 2026-09-19**; it adds no migration. Fresh strict `make ci` passed **530 tests,
zero failures/skips**, coverage 98%, `alembic check` no drift (single head
`d83f0a21c592`). Integrated M01–M14 final acceptance — the accepted writer, both
Menu SQL directions, and the selector exercised together across the full ADR-0005
matrix on a fresh CI-image database — was **accepted by the owner on 2026-09-19**
([integrated acceptance record](./docs/reviews/0002-step-5-menu-integrated-m01-m14-acceptance.md)).
Step 5 Menu engineering is complete; Gold read models are Step 6.

The scope was set menus-first on 2026-07-31 by
[RFC-0001](./docs/rfc/0001-menu-pricing-first.md): menu and item-price
coverage across the Austin / Round Rock metro is the product, and meal deals
become a layer built on top of it (Phase 10) rather than the foundation.

This build is **agent-driven with a human reviewer in the loop**. See
[CLAUDE.md](./CLAUDE.md) for agent working instructions and
[CONTRIBUTING.md](./CONTRIBUTING.md) for the PR/review workflow.

## Start here

- [ROADMAP.md](./ROADMAP.md) — what we're building, in what order, and why.
- [LEARNING_GUIDE.md](./LEARNING_GUIDE.md) — the module-by-module skills
  course (originally paced for a human learner; now primarily a curriculum
  for reviewing agent-authored work — see [ADR-0001](./docs/adr/0001-stack-choice.md)
  for context on the agent-driven shift).
- [docs/adr/](./docs/adr/) — standing architectural decisions.

## What's here now

- `packages/helios_core/provenance/` — six Bronze tables for sources,
  endpoints, captures, source records/versions, and Evidence; replay-safe
  observation persistence.
- `packages/helios_core/identity/` — Subject, Place, Organization, and
  Establishment; append-only resolution and lineage decisions; deterministic
  external-key/URL resolution and readiness guards.
- `packages/helios_core/db/` — shared model registration, schema ownership,
  and session/engine setup. The legacy `Venue` scaffold has been removed.
- `apps/api/` — FastAPI service. `/healthz` (liveness) and `/readyz`
  (checks the database) so far.
- `alembic/` — migrations. `alembic upgrade head` builds the schema from
  scratch.
- `infra/` — `Dockerfile` (multi-stage, non-root) and `docker-compose.yml`
  (Postgres/PostGIS → one-shot migrate → API).
- Tooling: `ruff`, `mypy --strict`, `pytest`, `pre-commit`, all wired into
  CI as required status checks on `main`.

Menu and Gold tables, discovery ingestion, extraction, scraping, and product
API endpoints are not implemented. Staging/production deployment has not
been verified by the current repository assessment.

## Local setup

Run the whole stack in Docker — Postgres, migrations, and the API:

```bash
git clone https://github.com/First-Helios/First-Helios.git
cd First-Helios

cp .env.example .env
make dev        # builds + starts postgres -> migrate -> api

curl localhost:8000/healthz   # {"status":"ok"}
curl localhost:8000/readyz    # {"status":"ok"} once Postgres is up
```

`make dev-logs` tails the stack, `make dev-down` stops it.

To work on the code directly (tests, linting, type checking):

```bash
make install   # uv sync + pre-commit hooks
make ci        # lint + typecheck + test + lockfile check
```

`make ci` runs local lint, type, test, and lockfile checks. GitHub CI also
builds and smoke-tests the Docker image. A local green run with skipped
database tests does not establish database acceptance.

For full database verification, provision a separate disposable `*_test`
database first, then use its connection URL. For example, with a separately
created local `helios_test` database and the example development credentials:

```bash
HELIOS_STRICT_DB_TESTS=1 DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios_test make ci
DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios_test uv run alembic check
```

Strict mode is enabled in CI. It fails instead of skipping when PostgreSQL
is unavailable or unsuitable and rejects any `HELIOS_ALLOW_NONTEST_DB` setting.
Without strict mode, optional local database tests can still skip.

The migration tests downgrade and rebuild that database, and concurrency
tests commit fixture rows. Do not point them at application data or set
`HELIOS_ALLOW_NONTEST_DB`. On 2026-09-17, a temporary PostgreSQL 16 cluster
passed strict `make ci`: 180 passed, zero failed/skipped, including the
migration and concurrency tests, using a percent-encoded socket URL.
`alembic check` reported no changes. That result was native PostgreSQL acceptance
only. On 2026-09-18 the CI PostGIS image passed strict pre-implementation
validation; the [provider review](./docs/reviews/0002-step-5-provider-prerequisite.md)
records its exact image versions, provider checks, and remaining limits.

## V1 archive

The prior version of this project lives on the
[`V1-Graveyard`](https://github.com/First-Helios/First-Helios/tree/V1-Graveyard)
branch — reference material for porting proven patterns (see
[ROADMAP.md §3](./ROADMAP.md#3-part-a--distilled-assets)), not a dependency
of `main`.

```bash
# browse V1 code without affecting your V2 working copy
git fetch origin V1-Graveyard
git worktree add ../helios-v1 V1-Graveyard
```

## License

[Business Source License 1.1](./LICENSE) — source-visible, non-commercial
use only until the Change Date, after which it converts to Apache License
2.0. See the LICENSE file for the current parameters, or contact
abdullahhijazi3@gmail.com for a commercial license.
