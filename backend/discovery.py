"""
backend/discovery.py — Discovery engine for expanding data collection.

Analyzes collected data to find gaps, surface new collection targets, and
prioritize what to collect next. This is the feedback loop that turns
"data we have" into "data we should go get."

Discovery strategies:
  1. coverage_gaps      — brands/industries with zero or thin store data
  2. data_dimension_gaps — stores with POI data but missing signals
  3. stale_leads         — source_freshness combos that are past threshold
  4. geographic_clusters — high-stress clusters suggesting nearby expansion
  5. local_opportunity   — areas dense with local employers but no chain tracking

The output is a ranked list of DiscoveryLead objects that can be converted
directly into AgentQuery proposals for OpenClaw to execute.

Depends on: backend.database, openclaw.industries, agent_interface.schemas
Called by: agent_interface/executor.py (via DISCOVERY_SCAN intent),
          server.py (via /api/discovery/*), backend/scheduler.py
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func

from backend.database import (
    LocalEmployer,
    Score,
    Signal,
    SourceFreshness,
    Store,
    WageIndex,
    get_engine,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Discovery lead — the output unit
# ══════════════════════════════════════════════════════════════════════

@dataclass
class DiscoveryLead:
    """A single discovery: something the system should go collect.

    Structured so it can be directly converted into an AgentQuery proposal
    for OpenClaw to validate and execute.
    """

    lead_type: str              # coverage_gap | data_gap | stale | cluster | local_opportunity
    priority: float             # 0–100, higher = more urgent
    industry: str | None        # target industry key
    brand: str | None           # target brand key (None for industry-wide leads)
    region: str                 # target region
    suggested_intent: str       # which AgentQuery intent to execute
    description: str            # human-readable explanation
    evidence: dict = field(default_factory=dict)   # data backing this lead
    estimated_yield: int = 0    # expected new records

    def to_dict(self) -> dict:
        return {
            "lead_type": self.lead_type,
            "priority": round(self.priority, 1),
            "industry": self.industry,
            "brand": self.brand,
            "region": self.region,
            "suggested_intent": self.suggested_intent,
            "description": self.description,
            "evidence": self.evidence,
            "estimated_yield": self.estimated_yield,
        }

    def to_agent_proposal(self) -> dict:
        """Convert to a dict suitable for an OpenClaw 'propose' action."""
        proposal = {
            "intent": self.suggested_intent,
            "region": self.region,
            "reason": f"[discovery:{self.lead_type}] {self.description}",
        }
        if self.brand:
            proposal["brand"] = self.brand
        if self.industry:
            proposal["industry"] = self.industry
        return proposal


@dataclass
class DiscoveryScan:
    """Results of a full discovery scan."""

    scanned_at: datetime = field(default_factory=datetime.utcnow)
    region: str = ""
    total_leads: int = 0
    leads_by_type: dict = field(default_factory=dict)
    leads: list[DiscoveryLead] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scanned_at": self.scanned_at.isoformat(),
            "region": self.region,
            "total_leads": self.total_leads,
            "leads_by_type": self.leads_by_type,
            "summary": self.summary,
            "leads": [ld.to_dict() for ld in self.leads],
        }


# ══════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════

def run_discovery(
    region: str = "austin_tx",
    max_leads: int = 50,
    include_types: list[str] | None = None,
) -> DiscoveryScan:
    """Run all discovery strategies and return ranked leads.

    Args:
        region: Which region to scan.
        max_leads: Maximum leads to return (highest priority first).
        include_types: Optional filter — only run these strategy types.
            Valid: coverage_gap, data_gap, stale, cluster, local_opportunity

    Returns:
        DiscoveryScan with ranked leads.
    """
    engine = init_db()
    session = get_session(engine)

    all_leads: list[DiscoveryLead] = []
    strategies = {
        "coverage_gap": _discover_coverage_gaps,
        "data_gap": _discover_data_dimension_gaps,
        "stale": _discover_stale_leads,
        "cluster": _discover_geographic_clusters,
        "local_opportunity": _discover_local_opportunities,
    }

    try:
        for stype, strategy_fn in strategies.items():
            if include_types and stype not in include_types:
                continue
            try:
                leads = strategy_fn(session, region)
                all_leads.extend(leads)
                logger.info("[Discovery] %s: %d leads", stype, len(leads))
            except Exception as e:
                logger.warning("[Discovery] %s failed: %s", stype, e)

        # Sort by priority descending, take top N
        all_leads.sort(key=lambda ld: ld.priority, reverse=True)
        top_leads = all_leads[:max_leads]

        # Build summary
        leads_by_type: dict[str, int] = defaultdict(int)
        for ld in top_leads:
            leads_by_type[ld.lead_type] += 1

        # Industry coverage stats for summary
        from openclaw.industries import INDUSTRY_REGISTRY
        industries_with_stores = set(
            r[0] for r in session.query(Store.industry).distinct().all()
            if r[0]
        )
        industries_registered = set(INDUSTRY_REGISTRY.keys())

        scan = DiscoveryScan(
            region=region,
            total_leads=len(top_leads),
            leads_by_type=dict(leads_by_type),
            leads=top_leads,
            summary={
                "industries_registered": len(industries_registered),
                "industries_with_data": len(industries_with_stores),
                "industries_missing": sorted(industries_registered - industries_with_stores),
                "total_stores": session.query(Store).filter(
                    Store.region == region, Store.is_active.is_(True)
                ).count(),
                "total_local_employers": session.query(LocalEmployer).filter(
                    LocalEmployer.region == region, LocalEmployer.is_active.is_(True)
                ).count(),
                "total_signals": session.query(Signal).count(),
                "total_scores": session.query(Score).count(),
            },
        )
        return scan

    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
# Strategy 1: Coverage gaps — brands/industries with missing stores
# ══════════════════════════════════════════════════════════════════════

def _discover_coverage_gaps(session, region: str) -> list[DiscoveryLead]:
    """Find brands and industries with zero or surprisingly low store counts.

    For every brand in the industry registry, check if we have stores in
    the database. Missing brands get high-priority leads.
    """
    from openclaw.industries import INDUSTRY_REGISTRY

    leads: list[DiscoveryLead] = []

    # Get current store counts per chain
    chain_counts = dict(
        session.query(Store.chain, func.count(Store.store_num))
        .filter(Store.region == region, Store.is_active.is_(True))
        .group_by(Store.chain)
        .all()
    )

    # Get current store counts per industry
    industry_counts = dict(
        session.query(Store.industry, func.count(Store.store_num))
        .filter(Store.region == region, Store.is_active.is_(True))
        .group_by(Store.industry)
        .all()
    )

    for ind_key, dim in INDUSTRY_REGISTRY.items():
        ind_store_count = industry_counts.get(ind_key, 0)

        # Check each mega-corp in this industry
        for mc in dim.mega_corps:
            brand_count = chain_counts.get(mc.key, 0)

            if brand_count == 0:
                # Zero stores for this brand — high priority
                leads.append(DiscoveryLead(
                    lead_type="coverage_gap",
                    priority=85.0,
                    industry=ind_key,
                    brand=mc.key,
                    region=region,
                    suggested_intent="poi_chain_locations",
                    description=(
                        f"No {mc.display_name} stores found in {region}. "
                        f"Industry '{dim.display_name}' has {ind_store_count} total stores."
                    ),
                    evidence={
                        "brand": mc.key,
                        "brand_name": mc.display_name,
                        "current_count": 0,
                        "industry_total": ind_store_count,
                        "wikidata_id": mc.wikidata_id,
                    },
                    estimated_yield=20,  # conservative guess
                ))
            elif brand_count < 5:
                # Very few stores — might be incomplete collection
                leads.append(DiscoveryLead(
                    lead_type="coverage_gap",
                    priority=60.0,
                    industry=ind_key,
                    brand=mc.key,
                    region=region,
                    suggested_intent="poi_chain_locations",
                    description=(
                        f"Only {brand_count} {mc.display_name} stores in {region} — "
                        f"likely incomplete. Most metro-area chains have 10+ locations."
                    ),
                    evidence={
                        "brand": mc.key,
                        "brand_name": mc.display_name,
                        "current_count": brand_count,
                        "industry_total": ind_store_count,
                    },
                    estimated_yield=max(10, 20 - brand_count),
                ))

        # Industry-level: no stores at all for this industry
        if ind_store_count == 0 and len(dim.mega_corps) > 0:
            leads.append(DiscoveryLead(
                lead_type="coverage_gap",
                priority=90.0,
                industry=ind_key,
                brand=dim.mega_corps[0].key,  # start with the first brand
                region=region,
                suggested_intent="poi_chain_locations",
                description=(
                    f"Zero stores for entire '{dim.display_name}' industry. "
                    f"{len(dim.mega_corps)} mega-corps registered but none tracked."
                ),
                evidence={
                    "industry": ind_key,
                    "industry_name": dim.display_name,
                    "registered_brands": [m.key for m in dim.mega_corps],
                    "brands_with_data": 0,
                },
                estimated_yield=50,
            ))

    return leads


# ══════════════════════════════════════════════════════════════════════
# Strategy 2: Data dimension gaps — stores missing signals/scores
# ══════════════════════════════════════════════════════════════════════

def _discover_data_dimension_gaps(session, region: str) -> list[DiscoveryLead]:
    """Find stores that have location data but are missing other dimensions.

    A fully-tracked store should have:
      - POI data (it exists in the stores table)         ✓ (if we're here)
      - Job posting signals (signal_type='listing')
      - Sentiment signals (signal_type='sentiment')
      - Wage data (in wage_index)
      - Composite score (in scores table)

    This strategy finds the gaps.
    """
    leads: list[DiscoveryLead] = []

    # Get all chains with stores
    chains_with_stores = (
        session.query(
            Store.chain,
            Store.industry,
            func.count(Store.store_num).label("store_count"),
        )
        .filter(Store.region == region, Store.is_active.is_(True))
        .group_by(Store.chain, Store.industry)
        .all()
    )

    if not chains_with_stores:
        return leads

    for chain_key, industry_key, store_count in chains_with_stores:
        store_nums = [
            r[0] for r in
            session.query(Store.store_num)
            .filter(Store.chain == chain_key, Store.region == region)
            .all()
        ]

        if not store_nums:
            continue

        # Check job posting signals
        listing_count = session.query(Signal).filter(
            Signal.store_num.in_(store_nums),
            Signal.signal_type == "listing",
        ).count()

        if listing_count == 0:
            leads.append(DiscoveryLead(
                lead_type="data_gap",
                priority=70.0,
                industry=industry_key,
                brand=chain_key,
                region=region,
                suggested_intent="job_posting_volume",
                description=(
                    f"{store_count} {chain_key} stores have zero job posting signals. "
                    f"Can't compute staffing stress without hiring data."
                ),
                evidence={
                    "store_count": store_count,
                    "listing_signals": 0,
                    "dimension": "job_posting_volume",
                },
                estimated_yield=store_count * 2,
            ))

        # Check sentiment signals
        sentiment_count = session.query(Signal).filter(
            Signal.store_num.in_(store_nums),
            Signal.signal_type.in_(["sentiment", "review_score"]),
        ).count()

        if sentiment_count == 0:
            leads.append(DiscoveryLead(
                lead_type="data_gap",
                priority=50.0,
                industry=industry_key,
                brand=chain_key,
                region=region,
                suggested_intent="sentiment_check",
                description=(
                    f"{store_count} {chain_key} stores have zero sentiment data. "
                    f"Worker sentiment is 25% of the composite score."
                ),
                evidence={
                    "store_count": store_count,
                    "sentiment_signals": 0,
                    "dimension": "sentiment_check",
                },
                estimated_yield=store_count,
            ))

        # Check scores
        scored_count = session.query(Score).filter(
            Score.store_num.in_(store_nums),
            Score.score_type == "composite",
        ).count()

        if scored_count == 0 and listing_count > 0:
            # Have data but no scores computed
            leads.append(DiscoveryLead(
                lead_type="data_gap",
                priority=80.0,
                industry=industry_key,
                brand=chain_key,
                region=region,
                suggested_intent="score_refresh",
                description=(
                    f"{store_count} {chain_key} stores have signals but no computed scores. "
                    f"Score refresh needed to rank them."
                ),
                evidence={
                    "store_count": store_count,
                    "scored_count": 0,
                    "listing_signals": listing_count,
                    "dimension": "score_refresh",
                },
                estimated_yield=store_count,
            ))

    # Check wage data coverage by industry
    industries_with_stores = set(r[1] for r in chains_with_stores if r[1])
    for ind_key in industries_with_stores:
        wage_count = session.query(WageIndex).filter(
            WageIndex.industry == ind_key,
        ).count()

        if wage_count == 0:
            leads.append(DiscoveryLead(
                lead_type="data_gap",
                priority=65.0,
                industry=ind_key,
                brand=None,
                region=region,
                suggested_intent="wage_baseline",
                description=(
                    f"No wage data for industry '{ind_key}'. "
                    f"Wage gap is 30% of the targeting score — can't rank without it."
                ),
                evidence={
                    "industry": ind_key,
                    "wage_observations": 0,
                    "dimension": "wage_baseline",
                },
                estimated_yield=5,
            ))

    # Check local employer coverage by industry
    for ind_key in industries_with_stores:
        local_count = session.query(LocalEmployer).filter(
            LocalEmployer.region == region,
            LocalEmployer.industry == ind_key,
            LocalEmployer.is_active.is_(True),
        ).count()

        if local_count == 0:
            leads.append(DiscoveryLead(
                lead_type="data_gap",
                priority=55.0,
                industry=ind_key,
                brand=None,
                region=region,
                suggested_intent="poi_local_density",
                description=(
                    f"No local employers indexed for '{ind_key}' in {region}. "
                    f"Can't compute local_alternatives targeting component."
                ),
                evidence={
                    "industry": ind_key,
                    "local_employers": 0,
                    "dimension": "poi_local_density",
                },
                estimated_yield=50,
            ))

    return leads


# ══════════════════════════════════════════════════════════════════════
# Strategy 3: Stale data — freshness records past their threshold
# ══════════════════════════════════════════════════════════════════════

def _discover_stale_leads(session, region: str) -> list[DiscoveryLead]:
    """Find data that's gone stale and needs re-collection.

    Reads the source_freshness table for records where age > threshold.
    Also generates leads for intent/brand combos that have NEVER been collected.
    """
    leads: list[DiscoveryLead] = []

    # Stale records
    all_freshness = session.query(SourceFreshness).filter(
        SourceFreshness.region == region,
    ).all()

    for record in all_freshness:
        if record.is_stale:
            # How overdue is it? More overdue = higher priority
            overdue_ratio = record.age_days / max(record.threshold_days, 1.0)
            priority = min(95.0, 40.0 + (overdue_ratio * 15.0))

            leads.append(DiscoveryLead(
                lead_type="stale",
                priority=priority,
                industry=record.industry,
                brand=record.brand,
                region=region,
                suggested_intent=record.intent,
                description=(
                    f"Data for {record.intent} "
                    f"({'brand=' + record.brand if record.brand else 'industry=' + (record.industry or '?')}) "
                    f"is {record.age_days:.0f} days old (threshold: {record.threshold_days:.0f} days). "
                    f"Last collected {record.records_collected} records."
                ),
                evidence={
                    "age_days": round(record.age_days, 1),
                    "threshold_days": record.threshold_days,
                    "overdue_ratio": round(overdue_ratio, 2),
                    "last_collected": record.last_collected_at.isoformat() if record.last_collected_at else None,
                    "last_record_count": record.records_collected,
                },
                estimated_yield=record.records_collected,  # expect similar yield
            ))

    # Never-collected combos: brands with stores but no freshness record
    from openclaw.industries import INDUSTRY_REGISTRY
    from agent_interface.schemas import FRESHNESS_THRESHOLDS

    chains_in_db = (
        session.query(Store.chain, Store.industry)
        .filter(Store.region == region, Store.is_active.is_(True))
        .distinct()
        .all()
    )

    # Key intents that every brand should have freshness records for
    brand_intents = ["job_posting_volume", "sentiment_check"]
    industry_intents = ["wage_baseline", "poi_local_density"]

    existing_freshness_keys = set()
    for record in all_freshness:
        key = (record.intent, record.brand, record.industry)
        existing_freshness_keys.add(key)

    for chain_key, industry_key in chains_in_db:
        for intent in brand_intents:
            if (intent, chain_key, industry_key) not in existing_freshness_keys:
                leads.append(DiscoveryLead(
                    lead_type="stale",
                    priority=75.0,
                    industry=industry_key,
                    brand=chain_key,
                    region=region,
                    suggested_intent=intent,
                    description=(
                        f"{intent} has never been collected for {chain_key} in {region}. "
                        f"This is a complete blind spot."
                    ),
                    evidence={
                        "never_collected": True,
                        "intent": intent,
                        "brand": chain_key,
                    },
                    estimated_yield=10,
                ))

    # Industry-level intents
    industries_in_db = set(r[1] for r in chains_in_db if r[1])
    for ind_key in industries_in_db:
        for intent in industry_intents:
            if (intent, None, ind_key) not in existing_freshness_keys:
                leads.append(DiscoveryLead(
                    lead_type="stale",
                    priority=65.0,
                    industry=ind_key,
                    brand=None,
                    region=region,
                    suggested_intent=intent,
                    description=(
                        f"{intent} never collected for industry '{ind_key}' in {region}."
                    ),
                    evidence={
                        "never_collected": True,
                        "intent": intent,
                        "industry": ind_key,
                    },
                    estimated_yield=10,
                ))

    return leads


# ══════════════════════════════════════════════════════════════════════
# Strategy 4: Geographic clusters — high-stress stores suggesting
#             nearby expansion
# ══════════════════════════════════════════════════════════════════════

def _discover_geographic_clusters(session, region: str) -> list[DiscoveryLead]:
    """Find geographic areas with high staffing stress that might benefit
    from tracking additional nearby chains.

    If we see 5 high-stress Starbucks in a 2-mile radius, there are
    probably stressed fast-food and retail chains nearby too.
    """
    leads: list[DiscoveryLead] = []

    # Get stores with high composite scores (critical tier)
    high_stress = (
        session.query(Score.store_num, Score.value)
        .filter(
            Score.score_type == "composite",
            Score.tier == "critical",
        )
        .all()
    )

    if len(high_stress) < 3:
        return leads  # Not enough data for cluster analysis

    # Get coordinates for high-stress stores
    high_stress_nums = [r[0] for r in high_stress]
    stores = (
        session.query(Store)
        .filter(
            Store.store_num.in_(high_stress_nums),
            Store.lat.isnot(None),
            Store.lng.isnot(None),
        )
        .all()
    )

    if len(stores) < 3:
        return leads

    # Simple grid clustering: divide the region into cells and find hotspots
    # Cell size: ~1 mile ≈ 0.0145 degrees lat, 0.0175 degrees lng at 30°N
    CELL_LAT = 0.0145
    CELL_LNG = 0.0175

    grid: dict[tuple[int, int], list] = defaultdict(list)
    for store in stores:
        cell = (int(store.lat / CELL_LAT), int(store.lng / CELL_LNG))
        grid[cell].append(store)

    # Find cells with 3+ high-stress stores
    for cell, cell_stores in grid.items():
        if len(cell_stores) < 3:
            continue

        # Get industries represented in this cluster
        industries_present = set(s.industry for s in cell_stores if s.industry)
        chains_present = set(s.chain for s in cell_stores if s.chain)

        # Find industries NOT represented in this high-stress cluster
        from openclaw.industries import INDUSTRY_REGISTRY
        missing_industries = set(INDUSTRY_REGISTRY.keys()) - industries_present

        center_lat = sum(s.lat for s in cell_stores) / len(cell_stores)
        center_lng = sum(s.lng for s in cell_stores) / len(cell_stores)

        # For missing industries with likely presence in any metro area,
        # suggest exploring them in this cluster area
        HIGH_DENSITY_INDUSTRIES = {
            "fast_food", "coffee_cafe", "retail_general", "retail_grocery",
            "hair_beauty", "auto_repair", "pharmacy",
        }
        explorable = missing_industries & HIGH_DENSITY_INDUSTRIES

        for ind_key in explorable:
            dim = INDUSTRY_REGISTRY.get(ind_key)
            if not dim or not dim.mega_corps:
                continue

            leads.append(DiscoveryLead(
                lead_type="cluster",
                priority=55.0,
                industry=ind_key,
                brand=dim.mega_corps[0].key,
                region=region,
                suggested_intent="poi_chain_locations",
                description=(
                    f"High-stress cluster at ({center_lat:.3f}, {center_lng:.3f}) "
                    f"has {len(cell_stores)} critical stores across {chains_present} "
                    f"but no '{dim.display_name}' tracking. Likely chains nearby."
                ),
                evidence={
                    "cluster_center": {"lat": round(center_lat, 4), "lng": round(center_lng, 4)},
                    "critical_stores_in_cluster": len(cell_stores),
                    "chains_present": sorted(chains_present),
                    "industries_present": sorted(industries_present),
                },
                estimated_yield=5,
            ))

    return leads


# ══════════════════════════════════════════════════════════════════════
# Strategy 5: Local employer opportunities — dense local areas
#             where chain workers have alternatives
# ══════════════════════════════════════════════════════════════════════

def _discover_local_opportunities(session, region: str) -> list[DiscoveryLead]:
    """Find areas with many local employers but few tracked chain stores.

    These are high-opportunity zones: plenty of local alternatives exist
    for workers, but we're not tracking the chains they'd leave.
    """
    leads: list[DiscoveryLead] = []

    # Get local employer counts by industry
    local_by_industry = dict(
        session.query(
            LocalEmployer.industry,
            func.count(LocalEmployer.id),
        )
        .filter(LocalEmployer.region == region, LocalEmployer.is_active.is_(True))
        .group_by(LocalEmployer.industry)
        .all()
    )

    if not local_by_industry:
        # No local employers at all — suggest initial collection
        leads.append(DiscoveryLead(
            lead_type="local_opportunity",
            priority=70.0,
            industry=None,
            brand=None,
            region=region,
            suggested_intent="poi_local_density",
            description=(
                f"Zero local employers indexed in {region}. "
                f"Local employer density is essential for targeting — "
                f"it's how we find where workers have alternatives."
            ),
            evidence={"local_employer_count": 0},
            estimated_yield=200,
        ))
        return leads

    # For each industry with local employers, check chain tracking
    chain_by_industry = dict(
        session.query(Store.industry, func.count(Store.store_num))
        .filter(Store.region == region, Store.is_active.is_(True))
        .group_by(Store.industry)
        .all()
    )

    for ind_key, local_count in local_by_industry.items():
        if not ind_key:
            continue

        chain_count = chain_by_industry.get(ind_key, 0)

        if local_count >= 10 and chain_count == 0:
            # Lots of local employers, no chain tracking — big opportunity
            from openclaw.industries import INDUSTRY_REGISTRY
            dim = INDUSTRY_REGISTRY.get(ind_key)
            if not dim or not dim.mega_corps:
                continue

            leads.append(DiscoveryLead(
                lead_type="local_opportunity",
                priority=75.0,
                industry=ind_key,
                brand=dim.mega_corps[0].key,
                region=region,
                suggested_intent="poi_chain_locations",
                description=(
                    f"{local_count} local '{dim.display_name}' employers indexed "
                    f"in {region}, but zero chain stores tracked. These local "
                    f"businesses are potential job fair partners — need chain "
                    f"store data to complete the targeting picture."
                ),
                evidence={
                    "local_employer_count": local_count,
                    "chain_store_count": 0,
                    "first_brand_to_try": dim.mega_corps[0].key,
                    "all_brands": [m.key for m in dim.mega_corps],
                },
                estimated_yield=20,
            ))
        elif local_count >= 20 and chain_count > 0 and chain_count < local_count * 0.1:
            # Many locals, very few chains — likely incomplete chain tracking
            leads.append(DiscoveryLead(
                lead_type="local_opportunity",
                priority=50.0,
                industry=ind_key,
                brand=None,
                region=region,
                suggested_intent="poi_chain_locations",
                description=(
                    f"Industry '{ind_key}': {local_count} local employers but "
                    f"only {chain_count} chain stores. Ratio suggests incomplete "
                    f"chain tracking."
                ),
                evidence={
                    "local_employer_count": local_count,
                    "chain_store_count": chain_count,
                    "ratio": round(chain_count / local_count, 3),
                },
                estimated_yield=10,
            ))

    return leads


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def get_discovery_summary(region: str = "austin_tx") -> dict:
    """Quick summary of discovery state without running full scan.

    Returns counts and high-level metrics useful for dashboards.
    """
    engine = init_db()
    session = get_session(engine)

    try:
        from openclaw.industries import INDUSTRY_REGISTRY

        total_registered_brands = sum(
            len(dim.mega_corps) for dim in INDUSTRY_REGISTRY.values()
        )

        # Brands with at least 1 store
        brands_with_stores = session.query(Store.chain).filter(
            Store.region == region, Store.is_active.is_(True)
        ).distinct().count()

        # Industries with at least 1 store
        industries_with_stores = session.query(Store.industry).filter(
            Store.region == region, Store.is_active.is_(True)
        ).distinct().count()

        # Stores with scores vs total
        total_stores = session.query(Store).filter(
            Store.region == region, Store.is_active.is_(True)
        ).count()
        scored_stores = session.query(Score).filter(
            Score.score_type == "composite"
        ).count()

        # Freshness: how many combos are stale?
        stale_count = 0
        all_freshness = session.query(SourceFreshness).filter(
            SourceFreshness.region == region
        ).all()
        for f in all_freshness:
            if f.is_stale:
                stale_count += 1

        return {
            "region": region,
            "brand_coverage": {
                "registered": total_registered_brands,
                "with_data": brands_with_stores,
                "coverage_pct": round(brands_with_stores / max(total_registered_brands, 1) * 100, 1),
            },
            "industry_coverage": {
                "registered": len(INDUSTRY_REGISTRY),
                "with_data": industries_with_stores,
                "coverage_pct": round(industries_with_stores / max(len(INDUSTRY_REGISTRY), 1) * 100, 1),
            },
            "scoring_coverage": {
                "total_stores": total_stores,
                "scored_stores": scored_stores,
                "coverage_pct": round(scored_stores / max(total_stores, 1) * 100, 1),
            },
            "freshness": {
                "total_tracked": len(all_freshness),
                "stale": stale_count,
                "fresh": len(all_freshness) - stale_count,
            },
        }

    finally:
        session.close()
