#!/usr/bin/env bash
# Copy var/replay/ (bundles, saved page and chunk answers) between the hosts (ADR-0030 D1, step 6).
# Run on the laptop:
#   DATA=<laptop deploy dir> bash infra/pipeline-host/replay-sync.sh <pi-to-laptop|laptop-to-pi>
# It must finish before the target extracts, or pages with missing saved answers go to the model
# again. Files are written 0644 since #175; into the Pi, directories are made writable for the
# worker's uid 999. Nothing is deleted on the target.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
RSH="ssh ${SSH_OPTS[*]}"
LOCAL="$(realpath "$DATA")/var/replay/"
REMOTE="$PI:$PI_DIR/var/replay/"
case "${1:-}" in
pi-to-laptop) rsync -a --stats -e "$RSH" --chmod=Da+rx,Fa+r "$REMOTE" "$LOCAL" ;;
laptop-to-pi) rsync -a --stats -e "$RSH" --chmod=Da+rwx,Fa+r "$LOCAL" "$REMOTE" ;;
*) die "usage: replay-sync.sh <pi-to-laptop|laptop-to-pi>" ;;
esac
log "replay synced ($1)"
