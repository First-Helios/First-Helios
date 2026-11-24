#!/usr/bin/env bash
# Move the master between the Pi (helios_work) and the laptop (helios_laptop) (ADR-0030 D1).
# Run on the laptop, from a checkout, after the loop has stopped on the source:
#   DATA=<laptop deploy dir> BACKUPS=<laptop backup dir> \
#     bash infra/pipeline-host/move-master.sh <pi-to-laptop|laptop-to-pi>
# Steps: refuse while a loop runs on either host; dump the source (sha256); copy and check it;
# back up the target; restore it (restore.sh resets the admission fence); sync var/replay/;
# write MASTER on both hosts with the Pi's DEPLOYED_COMMIT. The laptop then runs the loop from
# a `git archive` of that commit whose DEPLOYED_COMMIT says so (README).
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
BACKUPS=$(realpath -m "${BACKUPS:?set BACKUPS to the laptop backup directory}")
PI_BACKUPS=${PI_BACKUPS:-helios-backups/pipeline-host} # relative to the Pi user's home
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DIRECTION=${1:-}
case "$DIRECTION" in pi-to-laptop | laptop-to-pi) ;; *) die "usage: move-master.sh <pi-to-laptop|laptop-to-pi>" ;; esac
sha_of() { tail -1 | cut -d' ' -f1; }

# 1. No loop may be running: a move under a writing loop loses its writes.
if ssh "${SSH_OPTS[@]}" "$PI" systemctl is-active --quiet helios-pipeline-loop; then
  die "helios-pipeline-loop is active on the Pi: touch STOP and wait for 'loop end'"
fi
# the [a] keeps pgrep from matching the remote shell that runs it
if ssh "${SSH_OPTS[@]}" "$PI" "pgrep -f '[a]pps.menu_pipeline.batch_loop'" >/dev/null; then
  die "a batch loop is running on the Pi"
fi
if pgrep -f '[a]pps.menu_pipeline.batch_loop' >/dev/null; then die "a batch loop is running here"; fi
COMMIT=$(ssh "${SSH_OPTS[@]}" "$PI" cat "$PI_DIR/DEPLOYED_COMMIT")
mkdir -p "$BACKUPS"
log "move master $DIRECTION, commit $COMMIT"

if [ "$DIRECTION" = pi-to-laptop ]; then
  REMOTE="$PI_BACKUPS/helios_work-handover-$STAMP.dump"
  SHA=$(pi_script dump.sh pi helios_work "$REMOTE" | sha_of)
  scp "${SSH_OPTS[@]}" "$PI:$REMOTE" "$BACKUPS/"
  LOCAL="$BACKUPS/$(basename "$REMOTE")"
  [ "$(sha256sum "$LOCAL" | sha_of)" = "$SHA" ] || die "the copied dump's sha256 differs"
  bash infra/pipeline-host/dump.sh laptop helios_laptop \
    "$BACKUPS/helios_laptop-pre-handover-$STAMP.dump"
  bash infra/pipeline-host/restore.sh laptop helios_laptop "$LOCAL"
  bash infra/pipeline-host/replay-sync.sh pi-to-laptop
  TARGET=laptop
else
  LOCAL="$BACKUPS/helios_laptop-handover-$STAMP.dump"
  SHA=$(bash infra/pipeline-host/dump.sh laptop helios_laptop "$LOCAL" | sha_of)
  ssh "${SSH_OPTS[@]}" "$PI" mkdir -p "$PI_BACKUPS"
  scp "${SSH_OPTS[@]}" "$LOCAL" "$PI:$PI_BACKUPS/"
  REMOTE="$PI_BACKUPS/$(basename "$LOCAL")"
  [ "$(ssh "${SSH_OPTS[@]}" "$PI" sha256sum "$REMOTE" | sha_of)" = "$SHA" ] ||
    die "the copied dump's sha256 differs"
  pi_script dump.sh pi helios_work "$PI_BACKUPS/helios_work-pre-handover-$STAMP.dump"
  pi_script restore.sh pi helios_work "$REMOTE"
  bash infra/pipeline-host/replay-sync.sh laptop-to-pi
  TARGET=pi
fi

pi_script mark-master.sh "$TARGET" "$COMMIT" "$SHA"
bash infra/pipeline-host/mark-master.sh "$TARGET" "$COMMIT" "$SHA"
log "master is now on $TARGET (dump sha256 $SHA)"
