#!/usr/bin/env bash
# One night's backup out of the repository: helios.dump, helios_work.dump and manifest.json
# (ADR-0031 D2: both drills, and a real recovery).
#   bash infra/backup/fetch-night.sh <dir> [night-<stamp>]
# Without a night, it takes the newest complete one: backup.sh writes the manifest's snapshot
# last, so a night that has a manifest has both dumps. Prints the night, the time taken and each
# file's sha256. Secrets as restic.sh reads them.
set -euo pipefail
OUT=$(realpath -m "${1:?usage: fetch-night.sh <dir> [night-<stamp>]}")
TAG=${2:-}
R=(bash "$(dirname "$(realpath "$0")")/restic.sh")
RHOST=helios-pi
FILES=(manifest.json helios.dump helios_work.dump)
start=$SECONDS
if [ -z "$TAG" ]; then
  TAG=$("${R[@]}" snapshots --json --host "$RHOST" --path /manifest.json --latest 1 |
    python3 -c 'import json, sys
snaps = json.load(sys.stdin) or []
tags = [t for t in (snaps[-1].get("tags") or []) if t.startswith("night-")] if snaps else []
print(tags[0] if tags else "")')
fi
[[ "$TAG" =~ ^night-[0-9]{8}T[0-9]{6}Z$ ]] || {
  echo "error: no complete night in the repository, or not a night tag: '$TAG'" >&2
  exit 1
}
mkdir -p "$OUT"
for f in "${FILES[@]}"; do
  "${R[@]}" dump --host "$RHOST" --tag "$TAG" --path "/$f" latest "/$f" >"$OUT/$f.part"
  mv "$OUT/$f.part" "$OUT/$f"
done
echo "$TAG -> $OUT in $((SECONDS - start)) s"
(cd "$OUT" && sha256sum "${FILES[@]}")
