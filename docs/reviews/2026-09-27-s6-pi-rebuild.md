# S6 Pi rebuild and gate record

**Status (2026-09-28): rebuild complete. The precision audit was adjudicated under owner
delegation and fails both bars; the Pi gate is now split into 1a (location quality) and
1b (URL-resolution readiness), both closed. See the
[checklist's gate criteria](2026-09-22-remediation-checklist.md) (S6b block).**

S2 (#24), S3 (#25), S4 (#26), S14 (#35), and S6 (#42) are merged. The owner
explicitly authorized the agent to perform the Pi rebuild. It completed on
2026-09-28 at commit `3faae15e1cd452bcc00abfcd53b951ba3f46ae89` and migration
`c91a6f02de73`. See [the execution record](2026-09-28-pi-rebuild-results.md)
for backups, deployment details, ingestion counts, and audit status.
S6b is not Pi-gating.

Local acceptance passed strict `make ci` on a fresh disposable database:
957 passed, one expected parsing-package placeholder skip, 92% coverage.
PR and merged-main CI passed. The Pi build, migrations, `alembic check`,
`/healthz`, and `/readyz` passed too.

The procedure below is a template for a future rebuild, not an instruction to
repeat the completed operation. It removes active pre-ADR data; old Subject IDs
and precision worksheets cannot validate the rebuilt database. In this run,
the previous stack used `infra_postgres_data`: that volume was retained offline
and a fresh `helios_postgres_data` was created. The old checkout was a source
snapshot, so the exact merged commit was deployed with `git archive` instead
of `git pull`. Do not assume the template's volume or checkout layout without
inspecting the actual host.

## Rebuild the local Compose database

Use the repository root on the Pi. This procedure applies to the Compose-owned
Postgres database only. If `HELIOS_COMPOSE_DATABASE_URL` points to an external
database or the Compose project/volume has been overridden, reconcile that
configuration before deleting anything. The checked-in project is `helios`,
and its Postgres volume is `helios_postgres_data`. The `var/` cache is a host
bind mount and is not the database volume.

1. Stop any scheduler or discovery process. Update the checkout to the merged
   S6 commit, then stop the stack and inspect the intended volume:

   ```bash
   git pull --ff-only
   docker compose -f infra/docker-compose.yml --env-file .env down
   docker volume inspect helios_postgres_data
   ```

2. After verifying the volume belongs to this project, remove that volume and
   rebuild/start the stack:

   ```bash
   docker volume rm helios_postgres_data
   docker compose -f infra/docker-compose.yml --env-file .env up -d --build
   docker compose -f infra/docker-compose.yml --env-file .env ps -a
   docker compose -f infra/docker-compose.yml --env-file .env logs migrate
   ```

   The one-shot `migrate` service must exit successfully at revision
   `c91a6f02de73` (or a reviewed descendant). The API waits for it. Do not disable
   Bronze triggers or bypass the pre-ADR migration precondition.

3. Run discovery using the intended full-metro release. Substitute the actual
   published release in the example; retain the release date in the path:

   ```bash
   docker compose -f infra/docker-compose.yml --env-file .env exec api \
     python -m apps.discovery \
     --release 's3://overturemaps-us-west-2/release/YYYY-MM-DD.0/theme=places/type=place/*'
   ```

4. Re-export venues and repeat the confirmed precision audit using the
   [Phase 4 audit procedure](../retro/2026-09-21-phase-4.md#reproduce).
   If the anchor changes, see that document's export SQL and audit commands.
   Record the merged commit, release, new sample/worksheet, duplicate rate
   (below 2%), wrong-geocode rate (below 1%), and website coverage. Old IDs and
   old scores do not satisfy this step.

5. *(Superseded 2026-09-28: URL resolution is gated by Pi gate 1b, menu-URL
   precision, not by this audit. Run the command below only after 1b opens.)*
   Once that evidence passes, mark the Pi gate open and resume URL resolution:

   ```bash
   docker compose -f infra/docker-compose.yml --env-file .env exec api \
     python -m apps.discovery.resolve_urls --config config/sources.yaml
   ```

   `--limit` still counts work; failed/skipped site attempts now stay in Bronze
   and suppress another attempt for 20 days. A registry override can still
   provide a menu without crawling. Registry files used for provenance must
   live inside the checkout.

## Remaining gates

| Gate | Required evidence | Current state |
|---|---|---|
| Pi gate 1a: location quality | Correction plan; ADR-0014 location overrides; passing fresh-sample re-audit | Closed: adjudicated audit fails both bars (2026-09-28) |
| Pi gate 1b: URL resolution | Menu-URL re-verification (ADR-0015) and/or page classifier; platform content check; chain-link decision | Closed: ADR-0015 proposed |
| Platform breadth | S6b collects platform menus alongside own-site menus | Optional for Pi |
| Phase 5 extraction | S7/S11/S12/S13 merged; lifecycle acceptance including completion, rebrand, replay, and readiness | Gate passed 2026-09-28; code waits for proposed ADR-0013 |

ADR-0012 acceptance authorizes the S13 design; it is not evidence that lifecycle
code exists. S13 must add its completion/coverage state, fresh URL reassignment,
monotonic replay, closure-origin protection, API filtering, and readiness tests.
