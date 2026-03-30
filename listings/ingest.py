"""
listings/ingest.py — Single write path for all JobPosting records.

Every job-posting source — JobSpy, Jobicy, Workday careers_api, manual CSV —
calls ingest_job_posting() instead of writing to job_postings directly.
This mirrors the design of backend/ingest_layer.py for LocalEmployer rows.

Main entry point:
    ingest_job_posting(signal, region, session)

Pipeline per signal:
  1. Extract employer name, address, lat/lng, posted_date, external_id
  2. Deduplicate via (source, external_id) — skip if active, reactivate if expired
  3. Normalize name + compute fingerprint (backend.normalizer)
  4. Geocode if lat/lng absent and raw_address present (scrapers.geocoding)
  5. Compute H3 cells (r7, r8) from lat/lng — NULL if coordinates unavailable
  6. Match to LocalEmployer (listings.matcher)
  7. Compute expires_at = (posted_date or scraped_at) + TTL_DAYS
  8. Upsert via PostgreSQL INSERT … ON CONFLICT DO UPDATE

Companion function:
    expire_stale_postings(region, session) — bulk-expire postings past expires_at.
    Intended for a nightly scheduler job.
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.database import get_engine, get_session, init_db
from backend.normalizer import make_fingerprint, map_industry, normalize_name
from listings.config import POSTING_TTL_DAYS
from listings.matcher import match_posting_to_employer
from listings.models import JobPosting
from scrapers.base import ScraperSignal

logger = logging.getLogger(__name__)


# ── External ID derivation ────────────────────────────────────────────────────

def _sha40(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:40]


def _derive_external_id(signal: ScraperSignal) -> str:
    """Return a stable, unique ID for this posting within its source.

    Workday (careers_api): uses the externalPath field which is globally unique.
    JobSpy: uses job_url (hashed if > 255 chars to stay within the column).
    Generic fallback: content hash of employer + title + address + date.
    """
    meta: dict[str, Any] = signal.metadata or {}

    if signal.source == "careers_api":
        ext = meta.get("external_path") or meta.get("externalPath")
        return ext if ext else _sha40(signal.source_url or str(signal.observed_at))

    if signal.source == "workday_gov":
        ext = meta.get("external_path") or meta.get("job_req_id")
        return ext if ext else _sha40(signal.source_url or str(signal.observed_at))

    if signal.source == "jobspy":
        url = meta.get("job_url") or signal.source_url or ""
        return url if len(url) <= 255 else _sha40(url)

    if signal.source in ("theirstack", "serpapi_google_jobs", "rapidapi_activejobs", "juju", "jobicy"):
        ext = meta.get("external_path")
        if ext:
            return str(ext)
        return _sha40(signal.source_url or str(signal.observed_at))

    # Generic fallback
    key = "|".join([
        signal.chain or "",
        signal.role_title or "",
        meta.get("address") or meta.get("location") or "",
        str((signal.observed_at or datetime.utcnow()).date()),
    ])
    return _sha40(key)


# ── H3 computation ────────────────────────────────────────────────────────────

def _compute_h3(
    lat: float | None,
    lng: float | None,
) -> tuple[str | None, str | None]:
    """Return (h3_r7, h3_r8) for a coordinate pair, or (None, None) if unavailable."""
    if lat is None or lng is None:
        return None, None
    try:
        import h3
        return h3.latlng_to_cell(lat, lng, 7), h3.latlng_to_cell(lat, lng, 8)
    except Exception as exc:
        logger.warning("[ListingsIngest] H3 computation failed for (%s, %s): %s", lat, lng, exc)
        return None, None


# ── Geocoding helper ──────────────────────────────────────────────────────────

def _geocode_if_needed(
    lat: float | None,
    lng: float | None,
    address: str | None,
) -> tuple[float | None, float | None, str | None]:
    """Return (lat, lng, geocode_source).  Only calls Nominatim when necessary."""
    if lat is not None and lng is not None:
        return lat, lng, "provided"
    if not address:
        return None, None, None
    try:
        from scrapers.geocoding import geocode
        glat, glng = geocode(address)
        if glat is not None:
            return glat, glng, "nominatim"
    except Exception as exc:
        logger.warning("[ListingsIngest] Geocode failed for %r: %s", address, exc)
    return None, None, None


# ── Main ingest function ──────────────────────────────────────────────────────

def ingest_job_posting(
    signal: ScraperSignal,
    region: str,
    session: Session | None = None,
    ttl_days: int = POSTING_TTL_DAYS,
) -> "JobPosting | None":
    """Normalise and upsert one job-posting signal into the job_postings table.

    Args:
        signal:   ScraperSignal with signal_type == "listing".
        region:   Region key, e.g. "austin_tx".
        session:  Active SQLAlchemy session.  If None, one is created and
                  closed within this call.
        ttl_days: Override the default posting TTL.

    Returns:
        The JobPosting ORM row, or None if the signal was skipped / invalid.
    """
    if signal.signal_type != "listing":
        return None

    meta: dict[str, Any] = signal.metadata or {}

    # ── 1. Extract ────────────────────────────────────────────────────────────
    raw_employer = (
        meta.get("company")
        or meta.get("employer")
        or signal.chain
        or ""
    )
    if not raw_employer:
        logger.debug("[ListingsIngest] No employer name in signal — skipping")
        return None

    if "address" in meta:
        raw_address = meta["address"]  # explicit None respected — prevents geocoder fallback to "location"
    else:
        raw_address = meta.get("location_text") or meta.get("location")
    posting_lat = meta.get("lat") or meta.get("latitude")
    posting_lng = meta.get("lng") or meta.get("longitude")

    try:
        posting_lat = float(posting_lat) if posting_lat is not None else None
        posting_lng = float(posting_lng) if posting_lng is not None else None
    except (TypeError, ValueError):
        posting_lat = posting_lng = None

    # Parse posted_date from metadata or fall back to observed_at
    posted_date: datetime | None = None
    raw_date = meta.get("posted_date") or meta.get("date_posted")
    if raw_date:
        try:
            if isinstance(raw_date, datetime):
                posted_date = raw_date
            else:
                from dateutil.parser import parse as _parse_date
                posted_date = _parse_date(str(raw_date))
        except Exception:
            posted_date = None
    if posted_date is None:
        posted_date = signal.observed_at

    external_id = _derive_external_id(signal)

    # ── 2. Session management ─────────────────────────────────────────────────
    _owns_session = session is None
    if _owns_session:
        engine = init_db()
        session = get_session(engine)

    try:
        # ── 3. Normalise ──────────────────────────────────────────────────────
        normalized = normalize_name(raw_employer)
        fingerprint = make_fingerprint(raw_employer)

        # ── 4. Geocode ────────────────────────────────────────────────────────
        lat, lng, geocode_src = _geocode_if_needed(posting_lat, posting_lng, raw_address)

        # ── 5. H3 cells ───────────────────────────────────────────────────────
        h3_r7, h3_r8 = _compute_h3(lat, lng)

        # ── 6. Match to LocalEmployer ─────────────────────────────────────────
        employer, confidence, method = match_posting_to_employer(session, fingerprint, lat, lng)
        local_employer_id = employer.id if employer else None

        # ── 7. Industry ───────────────────────────────────────────────────────
        industry = (
            (employer.industry if employer else None)
            or map_industry(meta.get("category", ""))
        )

        # ── 8. Remote flag + address audit ────────────────────────────────────
        is_remote_raw = meta.get("is_remote")
        is_remote: bool | None = bool(is_remote_raw) if is_remote_raw is not None else None
        address_method: str | None = meta.get("address_method") or None
        job_excerpt: str | None = (meta.get("job_excerpt") or "")[:600] or None

        # ── 8b. Rich detail (JSONB) ───────────────────────────────────────────
        # Collect structured fields from metadata for the job board UI.
        _DETAIL_KEYS = (
            "minimum_qualifications", "ksa", "preferred_qualifications",
            "education", "licenses", "days_and_hours", "location_detail",
            "pay_range_raw", "time_type", "notes_to_candidate",
        )
        detail_json: dict | None = {k: meta[k] for k in _DETAIL_KEYS if meta.get(k)}
        # Preserve alternative apply URLs if the adapter collected them.
        apply_urls = meta.get("apply_urls")
        if apply_urls and isinstance(apply_urls, list) and len(apply_urls) > 1:
            if detail_json is None:
                detail_json = {}
            detail_json["apply_urls"] = apply_urls
        detail_json = detail_json or None  # store NULL not empty dict

        # ── 8c. Referral URL ──────────────────────────────────────────────────
        # Sources with affiliate/referral programs set metadata["referral_url"].
        # This is the preferred link for payout-earning clicks.
        referral_url: str | None = meta.get("referral_url") or None

        # ── 9. Compute expires_at ─────────────────────────────────────────────
        now = datetime.utcnow()
        # Initial insert anchors to posted_date; re-scrape rolls forward from now.
        # A listing that disappears from the feed stops getting refreshed and
        # naturally expires after TTL_DAYS of silence.
        initial_expires_at = (posted_date or now) + timedelta(days=ttl_days)
        refresh_expires_at = now + timedelta(days=ttl_days)

        # ── 10. Upsert ────────────────────────────────────────────────────────
        posting_data = {
            "source":             signal.source,
            "source_url":         signal.source_url,
            "external_id":        external_id,
            "raw_employer_name":  raw_employer,
            "normalized_name":    normalized,
            "fingerprint":        fingerprint,
            "role_title":         signal.role_title,
            "wage_min":           signal.wage_min,
            "wage_max":           signal.wage_max,
            "wage_period":        signal.wage_period,
            "region":             region,
            "industry":           industry,
            "raw_address":        raw_address,
            "lat":                lat,
            "lng":                lng,
            "geocode_source":     geocode_src,
            "h3_r7":              h3_r7,
            "h3_r8":              h3_r8,
            "is_remote":          is_remote,
            "address_method":     address_method,
            "job_excerpt":        job_excerpt,
            "detail_json":        detail_json,
            "referral_url":       referral_url,
            "local_employer_id":  local_employer_id,
            "match_confidence":   confidence if confidence > 0 else None,
            "match_method":       method,
            "posted_date":        posted_date,
            "scraped_at":         now,
            "expires_at":         initial_expires_at,
            "is_active":          True,
        }

        stmt = (
            pg_insert(JobPosting)
            .values(**posting_data)
            .on_conflict_do_update(
                constraint="uq_job_posting_source_external",
                set_={
                    # Freshness — always update on re-scrape
                    "is_active":          True,
                    "scraped_at":         now,
                    # Roll the expiry window forward from now so listings that
                    # remain active in the feed never go stale.
                    "expires_at":         refresh_expires_at,
                    # Mutable fields — update if the source changes them
                    "source_url":         signal.source_url,
                    "role_title":         signal.role_title,
                    "wage_min":           signal.wage_min,
                    "wage_max":           signal.wage_max,
                    "wage_period":        signal.wage_period,
                    "raw_address":        raw_address,
                    "lat":                lat,
                    "lng":                lng,
                    "geocode_source":     geocode_src,
                    "h3_r7":              h3_r7,
                    "h3_r8":              h3_r8,
                    "is_remote":          is_remote,
                    "address_method":     address_method,
                    "job_excerpt":        job_excerpt,
                    "detail_json":        detail_json,
                    "local_employer_id":  local_employer_id,
                    "match_confidence":   confidence if confidence > 0 else None,
                    "match_method":       method,
                    # Referral URL: only overwrite if new value is non-null.
                    # This preserves a referral link set by a different source.
                    **({
                        "referral_url": referral_url,
                    } if referral_url else {}),
                },
            )
            .returning(JobPosting.id)
        )

        result = session.execute(stmt)
        session.commit()
        row_id = result.scalar()

        logger.debug(
            "[ListingsIngest] Upserted job_posting id=%s  %r → employer=%s (method=%s conf=%.2f)",
            row_id, normalized, local_employer_id, method, confidence,
        )
        return session.get(JobPosting, row_id)

    except Exception as exc:
        logger.error("[ListingsIngest] Failed to ingest posting for %r: %s", raw_employer, exc)
        session.rollback()
        return None
    finally:
        if _owns_session:
            session.close()


# ── Expiry sweep ──────────────────────────────────────────────────────────────

def expire_stale_postings(region: str, session: Session) -> int:
    """Flip is_active = False on all job_postings where expires_at < NOW().

    Designed for a nightly scheduler job.  Does NOT delete rows — stale
    postings are kept for historical analysis.

    Args:
        region:  Region key to scope the sweep (e.g. "austin_tx").
        session: Active SQLAlchemy session.

    Returns:
        Number of rows expired.
    """
    now = datetime.utcnow()
    count = (
        session.query(JobPosting)
        .filter(
            JobPosting.region == region,
            JobPosting.is_active.is_(True),
            JobPosting.expires_at < now,
        )
        .update({"is_active": False}, synchronize_session=False)
    )
    session.commit()
    logger.info("[ListingsIngest] Expired %d stale postings for region=%s", count, region)
    return count
