"""
scrapers/activejobs_adapter.py — RapidAPI Active Jobs DB adapter.

Fetches job listings from https://active-jobs-db.p.rapidapi.com and
routes every result through listings/ingest.py (ingest_job_posting),
the single write path for all JobPosting records.

API overview:
  Product:   RapidAPI — Active Jobs DB
             https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/active-jobs-db
  Base URL:  https://active-jobs-db.p.rapidapi.com
  Auth:      RapidAPI key headers on every request
  source_key: "rapidapi_activejobs"

Endpoint discovery (tried in order until one returns 200 with job data):
  1. GET /active-ats-7d?limit=100&location_filter=Austin.*TX
  2. GET /active-ats-7d?limit=100&job_country=US  (then filter locally)
  3. GET /v1/jobs?limit=100&location=Austin,TX

Strategy: one call per 24 hours, limit=100 — the API maximum.  No
keyword/title filter is applied — broad collection, then local filter
to Austin/Round Rock metro after fetch.

Monthly hard caps: 25 requests/month and 250 jobs/month.  The 24-hour
gate and strong 24-hour cache (_TTL_MINUTES=1440) keep usage well within
those limits under normal scheduled operation.

Austin/Round Rock bounding area (lat 30.0–30.75, lng -98.3 to -97.4) is
used when the API returns lat/lng.  If only a location string is present,
jobs are kept when the string contains Austin, Round Rock, or any of the
listed surrounding cities, or "TX" broadly.

Called by: backend/scheduler.py, CLI
"""

import argparse
import html as _html_mod
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from core.tracked_request import check_budget, tracked_get
from collectors.base import BaseScraper, ScraperSignal
from collectors.cache import read_cache, write_cache

logger = logging.getLogger(__name__)

_BASE_URL = "https://active-jobs-db.p.rapidapi.com"
_SOURCE_KEY = "rapidapi_activejobs"
_RAPIDAPI_HOST = "active-jobs-db.p.rapidapi.com"

# 24-hour cache — strong gate to stay within 25 req/month limit
_TTL_MINUTES = 1440  # 24 hours
_MIN_INTERVAL_HOURS = 24

# Austin metro bounding box for lat/lng filtering
_LAT_MIN, _LAT_MAX = 30.0, 30.75
_LNG_MIN, _LNG_MAX = -98.3, -97.4

# Location strings accepted as Austin-area for string-based filtering
_AUSTIN_AREA_TERMS = frozenset({
    "austin", "round rock", "cedar park", "georgetown", "pflugerville",
    "hutto", "kyle", "buda", "san marcos",
})

# Candidate endpoints tried in order — first 200 with job data wins
_CANDIDATE_ENDPOINTS: list[tuple[str, dict[str, Any]]] = [
    ("/active-ats-7d", {"limit": 100, "location_filter": "Austin.*TX"}),
    ("/active-ats-7d", {"limit": 100, "job_country": "US"}),
    ("/v1/jobs",       {"limit": 100, "location": "Austin,TX"}),
]

# Country/region strings that are NOT geocodable street addresses.
_GEO_NOISE = frozenset({
    "usa", "us", "united states", "united states of america",
    "worldwide", "world", "global", "remote", "anywhere",
    "north america", "latin america", "south america",
    "europe", "asia", "africa", "oceania", "apac", "emea",
    "", "null", "none",
})

# Fallback regex: street number + named road type, no state required.
# Guards against common false positives in job descriptions:
#   - Salary fragments: "120,000 USD" → (?<![,\d]) blocks matching ",000"
#   - Zero-prefixed numbers: "000 employees" → [1-9] requires non-zero first digit
#   - St/Rd inside words: "Stock", "Road" in "railroad" → \b after each type token
_STREET_RE = re.compile(
    r'(?<![,\d])\b[1-9]\d{2,5}\s+[A-Za-z][A-Za-z0-9\s]{1,40}'
    r'(?:Street\b|St\b|Avenue\b|Ave\b|Boulevard\b|Blvd\b|Road\b|Rd\b|Drive\b|Dr\b|'
    r'Lane\b|Ln\b|Parkway\b|Pkwy\b|Way\b|Court\b|Ct\b|Place\b|Pl\b|Circle\b|Cir\b)'
    r'[^<\n]{0,120}',
    re.IGNORECASE,
)

# A real US street address is typically 15–120 characters.
_ADDR_MIN_LEN = 15
_ADDR_MAX_LEN = 120


def _strip_html(raw: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = _html_mod.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _find_address(text: str) -> tuple[str, str] | None:
    """Find the first US address in plain text.

    Returns (address, method) where method is 'pyap' or 'regex', or None.

    Tries pyap first (structured, state-abbreviation-aware). Falls back to
    _STREET_RE for addresses that omit the state (common in job descriptions
    where state is implied by context). Length-gates both to reject paragraph
    fragments captured by the regex.
    """
    try:
        import pyap
        found = pyap.parse(text, country='US')
        if found:
            candidate = str(found[0]).strip()
            if _ADDR_MIN_LEN <= len(candidate) <= _ADDR_MAX_LEN:
                return candidate, "pyap"
    except Exception:
        pass

    m = _STREET_RE.search(text)
    if m:
        candidate = m.group(0).strip()
        if _ADDR_MIN_LEN <= len(candidate) <= _ADDR_MAX_LEN:
            return candidate, "regex"

    return None


def _extract_address(job: dict) -> tuple[str | None, str | None]:
    """Pull the best available street address from an Active Jobs DB record.

    Returns (address, method) — method is 'pyap', 'regex', or None.

    Priority: location → description → job_description.
    """
    location = (job.get("location") or "").strip()
    if location and location.lower() not in _GEO_NOISE:
        result = _find_address(location)
        if result:
            return result

    desc = job.get("description") or job.get("job_description") or ""
    if desc:
        result = _find_address(_strip_html(str(desc)))
        if result:
            return result

    return None, None


def _is_austin_area(job: dict) -> bool:
    """Return True if the job appears to be in the Austin/Round Rock metro.

    Checks lat/lng bounding box first (uses *_derived fields from Active Jobs DB
    response); falls back to location string matching.
    """
    # Active Jobs DB returns derived list fields: lats_derived, lngs_derived
    lats = job.get("lats_derived") or []
    lngs = job.get("lngs_derived") or []
    if lats and lngs:
        try:
            for lat, lng in zip(lats, lngs):
                if lat is not None and lng is not None:
                    if _LAT_MIN <= float(lat) <= _LAT_MAX and _LNG_MIN <= float(lng) <= _LNG_MAX:
                        return True
        except (TypeError, ValueError):
            pass

    # Fallback: legacy scalar lat/lng fields
    lat = job.get("latitude") or job.get("lat")
    lng = job.get("longitude") or job.get("lng") or job.get("lon")
    if lat is not None and lng is not None:
        try:
            flat, flng = float(lat), float(lng)
            if _LAT_MIN <= flat <= _LAT_MAX and _LNG_MIN <= flng <= _LNG_MAX:
                return True
        except (TypeError, ValueError):
            pass

    # String matching — check derived location lists first, then scalar fields
    location_candidates = []
    for field in ("cities_derived", "locations_derived", "regions_derived"):
        val = job.get(field)
        if isinstance(val, list):
            location_candidates.extend(str(v) for v in val if v)
    for field in ("location", "city", "job_location"):
        val = job.get(field)
        if val:
            location_candidates.append(str(val))

    for loc in location_candidates:
        loc_lower = loc.lower()
        for term in _AUSTIN_AREA_TERMS:
            if term in loc_lower:
                return True
        # Broad TX acceptance
        if ", tx" in loc_lower or " tx " in loc_lower or loc_lower.endswith(" tx"):
            return True

    return False


def _daily_gate_ok() -> bool:
    """Return True if at least 24 hours have elapsed since the last request.

    Reads last_request_at from rate_manager.  Returns True (allow) when no
    prior request exists or the interval has elapsed.
    """
    try:
        from core.rate_manager import rate_manager
        status = rate_manager.get_source_status(_SOURCE_KEY)
        last_str = status.get("budget", {}).get("last_request_at")
        if not last_str:
            return True
        last = datetime.fromisoformat(last_str)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last
        return elapsed >= timedelta(hours=_MIN_INTERVAL_HOURS)
    except Exception as exc:
        logger.warning(
            "[ActiveJobs] Daily gate check failed, allowing request: %s", exc
        )
        return True


def _rapidapi_headers() -> dict[str, str]:
    """Build RapidAPI auth headers from environment."""
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "RAPIDAPI_KEY environment variable is not set. "
            "Add it to your .env file."
        )
    return {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": _RAPIDAPI_HOST,
    }


class ActiveJobsAdapter(BaseScraper):
    """Fetch Austin-area job listings from the RapidAPI Active Jobs DB.

    One call per run (endpoint discovered at runtime), limit=100.
    Hard-gated to ≤25 requests/month via the 24-hour interval gate and
    the rate_manager budget check.
    """

    name = "ActiveJobs"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch listings from Active Jobs DB and return as ScraperSignal list.

        Args:
            region:    Region key, e.g. "austin_tx". Used to tag postings.
            radius_mi: Unused (API has no radius concept); kept for interface
                       compatibility with BaseScraper.

        Returns:
            List of ScraperSignal objects (signal_type="listing").
            Empty list on budget exhaustion, daily gate, or API failure.
        """
        # ── Cache check — skip API + rate-manager entirely if fresh ──────────
        cached = read_cache(_SOURCE_KEY, ttl_minutes=_TTL_MINUTES)
        if cached is not None:
            logger.info("[ActiveJobs] Serving %d jobs from cache", len(cached))
            return self._jobs_to_signals(cached, region)

        # ── Pre-flight: monthly budget ────────────────────────────────────────
        if not check_budget(_SOURCE_KEY):
            logger.warning("[ActiveJobs] Monthly budget exhausted — skipping")
            return []

        # ── Pre-flight: 24-hour interval gate ────────────────────────────────
        if not _daily_gate_ok():
            logger.info(
                "[ActiveJobs] Daily gate active — last request < %dh ago, skipping",
                _MIN_INTERVAL_HOURS,
            )
            return []

        # ── Build auth headers ────────────────────────────────────────────────
        try:
            headers = _rapidapi_headers()
        except EnvironmentError as exc:
            logger.error("[ActiveJobs] %s", exc)
            return []

        # ── Endpoint discovery — try candidates in order ──────────────────────
        jobs: list[dict] = []
        successful_endpoint: str | None = None

        for path, params in _CANDIDATE_ENDPOINTS:
            url = f"{_BASE_URL}{path}"
            logger.info("[ActiveJobs] Trying endpoint: %s params=%s", url, params)
            try:
                resp = tracked_get(
                    _SOURCE_KEY,
                    "job_search",
                    url,
                    params=params,
                    headers=headers,
                    timeout=30,
                )
            except Exception as exc:
                logger.warning("[ActiveJobs] Request to %s failed: %s", url, exc)
                continue

            if not resp.ok:
                logger.warning(
                    "[ActiveJobs] %s returned HTTP %s — trying next",
                    url, resp.status_code,
                )
                continue

            # Parse response
            try:
                data = resp.json()
            except Exception as exc:
                logger.warning("[ActiveJobs] JSON parse failed for %s: %s", url, exc)
                continue

            if isinstance(data, list):
                candidate_jobs = data
            elif isinstance(data, dict):
                candidate_jobs = (
                    data.get("jobs")
                    or data.get("data")
                    or data.get("results")
                    or []
                )
            else:
                logger.warning(
                    "[ActiveJobs] Unexpected response type from %s: %s",
                    url, type(data),
                )
                continue

            if candidate_jobs:
                jobs = candidate_jobs
                successful_endpoint = url
                logger.info(
                    "[ActiveJobs] Endpoint %s responded with %d jobs",
                    url, len(jobs),
                )
                break
            else:
                logger.info(
                    "[ActiveJobs] %s returned 200 but no jobs — trying next", url
                )

        if not jobs:
            logger.warning("[ActiveJobs] All candidate endpoints returned no jobs")
            return []

        # ── Austin/Round Rock local filter ────────────────────────────────────
        pre_filter_count = len(jobs)
        # Second endpoint (job_country=US) returns all-US jobs; filter locally.
        # For the Austin-targeted endpoints the filter is still a useful safety net.
        austin_jobs = [j for j in jobs if isinstance(j, dict) and _is_austin_area(j)]
        logger.info(
            "[ActiveJobs] Local filter: %d → %d Austin-area jobs (endpoint=%s)",
            pre_filter_count, len(austin_jobs), successful_endpoint,
        )

        # If the Austin filter yields nothing (e.g. the API doesn't return location
        # data), fall back to the full set so we don't silently return empty results.
        if not austin_jobs and pre_filter_count > 0:
            logger.warning(
                "[ActiveJobs] Austin filter removed all jobs — "
                "falling back to full result set (%d jobs). "
                "Check whether the API is returning location fields.",
                pre_filter_count,
            )
            austin_jobs = [j for j in jobs if isinstance(j, dict)]

        write_cache(_SOURCE_KEY, austin_jobs)
        return self._jobs_to_signals(austin_jobs, region)

    # ── Signal conversion ─────────────────────────────────────────────────────

    def _jobs_to_signals(
        self, jobs: list[dict], region: str
    ) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for job in jobs:
            if not isinstance(job, dict):
                continue

            # Company / employer name — try multiple field names
            company = (
                job.get("company_name")
                or job.get("company")
                or job.get("employer")
                or job.get("organization")
                or ""
            ).strip()
            if not company:
                continue

            # Job URL
            job_url = (
                job.get("url")
                or job.get("job_url")
                or job.get("apply_url")
                or job.get("link")
                or ""
            )

            # Title
            title = (
                job.get("title")
                or job.get("job_title")
                or job.get("position")
                or ""
            ).strip()

            # Raw location string — prefer derived list fields from Active Jobs DB API
            _loc_derived = job.get("locations_derived")
            if isinstance(_loc_derived, list) and _loc_derived:
                raw_location = str(_loc_derived[0]).strip()
            else:
                raw_location = (
                    job.get("location")
                    or job.get("job_location")
                    or job.get("city")
                    or ""
                ).strip()

            # Category / industry
            category = (
                job.get("category")
                or job.get("industry")
                or job.get("job_category")
                or None
            )
            if category:
                category = str(category).strip() or None

            # Job type (full-time, part-time, contract…)
            job_type = (
                job.get("job_type")
                or job.get("employment_type")
                or job.get("type")
                or None
            )
            if job_type:
                job_type = str(job_type).strip() or None

            # Remote flag — Active Jobs DB provides remote_derived boolean
            is_remote_raw = (
                job.get("remote_derived")
                or job.get("remote")
                or job.get("is_remote")
                or job.get("remote_work")
            )
            if is_remote_raw is None:
                is_remote = "remote" in raw_location.lower()
            else:
                is_remote = bool(is_remote_raw)

            # Description
            description = job.get("description") or job.get("job_description") or ""
            if description:
                description = _strip_html(str(description))

            # Address extraction
            extracted_addr, extracted_method = _extract_address(job)

            # Stable external ID
            job_id = str(job.get("id") or job.get("job_id") or "")
            if job_id:
                external_id = f"activejobs:{job_id}"
            else:
                import hashlib
                key = job_url or f"{company}|{title}|{raw_location}"
                external_id = hashlib.sha256(key.encode()).hexdigest()[:40]

            # Posted date
            pub_date_raw = (
                job.get("date_posted")
                or job.get("posted_at")
                or job.get("published_at")
                or job.get("created_at")
            )
            posted_date: datetime | None = None
            if pub_date_raw:
                try:
                    from dateutil.parser import parse as _parse
                    posted_date = _parse(str(pub_date_raw))
                    if posted_date.tzinfo is not None:
                        posted_date = posted_date.replace(tzinfo=None)
                except Exception:
                    posted_date = None

            # Salary
            wage_min: float | None = None
            wage_max: float | None = None
            wage_period: str | None = None
            for min_key in ("salary_min", "min_salary", "wage_min"):
                if job.get(min_key):
                    try:
                        wage_min = float(job[min_key])
                        break
                    except (TypeError, ValueError):
                        pass
            for max_key in ("salary_max", "max_salary", "wage_max"):
                if job.get(max_key):
                    try:
                        wage_max = float(job[max_key])
                        break
                    except (TypeError, ValueError):
                        pass
            if wage_min is not None or wage_max is not None:
                raw_period = str(
                    job.get("salary_period") or job.get("wage_period") or ""
                ).lower()
                if "hour" in raw_period:
                    wage_period = "hourly"
                else:
                    wage_period = "yearly"

            signal = ScraperSignal(
                store_num=f"ACTIVEJOBS-{region}",
                chain="active_jobs_db",
                source=_SOURCE_KEY,
                signal_type="listing",
                value=1.0,
                metadata={
                    "company":          company,
                    "employer":         company,
                    "job_url":          job_url,
                    "date_posted":      posted_date.isoformat() if posted_date else None,
                    "location":         raw_location,
                    "address":          extracted_addr,   # MUST exist (even if None)
                    "address_method":   extracted_method,
                    "job_excerpt":      description[:500] if description else None,
                    "category":         category or None,
                    "job_type":         job_type or None,
                    "is_remote":        is_remote,
                    "source_platform":  "active_jobs_db",
                    "external_path":    external_id,     # careers_api compat key
                },
                observed_at=posted_date or now,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
                role_title=title or None,
                source_url=job_url or None,
            )
            signals.append(signal)

        return signals


# ── Convenience function ──────────────────────────────────────────────────────

def scrape_activejobs(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """One call per 24 hours, limit=100 — maximum yield from Active Jobs DB.

    The daily gate inside ActiveJobsAdapter.scrape() enforces the monthly
    25-request budget cap.  Results are filtered to Austin/Round Rock metro
    and tagged with region=austin_tx.

    Args:
        region: Region key for tagging ingested postings (default: austin_tx).
        ingest: If True, route all signals through ingest_job_posting.

    Returns:
        List of ScraperSignals (may be empty if gate is active or API fails).
    """
    adapter = ActiveJobsAdapter()
    signals = adapter.scrape(region)

    logger.info("[ActiveJobs] %d signals for region=%s", len(signals), region)

    if ingest and signals:
        from postings.ingest import ingest_job_posting
        from core.database import get_session, init_db

        engine = init_db()
        session = get_session(engine)
        ingested = 0
        try:
            for signal in signals:
                result = ingest_job_posting(signal, region, session=session)
                if result is not None:
                    ingested += 1
            logger.info(
                "[ActiveJobs] Ingested %d/%d postings", ingested, len(signals)
            )
        finally:
            session.close()

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Fetch Austin-area job listings from RapidAPI Active Jobs DB"
    )
    parser.add_argument(
        "--region", default="austin_tx", help="Region key (default: austin_tx)"
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Fetch and filter only; do not write to DB",
    )
    args = parser.parse_args()

    signals = scrape_activejobs(region=args.region, ingest=not args.no_ingest)
    logger.info("Done. %d signals.", len(signals))


if __name__ == "__main__":
    main()
