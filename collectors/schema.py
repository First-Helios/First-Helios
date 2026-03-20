"""
collectors/schema.py — Standardized output dataclasses for all collectors.

Every collector returns a list of one of these record types.
All records share: source, source_id, raw_properties, collected_at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class POIRecord:
    """A point-of-interest observation (store, restaurant, employer)."""

    source: str                          # e.g. "alltheplaces", "overture", "osm"
    source_id: str                       # unique within source
    name: str
    lat: float
    lng: float
    address: str = ""
    brand: Optional[str] = None          # normalized brand key (starbucks, mcdonalds)
    is_chain: bool = False
    confidence: float = 1.0              # 0.0–1.0
    category: Optional[str] = None       # raw category string from source
    industry: Optional[str] = None       # mapped internal industry key
    phone: Optional[str] = None
    website: Optional[str] = None
    raw_properties: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def stable_id(self) -> str:
        """Deterministic ID for deduplication: source-brand-source_id."""
        parts = [self.source]
        if self.brand:
            parts.append(self.brand[:2].upper())
        parts.append(self.source_id[:12])
        return "-".join(parts)


@dataclass
class WageRecord:
    """A wage or salary observation."""

    source: str                          # e.g. "bls", "jobspy", "indeed"
    source_id: str
    region: str
    brand: Optional[str] = None
    employer: Optional[str] = None
    role_title: Optional[str] = None
    hourly_wage: Optional[float] = None
    annual_salary: Optional[float] = None
    wage_min: Optional[float] = None
    wage_max: Optional[float] = None
    wage_period: str = "hourly"          # hourly | yearly
    industry: Optional[str] = None
    naics_code: Optional[str] = None
    is_chain: bool = False
    raw_properties: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class JobPostingRecord:
    """A job posting observation."""

    source: str                          # e.g. "workday", "jobspy", "indeed"
    source_id: str
    brand: Optional[str] = None
    employer: Optional[str] = None
    job_title: str = ""
    location: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_period: str = "hourly"
    posted_date: Optional[datetime] = None
    url: Optional[str] = None
    is_remote: bool = False
    raw_properties: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SentimentRecord:
    """A sentiment observation from social media or reviews."""

    source: str                          # e.g. "reddit", "google_maps"
    source_id: str
    brand: Optional[str] = None
    text: str = ""
    sentiment_score: Optional[float] = None  # -1.0 to 1.0
    rating: Optional[float] = None           # 1–5 star rating
    topic: Optional[str] = None              # e.g. "staffing", "wages", "management"
    author: Optional[str] = None
    posted_at: Optional[datetime] = None
    raw_properties: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EconomicIndicatorRecord:
    """A macro-economic data point (BLS, Census, etc.)."""

    source: str                          # e.g. "bls"
    source_id: str                       # series_id + period
    region: str
    indicator_type: str                  # unemployment | wage | employment | cpi
    value: float
    period: str                          # e.g. "2025-Q4", "2025-M12"
    year: Optional[int] = None
    month: Optional[int] = None
    naics_code: Optional[str] = None
    series_id: Optional[str] = None
    unit: str = ""                       # "thousands", "dollars", "percent"
    raw_properties: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)
