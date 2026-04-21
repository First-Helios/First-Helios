"""
backend/models/reference.py

Reference / taxonomy tables — pre-populated from public sources.
These give the intake pipeline context for classifying incoming POI data
and power the frontend filter dropdowns.

Tables:
    ref_industry          — NAICS-based industry hierarchy
    ref_brands            — Known chain profiles (Wikidata + curated)
    ref_regions           — Regional economic context (BLS / Census)
    ref_category_map      — External taxonomy → internal industry crosswalk
    ref_soc_major_groups  — SOC 2-digit major occupation groups
    ref_texaswages        — Texas MSA hourly wages by SOC (TWC / texaswages.com)

Depends on: backend.database.Base
Called by: scripts/one_shot/populate_reference_data.py, server.py /api/ref/*, revelio_ingest.py,
           scrapers/texaswages_ingest.py
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from core.database import Base

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return naive UTC timestamps without using deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class IndustryCategory(Base):
    """NAICS-based industry hierarchy.  Pre-populated from Census Bureau data."""

    __tablename__ = "ref_industry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    naics_code = Column(String(6), unique=True, nullable=False, index=True)
    naics_title = Column(String, nullable=False)
    internal_key = Column(String, nullable=False, index=True)
    parent_naics = Column(String(6), nullable=True)
    sector = Column(String, nullable=True)
    avg_hourly_wage_bls = Column(Float, nullable=True)
    avg_employees_per_location = Column(Float, nullable=True)
    seasonal_pattern = Column(String, nullable=True)

    def to_dict(self) -> dict:
        return {
            "naics_code": self.naics_code,
            "naics_title": self.naics_title,
            "internal_key": self.internal_key,
            "parent_naics": self.parent_naics,
            "sector": self.sector,
            "avg_hourly_wage_bls": self.avg_hourly_wage_bls,
            "avg_employees_per_location": self.avg_employees_per_location,
            "seasonal_pattern": self.seasonal_pattern,
        }


class BrandProfile(Base):
    """Known brand / chain reference data.

    Pre-populated from Wikidata + manual curation.  Single source of truth
    for what a chain is, how to classify it, and where to find its data.
    """

    __tablename__ = "ref_brands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_key = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    parent_company = Column(String, nullable=True)
    wikidata_id = Column(String, nullable=True)
    naics_code = Column(String(6), nullable=True)
    internal_industry = Column(String, nullable=True, index=True)
    is_chain = Column(Boolean, default=True)
    is_publicly_traded = Column(Boolean, default=False)
    stock_ticker = Column(String, nullable=True)
    approx_us_locations = Column(Integer, nullable=True)
    careers_url = Column(String, nullable=True)
    glassdoor_id = Column(String, nullable=True)
    indeed_query = Column(String, nullable=True)

    # Scraper integration: stored as JSON-encoded text
    atp_spider_names_json = Column("atp_spider_names", Text, nullable=True)
    overture_name_patterns_json = Column("overture_name_patterns", Text, nullable=True)
    osm_tags_json = Column("osm_tags", Text, nullable=True)

    # Scoring context
    avg_starting_wage = Column(Float, nullable=True)
    wage_source = Column(String, nullable=True)
    typical_store_staff = Column(Integer, nullable=True)
    union_presence = Column(Boolean, default=False)

    updated_at = Column(DateTime, default=_utcnow)

    # ── JSON property helpers ────────────────────────────────────

    @property
    def atp_spider_names(self) -> list[str]:
        import json
        return json.loads(self.atp_spider_names_json) if self.atp_spider_names_json else []

    @atp_spider_names.setter
    def atp_spider_names(self, val: list[str]) -> None:
        import json
        self.atp_spider_names_json = json.dumps(val)

    @property
    def overture_name_patterns(self) -> list[str]:
        import json
        return json.loads(self.overture_name_patterns_json) if self.overture_name_patterns_json else []

    @overture_name_patterns.setter
    def overture_name_patterns(self, val: list[str]) -> None:
        import json
        self.overture_name_patterns_json = json.dumps(val)

    @property
    def osm_tags(self) -> dict:
        import json
        return json.loads(self.osm_tags_json) if self.osm_tags_json else {}

    @osm_tags.setter
    def osm_tags(self, val: dict) -> None:
        import json
        self.osm_tags_json = json.dumps(val)

    def to_dict(self) -> dict:
        return {
            "brand_key": self.brand_key,
            "display_name": self.display_name,
            "parent_company": self.parent_company,
            "wikidata_id": self.wikidata_id,
            "naics_code": self.naics_code,
            "internal_industry": self.internal_industry,
            "is_chain": self.is_chain,
            "is_publicly_traded": self.is_publicly_traded,
            "stock_ticker": self.stock_ticker,
            "approx_us_locations": self.approx_us_locations,
            "careers_url": self.careers_url,
            "atp_spider_names": self.atp_spider_names,
            "overture_name_patterns": self.overture_name_patterns,
            "osm_tags": self.osm_tags,
            "avg_starting_wage": self.avg_starting_wage,
            "wage_source": self.wage_source,
            "typical_store_staff": self.typical_store_staff,
            "union_presence": self.union_presence,
        }


class RegionProfile(Base):
    """Pre-computed regional economic context from BLS / Census.

    Gives the scoring engine baseline expectations before any scraping.
    """

    __tablename__ = "ref_regions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_key = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    fips_code = Column(String, nullable=True)
    center_lat = Column(Float, nullable=True)
    center_lng = Column(Float, nullable=True)
    bbox_west = Column(Float, nullable=True)
    bbox_east = Column(Float, nullable=True)
    bbox_south = Column(Float, nullable=True)
    bbox_north = Column(Float, nullable=True)

    # BLS / Census context
    population = Column(Integer, nullable=True)
    median_household_income = Column(Integer, nullable=True)
    unemployment_rate = Column(Float, nullable=True)
    cost_of_living_index = Column(Float, nullable=True)
    min_wage_state = Column(Float, nullable=True)
    min_wage_local = Column(Float, nullable=True)
    living_wage_1adult = Column(Float, nullable=True)
    food_service_establishments = Column(Integer, nullable=True)
    food_service_employees = Column(Integer, nullable=True)
    retail_establishments = Column(Integer, nullable=True)
    retail_employees = Column(Integer, nullable=True)

    updated_at = Column(DateTime, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "region_key": self.region_key,
            "display_name": self.display_name,
            "fips_code": self.fips_code,
            "center_lat": self.center_lat,
            "center_lng": self.center_lng,
            "bbox": {
                "west": self.bbox_west,
                "east": self.bbox_east,
                "south": self.bbox_south,
                "north": self.bbox_north,
            } if self.bbox_west else None,
            "population": self.population,
            "median_household_income": self.median_household_income,
            "unemployment_rate": self.unemployment_rate,
            "cost_of_living_index": self.cost_of_living_index,
            "min_wage_state": self.min_wage_state,
            "min_wage_local": self.min_wage_local,
            "living_wage_1adult": self.living_wage_1adult,
            "food_service_establishments": self.food_service_establishments,
            "food_service_employees": self.food_service_employees,
            "retail_establishments": self.retail_establishments,
            "retail_employees": self.retail_employees,
        }


class CategoryMapping(Base):
    """Maps external taxonomy values to internal industry keys.

    One row per (source_system, source_value) → internal_industry.
    Used during intake to consistently classify POI data regardless of origin.
    """

    __tablename__ = "ref_category_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_system = Column(String, nullable=False, index=True)
    source_value = Column(String, nullable=False)
    internal_industry = Column(String, nullable=False, index=True)
    confidence = Column(Float, default=1.0)

    __table_args__ = (
        UniqueConstraint("source_system", "source_value", name="uq_source_mapping"),
    )

    def to_dict(self) -> dict:
        return {
            "source_system": self.source_system,
            "source_value": self.source_value,
            "internal_industry": self.internal_industry,
            "confidence": self.confidence,
        }


class IndustryTaxonomy(Base):
    """Master cross-walk: internal industry key → all external classification systems.

    Single source of truth replacing the scattered hardcoded maps in:
      - scrapers/overture_adapter.py  (CATEGORY_INDUSTRY_MAP, UPWARD_MOBILITY_CATEGORIES)
      - backend/scoring/engine.py     (industry_naics)
      - backend/baseline.py           (_naics_to_jolts_industry)

    Wage data sourced from OEWS (Austin MSA) and Revelio (Texas) determines
    upward_mobility and worker_tier — not editorial judgment.

    upward_mobility logic:
      baseline_wage_hr = median hourly wage of the dominant front-line occupation
      SERVICE_BASELINE = ~$14.20/hr  (avg of fast food, cashier, waiter)
      MOBILITY_THRESHOLD = SERVICE_BASELINE * 1.25 = ~$17.75/hr
      upward_mobility = True if baseline_wage_hr >= MOBILITY_THRESHOLD

    worker_tier values:
      service      — core labor pool (fast food, retail, hotel front desk, hair/nail)
      trades       — skilled/certified work, physical (mechanics, HVAC, electricians)
      professional — office/knowledge work, healthcare practitioners, finance
    """

    __tablename__ = "ref_industry_taxonomy"

    industry_key = Column(String, primary_key=True)      # e.g. "fast_food"
    display_name = Column(String, nullable=False)         # e.g. "Fast Food & QSR"

    # BLS / NAICS cross-walk
    naics_code = Column(String(6), nullable=True)         # primary NAICS (e.g. "7225")
    naics2d_code = Column(Integer, nullable=True)         # 2-digit sector (e.g. 72)
    jolts_industry_code = Column(String, nullable=True)   # JOLTS series industry code

    # Revelio cross-walk
    revelio_sector = Column(String, nullable=True)        # naics2d_name in revelio_* tables
    revelio_soc_group = Column(String, nullable=True)     # soc2d_name for primary occupation

    # OEWS occupation benchmark (front-line / entry-level role)
    primary_occ_code = Column(String(10), nullable=True)  # OEWS occ_code
    primary_occ_title = Column(String, nullable=True)
    baseline_wage_hr = Column(Float, nullable=True)       # OEWS median hourly wage
    wage_source = Column(String, nullable=True)           # "oews_austin" | "revelio_texas"

    # Classification (data-driven from wage comparison)
    worker_tier = Column(String, nullable=False, default="service")
    # service | trades | professional
    upward_mobility = Column(Boolean, default=False)
    # True if baseline_wage_hr >= SERVICE_BASELINE * 1.25

    # Overture intake categories (comma-separated list)
    overture_categories = Column(Text, nullable=True)

    notes = Column(String, nullable=True)
    updated_at = Column(DateTime, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "industry_key": self.industry_key,
            "display_name": self.display_name,
            "naics_code": self.naics_code,
            "naics2d_code": self.naics2d_code,
            "jolts_industry_code": self.jolts_industry_code,
            "revelio_sector": self.revelio_sector,
            "revelio_soc_group": self.revelio_soc_group,
            "primary_occ_code": self.primary_occ_code,
            "primary_occ_title": self.primary_occ_title,
            "baseline_wage_hr": self.baseline_wage_hr,
            "wage_source": self.wage_source,
            "worker_tier": self.worker_tier,
            "upward_mobility": self.upward_mobility,
            "overture_categories": self.overture_categories,
        }


class MobOccupation(Base):
    """Occupation reference node for the upward mobility graph.

    One row per unique SOC code appearing in the Emsi/Dashboard transition data.
    Stores occupation metadata, occupational cluster, and pre-aggregated wage
    trajectory outcomes (3yr/5yr/10yr) from the Dashboard-trajectories dataset.

    Primary join key into the mobility graph:
      internal_industry → ref_industry_taxonomy.primary_occ_code → soc_code
      soc_code → mob_transitions.origin_soc / dest_soc

    Source files: Emsi-dataset.dta, Dashboard-transitions-dataset.dta,
                  Dashboard-trajectories-dataset.dta
    Populated by: scripts/one_shot/populate_mobility_data.py
    """

    __tablename__ = "mob_occupation"

    soc_code = Column(String(10), primary_key=True)   # "35-3023" (2018 SOC / OES format)
    census_code = Column(Integer, nullable=True, index=True)  # 2002 Census occ code (bridge to trajectories)
    title = Column(String, nullable=False)             # from Emsi occ_title
    occ_family_code = Column(Integer, nullable=True)   # 1-12 (Emsi occ_family)
    occ_family_name = Column(String, nullable=True)    # "Personal Service"
    cluster_code = Column(Integer, nullable=True)      # 1-14 (Dashboard-transitions Cluster)
    cluster_name = Column(String, nullable=True)       # "Personal Service"
    median_hourly_wage = Column(Float, nullable=True)  # Emsi h_median
    job_zone = Column(Integer, nullable=True)          # O*NET job zone 1-5 (from Dashboard-trajectories)
    internal_industry = Column(String, nullable=True, index=True)  # primary industry key for this SOC (origin side)

    # Reverse crosswalk — for destinations: which internal_industry keys hire workers in this SOC?
    # JSON list, e.g. ["healthcare", "nursing_care", "ambulatory_health"]
    # Enables step 3 of the mobility map: dest_soc → nearby employers
    # Populated by: exact match on ref_industry_taxonomy.primary_occ_code
    #               + cluster_name → industry_keys for same-cluster industries
    dest_industry_keys_json = Column(Text, nullable=True)

    # Pre-aggregated trajectory outcomes (median across workers starting in this occupation)
    traj_med_wage_growth_3yr  = Column(Float, nullable=True)   # median $ wage growth at 3yr
    traj_med_wage_growth_5yr  = Column(Float, nullable=True)
    traj_med_wage_growth_10yr = Column(Float, nullable=True)
    traj_pct_earn_25plus_3yr  = Column(Float, nullable=True)   # fraction earning >$25/hr at 3yr
    traj_pct_earn_25plus_5yr  = Column(Float, nullable=True)
    traj_pct_earn_25plus_10yr = Column(Float, nullable=True)
    traj_pct_same_cluster_3yr = Column(Float, nullable=True)   # % still in same occ cluster at 3yr

    updated_at = Column(DateTime, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "soc_code": self.soc_code,
            "census_code": self.census_code,
            "title": self.title,
            "occ_family_code": self.occ_family_code,
            "occ_family_name": self.occ_family_name,
            "cluster_code": self.cluster_code,
            "cluster_name": self.cluster_name,
            "median_hourly_wage": self.median_hourly_wage,
            "job_zone": self.job_zone,
            "internal_industry": self.internal_industry,
            "traj_med_wage_growth_3yr": self.traj_med_wage_growth_3yr,
            "traj_med_wage_growth_5yr": self.traj_med_wage_growth_5yr,
            "traj_med_wage_growth_10yr": self.traj_med_wage_growth_10yr,
            "traj_pct_earn_25plus_3yr": self.traj_pct_earn_25plus_3yr,
            "traj_pct_earn_25plus_5yr": self.traj_pct_earn_25plus_5yr,
            "traj_pct_earn_25plus_10yr": self.traj_pct_earn_25plus_10yr,
            "traj_pct_same_cluster_3yr": self.traj_pct_same_cluster_3yr,
        }


class MobTransition(Base):
    """Directed edge in the upward mobility graph: origin occupation → destination occupation.

    One row per (origin_soc, dest_soc) pair.  Combines:
      - Actual transition frequency from Dashboard-transitions (TransitionOrder)
      - Skill transferability from Emsi ISA dimension deltas
      - Wage change from Emsi median wage delta
      - License requirement flag from Emsi

    Query pattern for a store:
      store.industry → ref_industry_taxonomy.primary_occ_code
        → mob_transitions WHERE origin_soc = ?
        → JOIN mob_occupation ON dest_soc
        → filter/rank by wage_direction, avg_skill_gap, same_cluster

    Source files: Emsi-dataset.dta, Dashboard-transitions-dataset.dta
    Populated by: scripts/one_shot/populate_mobility_data.py
    """

    __tablename__ = "mob_transition"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin_soc = Column(String(10), nullable=False, index=True)
    dest_soc   = Column(String(10), nullable=False, index=True)

    # Transition frequency (1 = most common actual move workers make)
    transition_order = Column(Integer, nullable=True)

    # Wage outcome
    wage_change_dollars = Column(Float, nullable=True)   # dest_median - origin_median
    wage_direction      = Column(Integer, nullable=True) # -1 down / 0 lateral / 1 up

    # Aggregate direction probabilities (from Emsi — distribution across workers who made this move)
    pct_upward   = Column(Float, nullable=True)
    pct_lateral  = Column(Float, nullable=True)
    pct_downward = Column(Float, nullable=True)

    # Skill transferability (from Emsi ISA dimensions; lower = easier transition)
    avg_skill_gap    = Column(Float, nullable=True)   # mean absolute ISA delta across 12 dims
    skill_gap_json   = Column(Text, nullable=True)    # JSON: {dim: delta, ...} for all 12

    # Structural flags
    requires_new_license = Column(Boolean, default=False)
    same_cluster         = Column(Boolean, nullable=True)  # True = in-industry path

    __table_args__ = (
        UniqueConstraint("origin_soc", "dest_soc", name="uq_mob_transition"),
        Index("ix_mob_transition_origin_direction", "origin_soc", "wage_direction"),
    )

    def get_skill_gaps(self) -> dict:
        import json
        return json.loads(self.skill_gap_json) if self.skill_gap_json else {}


class OccupationAlias(Base):
    """Census Alphabetical Index of Occupations — job title aliases → SOC code.

    Loaded by scripts/one_shot/load_occupation_aliases.py from the Census Bureau's
    December 2019 edition (~18,981 rows covering 647 SOC codes).
    Enables the Career Pathfinder autocomplete to match common job titles
    like 'barista' or 'personal trainer' to their official SOC codes.
    """

    __tablename__ = "ref_occupation_aliases"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    alias                = Column(String, nullable=False, index=True)   # lowercase
    soc_code             = Column(String(10), nullable=False, index=True)
    census_code          = Column(String(10), nullable=True)
    industry_restriction = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_roa_alias_soc", "alias", "soc_code"),
    )

    def to_dict(self) -> dict:
        return {
            "origin_soc": self.origin_soc,
            "dest_soc": self.dest_soc,
            "transition_order": self.transition_order,
            "wage_change_dollars": self.wage_change_dollars,
            "wage_direction": self.wage_direction,
            "pct_upward": self.pct_upward,
            "pct_lateral": self.pct_lateral,
            "pct_downward": self.pct_downward,
            "avg_skill_gap": self.avg_skill_gap,
            "requires_new_license": self.requires_new_license,
            "same_cluster": self.same_cluster,
        }


class SOCMajorGroup(Base):
    """2-digit Standard Occupational Classification (SOC) major groups.

    Populated from unique (soc2d_code, soc2d_name) pairs extracted from
    Revelio Labs employment data during ingestion.  Gives human-readable
    occupation group names for all SOC codes in the database.
    """

    __tablename__ = "ref_soc_major_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    soc2d_code = Column(Integer, unique=True, nullable=False, index=True)
    soc2d_name = Column(String, nullable=False)
    description = Column(String, nullable=True)  # Optional BLS standard description

    def to_dict(self) -> dict:
        return {
            "soc2d_code": self.soc2d_code,
            "soc2d_name": self.soc2d_name,
            "description": self.description,
        }


class TexasWages(Base):
    """Texas MSA hourly wages by SOC occupation, sourced from texaswages.com (TWC).

    Covers all 26 Texas MSAs plus statewide aggregates across four wage tiers:
      entry_level, experienced, mean, median

    Updated annually. Enables Austin entry-level vs experienced wage gap analysis
    and cross-MSA wage comparison for the Career Pathfinder.

    Source: data/reference/texaswages/
    Ingest: scrapers/texaswages_ingest.py
    """

    __tablename__ = "ref_texaswages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    soc_code = Column(String(10), nullable=False, index=True)   # e.g. "35-3023"
    soc_title = Column(String, nullable=False)
    msa_name = Column(String, nullable=False, index=True)       # e.g. "Austin-Round Rock"
    wage_tier = Column(String(20), nullable=False)              # entry_level | experienced | mean | median
    hourly_wage = Column(Float, nullable=True)                  # null when suppressed by TWC
    vintage_year = Column(Integer, nullable=False)              # e.g. 2024
    loaded_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "soc_code", "msa_name", "wage_tier", "vintage_year",
            name="uq_texaswages",
        ),
        Index("ix_texaswages_soc_msa", "soc_code", "msa_name"),
    )

    def to_dict(self) -> dict:
        return {
            "soc_code": self.soc_code,
            "soc_title": self.soc_title,
            "msa_name": self.msa_name,
            "wage_tier": self.wage_tier,
            "hourly_wage": self.hourly_wage,
            "vintage_year": self.vintage_year,
        }
