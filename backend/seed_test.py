#!/usr/bin/env python3
"""
seed_test.py — Seed the SpiritPool DB with realistic test data
================================================================
Usage:
    .venv/bin/python -m backend.seed_test          # POST to running server
    .venv/bin/python -m backend.seed_test --direct  # Write directly via SQLAlchemy

This sends realistic Starbucks/coffee-chain job signals to verify
the full ingestion pipeline works end-to-end.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

# ── Test Payloads ──────────────────────────────────────────────────────────

LINKEDIN_SIGNALS = [
    {
        "source": "linkedin.com",
        "signalType": "listing",
        "company": "Starbucks",
        "jobTitle": "Barista - Store #6281 (Capitol Hill)",
        "location": "Seattle, WA, US",
        "url": "https://www.linkedin.com/jobs/view/4100000001",
        "jobId": "4100000001",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 17.50, "max": 22.00, "period": "hourly"},
        "applicantCount": 34,
        "badges": ["Easy Apply", "Reposted"],
    },
    {
        "source": "linkedin.com",
        "signalType": "listing",
        "company": "Starbucks",
        "jobTitle": "Shift Supervisor - Store #10421",
        "location": "Portland, OR, US",
        "url": "https://www.linkedin.com/jobs/view/4100000002",
        "jobId": "4100000002",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 20.00, "max": 28.00, "period": "hourly"},
        "applicantCount": 12,
        "badges": ["Easy Apply"],
    },
    {
        "source": "linkedin.com",
        "signalType": "listing",
        "company": "Starbucks",
        "jobTitle": "Store Manager - Store #5512 (Downtown)",
        "location": "San Francisco, CA, US",
        "url": "https://www.linkedin.com/jobs/view/4100000003",
        "jobId": "4100000003",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 65000, "max": 85000, "period": "yearly"},
        "applicantCount": 67,
        "badges": [],
    },
    {
        "source": "linkedin.com",
        "signalType": "listing_detail",
        "company": "Starbucks",
        "jobTitle": "Barista - Store #6281 (Capitol Hill)",
        "location": "Seattle, WA, US",
        "url": "https://www.linkedin.com/jobs/view/4100000001",
        "jobId": "4100000001",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 17.50, "max": 22.00, "period": "hourly"},
        "applicantCount": 36,
        "badges": ["Easy Apply", "Reposted"],
    },
    {
        "source": "linkedin.com",
        "signalType": "listing",
        "company": "Dutch Bros Coffee",
        "jobTitle": "Broista (Barista)",
        "location": "Boise, ID, US",
        "url": "https://www.linkedin.com/jobs/view/4100000004",
        "jobId": "4100000004",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 15.00, "max": 19.00, "period": "hourly"},
        "applicantCount": 8,
        "badges": ["Easy Apply"],
    },
    {
        "source": "linkedin.com",
        "signalType": "listing",
        "company": "Peet's Coffee",
        "jobTitle": "Retail Shift Lead",
        "location": "Berkeley, CA, US",
        "url": "https://www.linkedin.com/jobs/view/4100000005",
        "jobId": "4100000005",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": None,
        "applicantCount": 15,
        "badges": [],
    },
]

INDEED_SIGNALS = [
    {
        "source": "indeed.com",
        "signalType": "listing",
        "company": "Starbucks",
        "jobTitle": "barista - Store 9983",
        "location": "Chicago, IL",
        "url": "https://www.indeed.com/viewjob?jk=abc123",
        "jobId": "abc123",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 16.00, "max": 20.00, "period": "hourly"},
        "applicantCount": None,
        "badges": ["Urgently hiring"],
    },
    {
        "source": "indeed.com",
        "signalType": "listing",
        "company": "Starbucks",
        "jobTitle": "Shift Manager",
        "location": "Austin, TX",
        "url": "https://www.indeed.com/viewjob?jk=def456",
        "jobId": "def456",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "salary": {"min": 22.00, "max": 30.00, "period": "hourly"},
        "applicantCount": None,
        "badges": [],
    },
]


def seed_via_http(base_url="http://localhost:8765"):
    """POST test payloads to the running server."""
    import requests

    url = f"{base_url}/api/spiritpool/contribute"
    contributor = "seed-test-uuid-001"

    print(f"Posting to {url}...")

    # LinkedIn batch
    resp = requests.post(url, json={
        "domain": "linkedin.com",
        "signals": LINKEDIN_SIGNALS,
        "contributorId": contributor,
    })
    print(f"  LinkedIn: {resp.status_code} → {resp.json()}")

    # Indeed batch
    resp = requests.post(url, json={
        "domain": "indeed.com",
        "signals": INDEED_SIGNALS,
        "contributorId": contributor,
    })
    print(f"  Indeed:   {resp.status_code} → {resp.json()}")

    # Check stats
    resp = requests.get(f"{base_url}/api/spiritpool/stats")
    stats = resp.json()
    print(f"\n--- Server Stats ---")
    print(f"  Total jobs:         {stats['total_jobs']}")
    print(f"  Total observations: {stats['total_observations']}")
    print(f"  Total companies:    {stats['total_companies']}")
    print(f"  Last 24h:           {stats['observations_last_24h']}")
    print(f"  By source:          {stats['by_source']}")

    # Quick sanity
    if stats["total_jobs"] >= 7 and stats["total_observations"] >= 8:
        print("\n✅ Seed successful — pipeline is working!")
    else:
        print("\n⚠ Unexpected counts — check server logs.")


def seed_direct():
    """Write directly to DB via SQLAlchemy (no running server needed)."""
    import os
    from pathlib import Path

    # Add project root to path
    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root))

    from flask import Flask
    from backend.models import db as _db
    from backend.ingest import ingest_batch

    db_path = root / "data" / "spiritpool.db"
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    _db.init_app(app)

    with app.app_context():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db.create_all()

        r1 = ingest_batch("linkedin.com", LINKEDIN_SIGNALS, "seed-test-uuid-001")
        print(f"LinkedIn: {r1}")

        r2 = ingest_batch("indeed.com", INDEED_SIGNALS, "seed-test-uuid-001")
        print(f"Indeed:   {r2}")

        from backend.models import Job, Observation, Company
        print(f"\n--- DB Stats ---")
        print(f"  Jobs:         {Job.query.count()}")
        print(f"  Observations: {Observation.query.count()}")
        print(f"  Companies:    {Company.query.count()}")
        print("\n✅ Direct seed complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed SpiritPool DB with test data")
    parser.add_argument("--direct", action="store_true",
                        help="Write directly via SQLAlchemy instead of HTTP POST")
    parser.add_argument("--url", default="http://localhost:8765",
                        help="Backend URL (default: http://localhost:8765)")
    args = parser.parse_args()

    if args.direct:
        seed_direct()
    else:
        seed_via_http(args.url)
