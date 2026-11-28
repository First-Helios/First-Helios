#!/usr/bin/env bash
# Recover a host that has no public database from a night's backup dumps (ADR-0031 D2, Q8):
# drill B, or a real loss of the Pi.
#   bash infra/pipeline-host/recover.sh <helios.dump> <helios_work.dump>
# Run on the Pi from the deploy directory, with the Compose `postgres` service up and the API
# stopped. Public changes only through swap.sh, or this script on a host with no public
# database. So it refuses unless `helios` is missing or has never been migrated (no
# alembic_version). The image's initdb creates an empty `helios`, so "missing" alone can't be
# the test. In order:
#   1. takes var/pipeline-host/db.lock (lib.sh db_lock);
#   2. restores <helios.dump> into helios_next, and <helios_work.dump> into helios_work. Both go
#      through restore.sh, so each gets the admission-fence reset. The master gets its own dump,
#      not public's: between a run and its swap, collected data lives only in the master;
#   3. drops the empty `helios` and renames helios_next -> helios;
#   4. writes MASTER (host pi, DEPLOYED_COMMIT, the master dump's sha256);
#   5. prints what backup_manifest compares: alembic, current_menu rows. The full check is
#      `backup_manifest --db helios --expect <manifest.json>` (infra/backup/README.md).
set -euo pipefail
USAGE="usage: recover.sh <helios.dump> <helios_work.dump>"
PUBLIC_DUMP=$(realpath "${1:?$USAGE}")
MASTER_DUMP=$(realpath "${2:?$USAGE}")
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
HOST=pi
[ -f "$PUBLIC_DUMP" ] || die "no such dump: $PUBLIC_DUMP"
[ -f "$MASTER_DUMP" ] || die "no such dump: $MASTER_DUMP"
[ -f DEPLOYED_COMMIT ] || die "no DEPLOYED_COMMIT in $(pwd): deploy the manifest's commit first"
COMMIT=$(tr -d '[:space:]' <DEPLOYED_COMMIT)

exists() { [ "$(sql postgres "select count(*) from pg_database where datname = '$1'")" = 1 ]; }
# A database that has ever been migrated has alembic_version; initdb's empty `helios` has not.
migrated() { exists "$1" && [ "$(sql "$1" "select count(*) from pg_class where relname = 'alembic_version'")" != 0 ]; }
refuse_live() {
  if migrated helios; then
    die "helios holds a migrated database: this host has a public database, so use swap.sh"
  fi
}

db_lock
refuse_live
log "recover: public from $PUBLIC_DUMP, master from $MASTER_DUMP, commit $COMMIT"
start=$(date +%s)
bash infra/pipeline-host/restore.sh pi helios_next "$PUBLIC_DUMP"
bash infra/pipeline-host/restore.sh pi helios_work "$MASTER_DUMP"

refuse_live # nothing else may have created it meanwhile; checked again just before the drop
"${DC[@]}" stop api
pg postgres psql -X -v ON_ERROR_STOP=1 -q \
  -c "DROP DATABASE IF EXISTS helios WITH (FORCE);" \
  -c "ALTER DATABASE helios_next RENAME TO helios;"
log "helios_next -> helios in $(($(date +%s) - start)) s since start"

bash infra/pipeline-host/mark-master.sh pi "$COMMIT" "$(sha256sum "$MASTER_DUMP" | cut -d' ' -f1)"
log "recovered: helios alembic $(sql helios 'select version_num from alembic_version'), current_menu rows $(sql helios 'select count(*) from gold.current_menu')"
log "next: start the API, then the manifest check (infra/backup/README.md, drill B)"
