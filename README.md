# Helios V2

A trustworthy, queryable price index of food in Austin — restaurant menus
and what they actually cost, rebuilt from scratch with professional rigor.

**Status (2026-09-17):** Bronze provenance and shared Identity are implemented
through Plan 0002 Step 4. Menu persistence is in design review; the API has
health endpoints only. Menu collection and the price-index product are not
implemented yet.

The [current reassessment](./docs/reviews/0002-step-5-readiness-reassessment.md)
records verified behavior, verification hardening before Menu, and the
next product demonstration.

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
`alembic check` reported no changes. Docker/PostGIS validation remains blocked
by local Docker socket permissions; this is native PostgreSQL acceptance only.

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
