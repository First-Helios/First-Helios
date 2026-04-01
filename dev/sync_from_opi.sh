#!/bin/bash
# sync_from_opi.sh — Pull live OPi database to local dev machine
#
# Usage:
#   bash dev/sync_from_opi.sh           # full replace (drop + restore)
#   bash dev/sync_from_opi.sh --dry-run # show row counts only, no changes
#
# One-way: OPi (production) → local (dev). Never runs in reverse.

set -e

OPI_HOST="192.168.0.104"
OPI_USER="orangepi"
OPI_PASS="orangepi"
DB_NAME="helios"
DB_USER="helios"
DB_PASS="helios"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# ── Helpers ───────────────────────────────────────────────────────────────────

opi_psql() {
    sshpass -p "$OPI_PASS" ssh -o StrictHostKeyChecking=no \
        "$OPI_USER@$OPI_HOST" \
        "PGPASSWORD=$DB_PASS psql -U $DB_USER -h localhost -d $DB_NAME -t -c \"$1\""
}

row_counts() {
    local label=$1
    local host_fn=$2
    local query="SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 8;"

    echo ""
    echo "  $label row counts:"
    if [[ "$host_fn" == "opi" ]]; then
        opi_psql "$query" | grep -v "^$" | awk '{printf "    %-35s %s\n", $1, $3}'
    else
        PGPASSWORD=$DB_PASS psql -U $DB_USER -h localhost -d $DB_NAME -t \
            -c "$query" 2>/dev/null \
            | grep -v "^$" | awk '{printf "    %-35s %s\n", $1, $3}' \
            || echo "    (local DB not available)"
    fi
}

# ── Pre-flight ────────────────────────────────────────────────────────────────

echo "=== First-Helios DB Sync: OPi → Local ==="
echo "  Source : $OPI_USER@$OPI_HOST ($DB_NAME)"
echo "  Target : localhost ($DB_NAME)"
echo ""

# Check sshpass
if ! command -v sshpass &>/dev/null; then
    echo "ERROR: sshpass not installed. Run: sudo apt-get install sshpass"
    exit 1
fi

# Check OPi reachable
if ! sshpass -p "$OPI_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "$OPI_USER@$OPI_HOST" "echo ok" &>/dev/null; then
    echo "ERROR: Cannot reach OPi at $OPI_HOST"
    exit 1
fi

row_counts "OPi (source)" "opi"
row_counts "Local (before)" "local"

if [[ $DRY_RUN -eq 1 ]]; then
    echo ""
    echo "Dry run — no changes made."
    exit 0
fi

# Warn if local server.py is running
if pgrep -f "server.py\|gunicorn.*server" &>/dev/null; then
    echo ""
    echo "WARNING: local Flask/Gunicorn is running. DB connections will be dropped."
    read -rp "  Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

# ── Sync ─────────────────────────────────────────────────────────────────────

echo ""
echo "Streaming dump from OPi → local psql..."
START=$(date +%s)

# Drop and recreate local DB cleanly
# Ensure local DB exists (first-time setup)
PGPASSWORD=$DB_PASS psql -U $DB_USER -h localhost -d $DB_NAME -c "SELECT 1;" \
    > /dev/null 2>&1 || {
    echo "  Local DB not found — creating (sudo required once)..."
    read -rsp "  [sudo] password for $USER: " _SUDO_PASS; echo
    echo "$_SUDO_PASS" | sudo -S -u postgres psql \
        -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" \
        -c "ALTER USER $DB_USER CREATEDB;" 2>/dev/null || {
        echo "ERROR: Could not create local DB. Run manually:"
        echo "  sudo -u postgres psql -c \"CREATE DATABASE $DB_NAME OWNER $DB_USER; ALTER USER $DB_USER CREATEDB;\""
        exit 1
    }
    unset _SUDO_PASS
}

# Stream dump with --clean so each object is dropped+recreated (no DROP DATABASE needed)
echo "  Streaming OPi dump into local DB..."
sshpass -p "$OPI_PASS" ssh -o StrictHostKeyChecking=no \
    "$OPI_USER@$OPI_HOST" \
    "PGPASSWORD=$DB_PASS pg_dump --clean --if-exists -U $DB_USER -h localhost -d $DB_NAME" \
    | PGPASSWORD=$DB_PASS psql -U $DB_USER -h localhost -d $DB_NAME \
    > /dev/null

ELAPSED=$(( $(date +%s) - START ))
echo "  Done in ${ELAPSED}s"

row_counts "Local (after)" "local"
echo ""
echo "Sync complete. Local DB matches OPi as of $(date '+%Y-%m-%d %H:%M')."
