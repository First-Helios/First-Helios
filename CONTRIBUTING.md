# Contributing

This project is built primarily by AI agents (Claude Code or similar) with a
human reviewer. If you're an agent working in this repo, read
[CLAUDE.md](./CLAUDE.md) first — it has agent-specific instructions this
document doesn't repeat.

## Workflow

1. Branch off `main`: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, or
   `docs/<slug>`.
2. Make your change. Keep PRs scoped to one logical change — a bug fix
   doesn't need a drive-by refactor riding along.
3. Run `make ci` locally before opening the PR. It runs the same lint,
   typecheck, test, and lockfile checks CI does.
4. Open a PR against `main`. Fill out the PR template.
5. All four CI jobs must pass (they're required status checks) and at least
   one review is required before merge.
6. Merge is squash-only; the head branch auto-deletes.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), enforced by a
pre-commit hook on the commit message:

```
<type>(<optional scope>): <description>

[optional body]
```

Common types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.

## Local setup

```bash
make install   # uv sync + pre-commit hooks
make lint      # ruff check + format
make typecheck # mypy --strict
make test      # pytest
make ci        # all of the above, plus lockfile check — mirrors CI exactly
```

Database-backed tests (`test/test_db.py`) need a reachable Postgres with a
`*_test`-named database — see that file's docstring, or the `infra/`
docker-compose service, once Docker support lands.

## When to write an ADR vs. an RFC

- **ADR** ([template](./docs/adr/0000-template.md)) — a single decision with
  a small, already-clear set of alternatives. Naming, a library choice, a
  migration strategy.
- **RFC** ([template](./docs/rfc/0000-template.md)) — a proposal where the
  shape of the solution itself is still open, or that spans multiple
  subsystems. Write one, get it reviewed, *then* implement.

Both live in `docs/adr/` and `docs/rfc/` respectively, numbered sequentially.

## Code review

- CODEOWNERS requires a human review on migrations (`alembic/versions/**`)
  and ORM models (`packages/**/db/models/**`) — these are the highest-cost
  mistakes to reverse once merged.
- Everything else can be agent-authored and agent-reviewed, gated by CI.

## License

By contributing, you agree your contribution is licensed under this repo's
[LICENSE](./LICENSE) (Business Source License 1.1).
