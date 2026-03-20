"""
SpiritPool — Signal Ingestion Service
======================================
Receives raw signals from the extension and writes normalised rows into the DB.

Handles:
  - Company dedup / upsert
  - Location dedup / upsert
  - Job dedup / upsert (by source + source_job_id, or by title+company+url hash)
  - Observation creation with point-in-time data
  - Contributor tracking
"""

import json
import logging
from datetime import datetime, timezone

from .models import Company, Contributor, Job, Location, Observation, db

log = logging.getLogger(__name__)


def get_or_create_contributor(uuid_str):
    """Find or create a contributor by UUID."""
    if not uuid_str:
        return None
    contributor = Contributor.query.filter_by(uuid=uuid_str).first()
    if not contributor:
        contributor = Contributor(uuid=uuid_str)
        db.session.add(contributor)
        db.session.flush()
    else:
        contributor.last_seen = datetime.now(timezone.utc)
    return contributor


def get_or_create_company(raw_name):
    """Find or create a company by normalised name."""
    norm = Company.normalise_name(raw_name)
    company = Company.query.filter_by(name_normalised=norm).first()
    if not company:
        company = Company(name=raw_name or "Unknown", name_normalised=norm)
        db.session.add(company)
        db.session.flush()
    return company


def get_or_create_location(raw_location):
    """Find or create a location by normalised text."""
    if not raw_location:
        return None
    norm = Location.normalise(raw_location)
    location = Location.query.filter_by(normalised=norm).first()
    if not location:
        city, state, country, is_remote = parse_location(raw_location)
        location = Location(
            raw=raw_location,
            normalised=norm,
            city=city,
            state=state,
            country=country,
            is_remote=is_remote,
        )
        db.session.add(location)
        db.session.flush()
    return location


def parse_location(raw):
    """Best-effort parse of location text."""
    lower = raw.lower().strip()
    is_remote = "remote" in lower
    city = state = country = None

    # Try "City, ST" pattern
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) >= 2:
        city = parts[0].strip()
        state = parts[1].strip()
        if len(parts) >= 3:
            country = parts[2].strip()
    elif lower in ("remote", "hybrid"):
        pass  # no city/state info
    else:
        city = raw.strip()

    return city, state, country, is_remote


def get_or_create_job(source, source_job_id, title, company, url):
    """Find or create a job by source+source_job_id or title+company+url."""
    now = datetime.now(timezone.utc)
    title_norm = Job.normalise_title(title)

    # Primary lookup: source + explicit job id
    if source_job_id:
        job = Job.query.filter_by(source=source, source_job_id=source_job_id).first()
        if job:
            job.last_seen = now
            if url and not job.url:
                job.url = url
            return job

    # Fallback: match by source + normalised title + company
    job = Job.query.filter_by(
        source=source,
        title_normalised=title_norm,
        company_id=company.id,
    ).first()
    if job:
        job.last_seen = now
        if url and not job.url:
            job.url = url
        if source_job_id and not job.source_job_id:
            job.source_job_id = source_job_id
        return job

    # Create new
    job = Job(
        company_id=company.id,
        title=title or "Unknown",
        title_normalised=title_norm,
        source=source,
        source_job_id=source_job_id,
        url=url,
        first_seen=now,
        last_seen=now,
    )
    db.session.add(job)
    db.session.flush()
    return job


def parse_iso_datetime(val):
    """Parse ISO datetime string, return None if invalid."""
    if not val:
        return None
    try:
        if isinstance(val, datetime):
            return val
        # Handle both ISO and common formats
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def ingest_signal(signal, contributor=None):
    """
    Ingest a single signal dict into the database.

    Parameters
    ----------
    signal : dict
        Raw signal from the extension with keys like:
        source, signalType, company, jobTitle, location, salary,
        postingDate, applicantCount, badges, url, observedAt, jobId
    contributor : Contributor or None

    Returns
    -------
    dict  {"job_id": int, "observation_id": int, "is_new_job": bool}
    """
    company = get_or_create_company(signal.get("company"))
    location = get_or_create_location(signal.get("location"))

    source = signal.get("source", "unknown")
    source_job_id = signal.get("jobId")
    title = signal.get("jobTitle", "Unknown")
    url = signal.get("url")

    # Check if this job already exists
    existing_job = None
    if source_job_id:
        existing_job = Job.query.filter_by(source=source, source_job_id=source_job_id).first()

    job = get_or_create_job(source, source_job_id, title, company, url)
    is_new_job = existing_job is None

    # Parse salary
    salary = signal.get("salary")
    salary_min = salary_max = salary_period = None
    if isinstance(salary, dict):
        salary_min = salary.get("min")
        salary_max = salary.get("max")
        salary_period = salary.get("period")

    # Parse badges
    badges_raw = signal.get("badges")
    badges_json = json.dumps(badges_raw) if badges_raw else None

    observed_at = parse_iso_datetime(signal.get("observedAt")) or datetime.now(timezone.utc)
    posting_date = parse_iso_datetime(signal.get("postingDate"))

    observation = Observation(
        job_id=job.id,
        location_id=location.id if location else None,
        contributor_id=contributor.id if contributor else None,
        signal_type=signal.get("signalType", "listing"),
        observed_at=observed_at,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period=salary_period,
        posting_date=posting_date,
        applicant_count=signal.get("applicantCount"),
        badges=badges_json,
        page_url=signal.get("tabUrl") or url,
    )
    db.session.add(observation)

    if contributor:
        contributor.total_signals += 1

    return {
        "job_id": job.id,
        "observation_id": observation.id,
        "is_new_job": is_new_job,
    }


def ingest_batch(domain, signals, contributor_uuid=None):
    """
    Ingest a batch of signals from one domain.

    Parameters
    ----------
    domain : str          e.g. "linkedin.com"
    signals : list[dict]  raw signal dicts from the extension
    contributor_uuid : str or None

    Returns
    -------
    dict  {"accepted": int, "new_jobs": int, "errors": int}
    """
    contributor = get_or_create_contributor(contributor_uuid)

    accepted = 0
    new_jobs = 0
    errors = 0

    for sig in signals:
        try:
            result = ingest_signal(sig, contributor)
            accepted += 1
            if result["is_new_job"]:
                new_jobs += 1
        except Exception as e:
            log.warning("Failed to ingest signal: %s — %s", sig.get("jobTitle", "?"), e)
            errors += 1

    db.session.commit()
    log.info(
        "Ingested batch from %s: %d accepted, %d new jobs, %d errors",
        domain, accepted, new_jobs, errors,
    )

    return {"accepted": accepted, "new_jobs": new_jobs, "errors": errors}
