"""
backend/models/reference.py

Reference / taxonomy tables — pre-populated from public sources.
These give the intake pipeline context for classifying incoming POI data
and power the frontend filter dropdowns.

Tables:
    ref_industry     — NAICS-based industry hierarchy
    ref_brands       — Known chain profiles (Wikidata + curated)
    ref_regions      — Regional economic context (BLS / Census)
    ref_category_map — External taxonomy → internal industry crosswalk

Depends on: backend.database.Base
Called by: scripts/populate_reference_data.py, server.py /api/ref/*
"""

import logging
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.database import Base

logger = logging.getLogger(__name__)


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

    updated_at = Column(DateTime, default=datetime.utcnow)

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

    updated_at = Column(DateTime, default=datetime.utcnow)

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
