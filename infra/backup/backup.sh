#!/usr/bin/env bash
# The nightly off-box backup: restic into the Cloudflare R2 bucket (ADR-0031 D1, Q1-Q3).
#   bash infra/backup/backup.sh        # helios-backup.timer runs it daily at 09:00 UTC
# Run on the Pi from the deploy directory. The unit puts RESTIC_REPOSITORY, the R2 keys
# (AWS_*), RESTIC_PASSWORD_FILE and, optionally, HC_BACKUP_URL in the environment, from
# ~/.config/helios-ops/. Never `set -x` here: the environment holds secrets. In order:
#   1. takes var/pipeline-host/db.lock (lib.sh db_lock), so no swap or recover renames a
#      database mid-dump (a running pipeline loop is fine: pg_dump reads one snapshot);
#   2. writes the night's manifest: the commit, and apps.menu_pipeline.backup_manifest's facts
#      for helios and helios_work. The drills compare a restore with it;
#   3. streams `pg_dump -Fc -Z0` of helios and helios_work into restic. Uncompressed, so restic
#      deduplicates unchanged tables from night to night; restic compresses. Through
#      --stdin-from-command: a pg_dump that fails fails its snapshot;
#   4. backs up var/replay/, var/pipeline-host/ and DEPLOYED_COMMIT;
#   5. backs up the manifest, last, as /manifest.json: a night with a manifest is complete;
#   6. forgets down to 7 daily / 5 weekly / 12 monthly, and prunes on Sundays (UTC).
# Every snapshot of one night has host helios-pi and the tag night-<stamp>, so a drill takes the
# dumps and the manifest of the same night (fetch-night.sh). With HC_BACKUP_URL (hc.env, D5) it
# pings /start, then /<exit status> with the log's tail (healthchecks.io: nonzero = failure).
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
HOST=pi
RHOST=helios-pi
DATABASES=(helios helios_work)
STATE=var/backup
mkdir -p "$STATE"
LOG=$STATE/last.log
exec > >(tee "$LOG") 2>&1

ping() {
  [ -n "${HC_BACKUP_URL:-}" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null --data-binary "${2:-}" "$HC_BACKUP_URL$1" || true
}
finish() {
  local rc=$?
  log "backup exit $rc"
  ping "/$rc" "$(tail -n 40 "$LOG")"
}
trap finish EXIT
ping /start

: "${RESTIC_REPOSITORY:?not set (r2.env)}"
: "${RESTIC_PASSWORD_FILE:?not set (helios-backup.service)}"
COMMIT=$(tr -d '[:space:]' <DEPLOYED_COMMIT)
[[ "$COMMIT" =~ ^[0-9a-f]{7,40}$ ]] || die "DEPLOYED_COMMIT is not a commit: '$COMMIT'"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TAG=night-$STAMP
step() {
  local t=$SECONDS
  "$@"
  log "  ... $((SECONDS - t)) s"
}

db_lock 7200
log "backup $TAG (commit $COMMIT) to $RHOST"
restic unlock # removes stale locks only (a run killed mid-way)

# 2. The manifest. stdout is the JSON; the compose noise goes to stderr.
FACTS=$("${DC[@]}" run --rm --no-deps -T api \
  python -m apps.menu_pipeline.backup_manifest "${DATABASES[@]/#/--db=}")
printf '{"taken_at": "%s", "commit": "%s", "tag": "%s", "databases": %s}\n' \
  "$STAMP" "$COMMIT" "$TAG" "$FACTS" >"$STATE/manifest.json"
log "manifest: $(tr -d '\n ' <"$STATE/manifest.json")"

# 3. The databases, one snapshot each.
for db in "${DATABASES[@]}"; do
  log "dump $db"
  step restic backup --host "$RHOST" --tag "$TAG" --stdin-filename "$db.dump" \
    --stdin-from-command -- "${DC[@]}" exec -T postgres pg_dump -U helios -d "$db" -Fc -Z0
done

# 4. The files.
log "files"
step restic backup --host "$RHOST" --tag "$TAG" var/replay var/pipeline-host DEPLOYED_COMMIT

# 5. The manifest, last: fetch-night.sh takes the newest night that has one.
step restic backup --host "$RHOST" --tag "$TAG" --stdin-filename manifest.json \
  --stdin-from-command -- cat "$STATE/manifest.json"

# 6. Retention. Grouped by host and paths (restic's default): each dump and the files apart.
log "forget"
step restic forget --host "$RHOST" --keep-daily 7 --keep-weekly 5 --keep-monthly 12
if [ "$(date -u +%u)" = 7 ]; then
  log "prune (Sunday)"
  step restic prune
fi
log "done: $(restic snapshots --host "$RHOST" --tag "$TAG" --compact | tail -n 1)"
