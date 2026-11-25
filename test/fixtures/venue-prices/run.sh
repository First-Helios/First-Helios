#!/usr/bin/env bash
# Run the redistributable end-to-end benchmark in a private local cluster.
set -euo pipefail
cd "$(dirname "$0")/../../.."
export PATH="$(pg_config --bindir):$PATH"
scratch=$(mktemp -d)
initdb -D "$scratch/db" -A trust >/dev/null
pg_ctl -D "$scratch/db" -o "-k $scratch -c listen_addresses=''" -l "$scratch/db.log" start >/dev/null
cleanup() {
  pg_ctl -D "$scratch/db" stop -m fast >/dev/null && rm -rf -- "$scratch"
}
trap cleanup EXIT
unset PGHOSTADDR PGSERVICE PGSERVICEFILE
export PGHOST="$scratch"
createdb venues_test
export DATABASE_URL="postgresql+psycopg:///venues_test?host=$scratch" HELIOS_STRICT_DB_TESTS=1
uv run --frozen pytest -qs test/test_venue_price_eval.py
