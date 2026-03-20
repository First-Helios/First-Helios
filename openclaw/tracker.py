"""
openclaw/tracker.py — Per-request success/fail tracker with daily rollup.

Every API request the agent triggers gets logged here with:
  - source, intent, search term
  - success/fail status
  - latency, records returned
  - timestamp

Daily rollups show the agent what worked and what didn't, so it can
adjust strategy.  This sits alongside rate_manager (which tracks budget)
but focuses on the AGENT's view of request outcomes.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRACKER_LOG_DIR = _PROJECT_ROOT / "data" / "openclaw_logs"


@dataclass
class RequestRecord:
    """One API request the agent caused."""
    request_id: str
    timestamp: str
    intent: str
    industry: str
    brand: str
    search_term: str
    source: str              # e.g. "bls_v1", "overpass_api"
    success: bool
    status_code: Optional[int] = None
    records_returned: int = 0
    latency_ms: int = 0
    error_message: Optional[str] = None
    prevalidation_passed: bool = True

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "intent": self.intent,
            "industry": self.industry,
            "brand": self.brand,
            "search_term": self.search_term,
            "source": self.source,
            "success": self.success,
            "status_code": self.status_code,
            "records_returned": self.records_returned,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "prevalidation_passed": self.prevalidation_passed,
        }


@dataclass
class DailyRollup:
    """Summary of one day's API request outcomes."""
    date: str
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    prevalidation_rejected: int = 0
    total_records: int = 0
    avg_latency_ms: float = 0.0
    by_source: dict = field(default_factory=dict)     # source → {success, fail, records}
    by_intent: dict = field(default_factory=dict)     # intent → {success, fail, records}
    by_industry: dict = field(default_factory=dict)   # industry → {success, fail}
    top_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "total_requests": self.total_requests,
            "successful": self.successful,
            "failed": self.failed,
            "prevalidation_rejected": self.prevalidation_rejected,
            "success_rate": round(self.successful / max(self.total_requests, 1) * 100, 1),
            "total_records": self.total_records,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "by_source": self.by_source,
            "by_intent": self.by_intent,
            "by_industry": self.by_industry,
            "top_errors": self.top_errors[:10],
        }


class RequestTracker:
    """Thread-safe tracker for all agent-triggered API requests.

    Stores records in memory (today's buffer) and flushes to JSON
    log files in data/openclaw_logs/ daily.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._today: str = datetime.utcnow().strftime("%Y-%m-%d")
        self._records: list[RequestRecord] = []
        self._counter: int = 0

        # Ensure log directory exists
        TRACKER_LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _rotate_if_needed(self) -> None:
        """Flush yesterday's records to disk if date changed."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self._today and self._records:
            self._flush_to_disk(self._today)
            self._records.clear()
            self._counter = 0
            self._today = today

    def log_request(
        self,
        intent: str,
        source: str,
        success: bool,
        industry: str = "",
        brand: str = "",
        search_term: str = "",
        status_code: Optional[int] = None,
        records_returned: int = 0,
        latency_ms: int = 0,
        error_message: Optional[str] = None,
        prevalidation_passed: bool = True,
    ) -> RequestRecord:
        """Log a single API request result."""
        with self._lock:
            self._rotate_if_needed()
            self._counter += 1
            rec = RequestRecord(
                request_id=f"{self._today}-{self._counter:04d}",
                timestamp=datetime.utcnow().isoformat(),
                intent=intent,
                industry=industry,
                brand=brand,
                search_term=search_term,
                source=source,
                success=success,
                status_code=status_code,
                records_returned=records_returned,
                latency_ms=latency_ms,
                error_message=error_message,
                prevalidation_passed=prevalidation_passed,
            )
            self._records.append(rec)
            logger.debug(
                "[Tracker] %s %s/%s success=%s records=%d",
                rec.request_id, intent, source, success, records_returned,
            )
            return rec

    def log_prevalidation_rejection(
        self,
        intent: str,
        industry: str = "",
        brand: str = "",
        search_term: str = "",
        rejection_reason: str = "",
    ) -> RequestRecord:
        """Log a query that was rejected by pre-validation (no API call made)."""
        return self.log_request(
            intent=intent,
            source="prevalidation",
            success=False,
            industry=industry,
            brand=brand,
            search_term=search_term,
            error_message=f"Pre-validation rejected: {rejection_reason}",
            prevalidation_passed=False,
        )

    def get_today_rollup(self) -> DailyRollup:
        """Compute rollup for today's requests."""
        with self._lock:
            self._rotate_if_needed()
            return self._compute_rollup(self._today, self._records)

    def get_rollup(self, date: str) -> Optional[DailyRollup]:
        """Get rollup for a specific date. Loads from disk if needed."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if date == today:
            return self.get_today_rollup()

        # Try loading from disk
        records = self._load_from_disk(date)
        if records is not None:
            return self._compute_rollup(date, records)
        return None

    def get_recent_records(self, limit: int = 50) -> list[dict]:
        """Return the most recent records as dicts."""
        with self._lock:
            return [r.to_dict() for r in self._records[-limit:]]

    def _compute_rollup(self, date: str, records: list[RequestRecord]) -> DailyRollup:
        """Compute summary statistics from a list of records."""
        rollup = DailyRollup(date=date)
        rollup.total_requests = len(records)

        latencies = []
        errors: dict[str, int] = {}

        for r in records:
            if not r.prevalidation_passed:
                rollup.prevalidation_rejected += 1
            elif r.success:
                rollup.successful += 1
            else:
                rollup.failed += 1

            rollup.total_records += r.records_returned
            if r.latency_ms > 0:
                latencies.append(r.latency_ms)

            if r.error_message:
                short = r.error_message[:80]
                errors[short] = errors.get(short, 0) + 1

            # By source
            if r.source not in rollup.by_source:
                rollup.by_source[r.source] = {"success": 0, "fail": 0, "records": 0}
            if r.success:
                rollup.by_source[r.source]["success"] += 1
            else:
                rollup.by_source[r.source]["fail"] += 1
            rollup.by_source[r.source]["records"] += r.records_returned

            # By intent
            if r.intent not in rollup.by_intent:
                rollup.by_intent[r.intent] = {"success": 0, "fail": 0, "records": 0}
            if r.success:
                rollup.by_intent[r.intent]["success"] += 1
            else:
                rollup.by_intent[r.intent]["fail"] += 1
            rollup.by_intent[r.intent]["records"] += r.records_returned

            # By industry
            if r.industry:
                if r.industry not in rollup.by_industry:
                    rollup.by_industry[r.industry] = {"success": 0, "fail": 0}
                if r.success:
                    rollup.by_industry[r.industry]["success"] += 1
                else:
                    rollup.by_industry[r.industry]["fail"] += 1

        if latencies:
            rollup.avg_latency_ms = sum(latencies) / len(latencies)

        # Top errors by frequency
        rollup.top_errors = sorted(errors, key=errors.get, reverse=True)[:10]

        return rollup

    def _flush_to_disk(self, date: str) -> None:
        """Write a day's records to a JSON file."""
        path = TRACKER_LOG_DIR / f"requests_{date}.json"
        try:
            data = [r.to_dict() for r in self._records]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info("[Tracker] Flushed %d records to %s", len(data), path)
        except Exception as e:
            logger.error("[Tracker] Failed to flush: %s", e)

    def _load_from_disk(self, date: str) -> Optional[list[RequestRecord]]:
        """Load records from a daily JSON file."""
        path = TRACKER_LOG_DIR / f"requests_{date}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records = []
            for d in data:
                records.append(RequestRecord(**d))
            return records
        except Exception as e:
            logger.error("[Tracker] Failed to load %s: %s", path, e)
            return None

    def flush_now(self) -> None:
        """Manually flush today's records (e.g. on shutdown)."""
        with self._lock:
            if self._records:
                self._flush_to_disk(self._today)


# Module-level singleton
request_tracker = RequestTracker()
