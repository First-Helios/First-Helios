"""
SpiritPool — Database Models
============================
Normalised schema for job signal ingestion.

Tables
------
companies      Canonical company records (deduplicated)
locations      Normalised location strings
jobs           Unique job postings (company + title + source_id)
observations   Each time we observe a job (captures point-in-time data)
contributors   Anonymous contributor tracking (one per extension install)

Designed for SQLAlchemy — default SQLite, switchable to MS SQL Server / Postgres
via DATABASE_URL environment variable.
"""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ── Companies ───────────────────────────────────────────────────────────────

class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(300), nullable=False, index=True)
    name_normalised = db.Column(db.String(300), nullable=False, unique=True, index=True)
    domain = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    jobs = db.relationship("Job", back_populates="company")

    @staticmethod
    def normalise_name(raw):
        """Lowercase, strip whitespace, collapse spaces."""
        if not raw:
            return "unknown"
        return " ".join(raw.lower().strip().split())


# ── Locations ───────────────────────────────────────────────────────────────

class Location(db.Model):
    __tablename__ = "locations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    raw = db.Column(db.String(300), nullable=False)
    normalised = db.Column(db.String(300), nullable=False, unique=True, index=True)
    city = db.Column(db.String(150), nullable=True)
    state = db.Column(db.String(50), nullable=True)
    country = db.Column(db.String(80), nullable=True)
    is_remote = db.Column(db.Boolean, default=False)

    observations = db.relationship("Observation", back_populates="location")

    @staticmethod
    def normalise(raw):
        if not raw:
            return "unknown"
        return " ".join(raw.lower().strip().split())


# ── Jobs ────────────────────────────────────────────────────────────────────

class Job(db.Model):
    __tablename__ = "jobs"
    __table_args__ = (
        db.UniqueConstraint("source", "source_job_id", name="uq_job_source_id"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(400), nullable=False, index=True)
    title_normalised = db.Column(db.String(400), nullable=False, index=True)

    source = db.Column(db.String(60), nullable=False, index=True)         # linkedin.com, indeed.com, etc.
    source_job_id = db.Column(db.String(100), nullable=True, index=True)  # e.g. LinkedIn job id "4100123456"
    url = db.Column(db.String(1000), nullable=True)

    first_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    company = db.relationship("Company", back_populates="jobs")
    observations = db.relationship("Observation", back_populates="job", order_by="Observation.observed_at.desc()")

    @staticmethod
    def normalise_title(raw):
        if not raw:
            return "unknown"
        return " ".join(raw.lower().strip().split())


# ── Observations ────────────────────────────────────────────────────────────

class Observation(db.Model):
    """
    Each row = one time a contributor's extension saw a job on a page.
    This captures point-in-time data: salary may change, applicant count
    grows, badges appear/disappear.
    """
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=True)
    contributor_id = db.Column(db.Integer, db.ForeignKey("contributors.id"), nullable=True)

    signal_type = db.Column(db.String(40), nullable=False, default="listing")  # listing, listing_detail
    observed_at = db.Column(db.DateTime, nullable=False, index=True)
    collected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Point-in-time fields
    salary_min = db.Column(db.Float, nullable=True)
    salary_max = db.Column(db.Float, nullable=True)
    salary_period = db.Column(db.String(20), nullable=True)  # yearly, hourly
    posting_date = db.Column(db.DateTime, nullable=True)
    applicant_count = db.Column(db.Integer, nullable=True)
    badges = db.Column(db.Text, nullable=True)  # JSON array as text: ["Easy Apply","Reposted"]

    # Raw page URL at observation time
    page_url = db.Column(db.String(1000), nullable=True)

    job = db.relationship("Job", back_populates="observations")
    location = db.relationship("Location", back_populates="observations")
    contributor = db.relationship("Contributor", back_populates="observations")


# ── Contributors ────────────────────────────────────────────────────────────

class Contributor(db.Model):
    """
    Anonymous per-install tracking. The extension generates a UUID on install
    and includes it in flush payloads. No PII stored.
    """
    __tablename__ = "contributors"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uuid = db.Column(db.String(64), unique=True, nullable=False, index=True)
    first_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    total_signals = db.Column(db.Integer, default=0)

    observations = db.relationship("Observation", back_populates="contributor")
