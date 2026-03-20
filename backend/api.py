"""
SpiritPool — API Blueprint
===========================
REST endpoints for the SpiritPool extension and any admin tools.

Endpoints
---------
POST /api/spiritpool/contribute
    Receive a batch of signals from the extension.
    Body: { "domain": str, "signals": [...], "contributorId": str|null }

GET  /api/spiritpool/stats
    Return aggregate stats (total jobs, observations, by source, etc.)

GET  /api/spiritpool/jobs
    Paginated job listing with optional filters.

GET  /api/spiritpool/jobs/<id>
    Full detail for a single job with all observations.
"""

import logging

from flask import Blueprint, jsonify, request

from .ingest import ingest_batch
from .models import Company, Job, Observation, db

log = logging.getLogger(__name__)

spiritpool_bp = Blueprint("spiritpool", __name__, url_prefix="/api/spiritpool")


# ── Signal Ingestion ────────────────────────────────────────────────────────

@spiritpool_bp.route("/contribute", methods=["POST"])
def contribute():
    """Receive a batch of signals from the browser extension."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    domain = data.get("domain")
    signals = data.get("signals")
    contributor_id = data.get("contributorId")

    if not domain or not isinstance(signals, list):
        return jsonify({"error": "Missing 'domain' or 'signals' array"}), 400

    if len(signals) == 0:
        return jsonify({"accepted": 0, "new_jobs": 0, "errors": 0}), 200

    # Cap batch size to prevent abuse
    if len(signals) > 1000:
        signals = signals[:1000]

    try:
        result = ingest_batch(domain, signals, contributor_id)
        return jsonify(result), 200
    except Exception as e:
        log.exception("Ingestion failed for domain=%s", domain)
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ── Stats ───────────────────────────────────────────────────────────────────

@spiritpool_bp.route("/stats", methods=["GET"])
def stats():
    """Return aggregate statistics."""
    total_jobs = Job.query.count()
    total_observations = Observation.query.count()
    total_companies = Company.query.count()

    # Per-source breakdown
    source_counts = (
        db.session.query(Job.source, db.func.count(Job.id))
        .group_by(Job.source)
        .all()
    )

    # Recent activity (last 24 hours)
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_observations = Observation.query.filter(Observation.observed_at >= cutoff).count()

    return jsonify({
        "total_jobs": total_jobs,
        "total_observations": total_observations,
        "total_companies": total_companies,
        "observations_last_24h": recent_observations,
        "by_source": {source: count for source, count in source_counts},
    })


# ── Job Listing ─────────────────────────────────────────────────────────────

@spiritpool_bp.route("/jobs", methods=["GET"])
def list_jobs():
    """Paginated job listing with filters."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    source = request.args.get("source")
    company = request.args.get("company")
    search = request.args.get("q")

    query = Job.query.join(Company)

    if source:
        query = query.filter(Job.source == source)
    if company:
        query = query.filter(Company.name_normalised.contains(Company.normalise_name(company)))
    if search:
        term = f"%{search.lower()}%"
        query = query.filter(
            db.or_(
                Job.title_normalised.like(term),
                Company.name_normalised.like(term),
            )
        )

    query = query.order_by(Job.last_seen.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    jobs = []
    for job in pagination.items:
        latest_obs = Observation.query.filter_by(job_id=job.id).order_by(
            Observation.observed_at.desc()
        ).first()

        jobs.append({
            "id": job.id,
            "title": job.title,
            "company": job.company.name,
            "source": job.source,
            "source_job_id": job.source_job_id,
            "url": job.url,
            "first_seen": job.first_seen.isoformat() if job.first_seen else None,
            "last_seen": job.last_seen.isoformat() if job.last_seen else None,
            "observation_count": len(job.observations),
            "latest_salary_min": latest_obs.salary_min if latest_obs else None,
            "latest_salary_max": latest_obs.salary_max if latest_obs else None,
            "latest_applicant_count": latest_obs.applicant_count if latest_obs else None,
        })

    return jsonify({
        "jobs": jobs,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total": pagination.total,
        "pages": pagination.pages,
    })


# ── Job Detail ──────────────────────────────────────────────────────────────

@spiritpool_bp.route("/jobs/<int:job_id>", methods=["GET"])
def job_detail(job_id):
    """Full detail for a single job with observation history."""
    job = Job.query.get_or_404(job_id)

    observations = []
    for obs in job.observations:
        observations.append({
            "id": obs.id,
            "signal_type": obs.signal_type,
            "observed_at": obs.observed_at.isoformat() if obs.observed_at else None,
            "location": obs.location.raw if obs.location else None,
            "salary_min": obs.salary_min,
            "salary_max": obs.salary_max,
            "salary_period": obs.salary_period,
            "posting_date": obs.posting_date.isoformat() if obs.posting_date else None,
            "applicant_count": obs.applicant_count,
            "badges": obs.badges,
        })

    return jsonify({
        "id": job.id,
        "title": job.title,
        "company": job.company.name,
        "source": job.source,
        "source_job_id": job.source_job_id,
        "url": job.url,
        "first_seen": job.first_seen.isoformat() if job.first_seen else None,
        "last_seen": job.last_seen.isoformat() if job.last_seen else None,
        "observations": observations,
    })
