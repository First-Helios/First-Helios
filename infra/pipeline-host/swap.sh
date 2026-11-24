#!/usr/bin/env bash
# Swap a gated master dump into the public database on the Pi (ADR-0030 D3, Q5).
#   bash infra/pipeline-host/swap.sh <gate.json> <master.dump> <backup dir> [accept-stop reason]
#   bash infra/pipeline-host/swap.sh --rollback
# Run on the Pi from the deploy directory. In order:
#   1. the gate report (python -m apps.menu_pipeline.swap_gate --out) must say "passed"; a
#      stopped gate goes ahead only with the owner's reason as the 4th argument (logged);
#   2. back up public `helios` (pi-helios-pre-swap-<stamp>.dump, sha256);
#   3. restore the dump into `helios_next` while the API keeps serving (fence reset, restore.sh);
#   4. stop the API, rename helios -> helios_prev and helios_next -> helios, start the API;
#   5. checks: migrate exit 0, local endpoints and firsthelios.com 200, `alembic check`;
#   6. removes var/pipeline-host/AWAITING_SWAP, so the loop (and its timer) may start again.
# A failed check renames back (helios -> helios_failed, helios_prev -> helios). `helios_prev`
# stays until the next swap, so --rollback can restore it.
set -euo pipefail
USAGE="usage: swap.sh <gate.json> <master.dump> <backup dir> [accept-stop reason] | --rollback"
MODE=${1:?$USAGE}
if [ "$MODE" != --rollback ]; then
  GATE=$(realpath "$1")
  DUMP=$(realpath "${2:?$USAGE}")
  BACKUPS=$(realpath -m "${3:?$USAGE}")
  ACCEPT=${4:-}
fi
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
HOST=pi
ENDPOINTS=(/healthz /readyz "/v1/venues?limit=1" "/v1/venues?limit=1&cuisine=mexican"
  /v1/venues/category-facets /v1/price-index/cells)
PUBLIC=(https://firsthelios.com/ https://firsthelios.com/healthz "https://firsthelios.com/v1/venues?limit=1")

admin() { pg postgres psql -X -v ON_ERROR_STOP=1 -q "$@"; }
terminate() {
  sql postgres "select count(pg_terminate_backend(pid)) from pg_stat_activity
                where datname in ('helios', 'helios_prev', 'helios_next', 'helios_failed')
                  and pid <> pg_backend_pid();" >/dev/null
}
exists() { [ "$(sql postgres "select count(*) from pg_database where datname = '$1'")" = 1 ]; }
wait_ready() {
  for _ in $(seq 1 60); do
    curl -fsS -o /dev/null http://127.0.0.1:8000/readyz 2>/dev/null && return 0
    sleep 2
  done
  return 1
}
checks() {
  local ok=0 code id
  wait_ready || {
    echo "readyz never answered"
    return 1
  }
  id=$("${DC[@]}" ps -a -q migrate)
  code=$(docker inspect "$id" --format '{{.State.ExitCode}}')
  echo "migrate exit $code"
  [ "$code" = 0 ] || ok=1
  for p in "${ENDPOINTS[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8000$p")
    echo "$p $code"
    [ "$code" = 200 ] || ok=1
  done
  for u in "${PUBLIC[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$u")
    echo "$u $code"
    [ "$code" = 200 ] || ok=1
  done
  "${DC[@]}" run --rm --no-deps -T api alembic check || ok=1
  return $ok
}
rollback() {
  exists helios_prev || die "no helios_prev to roll back to"
  log "rolling back: helios -> helios_failed, helios_prev -> helios"
  "${DC[@]}" stop api
  terminate
  admin -c "DROP DATABASE IF EXISTS helios_failed WITH (FORCE);" \
    -c "ALTER DATABASE helios RENAME TO helios_failed;" \
    -c "ALTER DATABASE helios_prev RENAME TO helios;"
  "${DC[@]}" up -d api
  if ! wait_ready; then die "rolled back, but readyz does not answer"; fi
  log "rolled back; the API answers"
}

if [ "$MODE" = --rollback ]; then
  rollback
  exit 0
fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

# 1. The gate.
if ! python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))["passed"] else 1)' "$GATE"; then
  [ -n "$ACCEPT" ] || die "the gate stopped ($GATE): ask the owner; a go-ahead is the 4th argument"
  log "gate stopped; going ahead on the owner's word: $ACCEPT"
fi
log "swap $DUMP (sha256 $(sha256sum "$DUMP" | cut -d' ' -f1))"

# 2. Back up public. 3. Restore into helios_next while the API serves.
bash infra/pipeline-host/dump.sh pi helios "$BACKUPS/pi-helios-pre-swap-$STAMP.dump"
bash infra/pipeline-host/restore.sh pi helios_next "$DUMP"
public_rev=$(sql helios 'select version_num from alembic_version')
next_rev=$(sql helios_next 'select version_num from alembic_version')
[ "$public_rev" = "$next_rev" ] ||
  die "helios_next is at $next_rev, public at $public_rev: deploy the matching code first"

# 4. The rename.
start=$(date +%s)
"${DC[@]}" stop api
terminate
admin -c "DROP DATABASE IF EXISTS helios_prev WITH (FORCE);" \
  -c "ALTER DATABASE helios RENAME TO helios_prev;" \
  -c "ALTER DATABASE helios_next RENAME TO helios;"
"${DC[@]}" up -d api
wait_ready || true
log "downtime $(($(date +%s) - start)) s"

# 5. The checks.
if ! checks; then
  rollback
  die "a check failed: rolled back to the pre-swap database (now helios; the swapped one is helios_failed)"
fi
log "swap done: current_menu rows $(sql helios 'select count(*) from gold.current_menu'); helios_prev kept for --rollback"
# 6. The run that waited for this swap is read: the loop may start again (ADR-0030 Amendment 1).
if [ -f var/pipeline-host/AWAITING_SWAP ]; then
  log "clearing AWAITING_SWAP ($(tr '\n' ' ' <var/pipeline-host/AWAITING_SWAP))"
  rm -f var/pipeline-host/AWAITING_SWAP
fi
