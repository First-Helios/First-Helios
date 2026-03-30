"""
listings/spiritpool_routes.py — Flask Blueprint for Spirit Pool crowdsourced ingest.

Endpoints:
    POST /api/spiritpool/contribute   Receive a batch of signals from the extension.
    GET  /api/spiritpool/stats        Return aggregate stats for the spiritpool dashboard.

Signal → job_posting flow:
    Spirit Pool signal (JSON) → ScraperSignal → ingest_job_posting() → job_postings table
"""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, text

from backend.database import get_session, init_db
from backend.normalizer import normalize_name
from postings.ingest import ingest_job_posting
from postings.models import JobPosting
from collectors.base import ScraperSignal

logger = logging.getLogger(__name__)

spiritpool_bp = Blueprint("spiritpool", __name__, url_prefix="/api/spiritpool")


# ── Helper: map Spirit Pool signal dict → ScraperSignal ───────────────────────

def _map_signal(raw: dict, domain: str, contributor_id: str) -> ScraperSignal | None:
    """Convert a raw Spirit Pool signal dict into a ScraperSignal.

    Returns None if the signal lacks a company name or job title (cannot be
    meaningfully ingested without at least one identifying field).
    """
    company = raw.get("company") or ""
    job_title = raw.get("jobTitle") or raw.get("title") or ""

    if not company and not job_title:
        return None

    salary = raw.get("salary") or {}
    wage_min = salary.get("min")
    wage_max = salary.get("max")
    wage_period = salary.get("period")

    # Normalise wage period to "hourly" | "yearly" understood by ingest
    if wage_period and wage_period not in ("hourly", "yearly"):
        if "hour" in wage_period.lower() or wage_period.lower() == "hr":
            wage_period = "hourly"
        elif "year" in wage_period.lower() or "annual" in wage_period.lower():
            wage_period = "yearly"
        else:
            wage_period = None

    # Source tag: "spiritpool_indeed", "spiritpool_linkedin", etc.
    domain_slug = domain.split(".")[0].lower()  # "indeed", "linkedin", ...
    source = f"spiritpool_{domain_slug}"

    # store_num is synthetic — Spirit Pool doesn't know the store number
    chain_slug = normalize_name(company)[:20] if company else "unknown"
    store_num = f"SP-{chain_slug}"

    return ScraperSignal(
        store_num=store_num,
        chain=normalize_name(company),
        source=source,
        signal_type="listing",
        value=1.0,
        metadata={
            "company":        company,
            "address":        raw.get("location"),
            "posted_date":    raw.get("postingDate"),
            "job_url":        raw.get("url"),
            "description":    raw.get("description"),
            "job_type":       raw.get("jobType"),
            "is_remote":      raw.get("isRemote"),
            "applicants":     raw.get("applicantCount"),
            "salary_source":  raw.get("salarySource"),
            "company_industry": raw.get("companyIndustry"),
            "job_level":      raw.get("jobLevel"),
            "badges":         raw.get("badges", []),
            "contributor_id": contributor_id,
            "rating":         raw.get("rating"),
        },
        wage_min=float(wage_min) if wage_min is not None else None,
        wage_max=float(wage_max) if wage_max is not None else None,
        wage_period=wage_period,
        role_title=job_title or None,
        source_url=raw.get("url"),
        observed_at=datetime.utcnow(),
    )


# ── POST /api/spiritpool/contribute ───────────────────────────────────────────

@spiritpool_bp.route("/contribute", methods=["POST"])
def contribute():
    """Receive a batch of Spirit Pool signals and ingest them into job_postings.

    Expected body:
        {
            "domain":        "indeed.com",
            "signals":       [ {signal}, ... ],
            "contributorId": "uuid",
            "region":        "austin_tx"   (optional, defaults to austin_tx)
        }

    Response:
        { "accepted": N, "new_jobs": N, "failed": K }
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    domain = body.get("domain", "unknown")
    signals_raw = body.get("signals", [])
    contributor_id = body.get("contributorId", "anonymous")
    region = body.get("region") or "austin_tx"

    if not isinstance(signals_raw, list):
        return jsonify({"error": "signals must be a list"}), 400

    engine = init_db()
    session = get_session(engine)

    accepted = 0
    failed = 0

    try:
        for raw in signals_raw:
            if not isinstance(raw, dict):
                failed += 1
                continue

            signal = _map_signal(raw, domain, contributor_id)
            if signal is None:
                failed += 1
                continue

            try:
                result = ingest_job_posting(signal, region=region, session=session)
                if result is not None:
                    accepted += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.warning(
                    "[SpiritPool] ingest failed for %r from %s: %s",
                    raw.get("jobTitle"), domain, exc,
                )
                session.rollback()
                failed += 1

        logger.info(
            "[SpiritPool] %s: accepted=%d failed=%d contributor=%s region=%s",
            domain, accepted, failed, contributor_id[:8], region,
        )
        return jsonify({
            "accepted": accepted,
            "new_jobs": accepted,   # kept for background.js compatibility
            "failed": failed,
        })

    except Exception as exc:
        logger.error("[SpiritPool] contribute error: %s", exc)
        return jsonify({"error": "internal error", "detail": str(exc)}), 500
    finally:
        session.close()


# ── GET /api/spiritpool/stats ─────────────────────────────────────────────────

@spiritpool_bp.route("/stats", methods=["GET"])
def stats():
    """Return aggregate stats for Spirit Pool contributions.

    Response:
        {
            "total_jobs":          N,
            "total_observations":  N,
            "by_source":           { "spiritpool_indeed": N, ... },
            "observations_last_24h": N
        }
    """
    engine = init_db()
    session = get_session(engine)
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)

        total = (
            session.query(func.count(JobPosting.id))
            .filter(JobPosting.source.like("spiritpool_%"))
            .scalar() or 0
        )

        last_24h = (
            session.query(func.count(JobPosting.id))
            .filter(
                JobPosting.source.like("spiritpool_%"),
                JobPosting.scraped_at >= cutoff,
            )
            .scalar() or 0
        )

        by_source_rows = (
            session.query(JobPosting.source, func.count(JobPosting.id))
            .filter(JobPosting.source.like("spiritpool_%"))
            .group_by(JobPosting.source)
            .all()
        )
        by_source = {row[0]: row[1] for row in by_source_rows}

        return jsonify({
            "total_jobs":            total,
            "total_observations":    total,
            "by_source":             by_source,
            "observations_last_24h": last_24h,
        })

    except Exception as exc:
        logger.error("[SpiritPool] stats error: %s", exc)
        return jsonify({"error": "internal error", "detail": str(exc)}), 500
    finally:
        session.close()
