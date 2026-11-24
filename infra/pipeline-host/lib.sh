# Shared by the pipeline-host scripts (ADR-0030); sourced, never run. The caller sets HOST
# (pi | laptop) and has changed to the repository root (the deploy directory on the Pi).
#   pi:     PostgreSQL tools run in the Compose `postgres` container, as role helios.
#   laptop: tools run on the host with the connection from $DATA/.env in PG* variables
#           (python -m apps.menu_pipeline.with_db --pg): no password on a command line.
set -euo pipefail
DATA=${DATA:-.}
DC=(docker compose -f infra/docker-compose.yml -f infra/docker-compose.pi.yml --env-file .env)
PI=${PI:-orangepi@192.168.1.191}
PI_DIR=${PI_DIR:-First-Helios} # the Pi's deploy directory, relative to its user's home
SSH_OPTS=(-o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

log() { echo "$(date -u +%FT%TZ) $*"; }
die() {
  echo "error: $*" >&2
  exit 1
}
need_host() { case "${1:-}" in pi | laptop) ;; *) die "host must be pi or laptop, not '${1:-}'" ;; esac }
need_db() { [[ "${1:-}" =~ ^[a-z_][a-z0-9_]*$ ]] || die "not a database name: '${1:-}'"; }

# pg <db> <tool> [args...]: a PostgreSQL client tool against one database; stdin and stdout
# pass through. `-d` is always given: pg_restore without it prints SQL instead of restoring.
pg() {
  local db=$1 tool=$2
  shift 2
  if [ "$HOST" = pi ]; then
    "${DC[@]}" exec -T postgres "$tool" -U helios -d "$db" "$@"
  else
    uv run --env-file "$DATA/.env" python -m apps.menu_pipeline.with_db "$db" --pg "$tool" -d "$db" "$@"
  fi
}

sql() { pg "$1" psql -X -v ON_ERROR_STOP=1 -Atc "$2"; }

# pi_script <script> [args...]: one of these scripts on the Pi. Its login shell is fish, so the
# remote command is a plain `bash <path> <args>` (no $(...), no quoting tricks): pass simple
# arguments (names, absolute paths).
pi_script() {
  local script=$1
  shift
  ssh "${SSH_OPTS[@]}" "$PI" bash "$PI_DIR/infra/pipeline-host/$script" "$@"
}
