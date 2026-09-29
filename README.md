# Helios V2

A trustworthy, queryable price index of food in Austin: restaurant menus and
what they actually cost, across the Austin / Round Rock metro. V2 is a
from-scratch rebuild; the scope was set menus-first by
[RFC-0001](./docs/rfc/0001-menu-pricing-first.md). It is built by AI agents
with a human reviewer in the loop: see [CLAUDE.md](./CLAUDE.md) for agent
instructions and [CONTRIBUTING.md](./CONTRIBUTING.md) for the PR workflow.

## Status

This section is the single current-status page. Other docs link here.

**Built** (schemas are owned per module; see
[`packages/helios_core/db/base.py`](./packages/helios_core/db/base.py)):

- **Bronze provenance**: `packages/helios_core/provenance/`. Sources, endpoints,
  captures, source records and versions, and Evidence (`bronze` schema);
  replay-safe observation persistence.
- **Identity**: `packages/helios_core/identity/`. Subject, Place, Organization,
  Establishment; append-only resolution and Subject-change lineage;
  deterministic external-key/URL resolution and readiness (`identity` schema).
- **Menu**: `packages/helios_core/domains/menu/`. Immutable Menu snapshots and
  their writer, plus the pure current/history price selector
  (`menu` schema, ADR-0005). Nothing writes menus in production yet.
- **Gold read model**: `packages/helios_core/gold/`. `gold.current_menu`, a
  rebuildable projection of the Menu selector, with bounded per-scope and
  full-catalog refresh (ADR-0006).
- **Read API**: `apps/api/`. FastAPI, conventions per ADR-0008:
  - `GET /healthz`: liveness, no database.
  - `GET /readyz`: readiness, checks the database.
  - `GET /v1/venues`: current venues, cursor-paginated (`limit`, `cursor`).
  - `GET /v1/venues/{venue_id}`: one current venue.
- **Overture discovery**: `apps/discovery/` (`__main__.py`, `overture.py`,
  `pipeline.py`). Seeds food venues from Overture Places into Bronze and
  Identity, with conservative dedupe and Nominatim gap-fill
  (`packages/helios_core/geo.py`) (ADR-0009).
- **Website and menu-URL resolution**: `apps/discovery/resolve_urls.py`,
  `url_pipeline.py`, `menu_url.py`, `web_client.py`, `registry.py`
  (+ `config/sources.yaml`). Bronze-first, robots-aware, rate-limited
  (ADR-0010, ADR-0011). Saved menu URLs record their page verifier and are
  re-verified when it changes or after 90 days; one that fails is re-discovered
  or withdrawn to `needs_review`. Platform pages pass the same page check, and a
  chain homepage's platform links are kept only for the location whose address
  the page shows (ADR-0015). The verifier is the ADR-0013 page classifier
  `classifier-v2` (`apps/menu_pipeline/classifier.py`, weights
  `config/page_classifier_v2.json`, model files pinned in `config/models.yaml`;
  evaluations: [v1](./docs/reviews/2026-09-29-classifier-v1-evaluation.md),
  [v2 and rendering](./docs/reviews/2026-09-29-s6f-render-measurement.md)); it runs
  in the `worker` image target. `--render` renders platform pages the static fetch
  can't verify and JavaScript-only own-site pages with headed Chromium under Xvfb
  (`apps/menu_pipeline/render.py`; ADR-0013 Amendments 1–2); off for Pi runs until
  the Pi measurement is recorded.
- **Venue lifecycle**: `apps/discovery/lifecycle.py`, `apps/discovery/models.py`.
  Release completion evidence and completion-gated closure, run at the end of
  each discovery run (ADR-0012). Limits: closure needs a completed baseline plus
  two linked completed releases (none recorded yet; completion is never
  back-filled); completion trusts iterator exhaustion, not upstream
  completeness; not yet run on the Pi.
- **Location overrides**: `apps/discovery/location_overrides.py`,
  `config/location_overrides.yaml` (ADR-0014). Reviewed coordinate/address
  corrections keyed by GERS id, persisted to Bronze, applied in place by minting,
  dedupe and lifecycle projection while the Overture point is unchanged; stale
  entries are ignored and reported. One entry (Lali Son); not yet run on the Pi.
- **Identity corrections**: `apps/discovery/corrections.py`,
  `config/identity_corrections.yaml` (S6e). Reviewed duplicate merges and
  non-venue retirements keyed by GERS id, applied idempotently through the
  evented Identity commands with a human Adjudication per entry (`python -m
  apps.discovery.corrections --actor <reviewer>`). 23 detector-pair merges
  committed; the sampled merges and retirements need GERS ids from the Pi. Not
  yet run on the Pi.
- **Precision audit**: `apps/discovery/audit.py`. DB-free duplicate and geocode
  audit over a venue export, with a hand-labeled worksheet, plus a corpus-wide
  twin search (misplaced twins, location-label records).
- **Migrations**: `alembic/`. `alembic upgrade head` builds the schema from
  scratch.

**Not built yet** (phases in [ROADMAP.md](./ROADMAP.md)):

- Phase 5 menu extraction (LLM extraction, validator). Waits on
  [ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md), which is Proposed except
  its page classifier (accepted 2026-09-29; the ADR-0015 verifier, now
  `classifier-v2`) and discovery's page rendering (S6f).
- The Gold price index: target shape accepted in
  [ADR-0007](./docs/adr/0007-gold-price-index-projection.md); no model,
  migration or code.
- Price-index API endpoints, the staging deploy (ADR-0008 Unit B), production,
  and the deals layer.

## Gates

- **Phase 5 gate: passed 2026-09-28.** S7 #28, S11 #33, S12 #34 and S13 #45
  merged; main CI run
  [36508316467](https://github.com/First-Helios/First-Helios/actions/runs/36508316467)
  green with strict DB tests. Phase 5 code still waits on ADR-0013 (Proposed).
  Owner decision G.b: the spike's pipeline replaces the Scrapy-vs-Crawlee
  question.
- **Pi gate 1a, Phase 4 location quality: closed.** The 2026-09-28 adjudication
  of the 100-row precision sample found 4 wrong geocodes and 6 sampled venues
  with a confirmed duplicate, so both ROADMAP Phase 4 bars fail (< 1% wrong
  geocodes, < 2% duplicates). Does not gate `resolve_urls`. Opens when all hold:
  - [x] a correction plan is committed:
    [location correction plan](./docs/reviews/2026-09-28-location-correction-plan.md)
    (S6c), with the corpus-wide twin search and the `audit.street_key` fix;
  - [x] ADR-0014 is accepted and implemented (S6c; 3 override entries still need
    a qualifying basis);
  - [ ] corrections are applied on the Pi in an owner-authorized run (no raw
    SQL; overrides via a discovery re-run, merges and retirements via the S6e
    corrections applier; steps in the plan's runbook). Before it,
    `config/identity_corrections.yaml` needs its 11 pending entries (6 sampled
    merges, 5 retirements) filled with GERS ids that only the Pi database has
    (the plan's "Pending entries" table; `--show-gers`);
  - [ ] a fresh-sample re-audit passes: new seed, 100 hand-labeled rows plus a
    regression check of the corrected cohort; 0 confirmed wrong geocodes, at most
    1 sampled venue with a confirmed duplicate, at most 5 unresolved rows per
    measure, worst case reported, denominator never changed.

  Label criteria for the re-audit (from the 2026-09-28 adjudication; unresolved
  never counts as correct):
  - *Geocode ok:* address corroborated (business, municipal or marketplace
    evidence) and an official pin or independent geocoder match within 150 m.
  - *Geocode wrong:* address corroborated, no evidence of a move, saved point
    more than 1,000 m from an official pin or geocoder match.
  - *Duplicate:* another current record for the same outlet at the same time
    (legal, trading and location-label names count); proximity alone never
    decides.
  - *Twin search, every sampled row:* same house-number street line, or name
    similarity ≥ 0.6 within 300 m; same fingerprint within 1 km; same address at
    any distance.
  - *Unresolved:* 150–1,000 m on interpolating geocoders only, no geocode,
    uncorroborated venue, address conflict, rename-vs-succession pairs (a
    succession is a new business, ADR-0012), virtual-brand granularity.
  - Corrected-cohort input: `reviewed.json` in the
    [removed precision-review data](https://github.com/First-Helios/First-Helios/tree/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/data/2026-09-28-precision-review)
    ([docs/HISTORY.md](./docs/HISTORY.md)).
- **Pi gate 1b, URL-resolution readiness: closed.** Gates the first Pi
  `resolve_urls` run; independent of 1a (URL records are keyed by GERS id and
  the URL path reads no coordinate, so location errors can't corrupt them).
  Opens when all hold:
  - [x] ADR-0015 accepted 2026-09-29 with the ADR-0013 page classifier as its
    verifier; re-verification, withdrawal, the platform content check and the
    chain guard implemented (S6d part 1, #51); `classifier-v1` implemented and
    merged with strict CI (S6d part 2, #52); platform-page rendering implemented
    (S6f, #54; `classifier-v2` accepts rendered platform menus);
  - [ ] the render's Pi time and memory recorded (the owner runs the
    [Pi measurement](./docs/reviews/2026-09-29-s6f-render-measurement.md#pi-measurement-owner-run);
    a laptop run is recorded there). Until then Pi runs leave `--render` off;
  - [ ] the owner authorizes the run. After it: record website/menu-URL
    coverage (the last Phase 4 "done when" item) and a hand-checked precision
    sample of saved menu URLs.
- **Code review remediation R01–R117: complete 2026-09-29 (S17).** Every
  finding was fixed or accepted/deferred by the owner; deferrals and their
  triggers are in [ROADMAP §7](./ROADMAP.md#7-open-questions). Close-out note at
  the top of the [review](./docs/reviews/2026-09-22-full-codebase-review.md); the
  retired trackers are listed in [docs/HISTORY.md](./docs/HISTORY.md).

## Quick start / How to run

### Local setup

Run Postgres/PostGIS, migrations and the API in Docker
([`infra/docker-compose.yml`](./infra/docker-compose.yml): `postgres`, a one-shot
`migrate`, then `api` on `127.0.0.1:8000`):

```bash
git clone https://github.com/First-Helios/First-Helios.git
cd First-Helios
cp .env.example .env
make dev                      # build + start postgres -> migrate -> api
curl localhost:8000/healthz   # {"status":"ok"}
curl localhost:8000/readyz    # {"status":"ok"} once Postgres is up
```

`make dev-logs` tails the stack, `make dev-down` stops it, `make migrate` re-runs
the one-shot migration. `.env` is read only by these Compose targets
(`--env-file .env`), and the containers take their database from
`HELIOS_COMPOSE_DATABASE_URL`. Everything else (the app, Alembic, pytest, the
CLIs) reads `DATABASE_URL` from the process environment only and never loads
`.env`. `DATABASE_URL` has no default: commands that need a database fail and
database tests skip when it is unset
([`packages/helios_core/config.py`](./packages/helios_core/config.py)).

### Develop

```bash
make install     # uv sync + pre-commit and commit-msg hooks
make lint        # pre-commit on all files (hygiene hooks, ruff, ruff-format, mypy)
make typecheck   # mypy .
make test        # pytest with coverage
make ci          # lockcheck + lint + typecheck + test (local subset of CI)
make build       # build the API image on its own
```

Run migrations or the API outside Docker by exporting `DATABASE_URL` first:

```bash
export DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios
uv run alembic upgrade head
uv run uvicorn apps.api.main:app
uv run python -m apps.api.export_openapi   # after an intentional API change
```

### Discovery CLIs

Discovery and `resolve_urls` make network calls and write to the database
`DATABASE_URL` names; the audit reads a venue export and needs no database.
None of them run in CI. On the Pi they run inside the API container
(`docker compose exec api ...`), except `resolve_urls`: its page verifier is the
ADR-0013 page classifier, which needs the `menu` extra and verified model files,
so it runs in the worker image
(`docker compose --profile menu run --rm worker python -m ...`).

```bash
# Seed venues from an Overture release, then record completion and run lifecycle
uv run python -m apps.discovery [--release <overture-parquet-glob>] \
    [--expected-predecessor <prior-release-path>] [--no-geocode]

# Page-classifier model files into var/models/, checked against config/models.yaml
uv run --extra menu python -m apps.menu_pipeline.models download

# Resolve website + menu URL (Pi gate 1b must be open before a Pi run)
uv run --extra menu python -m apps.discovery.resolve_urls --config config/sources.yaml [--limit N]

# Precision audit over a venue export (no database)
uv run python -m apps.discovery.audit --export <venue-export.json> [--geocode-check]
```

Each takes `--help` for the full flag list. The audit's venue export:

```bash
psql -At -f - <<'SQL' > venues.json
SELECT json_agg(row_to_json(t)) FROM (
  SELECT e.subject_id, o.canonical_name AS name, o.name_fingerprint AS fingerprint,
         p.latitude::float8 AS lat, p.longitude::float8 AS lon, p.address
  FROM identity.establishment e
  JOIN identity.subject_currentness sc ON sc.subject_id = e.subject_id AND sc.is_current
  JOIN identity.organization o ON o.subject_id = e.organization_subject_id
  JOIN identity.place p ON p.subject_id = e.place_subject_id
) t;
SQL
```

### Staging (Pi)

- An Orange Pi 5 Plus (ARM64) on the owner's LAN runs the `helios` Compose
  stack from `infra/docker-compose.yml` (`postgres`, one-shot `migrate`, `api`),
  bound to 127.0.0.1. Discovery CLIs run inside the API container:
  `docker compose -f infra/docker-compose.yml --env-file .env exec api python -m apps.discovery ...`.
- The deploy directory is a source snapshot of one merged commit (`git archive`),
  with a `DEPLOYED_COMMIT` file recording its SHA; `var/` is a host bind mount
  (caches, audit packets under `var/audits/`).
- Database volume `helios_postgres_data`. The pre-ADR-0011 volume
  `infra_postgres_data` is kept offline: never attach it to the current image.
  Backups are custom-format `pg_dump` files under `~/helios-backups/<run>/`; no
  restore has been rehearsed.
- Rebuild outline: stop runs and back up; deploy the commit; `down`; remove
  `helios_postgres_data` only after confirming it belongs to this stack;
  `up -d --build` (`migrate` exits 0 at head); check `alembic check`, `/healthz`,
  `/readyz`; run discovery (`--expected-predecessor` once a completed release
  exists); re-export and re-audit.
- Last rebuild: 2026-09-28 at `3faae15` (migration `c91a6f02de73`), before the
  S13 lifecycle migration; no completed discovery baseline yet.

### Database acceptance

A local `make ci` with skipped database tests is not database acceptance. Use a
separately provisioned, disposable PostgreSQL `*_test` database (never the
Compose dev database or application data):

```bash
HELIOS_STRICT_DB_TESTS=1 DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios_test make ci
DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios_test uv run alembic check
```

CI runs the same strict tests and `alembic check`. See
[CLAUDE.md](./CLAUDE.md#verification--run-before-calling-anything-done) for the
rules.

## Repository layout

```
alembic/                migrations (hand-reviewed)
apps/
  api/                  FastAPI read API and OpenAPI snapshot
  discovery/            Overture discovery, URL resolution, lifecycle, audit
  menu_pipeline/        page classifier runtime, model files, training script
config/sources.yaml     manual website / menu-URL registry
config/models.yaml      pinned model files (sha256, size, licence)
config/page_classifier_v1.json  page classifier weights
docs/
  adr/                  architecture decisions (index below)
  rfc/  plans/          proposals and build plans
  reviews/              review trackers and migration SQL artifacts
  spikes/menu-model/    menu-model spike (ADR-0013 evidence)
  diagrams/             ERD and context diagrams
infra/                  Dockerfile and docker-compose.yml
packages/helios_core/
  config.py             settings (DATABASE_URL, CORS)
  db/                   Base, schema ownership, model registry, sessions
  provenance/           Bronze
  identity/             Identity
  domains/menu/         Menu
  gold/                 Gold read models
  geo.py                Nominatim client
packages/helios_parsing/  pure page parsing: segmentation, price tokens, classifier features
test/                   pytest suite
```

## Decisions

The ADR index. Status is the short form of each ADR's Status line.

| ADR | Title | Status |
|---|---|---|
| [0001](./docs/adr/0001-stack-choice.md) | Language, framework, and data stack choices | Accepted |
| [0002](./docs/adr/0002-containerization.md) | Containerization, and pulling it forward from Phase 8 | Accepted |
| [0003](./docs/adr/0003-three-layer-schema.md) | Three-layer schema (raw / canonical / mart) | Superseded by ADR-0004 |
| [0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md) | Modular monolith, lifecycle layers, and shared identity | Accepted |
| [0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md) | Immutable Menu snapshots and scoped selection | Accepted |
| [0006](./docs/adr/0006-gold-menu-read-models.md) | Gold menu read models: shape, materialization, and refresh | Accepted |
| [0007](./docs/adr/0007-gold-price-index-projection.md) | Gold price-index projection: grain, aggregation, and its blocking dependencies | Accepted (target shape; implementation deferred) |
| [0008](./docs/adr/0008-read-api-conventions.md) | Read-API framework and conventions (First Light) | Accepted |
| [0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md) | Venue discovery: source, ingestion, dedupe/minting, and schedule | Accepted |
| [0010](./docs/adr/0010-website-and-menu-url-resolution.md) | Website & menu-URL resolution | Accepted |
| [0011](./docs/adr/0011-provenance-endpoints-vs-identity-match-keys.md) | Provenance endpoints vs identity match keys | Accepted |
| [0012](./docs/adr/0012-venue-lifecycle.md) | Venue lifecycle: re-observation, closure, re-homing, and readiness | Accepted |
| [0013](./docs/adr/0013-phase5-menu-pipeline.md) | Phase 5 menu pipeline: page classifier, on-device LLM extraction, validator | Proposed (page classifier accepted 2026-09-29) |
| [0014](./docs/adr/0014-location-overrides.md) | Location overrides: durable, evidence-backed coordinate corrections | Accepted |
| [0015](./docs/adr/0015-menu-url-reverification.md) | Menu-URL precision before the first Pi run: re-verify saved menu URLs | Accepted |

Also: [RFC-0001](./docs/rfc/0001-menu-pricing-first.md) (menu-and-pricing-first
scope) and the
[Step 5 menu schema proposal](./docs/plans/0002-step-5-menu-schema-proposal.md)
(normative detail for ADR-0005). New ADRs start from the
[template](./docs/adr/0000-template.md).

## Docs

- [ROADMAP.md](./ROADMAP.md): phases, plans, and why.
- [CONTRIBUTING.md](./CONTRIBUTING.md): workflow, commits, CI checks.
- [CLAUDE.md](./CLAUDE.md): agent instructions and verification rules.
- [LEARNING_GUIDE.md](./LEARNING_GUIDE.md): module-by-module curriculum for
  reviewing the work.
- [docs/HISTORY.md](./docs/HISTORY.md): index of removed historical docs.
- [docs/spikes/menu-model/README.md](./docs/spikes/menu-model/README.md): the
  menu-model spike (ADR-0013 evidence).
- [Full codebase review](./docs/reviews/2026-09-22-full-codebase-review.md):
  the 2026-09-22 findings R01–R117 (remediation complete).

The V1 code lives on the
[`V1-Graveyard`](https://github.com/First-Helios/First-Helios/tree/V1-Graveyard)
branch: reference material, not a dependency of `main`.

## License

[Business Source License 1.1](./LICENSE): source-visible, non-commercial use
only until the Change Date, after which it converts to Apache License 2.0. See
the LICENSE file for the current parameters, or contact
abdullahhijazi3@gmail.com for a commercial license.
