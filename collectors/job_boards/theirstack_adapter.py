"""
scrapers/theirstack_adapter.py — TheirStack Jobs API adapter.

Fetches job listings from https://api.theirstack.com/v1/jobs/search and
routes every result through listings/ingest.py (ingest_job_posting),
the single write path for all JobPosting records.

API overview:
  Endpoint:  POST https://api.theirstack.com/v1/jobs/search
  Auth:      Authorization: Bearer <THEIRSTACK_API_KEY>  (env var)
  Rate:      ~200 calls/month cap — each response is precious.
  Strategy:  Broad location-only collection, no title/keyword filters.
             Covers Austin, Round Rock, Cedar Park, Georgetown, Pflugerville.
             All industries, all roles — maximum reuse per cached response.

Caching strategy:
  TTL = 1440 min (24 h) — one call per day is adequate for a 200/month budget.
  MIN_INTERVAL = 240 min (4 h) — hard floor so re-runs don't burn quota.
  Cache key: "theirstack".  Only the parsed data list is cached.

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

from backend.tracked_request import check_budget, tracked_post
from collectors.base import BaseScraper, ScraperSignal
from collectors.cache import read_cache, write_cache

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.theirstack.com"
_ENDPOINT = "/v1/jobs/search"
_SEARCH_URL = _BASE_URL + _ENDPOINT
_SOURCE_KEY = "theirstack"

# 24 h TTL — API budget is 200 calls/month; treat each call as precious.
_TTL_MINUTES = 1440
# Hard floor: do not call more often than every 4 hours even if cache is cold.
_MIN_INTERVAL_MINUTES = 240

# Location patterns for the Austin metro area.
_LOCATION_PATTERNS = [
    "Austin",
    "Round Rock",
    "Cedar Park",
    "Georgetown",
    "Pflugerville",
]

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
# Guards against salary fragments and zero-prefixed numbers.
_STREET_RE = re.compile(
    r'(?<![,\d])\b[1-9]\d{2,5}\s+[A-Za-z][A-Za-z0-9\s]{1,40}'
    r'(?:Street\b|St\b|Avenue\b|Ave\b|Boulevard\b|Blvd\b|Road\b|Rd\b|Drive\b|Dr\b|'
    r'Lane\b|Ln\b|Parkway\b|Pkwy\b|Way\b|Court\b|Ct\b|Place\b|Pl\b|Circle\b|Cir\b)'
    r'[^<\n]{0,120}',
    re.IGNORECASE,
)

# Reasonable length bounds for a US street address.
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


# Austin-area cities where we can infer ", TX" when state is missing.
_AUSTIN_AREA_CITIES = {
    "austin", "round rock", "cedar park", "pflugerville", "georgetown",
    "kyle", "buda", "lakeway", "leander", "del valle", "san marcos",
    "manor", "hutto", "taylor", "bastrop", "lockhart", "dripping springs",
}


def _extract_address(job: dict) -> tuple[str | None, str | None]:
    """Pull the best available address from a TheirStack job record.

    Returns (address, method) — method is 'pyap', 'regex', 'city_state',
    'location_field', 'fallback_city', or None.

    Priority:
      1. Street address from description (pyap / regex)
      2. long_location (richest string — may include zip, e.g. "Austin, TX 78704")
      3. location / short_location (city-level, e.g. "Austin, TX")
      4. locations[0].city + state_code → "City, ST"
      5. company_object.city + state inference → "City, TX"
      6. None — no usable address
    """
    # ── 1. Street address from description ────────────────────────────────
    desc_raw = job.get("description") or job.get("job_description") or ""
    if desc_raw:
        result = _find_address(_strip_html(desc_raw))
        if result:
            return result

    # ── 2. long_location — richest API field, may contain zip code ────────
    #    e.g. "Methuen, MA 01844", "Austin, TX 78704", "Cedar Park, TX 78613"
    long_loc = (job.get("long_location") or "").strip()
    if long_loc and long_loc.lower() not in _GEO_NOISE:
        cleaned = re.sub(r'\s*Metropolitan\s+Area\s*', '', long_loc, flags=re.IGNORECASE).strip()
        if ',' in cleaned:
            return cleaned, "location_field"

    # ── 3. location / short_location (city-level fallback) ────────────────
    job_location = (job.get("location") or job.get("short_location") or "").strip()
    if job_location and job_location.lower() not in _GEO_NOISE:
        cleaned = re.sub(r'\s*Metropolitan\s+Area\s*', '', job_location, flags=re.IGNORECASE).strip()
        state_code = (job.get("state_code") or "").strip()
        if ',' in cleaned:
            return cleaned, "location_field"
        if cleaned and state_code:
            return f"{cleaned}, {state_code}", "location_field"

    # ── 4. locations array (structured geo data from API) ─────────────────
    locations = job.get("locations") or []
    if locations and isinstance(locations, list):
        loc0 = locations[0]
        if isinstance(loc0, dict):
            loc_city = (loc0.get("city") or "").strip()
            loc_state = (loc0.get("state_code") or "").strip()
            if loc_city and loc_state:
                return f"{loc_city}, {loc_state}", "city_state"

    # ── 5. company_object.city with state inference ───────────────────────
    company_obj = job.get("company_object") or {}
    city = (company_obj.get("city") or "").strip()
    state = (company_obj.get("state") or "").strip()
    state_code = (job.get("state_code") or "").strip()
    if city and state:
        return f"{city}, {state}", "city_state"
    if city and state_code:
        return f"{city}, {state_code}", "city_state"
    if city and city.lower() in _AUSTIN_AREA_CITIES:
        return f"{city}, TX", "fallback_city"

    return None, None


# ── Interval gate ─────────────────────────────────────────────────────────────

def _interval_gate_ok() -> bool:
    """Return True if enough time has passed since the last TheirStack request.

    Reads last_request_at from rate_manager for the theirstack source.
    Returns True (allow) when no prior request exists or the minimum
    interval has elapsed.
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
        logger.warning("[TheirStack] Interval gate check failed, allowing request: %s", exc)
        return True


# ── Adapter class ─────────────────────────────────────────────────────────────

class TheirStackAdapter(BaseScraper):
    """Fetch Austin-metro job listings from the TheirStack Jobs API.

    Broad location-only collection — no title/keyword filters — covering
    Austin, Round Rock, Cedar Park, Georgetown, and Pflugerville.
    One POST call, limit=50, ordered by discovered_at descending.
    """

    name = "TheirStack"

    def __init__(self) -> None:
        super().__init__()

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch listings from TheirStack and return as ScraperSignal list.

        Args:
            region:    Region key, e.g. "austin_tx". Used to tag postings.
            radius_mi: Unused for TheirStack (location patterns used instead);
                       kept for interface compatibility with BaseScraper.

        Returns:
            List of ScraperSignal objects (signal_type="listing").
            Empty list on missing API key, budget exhaustion, interval gate,
            or API failure.
        """
        # ── API key check ────────────────────────────────────────────────────
        api_key = os.environ.get("THEIRSTACK_API_KEY")
        if not api_key:
            logger.warning(
                "[TheirStack] THEIRSTACK_API_KEY not set — skipping"
            )
            return []

        # ── Cache check — skip API + rate-manager entirely if fresh ─────────
        cached = read_cache(_SOURCE_KEY, ttl_minutes=_TTL_MINUTES)
        if cached is not None:
            return self._jobs_to_signals(cached, region)

        # ── Pre-flight: daily budget ─────────────────────────────────────────
        if not check_budget(_SOURCE_KEY):
            logger.warning("[TheirStack] Daily budget exhausted — skipping")
            return []

        # ── Pre-flight: minimum interval gate ────────────────────────────────
        if not _interval_gate_ok():
            logger.info(
                "[TheirStack] Interval gate active — last request < %d min ago, skipping",
                _MIN_INTERVAL_MINUTES,
            )
            return []

        # ── Build request ────────────────────────────────────────────────────
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "page": 0,
            "limit": 25,
            "posted_at_max_age_days": 30,
            "job_location_pattern_or": _LOCATION_PATTERNS,
            "order_by": [{"desc": True, "field": "discovered_at"}],
            "blur_company_data": False,
        }

        jobs: list[dict] = []

        try:
            resp = tracked_post(
                _SOURCE_KEY,
                "jobs_search",
                _SEARCH_URL,
                json_body=body,
                headers=headers,
                timeout=30,
                data_items=None,
            )

            if not resp.ok:
                logger.error(
                    "[TheirStack] API returned HTTP %s: %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return []

            payload = resp.json()
            if isinstance(payload, dict):
                raw_data = payload.get("data") or []
                if not isinstance(raw_data, list):
                    logger.warning(
                        "[TheirStack] Unexpected 'data' type: %s", type(raw_data)
                    )
                    raw_data = []
                jobs = [j for j in raw_data if isinstance(j, dict)]
            else:
                logger.warning(
                    "[TheirStack] Unexpected top-level response type: %s", type(payload)
                )

        except Exception as exc:
            logger.error("[TheirStack] Request failed: %s", exc)
            return []

        if not jobs:
            logger.info("[TheirStack] No jobs returned from API")
            return []

        write_cache(_SOURCE_KEY, jobs)
        logger.info("[TheirStack] %d jobs returned", len(jobs))
        return self._jobs_to_signals(jobs, region)

    def _jobs_to_signals(self, jobs: list[dict], region: str) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for job in jobs:
            if not isinstance(job, dict):
                continue

            # ── Company name ─────────────────────────────────────────────────
            company_obj = job.get("company_object") or {}
            company_name = (
                (company_obj.get("name") or "").strip()
                or (job.get("company_name") or "").strip()
            )
            if not company_name:
                logger.debug("[TheirStack] Skipping job with no company name: %s", job.get("id"))
                continue

            # ── Core fields ──────────────────────────────────────────────────
            job_id = str(job.get("id") or "")
            external_id = f"theirstack:{job_id}" if job_id else None

            # URL priority: final_url (employer site) > url (listing page) > source_url (board)
            final_url = (job.get("final_url") or "").strip() or None
            listing_url = (job.get("url") or "").strip() or None
            board_url = (job.get("source_url") or "").strip() or None
            url = final_url or listing_url or board_url
            title = (job.get("job_title") or "").strip() or None
            job_location = (job.get("job_location") or "").strip() or None
            remote_flag = job.get("remote")
            is_remote: bool | None = bool(remote_flag) if remote_flag is not None else None

            # ── Industry / category ──────────────────────────────────────────
            industry = (company_obj.get("industry") or "").strip() or None

            # ── Company size ─────────────────────────────────────────────────
            num_employees = company_obj.get("num_employees")
            company_size: int | None = None
            if num_employees is not None:
                try:
                    company_size = int(num_employees)
                except (TypeError, ValueError):
                    pass

            # ── Coordinates (TheirStack provides lat/lng at job level) ─────
            api_lat: float | None = None
            api_lng: float | None = None
            raw_lat = job.get("latitude")
            raw_lng = job.get("longitude")
            if raw_lat is not None and raw_lng is not None:
                try:
                    api_lat = float(raw_lat)
                    api_lng = float(raw_lng)
                except (TypeError, ValueError):
                    pass

            # ── Address extraction ────────────────────────────────────────────
            extracted_addr, extracted_method = _extract_address(job)
            # When lat/lng are provided, mark method as provided_coords
            if api_lat is not None and api_lng is not None and not extracted_addr:
                extracted_method = "provided_coords"

            # ── Posted / discovered date ──────────────────────────────────────
            posted_date: datetime | None = None
            raw_date = job.get("date_posted") or job.get("discovered_at")
            if raw_date:
                try:
                    from dateutil.parser import parse as _parse
                    posted_date = _parse(str(raw_date))
                    if posted_date.tzinfo is not None:
                        posted_date = posted_date.replace(tzinfo=None)
                except Exception:
                    posted_date = None

            # ── Job description excerpt ───────────────────────────────────────
            desc_raw = job.get("job_description") or ""
            job_excerpt: str | None = None
            if desc_raw:
                job_excerpt = _strip_html(desc_raw)[:500] or None

            # ── Salary ────────────────────────────────────────────────────────
            wage_min: float | None = None
            wage_max: float | None = None
            wage_period: str | None = None

            raw_min = job.get("salary_min")
            raw_max = job.get("salary_max")
            if raw_min is not None:
                try:
                    wage_min = float(raw_min)
                    wage_period = "yearly"
                except (TypeError, ValueError):
                    pass
            if raw_max is not None:
                try:
                    wage_max = float(raw_max)
                    wage_period = "yearly"
                except (TypeError, ValueError):
                    pass

            # ── External ID fallback ──────────────────────────────────────────
            if not external_id:
                import hashlib
                external_id = hashlib.sha256((url or company_name).encode()).hexdigest()[:40]

            signal = ScraperSignal(
                store_num=f"THEIRSTACK-{region}",
                chain="theirstack",
                source=_SOURCE_KEY,
                signal_type="listing",
                value=1.0,
                metadata={
                    "company":          company_name,
                    "employer":         company_name,
                    "job_url":          url,
                    "apply_urls":       [u for u in [final_url, listing_url, board_url] if u],
                    "date_posted":      posted_date.isoformat() if posted_date else None,
                    "location":         job_location,
                    "address":          extracted_addr,
                    "address_method":   extracted_method,
                    "lat":              api_lat,
                    "lng":              api_lng,
                    "job_excerpt":      job_excerpt,
                    "category":         industry,
                    "job_type":         None,
                    "is_remote":        is_remote,
                    "source_platform":  "theirstack",
                    "company_size":     company_size,
                    "external_path":    external_id,
                },
                observed_at=posted_date or now,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
                role_title=title,
                source_url=url,
            )
            signals.append(signal)

        return signals


# ── Convenience function ──────────────────────────────────────────────────────

def scrape_theirstack(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Broad Austin-metro job collection from TheirStack — all industries, all roles.

    No title/keyword filters. Location patterns cover Austin, Round Rock,
    Cedar Park, Georgetown, and Pflugerville.  Results are cached for 24 h
    to stay within the 200/month API budget.

    Args:
        region:  Region key for tagging ingested postings (default: austin_tx).
        ingest:  If True, route all signals through ingest_job_posting.

    Returns:
        List of ScraperSignals (may be empty if gate is active or API fails).
    """
    adapter = TheirStackAdapter()
    signals = adapter.scrape(region)

    logger.info("[TheirStack] %d signals for region=%s", len(signals), region)

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
            logger.info("[TheirStack] Ingested %d/%d postings", ingested, len(signals))
        finally:
            session.close()

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch Austin-metro job listings from the TheirStack Jobs API"
    )
    parser.add_argument(
        "--region",
        default="austin_tx",
        help="Region key for tagging ingested postings (default: austin_tx)",
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Fetch and display signals only — do not write to DB",
    )
    args = parser.parse_args()

    signals = scrape_theirstack(
        region=args.region,
        ingest=not args.no_ingest,
    )
    logger.info("Done. %d signals.", len(signals))


if __name__ == "__main__":
    main()
