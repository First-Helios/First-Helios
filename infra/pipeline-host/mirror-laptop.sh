#!/usr/bin/env bash
# After a swap, make helios_laptop equal public again (ADR-0030 Q8): the only copy of the data
# off the Pi until Phase 8's off-box backups. Run on the laptop, with no master there:
#   DATA=<laptop deploy dir> BACKUPS=<laptop backup dir> \
#     bash infra/pipeline-host/mirror-laptop.sh <swapped dump's path on the Pi>
# Backs up helios_laptop, copies the dump (sha256 checked), restores it, syncs var/replay/.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
REMOTE=${1:?usage: mirror-laptop.sh <swapped dump path on the Pi>}
BACKUPS=$(realpath -m "${BACKUPS:?set BACKUPS to the laptop backup directory}")
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
MARKER="$DATA/var/pipeline-host/MASTER"
if [ -f "$MARKER" ] && grep -qx 'host=laptop' "$MARKER"; then
  die "the master is on the laptop ($MARKER): helios_laptop is not a mirror now"
fi
mkdir -p "$BACKUPS"
bash infra/pipeline-host/dump.sh laptop helios_laptop "$BACKUPS/helios_laptop-pre-mirror-$STAMP.dump"
scp "${SSH_OPTS[@]}" "$PI:$REMOTE" "$BACKUPS/"
LOCAL="$BACKUPS/$(basename "$REMOTE")"
want=$(ssh "${SSH_OPTS[@]}" "$PI" sha256sum "$REMOTE" | cut -d' ' -f1)
[ "$(sha256sum "$LOCAL" | cut -d' ' -f1)" = "$want" ] || die "the copied dump's sha256 differs"
bash infra/pipeline-host/restore.sh laptop helios_laptop "$LOCAL"
bash infra/pipeline-host/replay-sync.sh pi-to-laptop
log "helios_laptop mirrors the swapped dump ($want)"
