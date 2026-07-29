# CLAUDE.md

Instructions for agents (Claude Code or otherwise) working in this repo.

## What this is

Helios V2 — a from-scratch rebuild of a data intelligence platform for Austin,
TX. The prior version (`V1-Graveyard` branch) is reference material, not a
dependency: port patterns deliberately, don't drag over its accumulated debt.
See [ROADMAP.md](./ROADMAP.md) for the phased build plan and
[README.md](./README.md) for current state.

**This build is agent-driven with a human reviewer in the loop.** That
changes what "done" means: it's not just working code, it's code a human can
verify quickly. Prefer clarity and small diffs over cleverness.

## Ground truth

- `main` reflects what's actually built. If ROADMAP.md or README.md disagree
  with the code, the code wins — flag the doc drift, don't silently trust the
  doc.
- Don't invent tables, endpoints, or scale numbers that aren't in the current
  schema/code. V1's README described a mature system; V2 starts from zero.

## Before you write code

- Check [docs/adr/](./docs/adr/) for standing decisions (naming, schema
  layout, stack choices) before re-deciding them.
- For a genuinely new architectural choice (new dependency, schema pattern,
  service boundary) — write an ADR proposing it and **stop for human review**
  before implementing. Don't implement first and document after.
- For anything smaller than that, just build it.

## Verification — run before calling anything done

```bash
make ci        # lint + typecheck + test + lockfile check — same as CI
```

Never report a task complete without running this. If you can't run it
(no DB available, etc.), say so explicitly rather than claiming success.

- `make lint` — ruff check + format
- `make typecheck` — mypy --strict on `packages.helios_core.*`
- `make test` — pytest; DB-backed tests in `test/test_db.py` skip
  automatically unless `DATABASE_URL` points at a `*_test` database (or
  `HELIOS_ALLOW_NONTEST_DB=1` is set) — see that file's module docstring.
- `uv lock --check` — lockfile must match `pyproject.toml`

## Repo conventions

- Package root is `packages/helios_core/` (not `packages/core/` — the
  original roadmap draft used a different name; the code is what's real, see
  [ADR-0001](./docs/adr/0001-stack-choice.md)).
- All ORM models import `Base` from `packages/helios_core/db/base.py` and
  must be registered in `packages/helios_core/db/models/__init__.py` or
  Alembic autogenerate won't see them.
- Migrations are hand-reviewed, not blindly accepted from autogenerate —
  check the generated SQL, especially for anything touching an existing
  table with data in it.
- `packages/helios_core/db/session.py` builds `DATABASE_URL` from the
  environment; never hardcode a connection string outside that module.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (enforced by pre-commit's commit-msg hook).

## Stop and ask the human when

- A migration would drop or alter a column/table that already has a
  purpose (not a bare scaffold like the current `Venue` stub).
- Adding a new runtime dependency, especially anything with its own service
  (queue, cache, search index) — this affects the Docker/deploy story.
- The right design isn't obvious from ROADMAP.md/existing ADRs and two
  reasonable people could disagree.
- Anything touching auth, secrets, external API credentials, or
  `infra/`/deploy config.
- CODEOWNERS-protected paths always require human review before merge:
  `alembic/versions/**`, `packages/**/db/models/**`.

## Don't

- Don't use `Base.metadata.create_all()` outside of test fixtures — schema
  changes go through Alembic migrations only.
- Don't add abstractions, config flags, or "for later" scaffolding beyond
  what the current task needs.
- Don't skip pre-commit hooks or CI checks to get a merge through.
