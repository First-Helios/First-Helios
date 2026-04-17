#!/usr/bin/env bash
# dev/sync_from_opi.sh
#
# Pull the live write-path tables from the production OrangePi into the local
# dev Postgres so a workstation can reproduce production state without
# re-running every collector.
#
# What it syncs (data-only, TRUNCATE + reload):
#   public.job_postings       — all ingested listings (incl. spiritpool_*)
#   public.sp_events          — clean SpiritPool contributions
#   public.quarantine         — PII-flagged payloads
#   public.session_epochs     — contributor session lifecycle
#   public.burn_pool          — monthly burned-session aggregates
#   public.contributors       — anonymous contributor volume
#   dev_capture.raw_signals   — dev-mode raw HTML / extracted / sanitized captures
#   public.restaurant_urls    — resolved URLs (OSM, Google Places, manual)
#   public.meal_deals         — scraped deal data with price/calorie fields
#   public.deal_observations  — canonical observed deal artifacts
#   public.deal_applicability — resolved venue/brand applicability rows
#   public.deal_materializations — consumer-facing semantic deal rows
#
# What it does NOT sync (rebuild those separately):
#   ref_*, oews_*, mob_*, brand_groups, local_employers, scores, meta_*
#
# What it ALSO syncs by default:
#   data/cache/website_scrape_debug/  — replayable website scrape page bundles
#   data/cache/website_scrape_audit.json — per-site scrape audit output
#
# Usage:
#   bash dev/sync_from_opi.sh              # pull data
#   bash dev/sync_from_opi.sh --dry-run    # compare OPi vs local row counts only
#   bash dev/sync_from_opi.sh --skip-cache # skip website scrape cache sync
#
# Environment overrides (otherwise .env is sourced):
#   OPI_HOST    — default orangepi@192.168.1.191
#   OPI_PGURL   — default postgresql://helios:helios@localhost:5432/helios
#   OPI_PROJECT_ROOT — default /home/orangepi/First-Helios
#   LOCAL_PGURL — default DATABASE_URL from .env (SQLAlchemy +psycopg prefix stripped)
#
# Requirements: ssh key auth to OPi, psql on PATH, tar on both machines, local Postgres schema
# already migrated (alembic upgrade head).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ── Load .env ─────────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
    set -o allexport
    # shellcheck disable=SC1091
    source .env
    set +o allexport
fi

OPI_HOST="${OPI_HOST:-orangepi@192.168.1.191}"
OPI_PGURL="${OPI_PGURL:-postgresql://helios:helios@localhost:5432/helios}"
OPI_PROJECT_ROOT="${OPI_PROJECT_ROOT:-/home/orangepi/First-Helios}"
LOCAL_PGURL="${LOCAL_PGURL:-${DATABASE_URL:-postgresql://helios:helios@localhost:5432/helios}}"
CACHE_MIN_AGE_MINUTES="${CACHE_MIN_AGE_MINUTES:-1}"

# Strip SQLAlchemy driver prefix so libpq tools accept the URL
LOCAL_PGURL="${LOCAL_PGURL/postgresql+psycopg:\/\//postgresql:\/\/}"
LOCAL_PGURL="${LOCAL_PGURL/postgresql+psycopg2:\/\//postgresql:\/\/}"

# ── Argument parsing ──────────────────────────────────────────────────────────
DRY_RUN=false
SYNC_CACHE=true
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --skip-cache) SYNC_CACHE=false ;;
        -h|--help) sed -n '2,35p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

# ── Tables to sync (order matters: no FKs between them, but keep deterministic) ─
TABLES=(
    "public.job_postings"
    "public.sp_events"
    "public.quarantine"
    "public.session_epochs"
    "public.burn_pool"
    "public.contributors"
    "dev_capture.raw_signals"
    "public.restaurant_urls"
    "public.meal_deals"
    "public.deal_observations"
    "public.deal_applicability"
    "public.deal_materializations"
)

# ── Helpers ───────────────────────────────────────────────────────────────────
count_local() {
    local table="$1"
    psql "$LOCAL_PGURL" -tAc "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo "?"
}

count_opi() {
    local table="$1"
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" \
        "psql '$OPI_PGURL' -tAc 'SELECT COUNT(*) FROM $table;'" 2>/dev/null || echo "?"
}

sync_remote_cache_path() {
    local rel_path="$1"
    local local_path="$PROJECT_ROOT/$rel_path"
    local remote_path="$OPI_PROJECT_ROOT/$rel_path"
    local kind="$2"

    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" "test -e '$remote_path'" >/dev/null 2>&1; then
        echo "[cache] missing on OPi: $rel_path"
        if [[ "$kind" == "dir" ]]; then
            rm -rf "$local_path"
        else
            rm -f "$local_path"
        fi
        return 0
    fi

    if [[ "$kind" == "dir" ]]; then
        rm -rf "$local_path"
    else
        rm -f "$local_path"
    fi
    mkdir -p "$(dirname "$local_path")"

    if [[ "$kind" == "dir" ]]; then
        mkdir -p "$local_path"
        ssh -o BatchMode=yes -o ConnectTimeout=5 -C "$OPI_HOST" \
            "cd '$OPI_PROJECT_ROOT' && find '$rel_path' -type f -mmin +$CACHE_MIN_AGE_MINUTES -print0 | tar --null -T - -cf -" \
            | tar -xf - -C "$PROJECT_ROOT"
        echo "[cache] synced stable files from: $rel_path"
        return 0
    fi

    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" \
        "find '$remote_path' -maxdepth 0 -type f -mmin +$CACHE_MIN_AGE_MINUTES | grep -q ." >/dev/null 2>&1; then
        echo "[cache] skipping active file: $rel_path"
        return 0
    fi

    ssh -o BatchMode=yes -o ConnectTimeout=5 -C "$OPI_HOST" \
        "cd '$OPI_PROJECT_ROOT' && tar -cf - '$rel_path'" \
        | tar -xf - -C "$PROJECT_ROOT"

    echo "[cache] synced: $rel_path"
}

echo "============================================================"
echo "  sync_from_opi"
echo "  OPI host     : $OPI_HOST"
echo "  OPI DB       : $OPI_PGURL"
echo "  OPI root     : $OPI_PROJECT_ROOT"
echo "  Local DB     : $LOCAL_PGURL"
echo "  Dry run      : $DRY_RUN"
echo "  Sync cache   : $SYNC_CACHE"
echo "============================================================"

# ── Pre-sync row count comparison ─────────────────────────────────────────────
echo ""
printf "%-30s %14s %14s %14s\n" "TABLE" "OPI" "LOCAL" "DELTA"
printf "%-30s %14s %14s %14s\n" "-----" "---" "-----" "-----"
for t in "${TABLES[@]}"; do
    opi=$(count_opi "$t")
    loc=$(count_local "$t")
    if [[ "$opi" =~ ^[0-9]+$ && "$loc" =~ ^[0-9]+$ ]]; then
        delta=$((opi - loc))
    else
        delta="?"
    fi
    printf "%-30s %14s %14s %14s\n" "$t" "$opi" "$loc" "$delta"
done
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] No data synced."
    exit 0
fi

# ── Truncate local tables (single statement so PG resolves FK dependency
#    order itself; CASCADE is safe here because the only FKs inside this
#    set are between these same tables — e.g. session_epochs → contributors)
echo "-- Truncating local tables --"
TRUNCATE_LIST=$(IFS=,; echo "${TABLES[*]}")
psql "$LOCAL_PGURL" -v ON_ERROR_STOP=1 --quiet \
    -c "TRUNCATE TABLE $TRUNCATE_LIST RESTART IDENTITY CASCADE;"

# ── Dump from OPi and pipe into local ─────────────────────────────────────────
echo "-- Dumping from OPi and loading into local (data-only) --"

TABLE_ARGS=""
for t in "${TABLES[@]}"; do
    TABLE_ARGS+=" --table=$t"
done

# --data-only: local schema must already exist (alembic upgrade head)
# --no-owner / --no-privileges: portable SQL
# -C (ssh): compress stream for the WAN hop
ssh -o BatchMode=yes -o ConnectTimeout=5 -C "$OPI_HOST" \
    "pg_dump '$OPI_PGURL' --data-only --no-owner --no-privileges$TABLE_ARGS" \
    | psql "$LOCAL_PGURL" -v ON_ERROR_STOP=1 --quiet

if [[ "$SYNC_CACHE" == "true" ]]; then
    echo "-- Syncing website scrape replay cache --"
    sync_remote_cache_path "data/cache/website_scrape_debug" dir
    sync_remote_cache_path "data/cache/website_scrape_audit.json" file
fi

# ── Post-sync row counts ──────────────────────────────────────────────────────
echo ""
echo "-- Post-sync local row counts --"
for t in "${TABLES[@]}"; do
    loc=$(count_local "$t")
    printf "%-30s %14s\n" "$t" "$loc"
done
echo ""
echo "Done."
