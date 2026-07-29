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
- `alembic/` — migrations. `alembic upgrade head` builds the schema from
  scratch.
- `infra/docker-compose.yml` — local Postgres (with PostGIS) for dev.
- Tooling: `ruff`, `mypy --strict`, `pytest`, `pre-commit`, all wired into
  CI as required status checks on `main`.

Everything else in the roadmap (parsing library, venue identity, scrapers,
API surface, Docker deploy) is not yet built.

## Local setup

```bash
git clone https://github.com/First-Helios/First-Helios.git
cd First-Helios

cp .env.example .env
docker compose -f infra/docker-compose.yml up -d   # Postgres

make install   # uv sync + pre-commit hooks
uv run alembic upgrade head
make ci        # lint + typecheck + test + lockfile check
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
