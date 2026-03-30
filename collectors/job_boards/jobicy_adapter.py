"""
scrapers/jobicy_adapter.py — Jobicy Remote Jobs API adapter.

Fetches job listings from https://jobicy.com/api/v2/remote-jobs and
routes every result through listings/ingest.py (ingest_job_posting),
the single write path for all JobPosting records.

API overview:
  Endpoint:  GET https://jobicy.com/api/v2/remote-jobs
  Auth:      None (public)
  Rate:      ToS max once per hour (https://jobicy.com/jobs-rss-feed)
  Key params:
    count    1–100   Number of results per call (max 100)
    geo      str     Geographic region slug — only "usa" is available
    industry str     Job category slug
    tag      str     Keyword search in title/description

Strategy: one call per hour, count=100, geo=usa — this is the maximum
single-request yield the API supports. All results are labelled is_remote=True
with company address stored when present. H3 cells are NULL for postings
that have no geocodable address (common for remote roles).

Listing freshness: expires_at rolls forward on every re-scrape, so jobs
that stay in the feed never go stale. Jobs removed from the feed stop
getting refreshed and expire after POSTING_TTL_DAYS of silence.

Called by: backend/scheduler.py, CLI
"""

import argparse
import html as _html_mod
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.tracked_request import check_budget, log_external
from collectors.base import BaseScraper, ScraperSignal
from collectors.cache import read_cache, write_cache

logger = logging.getLogger(__name__)

_JOBICY_API = "https://jobicy.com/api/v2/remote-jobs"
_SOURCE_KEY = "jobicy"

# ToS: once per hour. One call at count=100 is the maximum single-request yield.
_MIN_INTERVAL_MINUTES = 60


# Country/region strings that are NOT geocodable street addresses.
# Jobicy uses these in jobGeo when a job has no specific location.
_GEO_NOISE = frozenset({
    "usa", "us", "united states", "united states of america",
    "worldwide", "world", "global", "remote", "anywhere",
    "north america", "latin america", "south america",
    "europe", "asia", "africa", "oceania", "apac", "emea",
    "", "null", "none",
})


def _coerce_str(value: object) -> str:
    """Return a plain string regardless of whether the API sent str or list."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value)


def _street_address(geo: str) -> str | None:
    """Return the geo string only if it looks like a real address, not a region label.

    Prevents Nominatim from geocoding 'USA' to the center of the country
    and placing every remote listing in Kansas.
    """
    if geo.strip().lower() in _GEO_NOISE:
        return None
    return geo or None


# Fallback regex: street number + named road type, no state required.
# pyap is preferred but requires a state abbreviation in the text.
# This catches addresses like "15305 N Dallas Parkway Suite 600 Addison 75001".
#
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


def _strip_html(raw: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = _html_mod.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


# A real US street address is typically 15–120 characters.
# Anything shorter is just a number; anything longer is captured paragraph text.
_ADDR_MIN_LEN = 15
_ADDR_MAX_LEN = 120


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
    """Pull the best available street address from a Jobicy job record.

    Returns (address, method) — method is 'pyap', 'regex', or None.
    None address means extraction failed; job_excerpt stored separately
    so failures can be reviewed to improve the extractor over time.

    Priority: jobGeo → jobDescription HTML → jobExcerpt.
    """
    geo = _coerce_str(job.get("jobGeo"))
    if geo and geo.strip().lower() not in _GEO_NOISE:
        result = _find_address(geo)
        if result:
            return result

    desc_html = job.get("jobDescription") or ""
    if desc_html:
        result = _find_address(_strip_html(desc_html))
        if result:
            return result

    excerpt = _html_mod.unescape(job.get("jobExcerpt") or "")
    if excerpt:
        result = _find_address(excerpt)
        if result:
            return result

    return None, None


def _hourly_gate_ok() -> bool:
    """Return True if enough time has passed since the last Jobicy request.

    Reads last_request_at from the rate_budget for today's jobicy row.
    Returns True (allow) when no prior request exists or the interval has
    elapsed.
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
        return elapsed >= timedelta(minutes=_MIN_INTERVAL_MINUTES)
    except Exception as exc:
        logger.warning("[Jobicy] hourly gate check failed, allowing request: %s", exc)
        return True


class JobicyAdapter(BaseScraper):
    """Fetch remote job listings from the Jobicy public API.

    One call, count=100, geo=usa — maximum single-request yield.
    """

    name = "Jobicy"

    def __init__(
        self,
        industry: str | None = None,
        tag: str | None = None,
    ) -> None:
        super().__init__()
        self.industry = industry
        self.tag = tag

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch listings from Jobicy and return as ScraperSignal list.

        Args:
            region:    Region key, e.g. "austin_tx". Used to tag postings.
            radius_mi: Unused for Jobicy (API has no radius concept); kept
                       for interface compatibility with BaseScraper.

        Returns:
            List of ScraperSignal objects (signal_type="listing").
            Empty list on budget exhaustion, hourly gate, or API failure.
        """
        # ── Cache check — skip API + rate-manager entirely if fresh ──────────
        cached = read_cache(_SOURCE_KEY, ttl_minutes=_MIN_INTERVAL_MINUTES)
        if cached is not None:
            return self._jobs_to_signals(cached, region)

        # ── Pre-flight: daily budget ──────────────────────────────────────────
        if not check_budget(_SOURCE_KEY):
            logger.warning("[Jobicy] Daily budget exhausted — skipping")
            return []

        # ── Pre-flight: hourly gate (ToS: no more than once per hour) ─────────
        if not _hourly_gate_ok():
            logger.info(
                "[Jobicy] Hourly gate active — last request < %d min ago, skipping",
                _MIN_INTERVAL_MINUTES,
            )
            return []

        # count=100 is the API maximum — one call, maximum yield
        params: dict[str, Any] = {"count": 100, "geo": "usa"}
        if self.industry:
            params["industry"] = self.industry
        if self.tag:
            params["tag"] = self.tag

        t0 = time.time()
        status_code: int | None = None
        success = False
        resp_bytes: int | None = None
        jobs: list = []

        try:
            resp = requests.get(_JOBICY_API, params=params, timeout=30)
            latency_ms = int((time.time() - t0) * 1000)
            status_code = resp.status_code
            resp_bytes = len(resp.content) if resp.content else 0
            success = resp.ok

            if not resp.ok:
                logger.error("[Jobicy] API returned HTTP %s", resp.status_code)
            else:
                data = resp.json()
                if isinstance(data, list):
                    jobs = data
                elif isinstance(data, dict):
                    jobs = data.get("jobs") or data.get("data") or []
                else:
                    logger.warning("[Jobicy] Unexpected response type: %s", type(data))

        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            logger.error("[Jobicy] Request failed: %s", exc)

        # Log *after* parsing so data_items reflects actual job count
        log_external(
            _SOURCE_KEY,
            "remote_jobs_feed",
            url=_JOBICY_API,
            success=success,
            latency_ms=latency_ms,
            response_bytes=resp_bytes,
            data_items=len(jobs),
            params=params,
        )

        if not jobs:
            return []

        write_cache(_SOURCE_KEY, jobs)
        logger.info("[Jobicy] %d jobs returned", len(jobs))
        return self._jobs_to_signals(jobs, region)

    def _jobs_to_signals(self, jobs: list[dict], region: str) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for job in jobs:
            if not isinstance(job, dict):
                continue

            company = (job.get("companyName") or "").strip()
            if not company:
                continue

            job_id = str(job.get("id") or "")
            url = job.get("url") or job.get("jobUrl") or ""
            title = (job.get("jobTitle") or "").strip()
            job_geo = _coerce_str(job.get("jobGeo"))
            industry = _coerce_str(job.get("jobIndustry"))
            job_type = _coerce_str(job.get("jobType"))
            pub_date_raw = job.get("pubDate") or job.get("publishedAt")
            raw_excerpt = _html_mod.unescape(job.get("jobExcerpt") or "")[:500]
            extracted_addr, extracted_method = _extract_address(job)

            # Parse publication date
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
            if job.get("annualSalaryMin"):
                try:
                    wage_min = float(job["annualSalaryMin"])
                    wage_period = "yearly"
                except (TypeError, ValueError):
                    pass
            if job.get("annualSalaryMax"):
                try:
                    wage_max = float(job["annualSalaryMax"])
                    wage_period = "yearly"
                except (TypeError, ValueError):
                    pass

            # Stable external ID: prefer numeric job id, fall back to url hash
            if job_id:
                external_id = f"jobicy:{job_id}"
            else:
                import hashlib
                external_id = hashlib.sha256(url.encode()).hexdigest()[:40]

            signal = ScraperSignal(
                store_num=f"JOBICY-{region}",
                chain="jobicy",
                source=_SOURCE_KEY,
                signal_type="listing",
                value=1.0,
                metadata={
                    "company":      company,
                    "employer":     company,
                    "job_url":      url,
                    "date_posted":  posted_date.isoformat() if posted_date else None,
                    "location":     job_geo,        # job's stated geo (e.g. "USA", "Worldwide")
                    # Best available street address: jobGeo → description → excerpt.
                    # None when no real address found (address_method will be NULL).
                    "address":          extracted_addr,
                    "address_method":   extracted_method,
                    "job_excerpt":      raw_excerpt,
                    "category":     industry,
                    "job_type":     job_type,
                    "job_level":    job.get("jobLevel"),
                    "is_remote":    True,           # all Jobicy listings are remote
                    "jobicy_geo":   "usa",          # geo slug used in the API request
                    "external_path": external_id,   # careers_api compat key
                },
                observed_at=posted_date or now,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
                role_title=title or None,
                source_url=url or None,
            )
            signals.append(signal)

        return signals


# ── Convenience function ──────────────────────────────────────────────────────

def scrape_jobicy(
    region: str = "austin_tx",
    industry: str | None = None,
    tag: str | None = None,
    ingest: bool = True,
) -> list[ScraperSignal]:
    """One call, count=100, geo=usa — maximum single-request yield from Jobicy.

    The hourly gate inside JobicyAdapter.scrape() enforces ToS compliance.
    Results are tagged region=austin_tx and is_remote=True.

    Args:
        region:   Region key for tagging ingested postings (default: austin_tx).
        industry: Optional Jobicy industry filter.
        tag:      Optional keyword filter.
        ingest:   If True, route all signals through ingest_job_posting.

    Returns:
        List of ScraperSignals (may be empty if gate is active or API fails).
    """
    adapter = JobicyAdapter(industry=industry, tag=tag)
    signals = adapter.scrape(region)

    logger.info("[Jobicy] %d signals for region=%s", len(signals), region)

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
            logger.info("[Jobicy] Ingested %d/%d postings", ingested, len(signals))
        finally:
            session.close()

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch remote job listings from Jobicy API")
    parser.add_argument("--region",   default="austin_tx", help="Region key (default: austin_tx)")
    parser.add_argument("--industry", default=None,        help="Jobicy industry filter")
    parser.add_argument("--tag",      default=None,        help="Keyword search tag")
    parser.add_argument("--no-ingest", action="store_true", help="Fetch only, do not write to DB")
    args = parser.parse_args()

    signals = scrape_jobicy(
        region=args.region,
        industry=args.industry,
        tag=args.tag,
        ingest=not args.no_ingest,
    )
    logger.info("Done. %d signals.", len(signals))


if __name__ == "__main__":
    main()
