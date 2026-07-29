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
5. All five CI jobs must pass — they're required status checks and they are
   the *only* mechanical gate (see below).
6. Read your own diff in the PR UI before merging. This is the review.
7. Merge is squash-only; the head branch auto-deletes.

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

## Code review — what actually gates a merge

This is a solo project, and being honest about that matters more than
describing an aspirational process.

**GitHub does not allow approving your own pull request.** So a required
approval count of 1 is unsatisfiable here — it can only be cleared by an
admin bypass, and a bypass skips *everything*, CI included. Branch protection
therefore requires **0 approvals**, which makes the five CI checks a real,
satisfiable gate instead of a formality that gets waived on every merge:

```
Lint & format · Type check · Tests · Lockfile up to date · Docker image
```

`.github/CODEOWNERS` is kept as a **signal, not a gate**. It flags PRs
touching `alembic/versions/**` and `packages/**/db/models/**` in the UI —
the paths where a mistake is most expensive — but with a single maintainer it
cannot block a merge. When you see that flag, slow down and read the diff
properly. That's a discipline, not an enforcement.

**Copilot's review does not count as an approval.** It leaves `COMMENTED`,
never `APPROVED`. Useful as a second pair of eyes; not a gate.

If a second maintainer ever joins, turn on `require_code_owner_reviews` and
raise the approval count — at that point CODEOWNERS starts doing real work.

## License

By contributing, you agree your contribution is licensed under this repo's
[LICENSE](./LICENSE) (Business Source License 1.1).
