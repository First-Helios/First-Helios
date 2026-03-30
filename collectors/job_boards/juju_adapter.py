"""
scrapers/juju_adapter.py — Juju Job Search API adapter.

Fetches job listings from http://api.juju.com/jobs (XML/RSS 2.0) and routes
every result through listings/ingest.py (ingest_job_posting), the single write
path for all JobPosting records.

API overview:
  Endpoint:  GET http://api.juju.com/jobs
  Format:    XML RSS 2.0 — parsed with xml.etree.ElementTree
  Auth:      partnerid query parameter (Juju publisher/partner ID)
             Set JUJU_PARTNER_ID in your .env.  Without it this adapter logs
             a warning and returns an empty list — no HTTP request is made.
  Rate:      12-hour TTL (_TTL_MINUTES = 720). One page per run; no pagination.
             Conserves daily budget and avoids hammering the XML endpoint.

Publisher ID note:
  A Juju partnerid is issued to registered publishers / affiliates.
  Apply at https://www.juju.com/publisher/  The ID must be present in .env
  as JUJU_PARTNER_ID before any live requests will succeed.

Namespace:
  Juju-specific fields live in the http://www.juju.com/terms/ XML namespace.
  They are accessed as {http://www.juju.com/terms/}fieldname.

Called by: backend/scheduler.py, CLI
"""

import argparse
import hashlib
import html as _html_mod
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
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

# ── Constants ─────────────────────────────────────────────────────────────────

_JUJU_API = "http://api.juju.com/jobs"
_SOURCE_KEY = "juju"

# 12-hour cache / minimum request interval
_TTL_MINUTES = 720
_MIN_INTERVAL_MINUTES = 720

# Juju XML namespace for juju:* elements
_JUJU_NS = "http://www.juju.com/terms/"
_NS = {"juju": _JUJU_NS}

# ── Address extraction helpers (mirrored from jobicy_adapter) ──────────────────

# Country/region strings that are NOT geocodable street addresses.
_GEO_NOISE = frozenset({
    "usa", "us", "united states", "united states of america",
    "worldwide", "world", "global", "remote", "anywhere",
    "north america", "latin america", "south america",
    "europe", "asia", "africa", "oceania", "apac", "emea",
    "", "null", "none",
})

# Fallback regex: street number + named road type, no state required.
# Guards against common false positives (salary fragments, zero-prefix numbers,
# road-type substrings inside longer words).
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


# ── XML parsing helpers ────────────────────────────────────────────────────────

def _juju_text(item: ET.Element, tag: str) -> str:
    """Return text of a juju:tag element, or empty string if absent."""
    el = item.find(f"{{{_JUJU_NS}}}{tag}")
    return (el.text or "").strip() if el is not None else ""


def _item_text(item: ET.Element, tag: str) -> str:
    """Return text of a plain (no-namespace) child element, or empty string."""
    el = item.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _parse_items(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 XML into a list of plain dicts (one per <item>).

    Converts all juju:* namespace elements into plain string values so the
    result is JSON-serialisable for caching.  Adapts gracefully when fields
    are absent.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("[Juju] XML parse error: %s", exc)
        return []

    items: list[dict] = []
    for item in root.findall(".//item"):
        record: dict[str, Any] = {
            "title":       _item_text(item, "title"),
            "link":        _item_text(item, "link"),
            "description": _item_text(item, "description"),
            "pubDate":     _item_text(item, "pubDate"),
            # juju:* fields
            "salary":      _juju_text(item, "salary"),
            "location":    _juju_text(item, "location"),
            "company":     _juju_text(item, "company"),
            "jobkey":      _juju_text(item, "jobkey"),
        }
        # Fall back to <source> for company name when juju:company is empty
        if not record["company"]:
            record["company"] = _item_text(item, "source")
        items.append(record)

    return items


# ── Interval gate (mirrors jobicy hourly gate) ────────────────────────────────

def _interval_gate_ok() -> bool:
    """Return True if enough time has passed since the last Juju request.

    Reads last_request_at from rate_budget for today's juju row.
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
        logger.warning("[Juju] interval gate check failed, allowing request: %s", exc)
        return True


# ── Adapter class ─────────────────────────────────────────────────────────────

class JujuAdapter(BaseScraper):
    """Fetch job listings from the Juju XML Search API.

    One page (jpp=50), location=Austin TX, radius=50 mi per run.
    No pagination — conserves daily budget.
    """

    name = "Juju"

    def scrape(self, region: str, radius_mi: int = 50) -> list[ScraperSignal]:
        """Fetch listings from Juju and return as ScraperSignal list.

        Args:
            region:    Region key, e.g. "austin_tx". Used to tag postings.
            radius_mi: Search radius in miles (default 50; covers Round Rock,
                       Cedar Park, Georgetown).

        Returns:
            List of ScraperSignal objects (signal_type="listing").
            Empty list on missing credentials, budget exhaustion, interval
            gate, or API failure.
        """
        # ── Auth check — fail fast, no HTTP if partner ID is absent ──────────
        partner_id = os.environ.get("JUJU_PARTNER_ID", "").strip()
        if not partner_id:
            logger.warning(
                "[Juju] JUJU_PARTNER_ID is not set — skipping. "
                "Set it in .env to enable this adapter."
            )
            return []

        # ── Cache check — skip API + rate-manager entirely if fresh ──────────
        cached = read_cache(_SOURCE_KEY, ttl_minutes=_TTL_MINUTES)
        if cached is not None:
            return self._items_to_signals(cached, region)

        # ── Pre-flight: daily budget ──────────────────────────────────────────
        if not check_budget(_SOURCE_KEY):
            logger.warning("[Juju] Daily budget exhausted — skipping")
            return []

        # ── Pre-flight: interval gate ─────────────────────────────────────────
        if not _interval_gate_ok():
            logger.info(
                "[Juju] Interval gate active — last request < %d min ago, skipping",
                _MIN_INTERVAL_MINUTES,
            )
            return []

        # ── Build request params ──────────────────────────────────────────────
        params: dict[str, str] = {
            "partnerid": partner_id,
            "ipaddress": "127.0.0.1",
            "useragent": "Mozilla/5.0 (compatible; FirstHelios/1.0)",
            "k":         "",           # broad — all jobs
            "l":         "Austin, TX",
            "r":         str(radius_mi),
            "jpp":       "50",
            "page":      "1",
            "order":     "date",
        }

        items: list[dict] = []

        try:
            resp = tracked_get(
                _SOURCE_KEY,
                "xml_search",
                _JUJU_API,
                params=params,
                timeout=30,
            )

            if not resp.ok:
                logger.error("[Juju] API returned HTTP %s", resp.status_code)
            else:
                items = _parse_items(resp.text)

        except Exception as exc:
            logger.error("[Juju] Request failed: %s", exc)

        if not items:
            return []

        write_cache(_SOURCE_KEY, items)
        logger.info("[Juju] %d jobs returned", len(items))
        return self._items_to_signals(items, region)

    # ── Signal conversion ─────────────────────────────────────────────────────

    def _items_to_signals(
        self, items: list[dict], region: str
    ) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for item in items:
            if not isinstance(item, dict):
                continue

            company = item.get("company", "").strip()
            if not company:
                continue

            title       = item.get("title", "").strip()
            link        = item.get("link", "").strip()
            description = item.get("description", "").strip()
            pubdate_raw = item.get("pubDate", "").strip()
            location_str = item.get("location", "").strip()
            jobkey      = item.get("jobkey", "").strip()
            salary_str  = item.get("salary", "").strip()

            # ── External ID ──────────────────────────────────────────────────
            if jobkey:
                external_id = f"juju:{jobkey}"
            else:
                external_id = hashlib.sha256(link.encode("utf-8", errors="replace")).hexdigest()[:40]

            # ── Publication date ─────────────────────────────────────────────
            posted_date: datetime | None = None
            if pubdate_raw:
                try:
                    from dateutil.parser import parse as _parse
                    posted_date = _parse(pubdate_raw)
                    if posted_date.tzinfo is not None:
                        posted_date = posted_date.replace(tzinfo=None)
                except Exception:
                    posted_date = None

            # ── Salary parsing ───────────────────────────────────────────────
            # Juju salary is a human-readable string like "$50,000 - $70,000"
            wage_min: float | None = None
            wage_max: float | None = None
            wage_period: str | None = None
            if salary_str:
                nums = re.findall(r'[\d,]+', salary_str.replace(",", ""))
                # After stripping commas, re-find plain digit sequences
                nums = re.findall(r'\d+', salary_str.replace(",", ""))
                if nums:
                    try:
                        wage_min = float(nums[0])
                        wage_period = "yearly"
                    except (ValueError, IndexError):
                        pass
                if len(nums) >= 2:
                    try:
                        wage_max = float(nums[1])
                    except (ValueError, IndexError):
                        pass

            # ── Address extraction ────────────────────────────────────────────
            # Priority: juju:location → description text
            extracted_addr: str | None = None
            extracted_method: str | None = None

            if location_str and location_str.strip().lower() not in _GEO_NOISE:
                result = _find_address(location_str)
                if result:
                    extracted_addr, extracted_method = result

            if extracted_addr is None and description:
                result = _find_address(_strip_html(description))
                if result:
                    extracted_addr, extracted_method = result

            # ── is_remote detection ───────────────────────────────────────────
            loc_lower  = location_str.lower()
            desc_lower = _strip_html(description).lower()
            is_remote = (
                "remote" in loc_lower
                or "remote work" in desc_lower
                or "work from home" in desc_lower
            )

            # ── Build ScraperSignal ───────────────────────────────────────────
            signal = ScraperSignal(
                store_num=f"JUJU-{region}",
                chain="juju",
                source=_SOURCE_KEY,
                signal_type="listing",
                value=1.0,
                metadata={
                    "company":          company,
                    "employer":         company,
                    "job_url":          link,
                    "date_posted":      posted_date.isoformat() if posted_date else None,
                    "location":         location_str,
                    "address":          extracted_addr,
                    "address_method":   extracted_method,
                    "job_excerpt":      _strip_html(description)[:500],
                    "category":         None,
                    "job_type":         None,
                    "is_remote":        is_remote,
                    "source_platform":  "juju",
                    "external_path":    external_id,   # careers_api compat key
                },
                observed_at=posted_date or now,
                wage_min=wage_min,
                wage_max=wage_max,
                wage_period=wage_period,
                role_title=title or None,
                source_url=link or None,
            )
            signals.append(signal)

        return signals


# ── Convenience function ───────────────────────────────────────────────────────

def scrape_juju(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Fetch one page of Austin-area jobs from the Juju XML Search API.

    The interval gate inside JujuAdapter.scrape() enforces the 12-hour
    minimum between requests.

    Args:
        region: Region key for tagging ingested postings (default: austin_tx).
        ingest: If True, route all signals through ingest_job_posting.

    Returns:
        List of ScraperSignals (may be empty if gate is active or API fails).
    """
    adapter = JujuAdapter()
    signals = adapter.scrape(region)

    logger.info("[Juju] %d signals for region=%s", len(signals), region)

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
            logger.info("[Juju] Ingested %d/%d postings", ingested, len(signals))
        finally:
            session.close()

    return signals


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch Austin-area job listings from the Juju XML Search API"
    )
    parser.add_argument(
        "--region",
        default="austin_tx",
        help="Region key (default: austin_tx)",
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Fetch only, do not write to DB",
    )
    args = parser.parse_args()

    signals = scrape_juju(
        region=args.region,
        ingest=not args.no_ingest,
    )
    logger.info("Done. %d signals.", len(signals))


if __name__ == "__main__":
    main()
