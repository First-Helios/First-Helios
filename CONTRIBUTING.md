# Contributing

This project is built primarily by AI agents (Claude Code or similar) with a
human reviewer. Agents read [CLAUDE.md](./CLAUDE.md) first: it has the working
rules, the stop-and-ask list, and the verification rules this document doesn't
repeat. Setup and current status are in [README.md](./README.md).

## Workflow

1. Branch off `main`: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, or
   `docs/<slug>`.
2. Keep each PR to one logical change. A bug fix doesn't need a drive-by
   refactor riding along.
3. Run `make ci` before opening the PR. For database changes, also run the
   database acceptance commands in
   [README.md](./README.md#database-acceptance).
4. Open a PR against `main` and fill out the
   [PR template](./.github/pull_request_template.md). If you skipped a check or
   are unsure a change is correct, say so under "Notes for reviewer".
5. The five CI checks must pass (see [CI](#ci)).
6. Read your own diff in the PR UI before merging. That is the review.
7. Merges are squashed, so the PR title becomes the commit on `main`.

## Local checks

| Target | Runs |
|---|---|
| `make install` | `uv sync`, then installs the pre-commit and commit-msg hooks |
| `make lint` | `pre-commit run --all-files`: whitespace/EOF/line-ending fixers, YAML/TOML checks, large-file (500 KB) and merge-conflict checks, stray-debugger check, `ruff --fix`, `ruff-format`, and `mypy .` |
| `make typecheck` | `mypy .` with `strict = True` over the whole repo ([mypy.ini](./mypy.ini); tests get a relaxed decorator rule) |
| `make test` | `pytest --cov=.` |
| `make ci` | `uv lock --check`, then lint, typecheck, test |

`make lint` rewrites files (ruff and the fixers); re-stage after it runs.
Optional database tests skip locally when PostgreSQL is unavailable or
`DATABASE_URL` doesn't name a disposable `*_test` database; a run with skipped
database tests is not database acceptance.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <description>

[optional body]
```

Common types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.

Commit messages are checked locally by the `conventional-pre-commit`
commit-msg hook (installed by `make install`), not in CI. CI checks only the PR
title, which becomes the squash commit, in the separate `PR title` workflow
([pr-title.yml](./.github/workflows/pr-title.yml)).

## CI

[ci.yml](./.github/workflows/ci.yml) runs five jobs on every PR and on pushes
to `main`. They are the required status checks and the only mechanical merge
gate:

```
Lint & format · Type check · Tests · Lockfile up to date · Docker image
```

- **Lint & format**: `pre-commit run --all-files`, the same as `make lint`.
- **Type check**: `mypy .`.
- **Tests**: pytest against a PostGIS service with `HELIOS_STRICT_DB_TESTS=1`
  (database tests fail instead of skipping) and a coverage floor, then
  `alembic upgrade head` and `alembic check` (models must match migrations).
- **Lockfile up to date**: `uv lock --check`.
- **Docker image**: builds `infra/Dockerfile` and smoke-tests `/healthz`.

## Review: what actually gates a merge

This is a solo project. GitHub doesn't allow approving your own PR, so branch
protection requires 0 approvals and the five CI checks are the gate. CLAUDE.md
explains the consequences.

[CODEOWNERS](./.github/CODEOWNERS) flags PRs that touch migrations, ORM models,
the model registry, `alembic/env.py`, workflows and `infra/`. With one
maintainer it can't block a merge. Treat the flag as a reason to read the diff
twice. If a second maintainer joins, turn on `require_code_owner_reviews` and
raise the approval count.

## ADRs, RFCs and plans

- **ADR** ([template](./docs/adr/0000-template.md)): one decision with a small,
  already-clear set of alternatives, such as naming, a library choice or a
  migration strategy. The index is in [README.md](./README.md#decisions).
- **RFC** ([template](./docs/rfc/0000-template.md)): a proposal where the shape
  of the solution is still open, or that spans several subsystems. Write it, get
  it reviewed, then implement.

ADRs live in `docs/adr/`, RFCs in `docs/rfc/`, plans in `docs/plans/`, each
numbered sequentially. A new ADR takes the next free number.

## License

By contributing, you agree your contribution is licensed under this repo's
[LICENSE](./LICENSE) (Business Source License 1.1).
