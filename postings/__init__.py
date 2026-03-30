"""
listings/ — Job-first layer for First-Helios.

Inverts the map model: a location only appears when it has an active job
posting.  Every dot = hiring right now.

Can be exercised independently before wiring into the main server:

    python -c "from postings.ingest import ingest_job_posting; print('OK')"
    python -c "from core.database import init_db; init_db()"  # creates job_postings table

Connected to the main server via one line in server.py:
    from postings.routes import jobs_bp
    app.register_blueprint(jobs_bp)

Connected to the scheduler via three lines in backend/scheduler.py:
    from postings.scheduler_jobs import register_listings_jobs
    register_listings_jobs(scheduler)
"""

from postings.ingest import expire_stale_postings, ingest_job_posting

__all__ = ["ingest_job_posting", "expire_stale_postings"]
