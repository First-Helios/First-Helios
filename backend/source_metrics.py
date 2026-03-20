"""
backend/source_metrics.py — Data source effectiveness metrics.

Aggregates per-source query counts, record yields, success rates,
and trend data from the existing ApiRequestLog and RateBudget tables.

Provides three main views:
  1. get_source_effectiveness()  — all sources, summary + daily sparkline
  2. get_source_detail()         — one source deep dive
  3. get_effectiveness_ranking() — cross-source comparison sorted by yield

Depends on: backend.database (ApiSource, ApiRequestLog, RateBudget)
Called by: server.py (/api/metrics/*)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer as SAInteger, func

from backend.database import (
    ApiRequestLog,
    ApiSource,
    RateBudget,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 1. All-sources effectiveness
# ══════════════════════════════════════════════════════════════════════

def get_source_effectiveness(days: int = 30) -> dict:
    """Per-source summary over the last *days* days.

    Returns a dict with:
      - generated_at: timestamp
      - period_days: requested lookback
      - totals: {queries, records, success_rate, avg_latency_ms}
      - sources: [ {source_key, display_name, queries, records,
                     records_per_query, success_rate, avg_latency_ms,
                     error_rate, daily_trend: [{date, queries, records}]} ]
    """
    engine = init_db()
    session = get_session(engine)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # ── Aggregates per source from RateBudget ────────────────
        budget_rows = (
            session.query(RateBudget)
            .filter(RateBudget.date >= cutoff.date().isoformat())
            .all()
        )

        # source_key → accumulated
        acc: dict[str, dict] = defaultdict(lambda: {
            "queries": 0, "succeeded": 0, "failed": 0,
            "records": 0, "total_latency_ms": 0, "total_bytes": 0,
            "daily": defaultdict(lambda: {"queries": 0, "records": 0}),
        })

        for b in budget_rows:
            a = acc[b.source_key]
            a["queries"] += b.used
            a["succeeded"] += b.succeeded
            a["failed"] += b.failed
            a["records"] += b.total_data_items
            a["total_latency_ms"] += b.total_latency_ms
            a["total_bytes"] += b.total_bytes
            a["daily"][b.date]["queries"] += b.used
            a["daily"][b.date]["records"] += b.total_data_items

        # Fetch display names
        all_sources = {
            s.source_key: s.display_name
            for s in session.query(ApiSource).all()
        }

        # ── Build per-source summaries ───────────────────────────
        sources = []
        total_queries = 0
        total_records = 0
        total_succeeded = 0
        total_latency = 0

        for sk, a in sorted(acc.items()):
            q = a["queries"]
            r = a["records"]
            total_queries += q
            total_records += r
            total_succeeded += a["succeeded"]
            total_latency += a["total_latency_ms"]

            daily_trend = sorted(
                [{"date": d, **v} for d, v in a["daily"].items()],
                key=lambda x: x["date"],
            )

            sources.append({
                "source_key": sk,
                "display_name": all_sources.get(sk, sk),
                "queries": q,
                "succeeded": a["succeeded"],
                "failed": a["failed"],
                "records": r,
                "records_per_query": round(r / q, 2) if q else 0,
                "success_rate": round(a["succeeded"] / q * 100, 1) if q else 0,
                "error_rate": round(a["failed"] / q * 100, 1) if q else 0,
                "avg_latency_ms": round(a["total_latency_ms"] / q, 1) if q else 0,
                "total_bytes": a["total_bytes"],
                "daily_trend": daily_trend,
            })

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_days": days,
            "totals": {
                "queries": total_queries,
                "records": total_records,
                "success_rate": round(total_succeeded / total_queries * 100, 1) if total_queries else 0,
                "avg_latency_ms": round(total_latency / total_queries, 1) if total_queries else 0,
            },
            "sources": sources,
        }
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
# 2. Single-source detail
# ══════════════════════════════════════════════════════════════════════

def get_source_detail(
    source_key: str,
    days: int = 30,
    log_limit: int = 50,
) -> dict:
    """Deep dive for one source: daily breakdown + recent request log.

    Returns:
      - source: ApiSource info
      - summary: aggregated stats for the period
      - daily: [{date, queries, records, success_rate, avg_latency}]
      - request_types: {type: {count, records, success_rate}}
      - recent_requests: last N log entries
    """
    engine = init_db()
    session = get_session(engine)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    cutoff_ts = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        src = session.query(ApiSource).filter_by(source_key=source_key).first()
        if not src:
            return {"error": f"Unknown source: {source_key}"}

        # ── Daily budget data ────────────────────────────────────
        budgets = (
            session.query(RateBudget)
            .filter(
                RateBudget.source_key == source_key,
                RateBudget.date >= cutoff_date,
            )
            .order_by(RateBudget.date)
            .all()
        )

        daily = []
        total_q = total_r = total_succ = total_lat = 0
        for b in budgets:
            total_q += b.used
            total_r += b.total_data_items
            total_succ += b.succeeded
            total_lat += b.total_latency_ms
            daily.append({
                "date": b.date,
                "queries": b.used,
                "records": b.total_data_items,
                "success_rate": b.success_rate,
                "avg_latency_ms": b.avg_latency_ms,
                "utilization_pct": round(b.used / b.daily_limit * 100, 1) if b.daily_limit else 0,
            })

        # ── Request type breakdown ───────────────────────────────
        type_rows = (
            session.query(
                ApiRequestLog.request_type,
                func.count(ApiRequestLog.id).label("cnt"),
                func.sum(ApiRequestLog.data_items_returned).label("items"),
                func.sum(func.cast(ApiRequestLog.success, SAInteger)).label("succ"),
            )
            .filter(
                ApiRequestLog.source_key == source_key,
                ApiRequestLog.requested_at >= cutoff_ts,
            )
            .group_by(ApiRequestLog.request_type)
            .all()
        )

        request_types = {}
        for row in type_rows:
            cnt = row.cnt or 0
            request_types[row.request_type] = {
                "count": cnt,
                "records": row.items or 0,
                "success_rate": round((row.succ or 0) / cnt * 100, 1) if cnt else 0,
            }

        # ── Recent requests ──────────────────────────────────────
        recent = (
            session.query(ApiRequestLog)
            .filter(ApiRequestLog.source_key == source_key)
            .order_by(ApiRequestLog.requested_at.desc())
            .limit(log_limit)
            .all()
        )

        return {
            "source": src.to_dict(),
            "summary": {
                "period_days": days,
                "total_queries": total_q,
                "total_records": total_r,
                "records_per_query": round(total_r / total_q, 2) if total_q else 0,
                "success_rate": round(total_succ / total_q * 100, 1) if total_q else 0,
                "avg_latency_ms": round(total_lat / total_q, 1) if total_q else 0,
            },
            "daily": daily,
            "request_types": request_types,
            "recent_requests": [r.to_dict() for r in recent],
        }
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
# 3. Cross-source effectiveness ranking
# ══════════════════════════════════════════════════════════════════════

def get_effectiveness_ranking(days: int = 7) -> dict:
    """Rank sources by data yield per query — shows which APIs are most useful.

    Returns:
      - period_days
      - rankings: sorted list of {source_key, display_name, queries, records,
                   records_per_query, success_rate, grade}
      - grades: explanation of grading criteria
    """
    engine = init_db()
    session = get_session(engine)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    try:
        budgets = (
            session.query(RateBudget)
            .filter(RateBudget.date >= cutoff)
            .all()
        )

        all_sources = {
            s.source_key: s.display_name
            for s in session.query(ApiSource).all()
        }

        acc: dict[str, dict] = defaultdict(lambda: {
            "queries": 0, "succeeded": 0, "records": 0,
        })

        for b in budgets:
            a = acc[b.source_key]
            a["queries"] += b.used
            a["succeeded"] += b.succeeded
            a["records"] += b.total_data_items

        rankings = []
        for sk, a in acc.items():
            q = a["queries"]
            r = a["records"]
            rpq = round(r / q, 2) if q else 0
            sr = round(a["succeeded"] / q * 100, 1) if q else 0

            # Grade: A / B / C / D / F
            grade = _compute_grade(rpq, sr, q)

            rankings.append({
                "source_key": sk,
                "display_name": all_sources.get(sk, sk),
                "queries": q,
                "records": r,
                "records_per_query": rpq,
                "success_rate": sr,
                "grade": grade,
            })

        # Sort by records_per_query descending, then success_rate
        rankings.sort(key=lambda x: (-x["records_per_query"], -x["success_rate"]))

        return {
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rankings": rankings,
            "grades": {
                "A": "High yield (>10 records/query) + >90% success",
                "B": "Good yield (>5 records/query) + >80% success",
                "C": "Moderate yield (>1 record/query) + >60% success",
                "D": "Low yield (<1 record/query) or <60% success",
                "F": "No data returned or too few queries to evaluate",
            },
        }
    finally:
        session.close()


def _compute_grade(records_per_query: float, success_rate: float, queries: int) -> str:
    """Assign a letter grade based on effectiveness metrics."""
    if queries < 1:
        return "F"
    if records_per_query == 0:
        return "F"
    if records_per_query > 10 and success_rate >= 90:
        return "A"
    if records_per_query > 5 and success_rate >= 80:
        return "B"
    if records_per_query > 1 and success_rate >= 60:
        return "C"
    return "D"
