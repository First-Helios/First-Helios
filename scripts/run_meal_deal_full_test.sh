#!/usr/bin/env bash
set -Eeuo pipefail


ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Missing virtualenv at .venv/bin/activate"
  echo "Create it first: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate
export PYTHONPATH=.

# Load .env for DATABASE_URL/API keys when running outside systemd.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DRY_GOOGLE_CALLS="${DRY_GOOGLE_CALLS:-50}"
LIVE_GOOGLE_CALLS="${LIVE_GOOGLE_CALLS:-200}"
DRY_MAX_SITES="${DRY_MAX_SITES:-100}"
LIVE_MAX_SITES="${LIVE_MAX_SITES:-200}"
RUN_STALE_SWEEP="${RUN_STALE_SWEEP:-1}"

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_DIR="reports/meal_deal_test_${STAMP}"
mkdir -p "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/run.log"

exec > >(tee -a "$LOG_FILE") 2>&1

run_step() {
  echo
  echo "==== $* ===="
  "$@"
}

ensure_alembic_ready() {
  local marker_file
  marker_file="$REPORT_DIR/alembic_drift_check.json"

  python - "$marker_file" <<'PY'
import json
import sys
from sqlalchemy import inspect, text
from core.database import init_db

out_path = sys.argv[1]
engine = init_db()

with engine.connect() as conn:
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    has_alembic_version = "alembic_version" in tables
    has_existing_schema = "venues" in tables or "local_employers" in tables
    version_row_count = 0

    if has_alembic_version:
        version_row_count = conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() or 0

payload = {
    "has_alembic_version": has_alembic_version,
    "has_existing_schema": has_existing_schema,
    "version_row_count": int(version_row_count),
}

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, sort_keys=True)
PY

  if python - "$marker_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    payload = json.load(f)

needs_stamp = payload["has_existing_schema"] and (
    (not payload["has_alembic_version"]) or payload["version_row_count"] == 0
)
raise SystemExit(0 if needs_stamp else 1)
PY
  then
    echo "Detected pre-existing schema without Alembic version tracking; stamping current DB to head."
    run_step alembic stamp head
  fi

  echo
  echo "==== alembic upgrade head ===="
  local upgrade_log
  upgrade_log="$REPORT_DIR/alembic_upgrade.log"

  if alembic upgrade head >"$upgrade_log" 2>&1; then
    cat "$upgrade_log"
    return 0
  fi

  cat "$upgrade_log"

  if grep -Eqi "DuplicateTable|already exists" "$upgrade_log"; then
    echo "Detected DuplicateTable during upgrade; stamping head and retrying once."
    run_step alembic stamp head
    run_step alembic upgrade head
    return 0
  fi

  echo "Alembic upgrade failed for a non-recoverable reason."
  return 1
}

write_snapshot() {
  local out_file="$1"
  python - "$out_file" <<'PY'
import json
import sys
from sqlalchemy import func
from core.database import RestaurantURL, LocalEmployer, MealDeal, init_db, get_session

out_path = sys.argv[1]
engine = init_db()
s = get_session(engine)
try:
    total_urls = s.query(func.count(RestaurantURL.id)).scalar() or 0
    urls_by_source = {
        source or "unknown": int(cnt)
        for source, cnt in s.query(RestaurantURL.source, func.count()).group_by(RestaurantURL.source).all()
    }

    total_food = s.query(func.count(LocalEmployer.id)).filter(
        LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
        LocalEmployer.is_active.is_(True),
    ).scalar() or 0
    has_url = s.query(func.count(func.distinct(RestaurantURL.local_employer_id))).scalar() or 0

    total_deals = s.query(func.count(MealDeal.id)).scalar() or 0
    active_deals = s.query(func.count(MealDeal.id)).filter(MealDeal.is_active.is_(True)).scalar() or 0
    brands_with_deals = s.query(func.count(func.distinct(MealDeal.brand_group_id))).filter(
        MealDeal.is_active.is_(True),
        MealDeal.brand_group_id.isnot(None),
    ).scalar() or 0
    deals_by_source = {
        source or "unknown": int(cnt)
        for source, cnt in s.query(MealDeal.source, func.count()).group_by(MealDeal.source).all()
    }

    payload = {
        "total_urls": int(total_urls),
        "urls_by_source": urls_by_source,
        "total_food_employers": int(total_food),
        "food_employers_with_url": int(has_url),
        "coverage_pct": round((has_url / total_food * 100.0), 2) if total_food else 0.0,
        "total_deals": int(total_deals),
        "active_deals": int(active_deals),
        "brands_with_active_deals": int(brands_with_deals),
        "deals_by_source": deals_by_source,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
finally:
    s.close()
PY
}

print_delta() {
  local before_file="$1"
  local after_file="$2"
  python - "$before_file" "$after_file" <<'PY'
import json
import sys

before_path, after_path = sys.argv[1], sys.argv[2]
with open(before_path, encoding="utf-8") as f:
    before = json.load(f)
with open(after_path, encoding="utf-8") as f:
    after = json.load(f)

def delta_int(key):
    return int(after.get(key, 0)) - int(before.get(key, 0))

print("\n==== FINAL SUMMARY ====")
print(f"URLs:   {before['total_urls']} -> {after['total_urls']} (delta {delta_int('total_urls'):+d})")
print(
    f"Coverage: {before['food_employers_with_url']}/{before['total_food_employers']} ({before['coverage_pct']}%) "
    f"-> {after['food_employers_with_url']}/{after['total_food_employers']} ({after['coverage_pct']}%)"
)
print(f"Deals:  {before['total_deals']} -> {after['total_deals']} (delta {delta_int('total_deals'):+d})")
print(f"Active deals: {before['active_deals']} -> {after['active_deals']} (delta {delta_int('active_deals'):+d})")
print(
    f"Brands w/ active deals: {before['brands_with_active_deals']} -> "
    f"{after['brands_with_active_deals']} (delta {delta_int('brands_with_active_deals'):+d})"
)
PY
}

echo "Starting meal deal full test at $(date -Is)"
echo "Repository: $ROOT_DIR"
echo "Report dir: $REPORT_DIR"

run_step python - <<'PY'
from core.database import init_db
engine = init_db()
print(f"Database backend: {engine.url.render_as_string(hide_password=True)}")
PY

ensure_alembic_ready

BEFORE_JSON="$REPORT_DIR/before_snapshot.json"
AFTER_JSON="$REPORT_DIR/after_snapshot.json"

run_step write_snapshot "$BEFORE_JSON"
run_step cat "$BEFORE_JSON"

echo
echo "---- Phase 1: Dry-run pipeline ----"
run_step python collectors/meal_deals/osm_url_resolver.py --dry-run
run_step python collectors/meal_deals/google_places_resolver.py --mode both --max-calls "$DRY_GOOGLE_CALLS" --dry-run
run_step python collectors/meal_deals/chain_deals.py --dry-run
run_step python collectors/meal_deals/website_scraper.py --max-sites "$DRY_MAX_SITES" --dry-run

echo
echo "---- Phase 2: Live pipeline ----"
run_step python collectors/meal_deals/osm_url_resolver.py
run_step python collectors/meal_deals/google_places_resolver.py --mode both --max-calls "$LIVE_GOOGLE_CALLS"
run_step python collectors/meal_deals/chain_deals.py
run_step python collectors/meal_deals/website_scraper.py --max-sites "$LIVE_MAX_SITES"

if [[ "$RUN_STALE_SWEEP" == "1" ]]; then
  run_step python collector_main.py --job deal_stale_sweep
fi

run_step write_snapshot "$AFTER_JSON"
run_step cat "$AFTER_JSON"
run_step print_delta "$BEFORE_JSON" "$AFTER_JSON"

echo
echo "---- API checks (best effort) ----"
if command -v curl >/dev/null 2>&1; then
  curl -sS http://localhost:8765/api/deals/stats > "$REPORT_DIR/api_deals_stats.json" || true
  curl -sS "http://localhost:8765/api/deals?limit=5" > "$REPORT_DIR/api_deals_sample.json" || true
  ls -lh "$REPORT_DIR"/api_deals_*.json 2>/dev/null || true
fi

echo
echo "Meal deal full test complete."
echo "Artifacts: $REPORT_DIR"
echo "Log: $LOG_FILE"
