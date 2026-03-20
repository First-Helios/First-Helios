"""
agent_interface/queue_manager.py — Thread-safe agent query queue.

Manages submission, validation, execution, pause/resume, and status
for all agent queries. Synchronous execution now; upgrade to async later.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

from backend.rate_manager import rate_manager

from agent_interface.executor import execute
from agent_interface.schemas import (
    AgentQuery,
    ConciseResult,
    QueueStatus,
    ResultStatus,
)
from agent_interface.validator import validate_and_check

logger = logging.getLogger(__name__)


class AgentQueueManager:
    """Thread-safe singleton for managing agent query execution.

    Usage:
        from agent_interface.queue_manager import agent_queue
        result = agent_queue.submit(query)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._pause_reason: Optional[str] = None
        self._completed_today: int = 0
        self._failed_today: int = 0
        self._last_reset_date: str = datetime.utcnow().strftime("%Y-%m-%d")
        self._history: list[dict] = []  # Recent query results (ring buffer)
        self._max_history = 100

    def _reset_daily_counters(self) -> None:
        """Reset daily counters if the date has changed."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._completed_today = 0
            self._failed_today = 0
            self._last_reset_date = today

    def submit(self, query: AgentQuery) -> ConciseResult:
        """Validate and execute a single agent query.

        Flow: pause check → validate → execute → record result
        """
        with self._lock:
            self._reset_daily_counters()

            # 1. Pause check
            if self._paused:
                return ConciseResult(
                    query_id=query.query_id,
                    status=ResultStatus.PAUSED,
                    intent=query.intent,
                    errors=[
                        f"Queue is paused: {self._pause_reason or 'no reason given'}. "
                        f"POST /api/agent/queue/resume to resume."
                    ],
                )

        # 2. Pre-flight validation (outside lock — may do DB queries)
        preflight = validate_and_check(query)
        if preflight is not None:
            self._record_result(preflight)
            return preflight

        # 3. Execute (outside lock — may take seconds)
        result = execute(query)

        # 4. Record result
        with self._lock:
            self._reset_daily_counters()
            if result.status in (ResultStatus.COMPLETED, ResultStatus.PARTIAL):
                self._completed_today += 1
            elif result.status == ResultStatus.FAILED:
                self._failed_today += 1

        self._record_result(result)
        return result

    def submit_batch(self, queries: list[AgentQuery]) -> list[ConciseResult]:
        """Submit multiple queries with cross-query dedup.

        Later queries benefit from earlier ones (freshness dedup).
        """
        results: list[ConciseResult] = []
        for query in queries:
            result = self.submit(query)
            results.append(result)
        return results

    def pause(self, reason: str = "") -> dict:
        """Pause the queue — all new queries return PAUSED status."""
        with self._lock:
            self._paused = True
            self._pause_reason = reason or "Paused by operator"
            logger.info("[QueueManager] Paused: %s", self._pause_reason)
            return {
                "status": "paused",
                "reason": self._pause_reason,
                "paused_at": datetime.utcnow().isoformat(),
            }

    def resume(self) -> dict:
        """Resume the queue."""
        with self._lock:
            was_paused = self._paused
            self._paused = False
            old_reason = self._pause_reason
            self._pause_reason = None
            logger.info("[QueueManager] Resumed (was paused: %s)", was_paused)
            return {
                "status": "resumed",
                "was_paused": was_paused,
                "previous_reason": old_reason,
                "resumed_at": datetime.utcnow().isoformat(),
            }

    def status(self) -> QueueStatus:
        """Return current queue state + budget summary."""
        with self._lock:
            self._reset_daily_counters()

            # Build budget summary from rate_manager
            budget_summary = {}
            try:
                all_status = rate_manager.get_all_status()
                for s in all_status:
                    budget_summary[s["source_key"]] = {
                        "used": s.get("used", 0),
                        "remaining": s.get("remaining", 0),
                        "daily_limit": s.get("daily_limit", 0),
                        "utilization_pct": s.get("utilization_pct", 0),
                    }
            except Exception as e:
                logger.warning("[QueueManager] Budget fetch error: %s", e)

            return QueueStatus(
                is_paused=self._paused,
                pause_reason=self._pause_reason,
                total_pending=0,  # synchronous for now
                total_reserved=0,
                completed_today=self._completed_today,
                failed_today=self._failed_today,
                budget_summary=budget_summary,
            )

    def get_result(self, query_id: str) -> Optional[ConciseResult]:
        """Look up a result by query ID from recent history."""
        with self._lock:
            for entry in reversed(self._history):
                if entry.get("query_id") == query_id:
                    # Reconstruct a summary dict (not full ConciseResult)
                    return entry
            return None

    def get_recent_history(self, limit: int = 20) -> list[dict]:
        """Return recent query results."""
        with self._lock:
            return list(reversed(self._history[-limit:]))

    def _record_result(self, result: ConciseResult) -> None:
        """Store a result in the ring buffer."""
        with self._lock:
            entry = result.to_dict()
            entry["recorded_at"] = datetime.utcnow().isoformat()
            self._history.append(entry)
            # Trim to max size
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]


# Module-level singleton
agent_queue = AgentQueueManager()
