#!/usr/bin/env bash
# restic against the Helios repository, with its secrets from ~/.config/helios-ops/ (ADR-0031 D1).
#   bash infra/backup/restic.sh snapshots --host helios-pi
# For people and the drill scripts; the nightly unit reads the same files with EnvironmentFile=.
# The Pi's login shell is fish, which can't source r2.env, hence this wrapper. HELIOS_OPS names
# another directory holding r2.env and restic-password (the laptop's copy, say). Never `set -x`.
set -euo pipefail
CONF=${HELIOS_OPS:-$HOME/.config/helios-ops}
set -a
# shellcheck source=/dev/null # the host's secrets, never in the repo
. "$CONF/r2.env"
set +a
export RESTIC_PASSWORD_FILE=${RESTIC_PASSWORD_FILE:-$CONF/restic-password}
exec restic "$@"
