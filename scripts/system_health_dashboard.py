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

from core.database import get_session, init_db


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


def check_spiritpool_events_freshness(session) -> None:
    """Check freshness of the sp_events table based on collected_at timestamps."""
    print_header("SPIRITPOOL — EVENTS FRESHNESS")

    query = text("""
    SELECT
      COUNT(*) as total_events,
      MAX(collected_at) as latest_event,
      CAST((julianday('now') - julianday(MAX(collected_at))) * 24 AS INTEGER) as hours_ago,
      CASE
        WHEN MAX(collected_at) IS NULL THEN 'NO DATA'
        WHEN (julianday('now') - julianday(MAX(collected_at))) > 7 THEN 'STALE'
        WHEN (julianday('now') - julianday(MAX(collected_at))) > 3 THEN 'AGING'
        ELSE 'FRESH'
      END as status
    FROM sp_events
    """)

    try:
        row = session.execute(query).fetchone()
    except Exception:
        print("  ⚠ sp_events table not yet created")
        return

    if not row or row[0] == 0:
        print("  📭 No events received yet")
        return

    total, latest, hours, status = row
    emoji = {"FRESH": "🟢", "AGING": "🟡", "STALE": "🔴"}.get(status, "⚪")
    latest_str = latest if isinstance(latest, str) else str(latest)
    print(f"  {emoji} sp_events  {status:<12} {total:>8} events   Latest: {latest_str} ({hours}h ago)")

    # Domain coverage breakdown
    domain_query = text("""
    SELECT
      event_type,
      COUNT(*) as count,
      ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM sp_events), 1) as pct
    FROM sp_events
    GROUP BY event_type
    ORDER BY count DESC
    """)
    domain_rows = session.execute(domain_query).fetchall()
    if domain_rows:
        print()
        print("  Domain coverage:")
        for etype, count, pct in domain_rows:
            bar_len = 20
            filled = int(bar_len * pct / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"    {etype:<25} [{bar}] {pct:>5.1f}% ({count})")


def check_quarantine_health(session) -> None:
    """Show quarantine table size, growth, and PII detection hit rate."""
    print_header("SPIRITPOOL — QUARANTINE & PII DETECTION")

    try:
        total_events = session.execute(text("SELECT COUNT(*) FROM sp_events")).scalar() or 0
        total_quarantined = session.execute(text("SELECT COUNT(*) FROM quarantine")).scalar() or 0
    except Exception:
        print("  ⚠ SpiritPool tables not yet created")
        return

    total_all = total_events + total_quarantined

    if total_all == 0:
        print("  📭 No events processed yet")
        return

    hit_rate = round(100.0 * total_quarantined / total_all, 1) if total_all else 0.0

    # Alerting thresholds (from Dev Req §6.2)
    if hit_rate > 15:
        emoji = "🔴"
        alert = "CRITICAL"
    elif hit_rate > 5:
        emoji = "🟡"
        alert = "WARNING"
    else:
        emoji = "🟢"
        alert = "HEALTHY"

    print(f"  {emoji} PII detection rate: {hit_rate}% ({total_quarantined}/{total_all}) — {alert}")
    print(f"     Clean events (sp_events):    {total_events}")
    print(f"     Quarantined:                 {total_quarantined}")

    # Quarantine breakdown by redaction type
    type_query = text("""
    SELECT redaction_types, COUNT(*) as count
    FROM quarantine
    GROUP BY redaction_types
    ORDER BY count DESC
    LIMIT 10
    """)
    type_rows = session.execute(type_query).fetchall()
    if type_rows:
        print()
        print("  Quarantine breakdown:")
        for types, count in type_rows:
            print(f"    {types:<40} {count:>5}")

    # Growth: last 7 days vs previous 7 days
    growth_query = text("""
    SELECT
      COUNT(CASE WHEN quarantined_at >= datetime('now', '-7 days') THEN 1 END) as last_7d,
      COUNT(CASE WHEN quarantined_at >= datetime('now', '-14 days')
                  AND quarantined_at < datetime('now', '-7 days') THEN 1 END) as prev_7d
    FROM quarantine
    """)
    growth = session.execute(growth_query).fetchone()
    if growth and (growth[0] > 0 or growth[1] > 0):
        last7, prev7 = growth
        if prev7 > 0:
            change = round((last7 - prev7) / prev7 * 100, 1)
            direction = "↑" if change > 0 else "↓" if change < 0 else "→"
            print(f"\n  Growth: {last7} last 7d vs {prev7} prev 7d ({direction} {abs(change)}%)")
        else:
            print(f"\n  Growth: {last7} last 7d (no prior data)")


def check_session_epochs(session) -> None:
    """Show session epoch count, active/burned breakdown, and burn rate."""
    print_header("SPIRITPOOL — SESSION EPOCHS & BURN RATE")

    try:
        total = session.execute(text("SELECT COUNT(*) FROM session_epochs")).scalar() or 0
        burned = session.execute(text(
            "SELECT COUNT(*) FROM session_epochs WHERE burned_at IS NOT NULL"
        )).scalar() or 0
    except Exception:
        print("  ⚠ session_epochs table not yet created")
        return

    active = total - burned

    if total == 0:
        print("  📭 No sessions recorded yet")
        return

    burn_rate = round(100.0 * burned / total, 1) if total else 0.0

    print(f"  Total sessions:   {total}")
    print(f"  Active:           {active}")
    print(f"  Burned:           {burned} ({burn_rate}%)")

    # Recent burn activity
    recent_query = text("""
    SELECT
      COUNT(CASE WHEN burned_at >= datetime('now', '-24 hours') THEN 1 END) as burns_24h,
      COUNT(CASE WHEN burned_at >= datetime('now', '-7 days') THEN 1 END) as burns_7d
    FROM session_epochs
    WHERE burned_at IS NOT NULL
    """)
    recent = session.execute(recent_query).fetchone()
    if recent:
        print(f"  Burns last 24h:   {recent[0]}")
        print(f"  Burns last 7d:    {recent[1]}")


def check_burn_pool(session) -> None:
    """Show burn pool monthly trends and expiry status."""
    print_header("SPIRITPOOL — BURN POOL MONTHLY TRENDS")

    try:
        rows = session.execute(text("""
        SELECT
          month_key,
          signal_count,
          burned_at,
          expires_at,
          CASE
            WHEN expires_at < datetime('now') THEN 'EXPIRED'
            WHEN expires_at < datetime('now', '+30 days') THEN 'EXPIRING SOON'
            ELSE 'ACTIVE'
          END as status
        FROM burn_pool
        ORDER BY month_key DESC
        LIMIT 12
        """)).fetchall()
    except Exception:
        print("  ⚠ burn_pool table not yet created")
        return

    if not rows:
        print("  📭 No burn pool data yet")
        return

    total_signals = sum(r[1] for r in rows)
    print(f"  Total burned signals (across all months): {total_signals}")
    print()

    for month_key, count, burned_at, expires_at, status in rows:
        emoji = {"ACTIVE": "🟢", "EXPIRING SOON": "🟡", "EXPIRED": "🔴"}[status]
        print(f"  {emoji} {month_key}  signals: {count:>6}  expires: {expires_at}  [{status}]")


def check_contributor_volume(session) -> None:
    """Show contributor volume trends."""
    print_header("SPIRITPOOL — CONTRIBUTOR VOLUME")

    try:
        total = session.execute(text("SELECT COUNT(*) FROM contributors")).scalar() or 0
        total_signals = session.execute(text(
            "SELECT COALESCE(SUM(total_signals), 0) FROM contributors"
        )).scalar() or 0
    except Exception:
        print("  ⚠ contributors table not yet created")
        return

    if total == 0:
        print("  📭 No contributors registered yet")
        return

    avg_signals = round(total_signals / total, 1) if total else 0
    print(f"  Total contributors:      {total}")
    print(f"  Total signals ingested:  {total_signals}")
    print(f"  Avg signals/contributor: {avg_signals}")

    # Activity by day (from sp_events collected_at)
    daily_query = text("""
    SELECT
      DATE(collected_at) as day,
      COUNT(*) as events
    FROM sp_events
    WHERE collected_at >= datetime('now', '-7 days')
    GROUP BY DATE(collected_at)
    ORDER BY day DESC
    """)
    try:
        daily_rows = session.execute(daily_query).fetchall()
        if daily_rows:
            print()
            print("  Daily event volume (last 7 days):")
            for day, count in daily_rows:
                bar = "█" * min(count, 50)
                print(f"    {day}  {count:>6}  {bar}")
    except Exception:
        pass


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

        # SpiritPool contributor pipeline health
        check_spiritpool_events_freshness(session)
        check_quarantine_health(session)
        check_session_epochs(session)
        check_burn_pool(session)
        check_contributor_volume(session)

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
