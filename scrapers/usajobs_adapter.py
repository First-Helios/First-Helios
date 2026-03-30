"""
scrapers/usajobs_adapter.py — USAJobs API adapter.

Fetches federal government job listings from https://data.usajobs.gov/api/Search
and routes every result through listings/ingest.py (ingest_job_posting),
the single write path for all JobPosting records.

API overview:
  Endpoint:  GET https://data.usajobs.gov/api/Search
  Auth:      Required — Authorization-Key header + User-Agent (email) header
             Register at https://developer.usajobs.gov/APIRequest/Index
  Rate:      No hard public limit documented; use conservatively
  Key params:
    Keyword          - Search keywords (job title, skills)
    LocationName     - City/state for location filtering
    ResultsPerPage   - Results per page (max 500)
    Page             - Pagination (1-based)
    JobCategoryCode  - OPM job series code filter

Credentials (required):
  USAJOBS_API_KEY    - Authorization-Key header value
  USAJOBS_EMAIL      - User-Agent header value (your email, per ToS)

Both must be set in .env or the environment — adapter skips entirely if missing.

Called by: backend/scheduler.py, CLI
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.tracked_request import check_budget, log_external
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

_USAJOBS_API = "https://data.usajobs.gov/api/Search"
_SOURCE_KEY = "usajobs"

# Max results per page the API supports
_PAGE_SIZE = 500


def _get_credentials() -> tuple[str | None, str | None]:
    """Return (api_key, email) from environment, or (None, None) if missing."""
    import os
    api_key = os.environ.get("USAJOBS_API_KEY")
    email = os.environ.get("USAJOBS_EMAIL")
    return api_key, email


def _parse_salary(pay_range: dict | None) -> tuple[float | None, float | None, str | None]:
    """Extract wage_min, wage_max, wage_period from PositionRemuneration entry."""
    if not pay_range:
        return None, None, None
    try:
        wage_min = float(pay_range.get("MinimumRange") or 0) or None
        wage_max = float(pay_range.get("MaximumRange") or 0) or None
        interval = (pay_range.get("RateIntervalCode") or "").upper()
        if interval in ("PA", "PY"):
            wage_period = "yearly"
        elif interval in ("PH",):
            wage_period = "hourly"
        else:
            wage_period = None
        return wage_min, wage_max, wage_period
    except (TypeError, ValueError):
        return None, None, None


def _parse_location(position: dict) -> tuple[str | None, float | None, float | None]:
    """Extract the first location address, lat, lng from PositionLocation list."""
    locations = position.get("PositionLocation") or []
    if not locations:
        return None, None, None
    loc = locations[0]
    address = loc.get("LocationName") or None
    try:
        lat = float(loc["Longitude"]) if loc.get("Longitude") else None  # API names are swapped
        lng = float(loc["Latitude"]) if loc.get("Latitude") else None
        # USAJobs API actually labels them correctly — swap back
        lat = float(loc.get("Latitude") or 0) or None
        lng = float(loc.get("Longitude") or 0) or None
    except (TypeError, ValueError):
        lat, lng = None, None
    return address, lat, lng


class USAJobsAdapter(BaseScraper):
    """Fetch federal job listings from the USAJobs public API.

    Paginates through results up to max_pages. Each page requests up to
    _PAGE_SIZE results. With max_pages=2, this yields up to 1000 listings
    per run — a reasonable daily batch for a regional install.
    """

    name = "USAJobs"

    def __init__(
        self,
        keyword: str | None = None,
        location: str | None = None,
        max_pages: int = 2,
    ) -> None:
        super().__init__()
        self.keyword = keyword
        self.location = location
        self.max_pages = max_pages

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch listings from USAJobs and return as ScraperSignal list.

        Args:
            region:    Region key, e.g. "austin_tx". Used to tag postings.
            radius_mi: Unused (USAJobs filters by LocationName, not radius);
                       kept for BaseScraper interface compatibility.

        Returns:
            List of ScraperSignal objects (signal_type="listing").
            Empty list on missing credentials, budget exhaustion, or API failure.
        """
        api_key, email = _get_credentials()
        if not api_key or not email:
            logger.warning(
                "[USAJobs] USAJOBS_API_KEY and USAJOBS_EMAIL must be set in .env — skipping"
            )
            return []

        if not check_budget(_SOURCE_KEY):
            logger.warning("[USAJobs] Daily budget exhausted — skipping")
            return []

        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": email,
            "Authorization-Key": api_key,
        }

        all_signals: list[ScraperSignal] = []

        for page in range(1, self.max_pages + 1):
            params: dict[str, Any] = {
                "ResultsPerPage": _PAGE_SIZE,
                "Page": page,
            }
            if self.keyword:
                params["Keyword"] = self.keyword
            if self.location:
                params["LocationName"] = self.location

            t0 = time.time()
            status_code: int | None = None
            success = False
            resp_bytes: int | None = None
            items: list = []

            try:
                resp = requests.get(
                    _USAJOBS_API,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
                latency_ms = int((time.time() - t0) * 1000)
                status_code = resp.status_code
                resp_bytes = len(resp.content) if resp.content else 0
                success = resp.ok

                if not resp.ok:
                    logger.error("[USAJobs] API returned HTTP %s: %s", resp.status_code, resp.text[:200])
                else:
                    data = resp.json()
                    items = (
                        data.get("SearchResult", {})
                            .get("SearchResultItems", [])
                    )
                    total = (
                        data.get("SearchResult", {})
                            .get("SearchResultCountAll", 0)
                    )
                    logger.info(
                        "[USAJobs] Page %d/%d — %d items (total available: %d)",
                        page, self.max_pages, len(items), total,
                    )

            except Exception as exc:
                latency_ms = int((time.time() - t0) * 1000)
                logger.error("[USAJobs] Request failed page=%d: %s", page, exc)

            log_external(
                _SOURCE_KEY,
                "job_search",
                url=_USAJOBS_API,
                success=success,
                latency_ms=latency_ms,
                response_bytes=resp_bytes,
                data_items=len(items),
                params=params,
            )

            if not items:
                break  # no more results

            signals = self._items_to_signals(items, region)
            all_signals.extend(signals)

            if len(items) < _PAGE_SIZE:
                break  # last page

        logger.info("[USAJobs] %d total signals for region=%s", len(all_signals), region)
        return all_signals

    def _items_to_signals(self, items: list[dict], region: str) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for item in items:
            if not isinstance(item, dict):
                continue

            pos = item.get("MatchedObjectDescriptor") or {}
            job_id = item.get("MatchedObjectId") or ""

            title = (pos.get("PositionTitle") or "").strip()
            org = (pos.get("OrganizationName") or pos.get("DepartmentName") or "").strip()
            apply_url = pos.get("ApplyOnlineURL") or pos.get("PositionURI") or ""

            if not org:
                continue

            address, lat, lng = _parse_location(pos)

            # Salary: use first remuneration entry
            remunerations = pos.get("PositionRemuneration") or []
            pay_range = remunerations[0] if remunerations else None
            wage_min, wage_max, wage_period = _parse_salary(pay_range)

            # Posted date
            posted_date: datetime | None = None
            raw_date = pos.get("PublicationStartDate") or pos.get("ApplicationCloseDate")
            if raw_date:
                try:
                    from dateutil.parser import parse as _parse
                    posted_date = _parse(str(raw_date))
                    if posted_date.tzinfo is not None:
                        posted_date = posted_date.replace(tzinfo=None)
                except Exception:
                    posted_date = None

            # Job categories for metadata
            job_cats = pos.get("JobCategory") or []
            category = ", ".join(c.get("Name", "") for c in job_cats if c.get("Name"))

            # Is remote?
            telework = (pos.get("TeleworkEligible") or "").lower()
            is_remote = "yes" in telework or "eligible" in telework

            signal = ScraperSignal(
                store_num=f"USAJOBS-{region}",
                chain="usajobs",
                source=_SOURCE_KEY,
                signal_type="listing",
                value=1.0,
                metadata={
                    "company":          org,
                    "employer":         org,
                    "job_url":          apply_url,
                    "date_posted":      posted_date.isoformat() if posted_date else None,
                    "address":          address,
                    "lat":              lat,
                    "lng":              lng,
                    "category":         category or None,
                    "is_remote":        is_remote,
                    "external_path":    f"usajobs:{job_id}",
                    "department":       pos.get("DepartmentName"),
                    "job_grade":        pos.get("JobGrade"),
                    "security_clearance": pos.get("SecurityClearance"),
                    "work_schedule":    pos.get("PositionSchedule", [{}])[0].get("Name") if pos.get("PositionSchedule") else None,
                },
                observed_at=posted_date or now,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
                role_title=title or None,
                source_url=apply_url or None,
            )
            signals.append(signal)

        return signals


# ── Convenience function ──────────────────────────────────────────────────────

def scrape_usajobs(
    region: str = "austin_tx",
    keyword: str | None = None,
    location: str | None = None,
    max_pages: int = 2,
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Fetch federal job listings from USAJobs and optionally ingest them.

    Args:
        region:    Region key for tagging ingested postings (default: austin_tx).
        keyword:   Optional keyword filter (e.g. "software engineer").
        location:  Optional location filter (e.g. "Austin, TX").
        max_pages: Max pages to fetch (500 results/page, default: 2 = up to 1000).
        ingest:    If True, route all signals through ingest_job_posting.

    Returns:
        List of ScraperSignals (may be empty if credentials missing or API fails).
    """
    adapter = USAJobsAdapter(keyword=keyword, location=location, max_pages=max_pages)
    signals = adapter.scrape(region)

    if ingest and signals:
        from listings.ingest import ingest_job_posting
        from backend.database import get_session, init_db

        engine = init_db()
        session = get_session(engine)
        ingested = 0
        try:
            for signal in signals:
                result = ingest_job_posting(signal, region, session=session)
                if result is not None:
                    ingested += 1
            logger.info("[USAJobs] Ingested %d/%d postings", ingested, len(signals))
        finally:
            session.close()

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch federal job listings from USAJobs API")
    parser.add_argument("--region",    default="austin_tx", help="Region key (default: austin_tx)")
    parser.add_argument("--keyword",   default=None,        help="Keyword search filter")
    parser.add_argument("--location",  default=None,        help="Location filter (e.g. 'Austin, TX')")
    parser.add_argument("--max-pages", type=int, default=2, help="Max pages to fetch (default: 2)")
    parser.add_argument("--no-ingest", action="store_true", help="Fetch only, do not write to DB")
    args = parser.parse_args()

    signals = scrape_usajobs(
        region=args.region,
        keyword=args.keyword,
        location=args.location,
        max_pages=args.max_pages,
        ingest=not args.no_ingest,
    )
    logger.info("Done. %d signals.", len(signals))


if __name__ == "__main__":
    main()
