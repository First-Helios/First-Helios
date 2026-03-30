"""
scrapers/workday_gov_adapter.py — Workday-based government careers adapter.

Scrapes municipal/government Workday career portals (starting with City of Austin)
and routes results through listings/ingest.py, the single write path for all
JobPosting records.

API pattern (standard Workday CXS):
  List:   POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  Detail: GET  https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{externalPath}

  Payload: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
  Auth: None required — public portal. Session cookies help avoid 422s.

Current sites:
  austin_gov:
    tenant=austintexas, wd=wd5, site=COA_Careers
    ~100-200 active postings at any time
    Salary data embedded in HTML job description (parse with regex)
    All positions located in Austin, TX metro

Called by: backend/scheduler.py, CLI (__main__)
"""

import argparse
import html
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

from backend.tracked_request import check_budget, log_external
from collectors.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

_SOURCE_KEY = "austin_gov_workday"

# ── Site definitions ─────────────────────────────────────────────────────────
# Each entry describes one Workday government career portal.
# Extend this dict to add more municipal Workday sites.

WORKDAY_GOV_SITES: dict[str, dict[str, Any]] = {
    "austin_gov": {
        "tenant": "austintexas",
        "wd_instance": "wd5",
        "site_id": "COA_Careers",
        "display_name": "City of Austin",
        "employer_name": "City of Austin",
        "base_url": "https://austintexas.wd5.myworkdayjobs.com",
        # All COA positions are in Austin — use city center as default coords
        "default_lat": 30.2672,
        "default_lng": -97.7431,
        "default_address": "Austin, TX",
        "page_size": 20,
    },
}


def _api_url(site: dict) -> str:
    """Build the Workday CXS jobs list API URL."""
    return (
        f"https://{site['tenant']}.{site['wd_instance']}.myworkdayjobs.com"
        f"/wday/cxs/{site['tenant']}/{site['site_id']}/jobs"
    )


def _detail_url(site: dict, external_path: str) -> str:
    """Build the Workday CXS single-job detail API URL."""
    return (
        f"https://{site['tenant']}.{site['wd_instance']}.myworkdayjobs.com"
        f"/wday/cxs/{site['tenant']}/{site['site_id']}{external_path}"
    )


def _public_url(site: dict, external_path: str) -> str:
    """Build the public-facing apply link."""
    return (
        f"https://{site['tenant']}.{site['wd_instance']}.myworkdayjobs.com"
        f"/en-US/{site['site_id']}{external_path}"
    )


# ── HTML → plain text ────────────────────────────────────────────────────────

def _html_to_text(raw_html: str) -> str:
    """Strip HTML tags and collapse whitespace to produce readable text."""
    text = re.sub(r"<[^>]+>", "\n", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Section extraction ───────────────────────────────────────────────────────
# COA Workday descriptions embed structured sections under bold headings.
# Section names vary across postings — we normalise to stable keys.

# Maps (regex pattern → output_key).  First match wins for each key.
_SECTION_PATTERNS: list[tuple[str, str]] = [
    (r"Pay\s*Range\s*:", "pay_range"),
    (r"Pay\s*Rate\s*:", "pay_range"),
    (r"Salary\s*:", "pay_range"),
    (r"Location\s*:", "location"),
    (r"Minimum\s+Qualifications\s*:", "minimum_qualifications"),
    (r"Education\s+and/?or\s+Equivalent\s+Experience\s*:", "education"),
    (r"Knowledge,?\s*Skills,?\s*and\s*Abilities\s*:", "ksa"),
    (r"Days?\s+and\s+Hours?\s*:", "days_and_hours"),
    (r"Hours?\s*:", "days_and_hours"),
    (r"Preferred\s+Qualifications\s*:", "preferred_qualifications"),
    (r"Licenses?\s+and\s+Certifications?\s+Required\s*:", "licenses"),
    (r"Notes?\s+to\s+Candidate[s]?\s*:", "notes_to_candidate"),
]

# All labels that might start a *new* section (used as stop boundaries)
_ALL_SECTION_HEADS_RE = re.compile(
    r"(?:Pay\s*Range|Pay\s*Rate|Salary|Location|Minimum\s+Qualifications"
    r"|Education\s+and/?or\s+Equivalent\s+Experience"
    r"|Knowledge,?\s*Skills,?\s*and\s*Abilities"
    r"|Days?\s+and\s+Hours?|Hours?"
    r"|Preferred\s+Qualifications"
    r"|Licenses?\s+and\s+Certifications?\s+Required"
    r"|Notes?\s+to\s+Candidate[s]?"
    r"|Responsibilities\s*[-–—]?\s*Supervisor"
    r"|Duties,?\s*Functions\s+and\s+Responsibilities"
    r"|Job\s+Description"
    r"|Purpose"
    r"|Additional\s+Information"
    r"|Employment\s+Application"
    r"|Skills?\s+Assessment"
    r"|EEO\s+Statement"
    r"|90\s*Day\s+Provision"
    r"|Driving\s+Requirement)\s*:",
    re.IGNORECASE,
)


def _extract_sections(description_html: str) -> dict[str, str]:
    """Parse the job description HTML into named section snippets.

    Returns a dict like:
        {
            "pay_range":              "$22.48-$25.42",
            "location":               "6301-A Harold Court Austin Texas",
            "minimum_qualifications":  "Graduation with …",
            "ksa":                     "Knowledge of …",
            "education":               "Graduation with …",
            "days_and_hours":          "Monday - Friday 8:00am to 5:00pm",
            "preferred_qualifications":"Experience with …",
            "licenses":                "Valid Texas Class C …",
        }
    Values are stripped plain text (up to ~1000 chars each).
    """
    if not description_html:
        return {}

    text = _html_to_text(description_html)
    sections: dict[str, str] = {}

    for pattern, key in _SECTION_PATTERNS:
        if key in sections:
            continue  # first match wins for each key

        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        # Content starts right after the label
        start = match.end()
        # Find the next section heading as a stop boundary
        next_head = _ALL_SECTION_HEADS_RE.search(text, pos=start + 1)
        end = next_head.start() if next_head else len(text)

        snippet = text[start:end].strip()
        # Clean up and cap length
        snippet = re.sub(r"\s+", " ", snippet)[:1000].strip()
        if snippet:
            sections[key] = snippet

    return sections


# ── Salary parsing ───────────────────────────────────────────────────────────

# "Pay Range: $22.48-$25.42" / "Pay Rate: $32.96 - $41.20" / bare "$55,000 - $65,000"
_DOLLAR_RANGE_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d{1,2})?)"
    r"\s*[-–—]\s*"
    r"\$\s*([\d,]+(?:\.\d{1,2})?)",
)


def _parse_salary_from_sections(sections: dict[str, str]) -> tuple[float | None, float | None, str | None]:
    """Extract (wage_min, wage_max, wage_period) from parsed sections.

    Looks in the 'pay_range' section first, which covers:
      "Pay Range: $22.48-$25.42"
      "Pay Rate: $32.96 - $41.20"
      "Salary: Commensurate …" (no numbers → returns None)
    """
    pay_text = sections.get("pay_range", "")
    if not pay_text:
        return None, None, None

    match = _DOLLAR_RANGE_RE.search(pay_text)
    if not match:
        return None, None, None

    try:
        wage_min = float(match.group(1).replace(",", ""))
        wage_max = float(match.group(2).replace(",", ""))
        # Heuristic: if both values < 200, it's hourly; otherwise yearly
        wage_period = "hourly" if wage_max < 200 else "yearly"
        return wage_min, wage_max, wage_period
    except (ValueError, IndexError):
        return None, None, None


# ── Location / address parsing ───────────────────────────────────────────────

# Match a street-style address: "1234 Some Street, Austin, TX 78xxx"
_STREET_ADDR_RE = re.compile(
    r"\d+[A-Za-z\-]?\s+[A-Za-z][\w\s,.]+(?:Austin|TX)\b[,\s]*(?:TX)?\s*\d{0,5}",
    re.IGNORECASE,
)


def _parse_location_from_sections(sections: dict[str, str], fallback: str) -> str:
    """Extract the best street address from parsed sections.

    The 'location' section often contains a real street address, e.g.:
      "6301-A Harold Court Austin Texas"
      "8700 Cameron Road, Austin, TX, 78754"
    Falls back to the building name + city if no street address found.
    """
    loc_text = sections.get("location", "")
    if loc_text:
        # Try to find a street address pattern
        m = _STREET_ADDR_RE.search(loc_text)
        if m:
            return m.group(0).strip().rstrip(",")
        # Return raw location section text if it looks useful (has digits = likely address)
        if re.search(r"\d", loc_text):
            # Take first ~120 chars as address
            return loc_text[:120].strip()
    return fallback


def _parse_relative_date(posted_text: str) -> datetime | None:
    """Convert Workday's relative date strings to absolute datetime.

    Examples: "Posted Today", "Posted 4 Days Ago", "Posted 30+ Days Ago"
    """
    if not posted_text:
        return None

    now = datetime.now(timezone.utc)
    text = posted_text.lower().strip()

    if "today" in text:
        return now
    if "yesterday" in text:
        return now - timedelta(days=1)

    match = re.search(r"(\d+)\+?\s*days?\s*ago", text)
    if match:
        days = int(match.group(1))
        return now - timedelta(days=days)

    return None


# ── Adapter ──────────────────────────────────────────────────────────────────

class WorkdayGovAdapter(BaseScraper):
    """Scrapes government Workday career portals for job listings.

    Paginates through the Workday CXS API, optionally fetches detail pages
    for salary data, and produces ScraperSignal objects suitable for
    listings/ingest.py.
    """

    name = "WorkdayGov"

    def __init__(self, site_key: str = "austin_gov", fetch_details: bool = True) -> None:
        super().__init__()
        if site_key not in WORKDAY_GOV_SITES:
            raise ValueError(f"Unknown site_key '{site_key}'. Available: {list(WORKDAY_GOV_SITES)}")
        self.site_key = site_key
        self.site = WORKDAY_GOV_SITES[site_key]
        self.fetch_details = fetch_details

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Scrape all active listings from the government Workday portal.

        Args:
            region: Region key (e.g. 'austin_tx'). Used as metadata only —
                    all COA listings are in Austin by definition.
            radius_mi: Ignored for government portals (not location-filtered).

        Returns:
            List of ScraperSignal objects. Empty list on failure.
        """
        try:
            if not check_budget(_SOURCE_KEY):
                logger.warning("[%s] Daily budget exhausted — skipping", self.name)
                return []

            listings = self._fetch_all_listings()
            if not listings:
                logger.info("[%s] No listings returned from %s", self.name, self.site_key)
                return []

            signals = self._convert_to_signals(listings, region)
            logger.info(
                "[%s] %s: %d listings → %d signals",
                self.name, self.site_key, len(listings), len(signals),
            )
            return signals

        except Exception as exc:
            logger.error("[%s] Failed for site=%s: %s", self.name, self.site_key, exc)
            return []

    def _fetch_all_listings(self) -> list[dict[str, Any]]:
        """Paginate through Workday CXS API to fetch all job listings."""
        api = _api_url(self.site)
        page_size = self.site["page_size"]
        all_jobs: list[dict] = []
        offset = 0
        max_pages = 50  # safety limit

        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        })

        # Warm-up request to get session cookies
        search_url = f"{self.site['base_url']}/en-US/{self.site['site_id']}"
        try:
            t0 = time.time()
            session.get(search_url, timeout=15)
            log_external(
                _SOURCE_KEY, "session_warmup",
                url=search_url, success=True,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except requests.RequestException:
            pass  # proceed anyway — cookies are helpful but not always required

        for page in range(max_pages):
            payload = {
                "appliedFacets": {},
                "limit": page_size,
                "offset": offset,
                "searchText": "",
            }

            try:
                t0 = time.time()
                resp = session.post(api, json=payload, timeout=15)
                latency = int((time.time() - t0) * 1000)

                if resp.status_code == 422:
                    log_external(
                        _SOURCE_KEY, "job_listing_page",
                        url=api, method="POST",
                        success=False,
                        error_message="HTTP 422 — Cloudflare or WAF block",
                        latency_ms=latency,
                    )
                    logger.warning(
                        "[%s] Workday API returned 422 for %s — "
                        "site may require browser rendering",
                        self.name, self.site_key,
                    )
                    break

                resp.raise_for_status()
                data = resp.json()
                items = data.get("jobPostings", [])
                log_external(
                    _SOURCE_KEY, "job_listing_page",
                    url=api, method="POST",
                    success=True, latency_ms=latency,
                    data_items=len(items),
                    response_bytes=len(resp.content) if resp.content else 0,
                )
            except requests.RequestException as exc:
                logger.error("[%s] API request failed (page %d): %s", self.name, page, exc)
                break

            if not items:
                break

            # Optionally fetch detail page for each listing (salary data)
            for job in items:
                if self.fetch_details:
                    detail = self._fetch_detail(session, job.get("externalPath", ""))
                    if detail:
                        job["_detail"] = detail
                all_jobs.append(job)

            total = data.get("total", 0)
            offset += page_size
            if offset >= total:
                break

            time.sleep(1.0)  # polite delay between pages

        logger.info("[%s] Fetched %d listings from %s", self.name, len(all_jobs), self.site_key)
        return all_jobs

    def _fetch_detail(self, session: requests.Session, external_path: str) -> dict | None:
        """Fetch a single job detail page for salary/section extraction.

        Only called when fetch_details=True. Respects rate limiting.
        The Workday CXS detail endpoint requires Accept: application/json
        but must NOT send Content-Type (which is set on the session for POSTs).
        """
        if not external_path:
            return None

        url = _detail_url(self.site, external_path)
        try:
            t0 = time.time()
            # Override Content-Type for GET — Workday returns empty description
            # if Content-Type: application/json is sent on detail GET requests
            resp = session.get(
                url,
                headers={"Content-Type": None},
                timeout=15,
            )
            latency = int((time.time() - t0) * 1000)

            if not resp.ok:
                log_external(
                    _SOURCE_KEY, "job_detail",
                    url=url, success=False,
                    error_message=f"HTTP {resp.status_code}",
                    latency_ms=latency,
                )
                return None

            data = resp.json()
            log_external(
                _SOURCE_KEY, "job_detail",
                url=url, success=True,
                latency_ms=latency,
            )
            time.sleep(0.5)  # polite delay between detail fetches
            return data.get("jobPostingInfo", {})

        except (requests.RequestException, ValueError) as exc:
            logger.debug("[%s] Detail fetch failed for %s: %s", self.name, external_path, exc)
            return None

    def _convert_to_signals(
        self, listings: list[dict], region: str
    ) -> list[ScraperSignal]:
        """Convert raw Workday listings to ScraperSignal objects."""
        signals: list[ScraperSignal] = []
        site = self.site

        for listing in listings:
            title = listing.get("title", "")
            external_path = listing.get("externalPath", "")
            loc_text = listing.get("locationsText", "")
            posted_text = listing.get("postedOn", "")
            time_type = listing.get("timeType", "")

            # Extract job requisition ID from bulletFields
            bullet_fields = listing.get("bulletFields", [])
            job_req_id = bullet_fields[0] if bullet_fields else None

            # Parse posted date from relative text
            posted_dt = _parse_relative_date(posted_text)

            # ── Parse detail page sections ───────────────────────────
            detail = listing.get("_detail", {})
            description_html = detail.get("jobDescription", "") if detail else ""
            sections = _extract_sections(description_html)

            # Salary from parsed sections
            wage_min, wage_max, wage_period = _parse_salary_from_sections(sections)

            # Street address from description (falls back to building + city)
            fallback_addr = f"{loc_text}, Austin, TX" if loc_text else site["default_address"]
            address = _parse_location_from_sections(sections, fallback_addr)

            # Use detail start date if available (ISO format)
            if detail and detail.get("startDate"):
                try:
                    posted_dt = datetime.fromisoformat(detail["startDate"]).replace(
                        tzinfo=timezone.utc
                    )
                except (ValueError, TypeError):
                    pass

            observed_at = posted_dt or datetime.now(timezone.utc)

            # Build source URL
            source_url = _public_url(site, external_path) if external_path else None

            # Build a compact job_excerpt from the key qualification sections
            excerpt_parts = []
            if sections.get("minimum_qualifications"):
                excerpt_parts.append(f"Min Quals: {sections['minimum_qualifications']}")
            elif sections.get("education"):
                excerpt_parts.append(f"Education: {sections['education']}")
            if sections.get("days_and_hours"):
                excerpt_parts.append(f"Schedule: {sections['days_and_hours']}")
            job_excerpt = " | ".join(excerpt_parts)[:600] or None

            signal = ScraperSignal(
                store_num=job_req_id or "",
                chain=site["employer_name"],
                source="workday_gov",
                signal_type="listing",
                value=1.0,
                metadata={
                    "company": site["employer_name"],
                    "external_path": external_path,
                    "job_req_id": job_req_id,
                    "location_text": loc_text,
                    "address": address,
                    # Omit lat/lng so ingest pipeline geocodes from `address`.
                    # Default city-center coords are set as fallback in
                    # _geocode_if_needed() only when Nominatim fails.
                    "posted_date": posted_dt.isoformat() if posted_dt else None,
                    "time_type": time_type,
                    "is_remote": False,
                    "site_key": self.site_key,
                    "job_category": detail.get("jobFamilyGroup", "") if detail else "",
                    "job_excerpt": job_excerpt,
                    # Structured fields parsed from description
                    "pay_range_raw": sections.get("pay_range"),
                    "minimum_qualifications": sections.get("minimum_qualifications"),
                    "education": sections.get("education"),
                    "ksa": sections.get("ksa"),
                    "days_and_hours": sections.get("days_and_hours"),
                    "preferred_qualifications": sections.get("preferred_qualifications"),
                    "licenses": sections.get("licenses"),
                    "location_detail": sections.get("location"),
                },
                observed_at=observed_at,
                role_title=title,
                source_url=source_url,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
            )
            signals.append(signal)

        return signals


# ── Convenience function (matches project pattern) ───────────────────────────

def scrape_austin_gov(region: str = "austin_tx") -> list[ScraperSignal]:
    """Scrape City of Austin job listings and ingest into job_postings.

    Convenience wrapper that mirrors scrape_usajobs() / scrape_jobspy() pattern.
    """
    from postings.ingest import ingest_job_posting

    adapter = WorkdayGovAdapter(site_key="austin_gov")
    signals = adapter.scrape(region)

    ingested = 0
    for signal in signals:
        result = ingest_job_posting(signal, region=region)
        if result:
            ingested += 1

    logger.info(
        "[WorkdayGov] Austin GOV: %d scraped, %d ingested into job_postings",
        len(signals), ingested,
    )
    return signals


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Scrape government Workday career portals")
    parser.add_argument(
        "--site", default="austin_gov",
        choices=list(WORKDAY_GOV_SITES),
        help="Which government Workday site to scrape (default: austin_gov)",
    )
    parser.add_argument(
        "--region", default="austin_tx",
        help="Region key for ingest context (default: austin_tx)",
    )
    parser.add_argument(
        "--no-details", action="store_true",
        help="Skip fetching individual job detail pages (faster but no salary data)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape and print results without ingesting into database",
    )
    args = parser.parse_args()

    adapter = WorkdayGovAdapter(site_key=args.site, fetch_details=not args.no_details)
    signals = adapter.scrape(args.region)

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN — {len(signals)} signals from {args.site}")
        print(f"{'='*60}\n")
        for i, sig in enumerate(signals, 1):
            wage_str = ""
            if sig.wage_min or sig.wage_max:
                wage_str = f"  ${sig.wage_min or '?'}-${sig.wage_max or '?'}/{sig.wage_period or '?'}"
            meta = sig.metadata or {}
            print(f"  {i:3d}. {sig.role_title}")
            print(f"       ID: {meta.get('job_req_id', 'N/A')}{wage_str}")
            print(f"       Location: {meta.get('address', 'N/A')}")
            if meta.get("location_detail"):
                print(f"       Loc Detail: {meta['location_detail'][:80]}")
            if meta.get("minimum_qualifications"):
                print(f"       Min Quals: {meta['minimum_qualifications'][:100]}...")
            if meta.get("education"):
                print(f"       Education: {meta['education'][:100]}...")
            if meta.get("ksa"):
                print(f"       KSA: {meta['ksa'][:80]}...")
            if meta.get("days_and_hours"):
                print(f"       Schedule: {meta['days_and_hours'][:80]}")
            print(f"       URL: {sig.source_url or 'N/A'}")
            print()
    else:
        from postings.ingest import ingest_job_posting
        ingested = 0
        for signal in signals:
            result = ingest_job_posting(signal, region=args.region)
            if result:
                ingested += 1
        print(f"Ingested {ingested}/{len(signals)} job postings from {args.site}")
