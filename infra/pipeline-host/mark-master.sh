#!/usr/bin/env bash
# Write this host's MASTER marker (ADR-0030 D1): which host holds the master, from which dump,
# under which commit. The batch loop refuses to start unless the marker names its own host and
# DEPLOYED_COMMIT. Write it on BOTH hosts after a move, so the old master refuses too.
#   DATA=<deploy dir> bash infra/pipeline-host/mark-master.sh <pi|laptop> <commit> <dump sha256>
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
need_host "${1:-}"
[[ "${2:-}" =~ ^[0-9a-f]{7,40}$ ]] || die "not a commit: '${2:-}'"
[[ "${3:-}" =~ ^[0-9a-f]{64}$ ]] || die "not a sha256: '${3:-}'"
DIR="$DATA/var/pipeline-host"
mkdir -p "$DIR"
printf 'host=%s\ncommit=%s\nmoved_at=%s\ndump_sha256=%s\n' "$1" "$2" "$(date -u +%FT%TZ)" "$3" \
  >"$DIR/MASTER.tmp"
mv "$DIR/MASTER.tmp" "$DIR/MASTER"
log "MASTER: host=$1 commit=$2 ($DIR/MASTER)"
