"""
System Health Dashboard

Check the health of your data infrastructure:
  python scripts/system_health_dashboard.py

This queries metadata to answer:
  - Are all my data sources fresh?
  - Have any jobs failed recently?
  - What tables are stale?
  - What's the last API error?

Usage:
  python scripts/system_health_dashboard.py [--detailed] [--days 7]
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

# Add project root
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.database import get_session, init_db


def print_header(title):
    """Print a formatted section header."""
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


def check_table_freshness(session, days_stale: int = 7) -> None:
    """Check if any tables are stale (older than SLA)."""
    print_header("TABLE FRESHNESS STATUS")

    query = text("""
    SELECT
      mtc.table_name,
      mtc.layer,
      mtc.source,
      MAX(mjr.run_timestamp) as last_update,
      CAST((julianday('now') - julianday(MAX(mjr.run_timestamp))) AS INTEGER) as hours_since_update,
      CASE
        WHEN MAX(mjr.run_timestamp) IS NULL THEN 'NEVER UPDATED'
        WHEN (julianday('now') - julianday(MAX(mjr.run_timestamp))) > 7 THEN 'STALE'
        WHEN (julianday('now') - julianday(MAX(mjr.run_timestamp))) > 3 THEN 'AGING'
        ELSE 'FRESH'
      END as status,
      MAX(mjr.status) as last_job_status,
      COUNT(CASE WHEN mjr.status = 'failed' THEN 1 END) as recent_failures
    FROM meta_table_catalog mtc
    LEFT JOIN meta_job_runs mjr ON mtc.table_name = mjr.job_id
    WHERE mjr.run_timestamp IS NOT NULL
       OR mtc.layer = 'reference'
    GROUP BY mtc.table_name
    ORDER BY CASE status WHEN 'STALE' THEN 0 WHEN 'AGING' THEN 1 ELSE 2 END,
             hours_since_update DESC
    """)

    results = session.execute(query).fetchall()

    if not results:
        print("  No job run history found. Run jobs first, then check again.")
        return

    stale_count = 0
    aging_count = 0
    fresh_count = 0

    for row in results:
        table, layer, source, last_update, hours_ago, status, job_status, failures = row

        # Status emoji
        if status == "STALE":
            emoji = "🔴"
            stale_count += 1
        elif status == "AGING":
            emoji = "🟡"
            aging_count += 1
        else:
            emoji = "🟢"
            fresh_count += 1

        # Format output
        update_str = last_update.strftime("%Y-%m-%d %H:%M") if last_update else "NEVER"
        print(f"  {emoji} {table:<35} {status:<15} Last: {update_str} ({hours_ago}h ago)")

        if failures > 0:
            print(f"     ⚠️  Recent failures: {failures}")

    print()
    print(f"  Summary: {fresh_count} 🟢 fresh, {aging_count} 🟡 aging, {stale_count} 🔴 stale")


def check_recent_failures(session, days: int = 7) -> None:
    """Check for recent job failures."""
    print_header("RECENT JOB FAILURES (Last 7 days)")

    since = datetime.utcnow() - timedelta(days=days)

    query = text("""
    SELECT
      job_id,
      status,
      COUNT(*) as count,
      MAX(run_timestamp) as latest_failure
    FROM meta_job_runs
    WHERE status != 'success'
      AND run_timestamp > :since
    GROUP BY job_id, status
    ORDER BY latest_failure DESC
    """)

    results = session.execute(query, {"since": since}).fetchall()

    if not results:
        print("  ✓ No failures in the last 7 days")
        return

    for job_id, status, count, latest in results:
        emoji = "🔴" if status == "failed" else "🟡"
        print(f"  {emoji} {job_id:<40} {count:>2} times  Latest: {latest}")


def check_api_errors(session, limit: int = 5) -> None:
    """Show the most recent API errors."""
    print_header("RECENT API ERRORS (Top 5)")

    query = text("""
    SELECT
      api_source,
      status_code,
      error_message,
      COUNT(*) as count,
      MAX(request_timestamp) as latest
    FROM meta_api_calls
    WHERE success = 0
      AND request_timestamp > datetime('now', '-7 days')
    GROUP BY api_source, status_code
    ORDER BY latest DESC
    LIMIT :limit
    """)

    results = session.execute(query, {"limit": limit}).fetchall()

    if not results:
        print("  ✓ No API errors in the last 7 days")
        return

    for source, status_code, error, count, timestamp in results:
        print(f"  🔴 {source:<30} HTTP {status_code}")
        if error:
            print(f"     Error: {error[:60]}")
        print(f"     Occurred {count} times, latest: {timestamp}")
        print()


def check_rate_limits(session) -> None:
    """Show current rate limit status."""
    print_header("RATE LIMIT STATUS")

    query = text("""
    SELECT
      source_key,
      used,
      daily_limit,
      CAST(100.0 * used / daily_limit AS INT) as percent_used,
      daily_limit - used as remaining,
      last_request_at
    FROM rate_budgets
    WHERE DATE(last_request_at) = DATE('now')
    ORDER BY percent_used DESC
    """)

    results = session.execute(query).fetchall()

    if not results:
        print("  No rate limit data for today")
        return

    for source, used, limit, percent, remaining, last_req in results:
        if percent > 80:
            emoji = "🔴"
        elif percent > 50:
            emoji = "🟡"
        else:
            emoji = "🟢"

        bar_len = 20
        filled = int(bar_len * percent / 100)
        bar = "█" * filled + "░" * (bar_len - filled)

        print(f"  {emoji} {source:<30} [{bar}] {percent:>3}% ({used}/{limit})")
        print(f"     Remaining: {remaining}  Last request: {last_req}")


def check_data_lineage(session) -> None:
    """Show data flow/lineage summary."""
    print_header("DATA LINEAGE CHAINS")

    query = text("""
    SELECT
      source_table,
      target_table,
      transformation_type,
      COUNT(*) as hop_count
    FROM meta_data_lineage
    WHERE deprecated_at IS NULL
    GROUP BY source_table, target_table
    ORDER BY source_table, target_table
    """)

    results = session.execute(query).fetchall()

    if not results:
        print("  No lineage information found")
        return

    print("  Data flows:")
    for source, target, trans_type, hops in results:
        print(f"    {source:<35} → {target:<35} [{trans_type}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="System Health Dashboard")
    parser.add_argument("--detailed", action="store_true", help="Show detailed information")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    args = parser.parse_args()

    print()
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "  CHAINSTAFF INGTRACKER — SYSTEM HEALTH DASHBOARD".center(78) + "║")
    print("║" + f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'):<76}  ║")
    print("║" + " " * 78 + "║")
    print("╚" + "=" * 78 + "╝")

    # Initialize database
    engine = init_db()
    session = get_session(engine)

    try:
        check_table_freshness(session)
        check_recent_failures(session, args.days)
        check_api_errors(session)
        check_rate_limits(session)

        if args.detailed:
            check_data_lineage(session)

        print()
        print("=" * 80)
        print("  For detailed analysis, query meta_* tables directly:")
        print("    sqlite3 data/tracker.db 'SELECT * FROM meta_table_catalog;'")
        print("=" * 80)
        print()

    finally:
        session.close()


if __name__ == "__main__":
    main()
