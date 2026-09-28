# S6 Pi rebuild and gate record

**Status: closed — S6 is not yet merged and the owner has not rebuilt/audited the Pi.**

S2 (#24), S3 (#25), S4 (#26), and S14 (#35) are merged. S6 must be merged,
with its strict database tests, migration SQL review, schema check, and Docker
check passing, before this procedure. ADR-0011 and ADR-0012 were accepted under
the owner's delegated authority on 2026-09-27. S6b is not Pi-gating.

Local acceptance on 2026-09-27 passed strict `make ci` against a fresh disposable
PostgreSQL database: 957 passed, one expected parsing-package placeholder skip,
92% coverage. `alembic check` reported no drift; the Docker build and `/healthz`
smoke test passed. Review and merge remain pending.

This procedure is for the **owner on the Pi**. No agent ran it. It deliberately
removes pre-ADR data; all Subject IDs change. The old precision worksheet cannot
validate the rebuilt IDs. Preserve a backup first if you want that historical
data; it cannot be upgraded in place by the S6 migration.

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

5. Once that evidence passes, mark the Pi gate open and resume URL resolution:

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
| Pi URL resolution | S2/S3/S4/S6 merged; owner rebuild and new precision audit | Closed |
| Platform breadth | S6b collects platform menus alongside own-site menus | Optional for Pi |
| Phase 5 extraction | S7/S11/S12/S13 merged; lifecycle acceptance including completion, rebrand, replay, and readiness | Closed; S13 not implemented |

ADR-0012 acceptance authorizes the S13 design; it is not evidence that lifecycle
code exists. S13 must add its completion/coverage state, fresh URL reassignment,
monotonic replay, closure-origin protection, API filtering, and readiness tests.
