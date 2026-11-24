#!/usr/bin/env bash
# Replace one non-public database with a dump, then reset the admission fence (ADR-0030 D1).
#   bash infra/pipeline-host/restore.sh <pi|laptop> <db> <in.dump>
# Drops and recreates <db>, restores with --no-owner --role=helios (stderr kept next to the
# dump), and ALWAYS resets menu.admission_fence: pg_restore carries the source cluster's
# transaction id, and Menu writes are refused on a younger cluster until it is reset (P8-23).
# The public `helios` database is replaced only by swap.sh.
set -euo pipefail
DUMP=$(realpath "${3:?usage: restore.sh <pi|laptop> <db> <in.dump>}")
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
HOST=$1
DB=$2
need_host "$HOST"
need_db "$DB"
[ "$DB" != helios ] || die "the public database is replaced only by swap.sh"
log "restore $DUMP -> $DB ($HOST), sha256 $(sha256sum "$DUMP" | cut -c1-16)"
start=$(date +%s)
pg postgres psql -X -v ON_ERROR_STOP=1 -q \
  -c "DROP DATABASE IF EXISTS $DB WITH (FORCE);" -c "CREATE DATABASE $DB OWNER helios;"
ERR="$DUMP.restore-$DB.err"
if ! pg "$DB" pg_restore --no-owner --role=helios <"$DUMP" 2>"$ERR"; then
  die "pg_restore failed ($(wc -l <"$ERR") stderr lines in $ERR)"
fi
log "pg_restore ok in $(($(date +%s) - start)) s ($(wc -l <"$ERR") stderr lines)"
sql "$DB" "select setval('menu.admission_fence', txid_current(), true);" >/dev/null
log "admission fence reset"
log "alembic $(sql "$DB" 'select version_num from alembic_version'), current_menu rows $(sql "$DB" 'select count(*) from gold.current_menu')"
