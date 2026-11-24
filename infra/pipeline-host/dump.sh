#!/usr/bin/env bash
# Dump one database (custom format) and print its sha256 (ADR-0030 D1, D3).
#   bash infra/pipeline-host/dump.sh <pi|laptop> <db> <out.dump>
# The dump is written to <out>.part and renamed when complete.
set -euo pipefail
OUT=$(realpath -m "${3:?usage: dump.sh <pi|laptop> <db> <out.dump>}")
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
HOST=$1
need_host "$HOST"
need_db "$2"
mkdir -p "$(dirname "$OUT")"
log "dump $2 ($HOST) -> $OUT"
pg "$2" pg_dump -Fc >"$OUT.part"
mv "$OUT.part" "$OUT"
sha256sum "$OUT"
