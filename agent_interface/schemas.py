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
    DISCOVERY_SCAN = "discovery_scan"                  # What should we collect next?


class Region(str, Enum):
    """Supported geographic regions."""
    AUSTIN_TX = "austin_tx"


class Industry(str, Enum):
    """Internal industry keys matching ref_industry table."""
    COFFEE_CAFE = "coffee_cafe"
    FAST_FOOD = "fast_food"
    FULL_SERVICE_RESTAURANT = "full_service_restaurant"
    RETAIL_GENERAL = "retail_general"
    RETAIL_GROCERY = "retail_grocery"
    HEALTHCARE_CLINIC = "healthcare_clinic"
    PHARMACY = "pharmacy"
    ACCOMMODATION = "accommodation"
    FITNESS_WELLNESS = "fitness_wellness"
    CHILDCARE = "childcare"
    HAIR_BEAUTY = "hair_beauty"
    AUTO_REPAIR = "auto_repair"
    HVAC_SKILLED_TRADES = "hvac_skilled_trades"


class Brand(str, Enum):
    """Known chain brand keys matching ref_brands table."""
    # Coffee & Café
    STARBUCKS = "starbucks"
    DUTCH_BROS = "dutch_bros"
    PEETS = "peets"
    DUNKIN = "dunkin"
    # Fast food
    MCDONALDS = "mcdonalds"
    WHATABURGER = "whataburger"
    CHIPOTLE = "chipotle"
    CHICKFILA = "chickfila"
    WENDYS = "wendys"
    # Full-service restaurant
    APPLEBEES = "applebees"
    CHILIS = "chilis"
    OLIVE_GARDEN = "olive_garden"
    IHOP = "ihop"
    # Retail general
    TARGET = "target"
    WALMART = "walmart"
    COSTCO = "costco"
    # Retail grocery
    HEB = "heb"
    KROGER = "kroger"
    WHOLE_FOODS = "whole_foods"
    TRADER_JOES = "trader_joes"
    # Healthcare
    CVS_MINUTECLINIC = "cvs_minuteclinic"
    WALGREENS_CLINIC = "walgreens_clinic"
    HCA = "hca"
    ASCENSION = "ascension"
    # Pharmacy
    CVS = "cvs"
    WALGREENS = "walgreens"
    # Accommodation
    MARRIOTT = "marriott"
    HILTON = "hilton"
    HYATT = "hyatt"
    # Fitness & Wellness
    PLANET_FITNESS = "planet_fitness"
    LA_FITNESS = "la_fitness"
    ORANGETHEORY = "orangetheory"
    # Childcare
    KINDERCARE = "kindercare"
    BRIGHT_HORIZONS = "bright_horizons"
    GODDARD_SCHOOL = "goddard_school"
    # Hair & Beauty
    GREAT_CLIPS = "great_clips"
    SUPERCUTS = "supercuts"
    SPORT_CLIPS = "sport_clips"
    FANTASTIC_SAMS = "fantastic_sams"
    # Auto Repair & Maintenance
    JIFFY_LUBE = "jiffy_lube"
    MIDAS = "midas"
    FIRESTONE = "firestone"
    PEP_BOYS = "pep_boys"
    VALVOLINE = "valvoline"
    # HVAC & Skilled Trades
    SERVICE_EXPERTS = "service_experts"
    AIRE_SERV = "aire_serv"
    ONE_HOUR_HEATING = "one_hour_heating"
    MR_ELECTRIC = "mr_electric"
    ROTO_ROOTER = "roto_rooter"


class AgentMode(str, Enum):
    """Operational mode controlling freshness, fallbacks, and success criteria."""
    COLLECT = "collect"     # External API collection — bypass freshness, no DB fallback
    ANALYZE = "analyze"     # Compute on existing data — no external API calls
    MONITOR = "monitor"     # Lightweight health/status checks — read-only
    MIXED   = "mixed"       # Smart default — freshness-aware, DB fallback allowed


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
    Intent.POI_CHAIN_LOCATIONS.value: 60.0,   # locations rarely change
    Intent.POI_LOCAL_DENSITY.value: 60.0,      # local employers stable
    Intent.WAGE_BASELINE.value: 90.0,          # BLS data quarterly
    Intent.JOB_POSTING_VOLUME.value: 14.0,     # job boards every ~2 weeks
    Intent.SENTIMENT_CHECK.value: 14.0,        # sentiment shifts slowly
    Intent.ECONOMIC_CONTEXT.value: 90.0,       # macro data quarterly
    Intent.SCORE_REFRESH.value: 1.0,           # recompute daily is fine
    Intent.DATA_QUALITY_AUDIT.value: 0.0,      # always runs
    Intent.CAMPAIGN_STATUS.value: 0.0,         # always runs
    Intent.DISCOVERY_SCAN.value: 0.0,          # always runs — analyzes DB, no API calls
}

# ══════════════════════════════════════════════════════════════════════
# Mode configuration — per-mode behavioral rules
# ══════════════════════════════════════════════════════════════════════

# Intents that hit external APIs (collectors)
COLLECTION_INTENTS: set[str] = {
    Intent.POI_CHAIN_LOCATIONS.value,
    Intent.POI_LOCAL_DENSITY.value,
    Intent.WAGE_BASELINE.value,
    Intent.JOB_POSTING_VOLUME.value,
    Intent.SENTIMENT_CHECK.value,
}

# Intents that compute on existing data (no external calls)
ANALYSIS_INTENTS: set[str] = {
    Intent.SCORE_REFRESH.value,
    Intent.DATA_QUALITY_AUDIT.value,
    Intent.DISCOVERY_SCAN.value,
    Intent.ECONOMIC_CONTEXT.value,
}

# Lightweight read-only status intents
MONITOR_INTENTS: set[str] = {
    Intent.DATA_QUALITY_AUDIT.value,
    Intent.CAMPAIGN_STATUS.value,
}


@dataclass
class ModeConfig:
    """Behavioral rules for an agent operational mode."""
    name: str
    description: str
    bypass_freshness: bool          # skip freshness gates entirely
    allow_db_fallback: bool         # if no collector runs, report DB data
    require_new_data: bool          # success requires records_new > 0
    allow_collection: bool          # allow external API calls
    allowed_intents: set[str]       # which intents can be executed
    max_api_calls_per_query: int    # per-query API budget cap
    success_on_partial: bool        # treat PARTIAL status as success in logging

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "bypass_freshness": self.bypass_freshness,
            "allow_db_fallback": self.allow_db_fallback,
            "require_new_data": self.require_new_data,
            "allow_collection": self.allow_collection,
            "allowed_intents": sorted(self.allowed_intents),
            "max_api_calls_per_query": self.max_api_calls_per_query,
            "success_on_partial": self.success_on_partial,
        }


MODE_CONFIG: dict[str, ModeConfig] = {
    AgentMode.COLLECT.value: ModeConfig(
        name="collect",
        description=(
            "Targeted data acquisition from external APIs for STALE or missing data. "
            "Freshness gates ACTIVE — queries for already-fresh data are rejected "
            "before the agent considers them. No DB fallback — if a collector fails, "
            "the query fails. Success requires at least one new record from an external source."
        ),
        bypass_freshness=False,
        allow_db_fallback=False,
        require_new_data=True,
        allow_collection=True,
        allowed_intents=COLLECTION_INTENTS | {
            Intent.DATA_QUALITY_AUDIT.value,   # allowed for planning
            Intent.CAMPAIGN_STATUS.value,       # allowed for budget checks
            Intent.DISCOVERY_SCAN.value,        # allowed for targeting
        },
        max_api_calls_per_query=10,
        success_on_partial=False,
    ),
    AgentMode.ANALYZE.value: ModeConfig(
        name="analyze",
        description=(
            "Compute insights from existing data. "
            "No external API calls attempted. "
            "Success = computation completed on DB data."
        ),
        bypass_freshness=True,
        allow_db_fallback=True,
        require_new_data=False,
        allow_collection=False,
        allowed_intents=ANALYSIS_INTENTS | {Intent.CAMPAIGN_STATUS.value},
        max_api_calls_per_query=0,
        success_on_partial=True,
    ),
    AgentMode.MONITOR.value: ModeConfig(
        name="monitor",
        description=(
            "Lightweight health and status checks. "
            "Read-only, no collection or scoring mutations. "
            "Success = report generated."
        ),
        bypass_freshness=True,
        allow_db_fallback=True,
        require_new_data=False,
        allow_collection=False,
        allowed_intents=MONITOR_INTENTS,
        max_api_calls_per_query=0,
        success_on_partial=True,
    ),
    AgentMode.MIXED.value: ModeConfig(
        name="mixed",
        description=(
            "Smart default — freshness-aware with DB fallback. "
            "Uses freshness thresholds to avoid redundant collection. "
            "Cached data counts as success."
        ),
        bypass_freshness=False,
        allow_db_fallback=True,
        require_new_data=False,
        allow_collection=True,
        allowed_intents={i.value for i in Intent},  # all intents
        max_api_calls_per_query=5,
        success_on_partial=True,
    ),
}


def get_mode_config(mode: AgentMode | str) -> ModeConfig:
    """Get the ModeConfig for a given mode."""
    key = mode.value if isinstance(mode, AgentMode) else mode
    return MODE_CONFIG[key]

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
    Intent.DISCOVERY_SCAN.value: [],
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
    mode: AgentMode = AgentMode.MIXED
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

        # Check mode allows this intent
        mode_cfg = get_mode_config(self.mode)
        if self.intent.value not in mode_cfg.allowed_intents:
            errors.append(
                f"Intent '{self.intent.value}' not allowed in mode '{self.mode.value}'. "
                f"Allowed intents: {sorted(mode_cfg.allowed_intents)}"
            )

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

        # Cap max_budget_spend (respect mode cap)
        effective_budget_cap = min(50, mode_cfg.max_api_calls_per_query) if mode_cfg.max_api_calls_per_query > 0 else 50
        if self.max_budget_spend > effective_budget_cap:
            errors.append(
                f"max_budget_spend ({self.max_budget_spend}) exceeds mode '{self.mode.value}' "
                f"cap of {effective_budget_cap}"
            )
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
            "mode": self.mode.value,
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
        "modes": [
            {"value": e.value, "config": MODE_CONFIG[e.value].to_dict()}
            for e in AgentMode
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
    "discovery_scan": "Analyze collected data to discover what to collect next — finds coverage gaps, stale data, and expansion targets",
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

    mode = AgentMode.MIXED
    if data.get("mode"):
        try:
            mode = AgentMode(data["mode"])
        except ValueError:
            errors.append(
                f"Invalid mode '{data['mode']}'. "
                f"Valid options: {[e.value for e in AgentMode]}"
            )

    if errors:
        return None, errors

    query = AgentQuery(
        intent=intent,
        region=region,
        mode=mode,
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
