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

from core.database import get_session, init_db
from core.normalizer import normalize_name
from postings.ingest import ingest_job_posting
from postings.models import JobPosting
from collectors.base import ScraperSignal

logger = logging.getLogger(__name__)


def _err(exc: Exception, status: int = 500):
    """Log exception server-side; never expose internal details in the response."""
    logger.error("[SpiritPool] %s", exc, exc_info=True)
    return jsonify({"error": "internal error"}), status

spiritpool_bp = Blueprint("spiritpool", __name__, url_prefix="/api/spiritpool")

# ── Input guards ──────────────────────────────────────────────────────────────

MAX_SIGNALS_PER_BATCH = 50

# Domains the extension is known to scrape. Unknown domains are rejected so
# attackers cannot fabricate arbitrary source tags in the database.
_ALLOWED_DOMAINS = {
    "indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
    "monster.com", "simplyhired.com", "careerbuilder.com", "dice.com",
    "lever.co", "greenhouse.io", "workday.com", "myworkdayjobs.com",
    "jobvite.com", "icims.com", "smartrecruiters.com", "taleo.net",
}

def _normalize_domain(raw: str) -> str | None:
    """Return the allowlisted domain slug or None if not recognised."""
    if not raw or not isinstance(raw, str):
        return None
    domain_lower = raw.strip().lower()
    # Accept "indeed.com" or bare "indeed"
    if domain_lower in _ALLOWED_DOMAINS:
        return domain_lower.split(".")[0]
    # Try matching by slug prefix
    slug = domain_lower.split(".")[0]
    for allowed in _ALLOWED_DOMAINS:
        if allowed.startswith(slug + "."):
            return slug
    return None


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
    # domain is already validated and normalised by the time _map_signal is called.
    domain_slug = domain  # caller passes the pre-validated slug
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

    domain_slug = _normalize_domain(body.get("domain", ""))
    if domain_slug is None:
        return jsonify({"error": "unrecognised domain"}), 400

    signals_raw = body.get("signals", [])
    contributor_id = body.get("contributorId", "anonymous")
    region = body.get("region") or "austin_tx"

    if not isinstance(signals_raw, list):
        return jsonify({"error": "signals must be a list"}), 400

    if len(signals_raw) > MAX_SIGNALS_PER_BATCH:
        return jsonify({"error": f"batch too large (max {MAX_SIGNALS_PER_BATCH})"}), 400

    engine = init_db()
    session = get_session(engine)

    accepted = 0
    failed = 0

    try:
        for raw in signals_raw:
            if not isinstance(raw, dict):
                failed += 1
                continue

            signal = _map_signal(raw, domain_slug, contributor_id)
            if signal is None:
                failed += 1
                continue

            try:
                result, _ = ingest_job_posting(signal, region=region, session=session)
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
            "[SpiritPool] %s: accepted=%d failed=%d contributor=%s ip=%s region=%s",
            domain_slug, accepted, failed, contributor_id,
            request.remote_addr, region,
        )
        return jsonify({
            "accepted": accepted,
            "new_jobs": accepted,   # kept for background.js compatibility
            "failed": failed,
        })

    except Exception as exc:
        logger.error("[SpiritPool] contribute error: %s", exc)
        return _err(exc)
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
        return _err(exc)
    finally:
        session.close()


# ── GET /api/spiritpool/insights ──────────────────────────────────────────────

@spiritpool_bp.route("/insights", methods=["GET"])
def insights():
    """Return job-market insight stats for the Spirit Pool extension popup.

    Query params:
      region   (default: austin_tx)
      industry (optional)

    Response:
        {
            "new_jobs_7d":          N,
            "new_jobs_prev_7d":     N,
            "trend_pct":            float,
            "top_hiring_employers": [ {"name": "...", "count": N}, ... ],
            "salary_p50_hourly":    float|null,
            "salary_p75_hourly":    float|null,
            "with_salary_pct":      float,
            "remote_pct":           float,
            "job_board_url":        "..."
        }
    """
    import statistics

    region = request.args.get("region", "austin_tx")
    industry = request.args.get("industry", "").strip() or None

    engine = init_db()
    session = get_session(engine)
    try:
        now = datetime.utcnow()
        cutoff_7d = now - timedelta(days=7)
        cutoff_14d = now - timedelta(days=14)

        base_q = session.query(JobPosting).filter(
            JobPosting.region == region,
            JobPosting.is_active.is_(True),
        )
        if industry:
            base_q = base_q.filter(JobPosting.industry == industry)

        # ── New jobs counts ───────────────────────────────────────────────
        new_7d = base_q.filter(JobPosting.scraped_at >= cutoff_7d).count()
        new_prev_7d = base_q.filter(
            JobPosting.scraped_at >= cutoff_14d,
            JobPosting.scraped_at < cutoff_7d,
        ).count()
        trend_pct = (
            round((new_7d - new_prev_7d) / new_prev_7d * 100, 1)
            if new_prev_7d > 0
            else 0.0
        )

        # ── Top hiring employers this week ────────────────────────────────
        top_rows = (
            base_q.filter(JobPosting.scraped_at >= cutoff_7d)
            .with_entities(
                JobPosting.raw_employer_name,
                func.count(JobPosting.id).label("cnt"),
            )
            .group_by(JobPosting.raw_employer_name)
            .order_by(text("cnt DESC"))
            .limit(5)
            .all()
        )
        top_hiring = [{"name": r[0], "count": r[1]} for r in top_rows]

        # ── Salary percentiles (hourly) ───────────────────────────────────
        wage_rows = (
            base_q.filter(JobPosting.wage_min.isnot(None))
            .with_entities(JobPosting.wage_min, JobPosting.wage_period)
            .all()
        )
        total_active = base_q.count()

        hourly_vals = []
        for wmin, wperiod in wage_rows:
            if wperiod == "yearly":
                hourly_vals.append(wmin / 2080)
            elif wperiod == "monthly":
                hourly_vals.append(wmin * 12 / 2080)
            elif wperiod == "weekly":
                hourly_vals.append(wmin / 40)
            else:
                hourly_vals.append(wmin)

        hourly_vals.sort()

        salary_p50 = round(statistics.median(hourly_vals), 2) if hourly_vals else None
        salary_p75 = None
        if hourly_vals:
            idx = int(len(hourly_vals) * 0.75)
            salary_p75 = round(hourly_vals[min(idx, len(hourly_vals) - 1)], 2)

        with_salary_pct = round(len(wage_rows) / total_active * 100, 1) if total_active else 0.0

        # ── Remote percentage ─────────────────────────────────────────────
        remote_count = base_q.filter(JobPosting.is_remote.is_(True)).count()
        remote_pct = round(remote_count / total_active * 100, 1) if total_active else 0.0

        # ── Job board URL ─────────────────────────────────────────────────
        board_url = "http://localhost:8765/?mode=jobfinder"
        if industry:
            from urllib.parse import quote
            board_url += "&category=" + quote(industry)

        return jsonify({
            "new_jobs_7d":          new_7d,
            "new_jobs_prev_7d":     new_prev_7d,
            "trend_pct":            trend_pct,
            "top_hiring_employers": top_hiring,
            "salary_p50_hourly":    salary_p50,
            "salary_p75_hourly":    salary_p75,
            "with_salary_pct":      with_salary_pct,
            "remote_pct":           remote_pct,
            "job_board_url":        board_url,
        })

    except Exception as exc:
        logger.error("[SpiritPool] insights error: %s", exc)
        return _err(exc)
    finally:
        session.close()
