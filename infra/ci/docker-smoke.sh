#!/usr/bin/env bash
# CI smoke test for the API image (ADR-0031 D3, R116). In order:
#   1. the image's own HEALTHCHECK reports healthy (liveness, /healthz);
#   2. `alembic upgrade head` from the image migrates an empty database;
#   3. /readyz and /v1/venues?limit=1 answer 200 from that database.
#   bash infra/ci/docker-smoke.sh <image> [database URL]
# The database defaults to the CI job's PostgreSQL service on 127.0.0.1:5432. Containers use the
# host network, so 127.0.0.1 is the runner. The API container is named helios-api, which the
# job's failure step reads logs from.
set -euo pipefail
IMAGE=${1:?usage: docker-smoke.sh <image> [database URL]}
DB=${2:-postgresql+psycopg://helios:helios@127.0.0.1:5432/helios}
NAME=helios-api
API=http://127.0.0.1:8000
BODY=$(mktemp)

docker run -d --name "$NAME" --network host -e DATABASE_URL="$DB" "$IMAGE" >/dev/null

# 1. The HEALTHCHECK. "none" means the image has none; "starting" lasts until the first probe.
status=
for _ in $(seq 1 45); do
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$NAME")
  [ "$status" = healthy ] && break
  [ "$status" = none ] && break
  sleep 2
done
echo "health: $status"
[ "$status" = healthy ] || exit 1

# 2. Migrations, as the Compose `migrate` one-shot runs them.
docker run --rm --network host -e DATABASE_URL="$DB" "$IMAGE" alembic upgrade head

# 3. Readiness and one domain route on the empty, migrated database.
fail=0
for path in /readyz "/v1/venues?limit=1"; do
  code=$(curl -s -o "$BODY" -w '%{http_code}' "$API$path" || true)
  echo "$path $code"
  if [ "$code" != 200 ]; then
    cat "$BODY" || true
    echo
    fail=1
  fi
done
exit $fail
