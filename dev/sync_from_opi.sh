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
#   bash dev/sync_from_opi.sh              # pull data (incremental cache sync)
#   bash dev/sync_from_opi.sh --dry-run    # compare OPi vs local counts + cache delta
#   bash dev/sync_from_opi.sh --skip-cache # skip website scrape cache sync
#   bash dev/sync_from_opi.sh --cache-only # skip DB tables, only sync cache bundles
#   bash dev/sync_from_opi.sh --full-resync-cache # force full tar re-pull (bypass manifest diff)
#
# Cache sync model (incremental, bundle-identity keyed):
#   * Each site debug bundle is a single JSON file named slug__<sha1-digest>.json
#     under data/cache/website_scrape_debug/ — the filename is a stable identity
#     key for the site, and the file itself is the unit we track.
#   * Sync compares remote vs local manifests by (name, size, mtime). Only new
#     or changed bundles are pulled; unchanged bundles are skipped with zero
#     transfer. Files younger than CACHE_MIN_AGE_MINUTES on OPi are treated as
#     in-flight and skipped until the next run.
#   * Tracking overhead is kept to one find-based manifest per side, so only
#     large slow-changing bundles pay the identity cost — per-page sub-artifacts
#     are not individually keyed.
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
SYNC_DB=true
FULL_RESYNC_CACHE=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --skip-cache) SYNC_CACHE=false ;;
        --cache-only) SYNC_DB=false ;;
        --full-resync-cache) FULL_RESYNC_CACHE=true ;;
        -h|--help) sed -n '2,46p' "$0"; exit 0 ;;
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

    mkdir -p "$(dirname "$local_path")"

    if [[ "$kind" == "dir" ]]; then
        mkdir -p "$local_path"
        if [[ "$FULL_RESYNC_CACHE" == "true" ]]; then
            rm -rf "$local_path"
            mkdir -p "$local_path"
            ssh -o BatchMode=yes -o ConnectTimeout=5 -C "$OPI_HOST" \
                "cd '$OPI_PROJECT_ROOT' && find '$rel_path' -type f -mmin +$CACHE_MIN_AGE_MINUTES -print0 | tar --null -T - -cf -" \
                | tar -xf - -C "$PROJECT_ROOT"
            echo "[cache] full-resync of: $rel_path"
            return 0
        fi
        incremental_sync_dir "$rel_path" "$local_path"
        return 0
    fi

    # Single file: skip if remote is still being written to.
    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" \
        "find '$remote_path' -maxdepth 0 -type f -mmin +$CACHE_MIN_AGE_MINUTES | grep -q ." >/dev/null 2>&1; then
        echo "[cache] skipping active file: $rel_path"
        return 0
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        # Compare remote vs local size+mtime without transferring.
        local rsig lsig
        rsig=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" \
            "stat -c '%s %Y' '$remote_path' 2>/dev/null" || echo "missing")
        lsig=$(stat -c '%s %Y' "$local_path" 2>/dev/null || echo "missing")
        if [[ "$rsig" == "$lsig" ]]; then
            echo "[cache] unchanged file: $rel_path"
        else
            echo "[cache] would update file: $rel_path (remote=$rsig local=$lsig)"
        fi
        return 0
    fi

    # rsync with --update avoids re-fetching when local is already newer/same.
    rsync -az --update --partial \
        -e "ssh -o BatchMode=yes -o ConnectTimeout=5" \
        "$OPI_HOST:$remote_path" "$local_path"

    echo "[cache] synced file: $rel_path"
}

# Incremental directory sync keyed by bundle filename identity.
#
# Each bundle file (e.g. website_scrape_debug/<slug>__<digest>.json) is its own
# unit of identity. We compare a remote manifest (name, size, mtime) to the
# local manifest, pull only new/changed bundles, and skip unchanged ones with
# zero bytes transferred. Files younger than CACHE_MIN_AGE_MINUTES on OPi are
# treated as in-flight and deferred to the next run.
incremental_sync_dir() {
    local rel_path="$1"
    local local_path="$2"

    local tmpdir
    tmpdir="$(mktemp -d)"
    # Use a local trap variable instead of a global RETURN trap so subsequent
    # calls from sync_remote_cache_path do not inherit a stale $tmpdir.
    _cleanup_tmpdir() { rm -rf "$tmpdir"; }

    local remote_manifest="$tmpdir/remote.tsv"
    local local_manifest="$tmpdir/local.tsv"
    local skipped_manifest="$tmpdir/remote_skipped.tsv"

    # Remote manifest: stable files only (older than CACHE_MIN_AGE_MINUTES).
    # %p gives the path relative to $OPI_PROJECT_ROOT (since we cd into it),
    # which is exactly what rsync --files-from needs.
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" \
        "cd '$OPI_PROJECT_ROOT' && find '$rel_path' -type f -mmin +$CACHE_MIN_AGE_MINUTES -printf '%p\t%s\t%T@\n' | LC_ALL=C sort" \
        > "$remote_manifest"

    # Remote in-flight files (for reporting only).
    ssh -o BatchMode=yes -o ConnectTimeout=5 "$OPI_HOST" \
        "cd '$OPI_PROJECT_ROOT' && find '$rel_path' -type f -mmin -$CACHE_MIN_AGE_MINUTES -printf '%p\n' | LC_ALL=C sort" \
        > "$skipped_manifest" 2>/dev/null || : > "$skipped_manifest"

    # Local manifest, same shape.
    if [[ -d "$local_path" ]]; then
        (cd "$PROJECT_ROOT" && find "$rel_path" -type f -printf '%p\t%s\t%T@\n' 2>/dev/null | LC_ALL=C sort) \
            > "$local_manifest"
    else
        : > "$local_manifest"
    fi

    # Diff by (name, size, mtime-rounded). A bundle is "unchanged" only if all
    # three match — filename identity is the primary key, size+mtime guard
    # against silent overwrites.
    local to_transfer="$tmpdir/to_transfer.txt"
    local new_count=0 changed_count=0 unchanged_count=0
    awk -F'\t' -v out="$to_transfer" -v new_f="$tmpdir/new.txt" -v chg_f="$tmpdir/changed.txt" -v unc_f="$tmpdir/unchanged.txt" '
        BEGIN { while ((getline line < ARGV[1]) > 0) {
                    n = split(line, f, "\t");
                    local_size[f[1]] = f[2];
                    # Round mtime to whole seconds (rsync treats sub-second drift as equal).
                    local_mtime[f[1]] = int(f[3]);
                }
                close(ARGV[1]);
                ARGV[1] = ""; }
        {
            name = $1; rsize = $2; rmtime = int($3);
            if (!(name in local_size)) {
                print name >> new_f;
                print name >> out;
            } else if (local_size[name] != rsize || local_mtime[name] != rmtime) {
                print name >> chg_f;
                print name >> out;
            } else {
                print name >> unc_f;
            }
        }
    ' "$local_manifest" "$remote_manifest"

    [[ -f "$tmpdir/new.txt" ]] && new_count=$(wc -l < "$tmpdir/new.txt")
    [[ -f "$tmpdir/changed.txt" ]] && changed_count=$(wc -l < "$tmpdir/changed.txt")
    [[ -f "$tmpdir/unchanged.txt" ]] && unchanged_count=$(wc -l < "$tmpdir/unchanged.txt")
    local skipped_inflight=0
    [[ -s "$skipped_manifest" ]] && skipped_inflight=$(wc -l < "$skipped_manifest")

    # Files present locally but missing from remote manifest. These may have
    # been pruned remotely, or excluded as in-flight. We do NOT delete locally
    # to avoid racing against active scrapes — report only.
    local orphan_count=0
    if [[ -s "$local_manifest" ]]; then
        orphan_count=$( { LC_ALL=C comm -23 \
            <(cut -f1 "$local_manifest" | LC_ALL=C sort -u) \
            <(cat "$remote_manifest" "$skipped_manifest" 2>/dev/null | cut -f1 | LC_ALL=C sort -u) \
            2>/dev/null || true; } | wc -l)
    fi

    echo "[cache] $rel_path: new=$new_count changed=$changed_count unchanged=$unchanged_count in-flight-skipped=$skipped_inflight local-only=$orphan_count"

    if [[ "$DRY_RUN" == "true" ]]; then
        _cleanup_tmpdir
        return 0
    fi

    if [[ "$new_count" -eq 0 && "$changed_count" -eq 0 ]]; then
        _cleanup_tmpdir
        return 0
    fi

    # Transfer only the delta. rsync --files-from reads remote-relative paths
    # from stdin; -a preserves mtime so the next run's manifest diff is exact.
    rsync -az --partial --files-from="$to_transfer" \
        -e "ssh -o BatchMode=yes -o ConnectTimeout=5" \
        "$OPI_HOST:$OPI_PROJECT_ROOT/" "$PROJECT_ROOT/"

    echo "[cache] transferred $((new_count + changed_count)) bundles for: $rel_path"
    _cleanup_tmpdir
}

echo "============================================================"
echo "  sync_from_opi"
echo "  OPI host     : $OPI_HOST"
echo "  OPI DB       : $OPI_PGURL"
echo "  OPI root     : $OPI_PROJECT_ROOT"
echo "  Local DB     : $LOCAL_PGURL"
echo "  Dry run      : $DRY_RUN"
echo "  Sync DB      : $SYNC_DB"
echo "  Sync cache   : $SYNC_CACHE"
echo "  Full resync  : $FULL_RESYNC_CACHE"
echo "============================================================"

# ── Pre-sync row count comparison ─────────────────────────────────────────────
if [[ "$SYNC_DB" == "true" ]]; then
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
fi

# ── Cache manifest preview (always runs when cache sync is on — cheap) ────────
if [[ "$SYNC_CACHE" == "true" && "$DRY_RUN" == "true" ]]; then
    echo "-- Cache manifest delta (dry-run) --"
    sync_remote_cache_path "data/cache/website_scrape_debug" dir
    sync_remote_cache_path "data/cache/website_scrape_audit.json" file
    echo ""
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] No data synced."
    exit 0
fi

if [[ "$SYNC_DB" == "true" ]]; then
    # ── Truncate local tables (single statement so PG resolves FK dependency
    #    order itself; CASCADE is safe here because the only FKs inside this
    #    set are between these same tables — e.g. session_epochs → contributors)
    echo "-- Truncating local tables --"
    TRUNCATE_LIST=$(IFS=,; echo "${TABLES[*]}")
    psql "$LOCAL_PGURL" -v ON_ERROR_STOP=1 --quiet \
        -c "TRUNCATE TABLE $TRUNCATE_LIST RESTART IDENTITY CASCADE;"

    # ── Dump from OPi and pipe into local ─────────────────────────────────────
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
else
    echo "-- Skipping DB sync (--cache-only) --"
fi

if [[ "$SYNC_CACHE" == "true" ]]; then
    echo "-- Syncing website scrape replay cache (incremental, bundle-keyed) --"
    sync_remote_cache_path "data/cache/website_scrape_debug" dir
    sync_remote_cache_path "data/cache/website_scrape_audit.json" file
fi

# ── Post-sync row counts ──────────────────────────────────────────────────────
if [[ "$SYNC_DB" == "true" ]]; then
    echo ""
    echo "-- Post-sync local row counts --"
    for t in "${TABLES[@]}"; do
        loc=$(count_local "$t")
        printf "%-30s %14s\n" "$t" "$loc"
    done
fi
echo ""
echo "Done."
