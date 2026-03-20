"""
agent_interface/schemas.py — Enums, input/output dataclasses for the agent API.

All agent queries must use these constrained enumerations.
Invalid enum values result in HTTP 422 with valid_options for self-correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


# ══════════════════════════════════════════════════════════════════════
# Constrained Enumerations — agent MUST pick from these
# ══════════════════════════════════════════════════════════════════════


class Intent(str, Enum):
    """What question the agent is asking."""
    POI_CHAIN_LOCATIONS = "poi_chain_locations"       # Where are all X stores in region?
    POI_LOCAL_DENSITY = "poi_local_density"            # How many local employers near a point?
    WAGE_BASELINE = "wage_baseline"                    # What do workers earn in this industry/region?
    JOB_POSTING_VOLUME = "job_posting_volume"          # How many open positions for X in region?
    SENTIMENT_CHECK = "sentiment_check"                # What do workers say about X?
    ECONOMIC_CONTEXT = "economic_context"              # Unemployment, CPI, cost of living
    SCORE_REFRESH = "score_refresh"                    # Recompute scores with latest data
    DATA_QUALITY_AUDIT = "data_quality_audit"          # What's stale, missing, conflicting?
    CAMPAIGN_STATUS = "campaign_status"                # What's the state of the queue?


class Region(str, Enum):
    """Supported geographic regions."""
    AUSTIN_TX = "austin_tx"


class Industry(str, Enum):
    """Internal industry keys matching ref_industry table."""
    COFFEE_CAFE = "coffee_cafe"
    FAST_FOOD = "fast_food"
    FULL_SERVICE_RESTAURANT = "full_service_restaurant"
    RETAIL_GENERAL = "retail_general"
    ACCOMMODATION = "accommodation"


class Brand(str, Enum):
    """Known chain brand keys matching ref_brands table."""
    STARBUCKS = "starbucks"
    DUTCH_BROS = "dutch_bros"
    MCDONALDS = "mcdonalds"
    WHATABURGER = "whataburger"
    CHIPOTLE = "chipotle"
    TARGET = "target"


class DataSource(str, Enum):
    """Which collector(s) to use."""
    AUTO = "auto"                   # system picks best available
    ALLTHEPLACES = "alltheplaces"
    OVERTURE = "overture"
    OSM = "osm"
    BLS = "bls"
    JOBSPY = "jobspy"
    REDDIT = "reddit"
    WORKDAY = "workday"


class QueuePriority(str, Enum):
    """Execution priority in the queue."""
    CRITICAL = "critical"       # weight 10
    HIGH = "high"               # weight 25
    NORMAL = "normal"           # weight 50
    LOW = "low"                 # weight 75
    BACKFILL = "backfill"       # weight 90

    @property
    def weight(self) -> int:
        return {
            "critical": 10,
            "high": 25,
            "normal": 50,
            "low": 75,
            "backfill": 90,
        }[self.value]


class ResultStatus(str, Enum):
    """Outcome of a query execution."""
    COMPLETED = "completed"
    PARTIAL = "partial"
    QUEUED = "queued"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    PAUSED = "paused"
    NO_BUDGET = "no_budget"
    FAILED = "failed"


# ══════════════════════════════════════════════════════════════════════
# Freshness thresholds (days) — how old data can be before re-collection
# ══════════════════════════════════════════════════════════════════════

FRESHNESS_THRESHOLDS: dict[str, float] = {
    Intent.POI_CHAIN_LOCATIONS.value: 7.0,
    Intent.POI_LOCAL_DENSITY.value: 7.0,
    Intent.WAGE_BASELINE.value: 30.0,
    Intent.JOB_POSTING_VOLUME.value: 1.0,
    Intent.SENTIMENT_CHECK.value: 3.0,
    Intent.ECONOMIC_CONTEXT.value: 90.0,
    Intent.SCORE_REFRESH.value: 1.0,
    Intent.DATA_QUALITY_AUDIT.value: 0.0,   # always runs
    Intent.CAMPAIGN_STATUS.value: 0.0,       # always runs
}

# ══════════════════════════════════════════════════════════════════════
# Intent → required fields validation
# ══════════════════════════════════════════════════════════════════════

INTENT_REQUIRED_FIELDS: dict[str, list[str]] = {
    Intent.POI_CHAIN_LOCATIONS.value: ["brand"],
    Intent.POI_LOCAL_DENSITY.value: ["industry"],
    Intent.WAGE_BASELINE.value: ["industry"],
    Intent.JOB_POSTING_VOLUME.value: ["brand"],
    Intent.SENTIMENT_CHECK.value: ["brand"],
    Intent.ECONOMIC_CONTEXT.value: [],
    Intent.SCORE_REFRESH.value: [],
    Intent.DATA_QUALITY_AUDIT.value: [],
    Intent.CAMPAIGN_STATUS.value: [],
}


# ══════════════════════════════════════════════════════════════════════
# Input dataclass
# ══════════════════════════════════════════════════════════════════════


@dataclass
class AgentQuery:
    """Structured query from the LLM agent.

    Every field is validated against the constrained enumerations above.
    """

    intent: Intent
    region: Region
    priority: QueuePriority = QueuePriority.NORMAL
    brand: Optional[Brand] = None
    industry: Optional[Industry] = None
    source_preference: DataSource = DataSource.AUTO
    max_results: int = 500
    max_budget_spend: int = 5           # max API calls for this query
    known_count: Optional[int] = None   # what agent already has (for dedup)
    reason: str = ""                    # why (for logging)

    # Set at submission time
    query_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    submitted_at: datetime = field(default_factory=datetime.utcnow)

    def validate(self) -> list[str]:
        """Return list of validation errors, or empty list if valid."""
        errors: list[str] = []

        # Check intent-specific required fields
        required = INTENT_REQUIRED_FIELDS.get(self.intent.value, [])
        for f in required:
            val = getattr(self, f, None)
            if val is None:
                errors.append(
                    f"Intent '{self.intent.value}' requires '{f}'. "
                    f"Valid options: {[e.value for e in _FIELD_ENUM_MAP.get(f, [])]}"
                )

        # Cap max_results
        if self.max_results > 5000:
            errors.append("max_results cannot exceed 5000")
        if self.max_results < 1:
            errors.append("max_results must be >= 1")

        # Cap max_budget_spend
        if self.max_budget_spend > 50:
            errors.append("max_budget_spend cannot exceed 50")
        if self.max_budget_spend < 1:
            errors.append("max_budget_spend must be >= 1")

        return errors

    def to_dict(self) -> dict:
        """Serialize for JSON response / logging."""
        return {
            "query_id": self.query_id,
            "intent": self.intent.value,
            "region": self.region.value,
            "priority": self.priority.value,
            "brand": self.brand.value if self.brand else None,
            "industry": self.industry.value if self.industry else None,
            "source_preference": self.source_preference.value,
            "max_results": self.max_results,
            "max_budget_spend": self.max_budget_spend,
            "known_count": self.known_count,
            "reason": self.reason,
            "submitted_at": self.submitted_at.isoformat(),
        }


# Helper for validation error messages
_FIELD_ENUM_MAP: dict[str, type] = {
    "brand": Brand,
    "industry": Industry,
    "region": Region,
}


# ══════════════════════════════════════════════════════════════════════
# Output dataclasses
# ══════════════════════════════════════════════════════════════════════


@dataclass
class ConciseResult:
    """Structured response from query execution."""

    query_id: str
    status: ResultStatus
    intent: Intent
    records_found: int = 0
    records_new: int = 0
    records_updated: int = 0
    staleness_days: Optional[float] = None    # age of freshest existing data
    coverage_pct: Optional[float] = None      # estimated coverage
    source_agreement: Optional[float] = None  # do multiple sources agree? 0-1
    api_calls_used: int = 0
    api_calls_remaining_today: Optional[int] = None
    estimated_seconds: Optional[float] = None
    anomalies: list[str] = field(default_factory=list)
    suggested_next: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    valid_options: Optional[dict] = None      # populated on REJECTED status

    def to_dict(self) -> dict:
        """Serialize for JSON response."""
        d = {
            "query_id": self.query_id,
            "status": self.status.value,
            "intent": self.intent.value,
            "records_found": self.records_found,
            "records_new": self.records_new,
            "records_updated": self.records_updated,
            "staleness_days": self.staleness_days,
            "coverage_pct": self.coverage_pct,
            "source_agreement": self.source_agreement,
            "api_calls_used": self.api_calls_used,
            "api_calls_remaining_today": self.api_calls_remaining_today,
            "estimated_seconds": self.estimated_seconds,
            "anomalies": self.anomalies,
            "suggested_next": self.suggested_next,
            "errors": self.errors,
        }
        if self.valid_options:
            d["valid_options"] = self.valid_options
        return d


@dataclass
class QueueStatus:
    """Current state of the agent execution queue."""

    is_paused: bool = False
    pause_reason: Optional[str] = None
    total_pending: int = 0
    total_reserved: int = 0
    completed_today: int = 0
    failed_today: int = 0
    budget_summary: dict = field(default_factory=dict)  # source → {used, remaining, limit}

    def to_dict(self) -> dict:
        return {
            "is_paused": self.is_paused,
            "pause_reason": self.pause_reason,
            "total_pending": self.total_pending,
            "total_reserved": self.total_reserved,
            "completed_today": self.completed_today,
            "failed_today": self.failed_today,
            "budget_summary": self.budget_summary,
        }


# ══════════════════════════════════════════════════════════════════════
# Helper: get all valid options (for the /api/agent/options endpoint)
# ══════════════════════════════════════════════════════════════════════


def get_all_options() -> dict:
    """Return all valid enum values the agent can use.

    This is the first thing an agent should request so it knows
    what inputs are acceptable.
    """
    return {
        "intents": [
            {"value": e.value, "description": _INTENT_DESCRIPTIONS.get(e.value, "")}
            for e in Intent
        ],
        "regions": [{"value": e.value} for e in Region],
        "industries": [{"value": e.value} for e in Industry],
        "brands": [{"value": e.value} for e in Brand],
        "data_sources": [{"value": e.value} for e in DataSource],
        "priorities": [
            {"value": e.value, "weight": e.weight}
            for e in QueuePriority
        ],
        "intent_required_fields": INTENT_REQUIRED_FIELDS,
        "freshness_thresholds_days": FRESHNESS_THRESHOLDS,
    }


_INTENT_DESCRIPTIONS: dict[str, str] = {
    "poi_chain_locations": "Find all locations for a chain brand in the region",
    "poi_local_density": "Count local (non-chain) employers in an industry near chain stores",
    "wage_baseline": "Fetch BLS wage data for an industry/region",
    "job_posting_volume": "Count open job postings for a brand in the region",
    "sentiment_check": "Gather worker sentiment from Reddit/reviews for a brand",
    "economic_context": "Fetch macro-economic indicators (unemployment, CPI) for the region",
    "score_refresh": "Recompute composite staffing scores with latest data",
    "data_quality_audit": "Check for stale, missing, or conflicting data",
    "campaign_status": "Report on queue state and budget usage",
}


def parse_agent_query(data: dict) -> tuple[Optional[AgentQuery], list[str]]:
    """Parse a raw dict (from JSON request body) into an AgentQuery.

    Returns:
        (AgentQuery, []) on success
        (None, [error_strings]) on validation failure
    """
    errors: list[str] = []

    # Parse intent
    raw_intent = data.get("intent", "")
    try:
        intent = Intent(raw_intent)
    except ValueError:
        errors.append(
            f"Invalid intent '{raw_intent}'. "
            f"Valid options: {[e.value for e in Intent]}"
        )
        # Return early with valid_options on enum parse failure
        return None, errors

    # Parse region
    raw_region = data.get("region", "")
    try:
        region = Region(raw_region)
    except ValueError:
        errors.append(
            f"Invalid region '{raw_region}'. "
            f"Valid options: {[e.value for e in Region]}"
        )
        return None, errors

    # Parse optional enums
    brand = None
    if data.get("brand"):
        try:
            brand = Brand(data["brand"])
        except ValueError:
            errors.append(
                f"Invalid brand '{data['brand']}'. "
                f"Valid options: {[e.value for e in Brand]}"
            )

    industry = None
    if data.get("industry"):
        try:
            industry = Industry(data["industry"])
        except ValueError:
            errors.append(
                f"Invalid industry '{data['industry']}'. "
                f"Valid options: {[e.value for e in Industry]}"
            )

    priority = QueuePriority.NORMAL
    if data.get("priority"):
        try:
            priority = QueuePriority(data["priority"])
        except ValueError:
            errors.append(
                f"Invalid priority '{data['priority']}'. "
                f"Valid options: {[e.value for e in QueuePriority]}"
            )

    source_preference = DataSource.AUTO
    if data.get("source_preference"):
        try:
            source_preference = DataSource(data["source_preference"])
        except ValueError:
            errors.append(
                f"Invalid source_preference '{data['source_preference']}'. "
                f"Valid options: {[e.value for e in DataSource]}"
            )

    if errors:
        return None, errors

    query = AgentQuery(
        intent=intent,
        region=region,
        priority=priority,
        brand=brand,
        industry=industry,
        source_preference=source_preference,
        max_results=min(data.get("max_results", 500), 5000),
        max_budget_spend=min(data.get("max_budget_spend", 5), 50),
        known_count=data.get("known_count"),
        reason=data.get("reason", ""),
    )

    # Validate intent-specific requirements
    validation_errors = query.validate()
    if validation_errors:
        return None, validation_errors

    return query, []
