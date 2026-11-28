#!/usr/bin/env bash
# The laptop's monthly second copy (ADR-0031 Q5b): `restic copy` from R2 into a repository on the
# laptop. The Pi's token can delete objects in R2, so a compromised Pi could delete its own
# backups; this copy only ever adds, from the laptop's side.
#   bash infra/backup/laptop-copy.sh [repository dir]      # default ~/helios-restic
# Reads the laptop's ~/.config/helios-ops/ (or HELIOS_OPS): r2.env and restic-password, both from
# the password manager. The laptop repository has the same password. The first run creates it
# with R2's chunker parameters, so copies deduplicate. Then it keeps the Pi's retention, checks
# the copy, and prints the newest night. Run on drill A's day, after the month's swap.
set -euo pipefail
CONF=${HELIOS_OPS:-$HOME/.config/helios-ops}
DEST=$(realpath -m "${1:-$HOME/helios-restic}")
set -a
# shellcheck source=/dev/null # the host's secrets, never in the repo
. "$CONF/r2.env"
set +a
export RESTIC_FROM_REPOSITORY=$RESTIC_REPOSITORY RESTIC_FROM_PASSWORD_FILE=$CONF/restic-password
export RESTIC_REPOSITORY=$DEST RESTIC_PASSWORD_FILE=$CONF/restic-password
start=$SECONDS
if [ ! -f "$DEST/config" ]; then
  restic init --copy-chunker-params
fi
restic copy --host helios-pi
restic forget --host helios-pi --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune
restic check
echo "laptop copy in $((SECONDS - start)) s: $(restic snapshots --host helios-pi --path /manifest.json --latest 1 --compact | sed -n 3p)"
