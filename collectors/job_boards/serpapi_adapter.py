"""
scrapers/serpapi_adapter.py — SerpAPI Google Jobs adapter.

Fetches job listings from the SerpAPI Google Jobs endpoint and routes
every result through listings/ingest.py (ingest_job_posting), the single
write path for all JobPosting records.

API overview:
  Endpoint:  GET https://serpapi.com/search.json
  Auth:      api_key query param — read from SERPAPI_KEY env var
  Rate:      100 credits total. ONE call per run (start=0 only).
             Each additional page costs a credit, so pagination is disabled.
  Key params:
    engine   google_jobs
    q        jobs          (broad — maximises yield per credit)
    location Austin, Texas, United States
    hl       en
    gl       us
    api_key  <SERPAPI_KEY>

Strategy: one call per run (start=0), broad query — maximum single-request
yield within the 100-credit lifetime budget. Results include on-site and
remote Austin-area listings. H3 cells are computed when an address can be
geocoded; NULL otherwise.

Called by: backend/scheduler.py, CLI
"""

import argparse
import logging
import os
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

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from backend.tracked_request import check_budget, log_external
from collectors.base import BaseScraper, ScraperSignal
from collectors.cache import read_cache, write_cache

logger = logging.getLogger(__name__)

_SERPAPI_URL = "https://serpapi.com/search.json"
_SOURCE_KEY = "serpapi_google_jobs"

# One call per run — 8-hour TTL mirrors the polling interval.
_TTL_MINUTES = 480
_MIN_INTERVAL_MINUTES = 480


# ── Address-extraction helpers (mirrored from jobicy_adapter) ─────────────────

# Country/region strings that are NOT geocodable street addresses.
_GEO_NOISE = frozenset({
    "usa", "us", "united states", "united states of america",
    "worldwide", "world", "global", "remote", "anywhere",
    "north america", "latin america", "south america",
    "europe", "asia", "africa", "oceania", "apac", "emea",
    "", "null", "none",
})

# Fallback regex: street number + named road type, no state required.
# pyap is preferred but requires a state abbreviation in the text.
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


# ── Salary parsing ────────────────────────────────────────────────────────────

# Patterns for common SerpAPI salary strings:
#   "$50,000 - $70,000 a year"
#   "$25 an hour"
#   "$18 - $22 an hour"
#   "50,000 USD annually"
_SALARY_RE = re.compile(
    r'\$?([\d,]+(?:\.\d+)?)'                            # first number
    r'(?:\s*[-–]\s*\$?([\d,]+(?:\.\d+)?))?'             # optional second number
    r'\s*(?:a\s+|an\s+|per\s+)?'
    r'(year|yr|annual|annually|month|week|wk|hour|hr)',  # period keyword
    re.IGNORECASE,
)

_PERIOD_MAP = {
    "year": "yearly", "yr": "yearly", "annual": "yearly", "annually": "yearly",
    "month": "monthly",
    "week": "weekly", "wk": "weekly",
    "hour": "hourly", "hr": "hourly",
}


def _parse_salary(s: str) -> tuple[float | None, float | None, str | None]:
    """Parse a SerpAPI salary string into (wage_min, wage_max, wage_period).

    Examples:
        "$50,000 - $70,000 a year" → (50000.0, 70000.0, "yearly")
        "$25 an hour"              → (25.0, None, "hourly")
        "$18 - $22 an hour"        → (18.0, 22.0, "hourly")
        "bad string"               → (None, None, None)
    """
    if not s:
        return None, None, None

    m = _SALARY_RE.search(s)
    if not m:
        return None, None, None

    def _clean(n: str | None) -> float | None:
        if n is None:
            return None
        try:
            return float(n.replace(",", ""))
        except (TypeError, ValueError):
            return None

    wage_min = _clean(m.group(1))
    wage_max = _clean(m.group(2))
    raw_period = (m.group(3) or "").lower()
    wage_period = _PERIOD_MAP.get(raw_period)

    return wage_min, wage_max, wage_period


# ── is_remote detection ────────────────────────────────────────────────────────

def _detect_remote(
    schedule_type: str | None,
    location: str | None,
    description: str | None,
) -> bool | None:
    """Return True if the listing appears to be remote, else None.

    Checks (in order):
      1. detected_extensions.schedule_type contains "Remote"
      2. location contains "Remote" or "Anywhere"
      3. description contains the word "remote" (case-insensitive)
    """
    if schedule_type and "remote" in schedule_type.lower():
        return True
    if location:
        loc_lower = location.lower()
        if "remote" in loc_lower or "anywhere" in loc_lower:
            return True
    if description and re.search(r'\bremote\b', description, re.IGNORECASE):
        return True
    return None


# ── Hourly (interval) gate ────────────────────────────────────────────────────

def _hourly_gate_ok() -> bool:
    """Return True if enough time has passed since the last SerpAPI request.

    Reads last_request_at from the rate_budget for today's serpapi row.
    Returns True (allow) when no prior request exists or the interval has
    elapsed.
    """
    try:
        from backend.rate_manager import rate_manager
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
        logger.warning("[SerpAPI] interval gate check failed, allowing request: %s", exc)
        return True


# ── Adapter ───────────────────────────────────────────────────────────────────

class SerpApiAdapter(BaseScraper):
    """Fetch Austin-area job listings from SerpAPI Google Jobs.

    One call per run, start=0 — maximum single-request yield within the
    100-credit lifetime budget. Broad query (q="jobs") maximises result count.
    """

    name = "SerpAPI"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch listings from SerpAPI Google Jobs and return as ScraperSignal list.

        Args:
            region:    Region key, e.g. "austin_tx". Used to tag postings.
            radius_mi: Unused (API has no radius concept); kept for BaseScraper
                       interface compatibility.

        Returns:
            List of ScraperSignal objects (signal_type="listing").
            Empty list on missing API key, budget exhaustion, interval gate,
            or API failure.
        """
        # ── API key check — fail fast, no HTTP call ───────────────────────────
        api_key = os.environ.get("SERPAPI_KEY")
        if not api_key:
            logger.warning("[SerpAPI] SERPAPI_KEY not set in environment — skipping")
            return []

        # ── Cache check — skip API + rate-manager entirely if fresh ──────────
        cached = read_cache(_SOURCE_KEY, ttl_minutes=_TTL_MINUTES)
        if cached is not None:
            return self._jobs_to_signals(cached, region)

        # ── Pre-flight: daily budget ──────────────────────────────────────────
        if not check_budget(_SOURCE_KEY):
            logger.warning("[SerpAPI] Daily budget exhausted — skipping")
            return []

        # ── Pre-flight: interval gate ─────────────────────────────────────────
        if not _hourly_gate_ok():
            logger.info(
                "[SerpAPI] Interval gate active — last request < %d min ago, skipping",
                _MIN_INTERVAL_MINUTES,
            )
            return []

        # ── Build request ─────────────────────────────────────────────────────
        params: dict[str, Any] = {
            "engine":   "google_jobs",
            "q":        "jobs",
            "location": "Austin, Texas, United States",
            "hl":       "en",
            "gl":       "us",
            "api_key":  api_key,
        }

        t0 = time.time()
        status_code: int | None = None
        success = False
        resp_bytes: int | None = None
        jobs: list = []

        try:
            resp = requests.get(_SERPAPI_URL, params=params, timeout=30)
            latency_ms = int((time.time() - t0) * 1000)
            status_code = resp.status_code
            resp_bytes = len(resp.content) if resp.content else 0
            success = resp.ok

            if not resp.ok:
                logger.error("[SerpAPI] API returned HTTP %s", resp.status_code)
            else:
                data = resp.json()
                jobs = data.get("jobs_results") or []
                if not isinstance(jobs, list):
                    logger.warning("[SerpAPI] Unexpected jobs_results type: %s", type(jobs))
                    jobs = []

        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            logger.error("[SerpAPI] Request failed: %s", exc)

        # Log after parsing so data_items reflects actual job count
        log_external(
            _SOURCE_KEY,
            "google_jobs_search",
            url=_SERPAPI_URL,
            success=success,
            latency_ms=latency_ms,
            response_bytes=resp_bytes,
            data_items=len(jobs),
            params={k: v for k, v in params.items() if k != "api_key"},
        )

        if not jobs:
            return []

        write_cache(_SOURCE_KEY, jobs)
        logger.info("[SerpAPI] %d jobs returned", len(jobs))
        return self._jobs_to_signals(jobs, region)

    def _jobs_to_signals(self, jobs: list[dict], region: str) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for job in jobs:
            if not isinstance(job, dict):
                continue

            company = (job.get("company_name") or "").strip()
            if not company:
                continue

            title = (job.get("title") or "").strip()
            raw_location = (job.get("location") or "").strip()
            description = job.get("description") or ""
            job_id = str(job.get("job_id") or "")

            # Apply URL: prefer source_link (direct job-board link),
            # fall back to share_link (Google Jobs search result).
            # Also capture apply_options if present (some responses include it).
            apply_options = job.get("apply_options") or []
            apply_link: str | None = None
            if apply_options and isinstance(apply_options, list):
                first = apply_options[0]
                if isinstance(first, dict):
                    apply_link = first.get("link") or None
            source_url = (
                apply_link
                or job.get("source_link")    # direct link to original job board
                or job.get("share_link")     # Google Jobs share URL
                or None
            )

            # detected_extensions sub-dict (may be absent)
            ext = job.get("detected_extensions") or {}
            salary_raw: str | None = ext.get("salary") or None
            schedule_type: str | None = ext.get("schedule_type") or None
            posted_at_raw: str | None = ext.get("posted_at") or None

            # ── Salary ────────────────────────────────────────────────────────
            wage_min, wage_max, wage_period = _parse_salary(salary_raw or "")

            # ── Posted date ───────────────────────────────────────────────────
            posted_date: datetime | None = None
            if posted_at_raw:
                try:
                    from dateutil.parser import parse as _parse_dt
                    posted_date = _parse_dt(str(posted_at_raw))
                    if posted_date.tzinfo is not None:
                        posted_date = posted_date.replace(tzinfo=None)
                except Exception:
                    posted_date = None

            # ── Address extraction ────────────────────────────────────────────
            # Priority: street address from description > raw_location city string
            extracted_addr: str | None = None
            extracted_method: str | None = None
            if description:
                result = _find_address(description)
                if result:
                    extracted_addr, extracted_method = result

            # Fall back to the location field (e.g. "Austin, TX") — a valid
            # geocodable city-level string covered by _OVERRIDES.
            if not extracted_addr and raw_location:
                loc_clean = raw_location.strip()
                # Strip trailing "(+N other)" noise from SerpAPI
                loc_clean = re.sub(r'\s*\(\+\d+\s+other\w*\)\s*$', '', loc_clean)
                if loc_clean and loc_clean.lower() not in _GEO_NOISE:
                    extracted_addr = loc_clean
                    extracted_method = "location_field"

            # ── is_remote ─────────────────────────────────────────────────────
            is_remote = _detect_remote(schedule_type, raw_location, description)

            # ── External ID ───────────────────────────────────────────────────
            if job_id:
                external_id = f"serpapi:{job_id}"
            else:
                import hashlib
                external_id = hashlib.sha256(
                    (company + title + raw_location).encode()
                ).hexdigest()[:40]

            signal = ScraperSignal(
                store_num=f"SERPAPI-{region}",
                chain="serpapi_google_jobs",
                source=_SOURCE_KEY,
                signal_type="listing",
                value=1.0,
                metadata={
                    "company":          company,
                    "employer":         company,
                    "job_url":          source_url,
                    "date_posted":      posted_date.isoformat() if posted_date else None,
                    "location":         raw_location,
                    # Best available address: street from description, or
                    # city-level from location field (geocodable via _OVERRIDES).
                    "address":          extracted_addr,
                    "address_method":   extracted_method,
                    "job_excerpt":      description[:500] if description else None,
                    "category":         None,           # not available from SerpAPI
                    "job_type":         schedule_type,
                    "is_remote":        is_remote,
                    "source_platform":  "google_jobs",
                    "external_path":    external_id,    # careers_api compat key
                },
                observed_at=posted_date or now,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
                role_title=title or None,
                source_url=source_url or None,
            )
            signals.append(signal)

        return signals


# ── Convenience function ──────────────────────────────────────────────────────

def scrape_serpapi(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """One call, start=0, broad query — maximum single-request yield from SerpAPI.

    The interval gate inside SerpApiAdapter.scrape() prevents calling the API
    more than once per 8-hour window to conserve the 100-credit lifetime budget.

    Args:
        region:  Region key for tagging ingested postings (default: austin_tx).
        ingest:  If True, route all signals through ingest_job_posting.

    Returns:
        List of ScraperSignals (may be empty if gate is active or API fails).
    """
    adapter = SerpApiAdapter()
    signals = adapter.scrape(region)

    logger.info("[SerpAPI] %d signals for region=%s", len(signals), region)

    if ingest and signals:
        from postings.ingest import ingest_job_posting
        from backend.database import get_session, init_db

        engine = init_db()
        session = get_session(engine)
        ingested = 0
        try:
            for signal in signals:
                result = ingest_job_posting(signal, region, session=session)
                if result is not None:
                    ingested += 1
            logger.info("[SerpAPI] Ingested %d/%d postings", ingested, len(signals))
        finally:
            session.close()

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch Austin job listings from SerpAPI Google Jobs")
    parser.add_argument("--region",    default="austin_tx", help="Region key (default: austin_tx)")
    parser.add_argument("--no-ingest", action="store_true",  help="Fetch only, do not write to DB")
    parser.add_argument("--dry-run",   action="store_true",  help="Print signal count, no DB writes")
    args = parser.parse_args()

    if args.dry_run:
        signals = SerpApiAdapter().scrape(args.region)
        logger.info("[SerpAPI] dry-run: %d signals (not ingested)", len(signals))
        for s in signals:
            logger.info(
                "  %s | %s | %s",
                s.role_title, s.metadata.get("employer"), s.metadata.get("location"),
            )
        return

    signals = scrape_serpapi(
        region=args.region,
        ingest=not args.no_ingest,
    )
    logger.info("Done. %d signals.", len(signals))


if __name__ == "__main__":
    main()
