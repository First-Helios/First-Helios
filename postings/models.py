"""
listings/models.py — SQLAlchemy model for the job_postings table.

Imported by backend/database._import_listings_models() so the table is
created automatically by Base.metadata.create_all() on app start.

Design notes:
  - source + external_id is the dedup key.  For Workday it is the
    externalPath field; for JobSpy it is the job_url (SHA-256 hash if
    longer than 255 chars); for generics a content hash.
  - local_employer_id is nullable.  NULL means "unmatched" — this is a
    first-class valid state.  Unmatched postings still appear on the map
    using their own geocoded lat/lng.
  - expires_at is computed at ingest time (posted_date + TTL or
    scraped_at + TTL).  The map query filters on is_active = TRUE, which
    is flipped by a nightly expiry sweep job — not computed at query time.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class JobPosting(Base):
    """One normalised, geocoded, employer-matched job posting."""

    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Source provenance ─────────────────────────────────────────────────────
    source = Column(String, nullable=False, index=True)      # "careers_api" | "jobspy"
    source_url = Column(String, nullable=True)               # direct link to apply
    external_id = Column(String, nullable=False)             # stable ID within the source

    # ── Employer identity (raw + normalised) ──────────────────────────────────
    raw_employer_name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    fingerprint = Column(String, nullable=False, index=True)

    # ── Job detail ────────────────────────────────────────────────────────────
    role_title = Column(String, nullable=True)
    wage_min = Column(Float, nullable=True)
    wage_max = Column(Float, nullable=True)
    wage_period = Column(String, nullable=True)    # "hourly" | "yearly"
    region = Column(String, nullable=False, index=True)
    industry = Column(String, nullable=True, index=True)

    # ── Location (from the posting itself; may differ from LocalEmployer) ─────
    raw_address = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    geocode_source = Column(String, nullable=True)  # "provided" | "nominatim" | "override" | None

    # ── H3 hexagonal index (pre-computed at ingest from lat/lng) ─────────────
    # NULL when no coordinates available (common for fully-remote postings).
    h3_r7 = Column(String(15), nullable=True, index=True)  # neighborhood  ~3.5 km
    h3_r8 = Column(String(15), nullable=True, index=True)  # corridor      ~461 m

    # ── Match result ──────────────────────────────────────────────────────────
    local_employer_id = Column(
        Integer, ForeignKey("local_employers.id"), nullable=True, index=True
    )
    match_confidence = Column(Float, nullable=True)           # 0.0–1.0
    match_method = Column(String, nullable=True)              # "exact_fp+proximity" | "fp_only" | "none"

    # ── Remote flag ───────────────────────────────────────────────────────────
    is_remote = Column(Boolean, nullable=True)  # True=remote, False=on-site, None=unknown

    # ── Address extraction audit ───────────────────────────────────────────────
    # address_method: how raw_address was found. NULL means extraction was
    # attempted but failed — query (source='jobicy' AND address_method IS NULL)
    # to review failures and improve the extractor.
    address_method = Column(String, nullable=True)  # "pyap" | "regex" | NULL
    # Short plain-text excerpt stored at ingest time so failures can be
    # reviewed offline without re-calling the API.
    job_excerpt = Column(String(600), nullable=True)

    # ── Referral / apply links ────────────────────────────────────────────────
    # referral_url: preferred link that earns a referral payout (e.g. Jobicy).
    # When another source of the same job carries a paid referral program, this
    # column stores that link.  The frontend displays referral_url when present,
    # falling back to source_url.  NULL for sources without referral programs.
    referral_url = Column(String, nullable=True)

    # ── Rich detail (JSONB) ───────────────────────────────────────────────────
    # Stores structured fields that don't warrant dedicated columns but are
    # valuable for the job board UI: minimum_qualifications, ksa,
    # preferred_qualifications, education, licenses, days_and_hours,
    # location_detail, pay_range_raw, time_type, notes_to_candidate.
    # NULL for sources that don't provide structured data.
    detail_json = Column(JSONB, nullable=True)

    # ── Freshness ─────────────────────────────────────────────────────────────
    posted_date = Column(DateTime, nullable=True, index=True) # from the source
    scraped_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # expires_at rolls forward every time the listing is re-confirmed in the feed.
    # A listing that disappears from the source will naturally expire after TTL_DAYS
    # of silence — it is not deleted, just marked is_active=False by the nightly sweep.
    expires_at = Column(DateTime, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_posting_source_external"),
        Index("ix_job_postings_active_region",    "is_active", "region"),
        Index("ix_job_postings_employer_active",  "local_employer_id", "is_active"),
        Index("ix_job_postings_fp_active",        "fingerprint", "is_active"),
        Index("ix_job_postings_h3r7_active",      "h3_r7", "is_active"),
        Index("ix_job_postings_h3r8_active",      "h3_r8", "is_active"),
        Index("ix_job_postings_region_industry_active", "region", "industry", "is_active"),
        Index("ix_job_posting_detail_gin", "detail_json", postgresql_using="gin"),
    )

    def to_dict(self) -> dict:
        return {
            "id":                  self.id,
            "source":              self.source,
            "source_url":          self.source_url,
            "referral_url":        self.referral_url,
            "external_id":         self.external_id,
            "raw_employer_name":   self.raw_employer_name,
            "normalized_name":     self.normalized_name,
            "fingerprint":         self.fingerprint,
            "role_title":          self.role_title,
            "wage_min":            self.wage_min,
            "wage_max":            self.wage_max,
            "wage_period":         self.wage_period,
            "region":              self.region,
            "industry":            self.industry,
            "raw_address":         self.raw_address,
            "lat":                 self.lat,
            "lng":                 self.lng,
            "geocode_source":      self.geocode_source,
            "h3_r7":               self.h3_r7,
            "h3_r8":               self.h3_r8,
            "is_remote":           self.is_remote,
            "local_employer_id":   self.local_employer_id,
            "match_confidence":    self.match_confidence,
            "match_method":        self.match_method,
            "posted_date":         self.posted_date.isoformat() if self.posted_date else None,
            "scraped_at":          self.scraped_at.isoformat() if self.scraped_at else None,
            "expires_at":          self.expires_at.isoformat() if self.expires_at else None,
            "is_active":           self.is_active,
        }
