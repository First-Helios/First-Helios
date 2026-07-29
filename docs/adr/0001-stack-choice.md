# ADR-0001: Language, framework, and data stack choices

**Status:** Accepted
**Date:** 2026-07-29

## Context

Helios V2 is a from-scratch rebuild (see [ROADMAP.md](../../ROADMAP.md)).
Bootstrap tooling and an initial `Venue` model already landed on `main`
(PRs #1, #2) before this ADR existed, so this document ratifies decisions
already made in code rather than proposing new ones. Writing it now, before
Phase 1's schema work begins, gives later ADRs (schema layering, framework
choice, hosting) a documented baseline to build on instead of an implicit one.

The build is agent-driven with a human reviewer in the loop. That favors
strict, mechanically-enforced tooling (types, lint, migrations-as-code) over
conventions that rely on a reviewer remembering to check them by hand.

## Decision

- **Language:** Python 3.12, managed with `uv` (lockfile + install + venv).
- **Database:** PostgreSQL 16 via the `postgis/postgis` image — PostGIS
  ships in the same container so geospatial work (Phase 3+) doesn't require
  a separate migration later.
- **ORM:** SQLAlchemy 2.0 with typed `Mapped[...]` declarative models, one
  shared `Base` (`packages/helios_core/db/base.py`) so Alembic can
  introspect all models from a single `MetaData`.
- **Migrations:** Alembic, autogenerate-assisted but hand-reviewed before
  merge. No `Base.metadata.create_all()` outside test fixtures.
- **DB driver:** `psycopg` v3 (binary extra), explicitly normalized —
  `postgresql://` and `postgres://` URLs are rewritten to
  `postgresql+psycopg://` at both the app and Alembic entry points
  (`packages/helios_core/db/url.py`) so a bare `DATABASE_URL` from any host
  (Docker, a PaaS, a local shell) works without per-environment tweaks.
- **Package layout:** `packages/helios_core/` is the first-party package
  root. (The original roadmap draft sketched `packages/core/` — that name
  never shipped; the code that landed is the real name. See
  [Alternatives considered](#alternatives-considered).)
- **Linting/formatting:** ruff (lint + format), single tool for both.
- **Type checking:** mypy `--strict` for first-party code
  (`packages.helios_core.*`), relaxed for test fixtures.
- **Pre-commit:** ruff, mypy, Conventional Commits enforcement, standard
  hygiene hooks (trailing whitespace, large files, merge conflicts).
- **CI:** GitHub Actions — separate lint / typecheck / test / lockfile jobs,
  all required status checks on `main` (see repo branch protection).
- **Web framework (Phase 7+):** not yet chosen in code. Roadmap targets
  FastAPI for the API layer; this will be reaffirmed or revised in a
  dedicated ADR once `apps/api/` exists, since it's a bigger surface than a
  one-line ratification covers.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| `packages/core/` (original roadmap name) | Matches the roadmap doc as first drafted | Never implemented; renaming now touches every import in `session.py`, `url.py`, `base.py`, `models/*`, `alembic/env.py`, `mypy.ini`, both test files for a purely cosmetic gain |
| Django ORM instead of SQLAlchemy | Batteries-included, familiar to many | Couples the data layer to a full web framework before one's chosen (Phase 7 framework choice isn't made yet); SQLAlchemy 2.0's typed `Mapped` API already gives compile-time-checked models without that coupling |
| Plain psycopg / raw SQL instead of an ORM | No ORM overhead, full control | Migrations, typed models, and relationship handling would all be hand-rolled; not worth it for a schema this relationally complex (Phase 1's `deal_observation` → `deal_applicability` → `deal_materialization` fan-out) |
| Poetry or pip-tools instead of `uv` | More established | `uv` is materially faster and already fully wired into CI/pre-commit; switching now is pure churn with no functional gain |

## Consequences

- Package naming now matches reality; **ROADMAP.md's repo-layout diagram
  is updated in this same PR** to say `packages/helios_core/` instead of
  `packages/core/`, so the doc and code stop disagreeing.
- Future PRs adding a second package (the roadmap's `packages/parsing/`)
  should follow the same `helios_<name>` convention for consistency —
  `packages/helios_parsing/`. `mypy.ini` already has a stanza anticipating
  this name.
- PostGIS in the dev image means `alembic/env.py`'s `include_object` filter
  has to keep excluding reflected-but-unmanaged objects (Tiger geocoder
  tables, `spatial_ref_sys`, etc.) — already handled, documented in that
  file.
- Deferring the web framework decision means Phase 1 (schema) and Phase 2
  (parsing) work can proceed without blocking on it, but Phase 7 will need
  its own ADR before `apps/api/` is scaffolded.

## References

- PR #1 (`chore/bootstrap-tooling`), PR #2 (`feat/venue_initial_migration`)
- [ROADMAP.md §4](../../ROADMAP.md), [§3.3 Skills Inventory](../../ROADMAP.md)
