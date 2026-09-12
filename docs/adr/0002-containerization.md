# ADR-0002: Containerization, and pulling it forward from Phase 8

**Status:** Accepted
**Date:** 2026-07-29

## Context

[ROADMAP.md §5](../../ROADMAP.md) sequences Docker into Phase 8, alongside
systemd units, Prometheus, and backups. That ordering assumed a human
learning the codebase first and shipping late.

Two things changed:

1. **The build is agent-driven** (see [CLAUDE.md](../../CLAUDE.md)). Agents
   need a reproducible environment *now*, because "the agent says tests
   pass" only means something if it maps to the same environment CI and prod
   use. Without it, drift is invisible until a human catches it by hand.
2. **This is a live web service**, not a batch pipeline. A container needs a
   long-running process to be meaningful, which is why
   [PR #4](https://github.com/First-Helios/First-Helios/pull/4) added
   `apps/api/main.py` with `/healthz` and `/readyz` first.

A third thing forced the issue: `infra/docker-compose.yml` had specified
`postgis/postgis:16-3.4` since PR #1, and **that image cannot run on the
Orange Pi at all**. The official PostGIS image is amd64-only by design —
their README states "Supported architecture: `amd64` (x86-64)" — so it fails
with `exec format error` on the ARM64/RK3588 staging host this project
targets. The bug sat unnoticed for five weeks because nobody had run
`docker compose up` on the Pi.

## Decision

**Pull basic containerization forward to now; leave ops hardening in Phase 8.**

In scope now:

- `infra/Dockerfile` — multi-stage (`python:3.12-slim-bookworm` + pinned
  `uv` 0.12.0), non-root runtime user, single image with the API as default
  `CMD` and future scraper workers overriding it.
- `infra/docker-compose.yml` — `postgres` → one-shot `migrate` → `api`, wired
  with `service_healthy` / `service_completed_successfully` conditions.
- `make build` / `dev` / `dev-down` / `dev-logs` / `migrate`.
- A `Docker image` CI job that builds the image and smoke-tests `/healthz`.

Explicitly **not** in scope now (stays Phase 8): systemd units, Prometheus,
backup/restore, image registry, promotion flow, multi-arch publishing.

**Database image: `imresamu/postgis:16-3.4`.** This is a fork of the official
`postgis/docker-postgis` build system by that repo's second-highest
contributor (104 commits, vs. 115 for the lead), publishing multi-arch tags
the official repo declines to. Verified on the Orange Pi: boots natively on
arm64, `alembic upgrade head` succeeds, full test suite passes against it.
The same image is now used in CI so dev, staging, and CI run identical
Postgres.

**Migrations never run on container start.** `alembic upgrade head` is a
separate one-shot `migrate` service. Running it from the API entrypoint
races when more than one replica boots at once — a real hazard for a live
service, and cheap to avoid now rather than after it corrupts something.

**Build architecture stays implicit for now.** The Dockerfile is
arch-agnostic (both `python:3.12-slim` and `uv` publish arm64 and amd64), so
it builds natively wherever it runs — arm64 on the Pi, amd64 in CI. The
*publishing* question (multi-arch buildx vs. arm64-only) is deferred to
ADR-0007 in Phase 8, when there's actually a registry and a chosen prod host.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Keep Docker in Phase 8 | Follows the roadmap as written | Leaves agent work unverifiable against a real environment for months, and leaves the arm64 compose bug in place |
| Build our own PostGIS image on official `postgres:16` | Maximal trust in the base, full control of the postgis version | ~6 lines plus ongoing responsibility for tracking postgis releases; adds a build step to `docker compose up` for a dev/staging-only concern |
| Drop PostGIS, use official `postgres:16` | Official multi-arch image, no third-party trust question; no code uses PostGIS until Phase 3 | Dev/prod parity gap once geospatial lands, and `alembic/env.py`'s PostGIS-table filter would go untested until Phase 3 |
| Run the amd64 PostGIS image under QEMU emulation on the Pi | No image change | Substantially slower, and papers over an architecture mismatch that prod would hit too if prod is ARM |
| Do the full Phase 8 scope now | One less migration later | Systemd/Prometheus/backups are useless before there's anything to operate; large diff, little value |

## Consequences

- `make dev` now brings up a working stack on the Orange Pi, which was
  impossible before. Agents (and humans) can verify against a real database
  instead of skipping DB-backed tests.
- Adds a fifth CI job (`Docker image`). **It is not yet a required status
  check** — the context name doesn't exist on `main` until this merges. Add
  it to branch protection afterward, or the gate has a hole.
- Pins us to a third-party image for Postgres. Mitigated by the provenance
  above and by the roadmap's own plan
  ([§4.2](../../ROADMAP.md#42-environments-dev--staging--prod)) to run prod
  Postgres **on the host**, not in compose — so the blast radius is dev,
  staging, and CI. **Revisit if** the image goes stale (it self-labels
  "(test)"), or when Phase 8 picks a prod host.
- At acceptance, this renumbered the roadmap's then-planned ADRs. Planned
  identifiers have moved again as intervening ADRs were written; the current
  ROADMAP ADR ledger is authoritative.

## References

- Official image's amd64-only statement:
  https://github.com/postgis/docker-postgis (README, "Versions")
- Multi-arch fork: https://github.com/ImreSamu/docker-postgis
- PR #4 — `/healthz`, `/readyz`, and the lazy-config refactor this builds on
