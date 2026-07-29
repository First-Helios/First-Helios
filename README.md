# Helios V2

A trustworthy, queryable map of real food deals in Austin — rebuilt from
scratch with professional rigor.

**Status:** Phase 0/1 — bootstrap tooling and the first schema migration are
on `main`. Not yet a running service.

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

- `packages/helios_core/` — SQLAlchemy 2.0 models and DB session/engine
  setup. One model so far: `Venue` (name, address — geocoding comes later).
- `apps/api/` — FastAPI service. `/healthz` (liveness) and `/readyz`
  (checks the database) so far.
- `alembic/` — migrations. `alembic upgrade head` builds the schema from
  scratch.
- `infra/` — `Dockerfile` (multi-stage, non-root) and `docker-compose.yml`
  (Postgres/PostGIS → one-shot migrate → API).
- Tooling: `ruff`, `mypy --strict`, `pytest`, `pre-commit`, all wired into
  CI as required status checks on `main`.

Everything else in the roadmap (parsing library, venue identity, scrapers,
the real API surface, deployment) is not yet built.

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

`make ci` mirrors CI exactly. Database-backed tests skip unless
`DATABASE_URL` points at a `*_test` database — with the stack up, use:

```bash
DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios \
  HELIOS_ALLOW_NONTEST_DB=1 make test
```

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
