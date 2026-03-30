"""
NLRB (National Labor Relations Board) case adapter for ChainStaffingTracker.

Fetches union election petitions and unfair labor practice (ULP) charges filed
against tracked chain employers in Texas. A petition or charge at a specific
store address is a direct store-level indicator of labor unrest and often
precedes turnover spikes or staffing instability.

Data source: NLRB public case search API (no auth required)
  https://www.nlrb.gov/cases-and-decisions/cases

Case types tracked:
  RC  — Representation Case (union election petition)
  RD  — Decertification petition
  UD  — Deauthorization petition
  CA  — ULP charge against employer
  CB  — ULP charge against union

Signals produced:
  signal_type="labor_unrest"   value = intensity score 0-1
    - RC/RD: 0.8  (active election petition — high unrest indicator)
    - CA:    0.7  (ULP charge against employer)
    - UD/CB: 0.4  (lower intensity)

Depends on: requests, config.loader, scrapers.base
Called by: backend/scheduler.py, CLI
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import get_all_chains, get_http_config, get_rate_limit, get_region
from collectors.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

# NLRB public case search endpoint (Solr-backed, no API key required)
_NLRB_SEARCH_URL = "https://www.nlrb.gov/api/cases/search"

# Intensity scores per case type
_CASE_TYPE_SCORES: dict[str, float] = {
    "RC": 0.8,   # Union election petition — strongest unrest signal
    "RD": 0.75,  # Decertification petition
    "CA": 0.70,  # ULP charge against employer
    "UD": 0.40,  # Deauthorization of union security
    "CB": 0.30,  # ULP charge against union
}

# Employer name variants to match against NLRB records per chain key
_EMPLOYER_ALIASES: dict[str, list[str]] = {
    "starbucks": ["starbucks", "starbucks coffee"],
    "dutch_bros": ["dutch bros", "dutch brothers"],
    "mcdonalds": ["mcdonald's", "mcdonalds"],
}


class NLRBAdapter(BaseScraper):
    """Fetches NLRB case filings for tracked chain employers.

    Queries the NLRB public search API for cases in the target state,
    filters by employer name aliases, and emits labor_unrest signals.
    When an exact store address is present in the case record it is used
    as the store identifier; otherwise the signal is attributed to the
    regional bucket.
    """

    name = "NLRB"

    def __init__(self) -> None:
        super().__init__()
        self.http_cfg = get_http_config()
        self.rate_limit = get_rate_limit("nlrb")

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch NLRB cases for all tracked chains in the region's state.

        Args:
            region: Region key from config, e.g. 'austin_tx'.
            radius_mi: Unused — NLRB queries are statewide.

        Returns:
            List of ScraperSignal with signal_type='labor_unrest'.
        """
        try:
            region_cfg = get_region(region)
            state = region_cfg.get("state", "TX")
            chains = get_all_chains()

            all_signals: list[ScraperSignal] = []

            for chain_key, chain_cfg in chains.items():
                aliases = _EMPLOYER_ALIASES.get(chain_key, [chain_cfg.get("display_name", chain_key).lower()])
                for alias in aliases:
                    signals = self._fetch_cases_for_employer(alias, chain_key, state, region)
                    all_signals.extend(signals)
                    time.sleep(self.rate_limit.get("delay_seconds", 2.0))

            # Deduplicate by case number — multiple aliases may match the same case
            seen_cases: set[str] = set()
            unique_signals: list[ScraperSignal] = []
            for sig in all_signals:
                case_num = sig.metadata.get("case_number", "")
                if case_num and case_num in seen_cases:
                    continue
                if case_num:
                    seen_cases.add(case_num)
                unique_signals.append(sig)

            logger.info(
                "[%s] %d labor_unrest signals for region=%s (state=%s)",
                self.name, len(unique_signals), region, state,
            )
            return unique_signals

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _fetch_cases_for_employer(
        self,
        employer_query: str,
        chain_key: str,
        state: str,
        region: str,
    ) -> list[ScraperSignal]:
        """Query NLRB API for cases matching an employer name in a state."""
        signals: list[ScraperSignal] = []

        # Look back 24 months to capture recent union activity waves
        date_start = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
        date_end = datetime.utcnow().strftime("%Y-%m-%d")

        params: dict[str, Any] = {
            "q": employer_query,
            "state": state,
            "dateStart": date_start,
            "dateEnd": date_end,
            "rows": 100,
            "page": 0,
            "sort": "date_filed desc",
        }

        try:
            from core.tracked_request import tracked_get
            resp = tracked_get(
                "nlrb", "case_search",
                _NLRB_SEARCH_URL,
                params=params,
                headers={
                    "User-Agent": self.http_cfg["user_agent"],
                    "Accept": "application/json",
                },
                timeout=self.http_cfg["timeout_seconds"],
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("[%s] API call failed for employer='%s': %s", self.name, employer_query, e)
            # Try fallback parse — some NLRB endpoints return HTML; log and skip
            return signals

        cases = self._extract_cases(data)
        for case in cases:
            sig = self._case_to_signal(case, chain_key, region)
            if sig is not None:
                signals.append(sig)

        return signals

    def _extract_cases(self, data: Any) -> list[dict]:
        """Extract case records from various NLRB API response shapes."""
        if isinstance(data, list):
            return data

        # Common Solr-style response: {"response": {"docs": [...]}}
        if isinstance(data, dict):
            if "response" in data:
                return data["response"].get("docs", [])
            if "cases" in data:
                return data["cases"]
            if "data" in data:
                return data["data"] if isinstance(data["data"], list) else []

        return []

    def _case_to_signal(
        self,
        case: dict,
        chain_key: str,
        region: str,
    ) -> ScraperSignal | None:
        """Convert a raw NLRB case dict to a ScraperSignal."""
        # Normalize field names — NLRB API uses varied casing
        case_num = (
            case.get("case_number")
            or case.get("caseNumber")
            or case.get("id")
            or ""
        )
        case_type = (
            case.get("case_type")
            or case.get("caseType")
            or case.get("type")
            or ""
        ).upper()[:2]  # "RC", "CA", etc.

        employer_name = (
            case.get("employer_name")
            or case.get("employerName")
            or case.get("employer")
            or ""
        )
        filing_address = (
            case.get("employer_address")
            or case.get("employerAddress")
            or case.get("address")
            or ""
        )
        city = case.get("city") or case.get("employer_city") or ""
        state_field = case.get("state") or case.get("employer_state") or ""
        zip_code = case.get("zip") or case.get("employer_zip") or ""

        date_filed_raw = (
            case.get("date_filed")
            or case.get("dateFiled")
            or case.get("filed_date")
            or ""
        )
        status = case.get("status") or case.get("case_status") or "unknown"
        case_url = case.get("url") or case.get("case_url") or f"https://www.nlrb.gov/cases-and-decisions/cases?q={case_num}"

        # Skip if case type is unknown / irrelevant
        intensity = _CASE_TYPE_SCORES.get(case_type, 0.0)
        if intensity == 0.0 and case_type:
            # Still emit low-intensity signal for any tracked employer case
            intensity = 0.25

        # Parse filing date
        try:
            if date_filed_raw:
                observed_at = datetime.fromisoformat(str(date_filed_raw).replace("Z", "+00:00").split("T")[0])
            else:
                observed_at = datetime.utcnow()
        except (ValueError, TypeError):
            observed_at = datetime.utcnow()

        # Build store_num — use address if available for store-level attribution
        full_address = " ".join(filter(None, [filing_address, city, state_field, zip_code])).strip()
        if full_address:
            from collectors.geocoding import extract_store_num
            chain_cfg = {}
            try:
                from config.loader import get_chain
                chain_cfg = get_chain(chain_key)
            except Exception:
                pass
            prefix = chain_cfg.get("store_num_prefix", chain_key[:2].upper())
            store_num = extract_store_num(prefix, None, full_address)
        else:
            store_num = f"REGIONAL-{region}"

        return ScraperSignal(
            store_num=store_num,
            chain=chain_key,
            source="nlrb",
            signal_type="labor_unrest",
            value=intensity,
            metadata={
                "case_number": case_num,
                "case_type": case_type,
                "case_type_description": _case_type_description(case_type),
                "employer_name": employer_name,
                "address": full_address,
                "store_name": employer_name,
                "city": city,
                "state": state_field,
                "zip_code": zip_code,
                "status": status,
                "date_filed": str(date_filed_raw),
                "intensity": intensity,
            },
            observed_at=observed_at,
            source_url=case_url,
        )


def _case_type_description(case_type: str) -> str:
    """Human-readable label for NLRB case type codes."""
    return {
        "RC": "Union Election Petition (employees seeking union)",
        "RD": "Decertification Petition (employees seeking to remove union)",
        "UD": "Deauthorization Petition",
        "CA": "Unfair Labor Practice Charge (against employer)",
        "CB": "Unfair Labor Practice Charge (against union)",
    }.get(case_type, f"NLRB Case ({case_type})")


def scrape_nlrb(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape NLRB and optionally ingest."""
    adapter = NLRBAdapter()
    signals = adapter.scrape(region)

    if ingest and signals:
        from core.ingest import ingest_signals
        count = ingest_signals(signals, region, chain=None, source="nlrb")
        logger.info("[NLRB] Ingested %d signals", count)

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch NLRB labor unrest signals")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_nlrb(region=args.region, ingest=not args.no_ingest)
    for sig in signals:
        print(
            f"  [{sig.metadata.get('case_number','?')}] "
            f"{sig.metadata.get('case_type','?')} "
            f"{sig.metadata.get('employer_name','?')} "
            f"@ {sig.metadata.get('address','?')} "
            f"(value={sig.value:.2f})"
        )
    logger.info("Total: %d signals", len(signals))


if __name__ == "__main__":
    main()
