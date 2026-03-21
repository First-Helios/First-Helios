"""
pipeline/tracing.py — Structured span recording for pipeline execution.

PipelineTrace is created at the start of execute_query() and threaded through
each stage.  Each logical unit (validator, scraper call, ingest, scoring) appends
a TraceSpan.  The completed trace is attached to the ConciseResult for logging
and observability.

Usage
-----
    from pipeline.tracing import PipelineTrace, TraceSpan
    from datetime import datetime

    trace = PipelineTrace(intent="poi_chain_locations", brand="starbucks", region="austin_tx")

    span = TraceSpan(
        span_id="s-val",
        name="validator.validate_and_check",
        started_at=datetime.utcnow(),
        status="success",
    )
    span.ended_at = datetime.utcnow()
    trace.spans.append(span)

    print(trace.to_dict())
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TraceSpan:
    """A single timed stage within a pipeline execution.

    Fields
    ------
    span_id     unique ID for this span (set by caller)
    name        dotted path identifying the code stage (e.g. "executor._execute_poi_chain")
    started_at  UTC datetime when the span began
    status      "running" | "success" | "failed" | "skipped"
    ended_at    UTC datetime when the span ended (None if still running)
    records_in  number of records received at the start of this span
    records_out number of records emitted at the end of this span
    error       exception message if status == "failed"
    metadata    arbitrary key/value for extra context (source_key, adapter, etc.)
    """

    span_id: str
    name: str
    started_at: datetime
    status: str                              # "running" | "success" | "failed" | "skipped"
    ended_at: Optional[datetime] = None
    records_in: int = 0
    records_out: int = 0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "records_in": self.records_in,
            "records_out": self.records_out,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class PipelineTrace:
    """End-to-end execution trace for a single AgentQuery.

    Fields
    ------
    trace_id            unique ID auto-generated at creation
    intent              intent enum value being executed
    brand               brand key (or None)
    region              region key
    mode                agent mode (collect / analyze / monitor / mixed)
    spans               ordered list of TraceSpans, one per pipeline stage
    records_written     total DB rows written across all stages
    freshness_stamped   True if a SourceFreshness row was updated this run
    started_at          when the trace was created
    ended_at            when the final span completed (set by caller)
    """

    intent: Optional[str] = None
    brand: Optional[str] = None
    region: Optional[str] = None
    mode: Optional[str] = None
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    spans: list[TraceSpan] = field(default_factory=list)
    records_written: int = 0
    freshness_stamped: bool = False
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None

    def add_span(
        self,
        name: str,
        status: str = "running",
        *,
        span_id: Optional[str] = None,
        **metadata,
    ) -> TraceSpan:
        """Create a new TraceSpan, append it to this trace, and return it."""
        span = TraceSpan(
            span_id=span_id or str(uuid.uuid4())[:8],
            name=name,
            started_at=datetime.utcnow(),
            status=status,
            metadata=metadata,
        )
        self.spans.append(span)
        return span

    def finish_span(self, span: TraceSpan, status: str = "success", error: Optional[str] = None) -> None:
        """Mark a span as complete."""
        span.status = status
        span.ended_at = datetime.utcnow()
        if error:
            span.error = error

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "intent": self.intent,
            "brand": self.brand,
            "region": self.region,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "records_written": self.records_written,
            "freshness_stamped": self.freshness_stamped,
            "spans": [s.to_dict() for s in self.spans],
        }
