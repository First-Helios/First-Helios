#!/usr/bin/env bash
# dev_toolkit/rebuild_local_employers.sh
#
# Full rebuild of the local_employers and brand_groups tables from a cached
# Overture GeoJSON file.
#
# What it does:
#   1. Ingests all POIs from the GeoJSON through backend/ingest_layer.py.
#      Every record is normalized (strip store numbers, join initials, strip legal
#      suffixes), fingerprinted, and upserted. brand_groups.location_count is
#      maintained atomically — no separate classify step needed.
#   2. Classification (brand vs. local) is done at query time by the server
#      using CHAIN_THRESHOLD = 5 on brand_groups.location_count.
#
# When to run:
#   - After purging local_employers / brand_groups data
#   - After downloading a fresh Overture GeoJSON file
#   - After changing CATEGORY_INDUSTRY_MAP or name normalization logic
#
# Usage:
#   ./dev_toolkit/rebuild_local_employers.sh
#   ./dev_toolkit/rebuild_local_employers.sh --geojson data/my_custom_file.geojson
#   ./dev_toolkit/rebuild_local_employers.sh --region austin_tx
#   ./dev_toolkit/rebuild_local_employers.sh --dry-run   # parse only, no writes
#
# Environment:
#   DATABASE_URL  — set in .env (PostgreSQL) or leave unset for SQLite fallback

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
GEOJSON="data/overture_austin_places.geojson"
REGION="austin_tx"
DRY_RUN=false

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --geojson)  GEOJSON="$2"; shift 2 ;;
        --region)   REGION="$2";  shift 2 ;;
        --dry-run)  DRY_RUN=true; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Resolve project root (script lives in dev_toolkit/) ───────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Load .env if present
if [[ -f .env ]]; then
    set -o allexport
    source .env
    set +o allexport
fi

echo "============================================================"
echo "  local_employers rebuild"
echo "  GeoJSON      : $GEOJSON"
echo "  Region       : $REGION"
echo "  DATABASE_URL : ${DATABASE_URL:-sqlite (fallback)}"
echo "  Dry run      : $DRY_RUN"
echo "============================================================"

if [[ ! -f "$GEOJSON" ]]; then
    echo "ERROR: GeoJSON file not found: $GEOJSON"
    exit 1
fi

# ── Ingest ─────────────────────────────────────────────────────────────────────
echo ""
echo "── Ingesting POIs from $GEOJSON ──"
echo "   (normalization + fingerprint + brand_groups upsert handled by ingest_layer)"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would run: python scrapers/overture_adapter.py --local-file $GEOJSON --region $REGION"
else
    python scrapers/overture_adapter.py --local-file "$GEOJSON" --region "$REGION"
fi

echo ""
echo "Done. Restart the server to pick up the new data."
