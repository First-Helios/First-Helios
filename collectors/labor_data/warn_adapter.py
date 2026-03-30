"""
Texas WARN Act adapter for ChainStaffingTracker.

Fetches Worker Adjustment and Retraining Notification (WARN) filings from
the Texas Open Data Portal (Socrata API). WARN notices identify specific
establishment addresses where mass layoffs (50+ employees) or plant closings
are imminent — the most direct public signal of an employer winding down
a location.

Data source: Texas Open Data Portal — Socrata REST API (no auth required)
  https://data.texas.gov/resource/8w53-c4f6.json

Scope:
  The federal WARN Act applies to employers with 100+ employees laying off
  50+ workers at a single site. A single Starbucks store (typically 15-30
  employees) will NOT trigger WARN. This adapter is most useful for:
    - Large format company-operated Starbucks Reserve locations
    - Corporate office / regional hub closures
    - Distribution/roasting facilities
    - Future coverage of additional larger chains (fast food, grocery)

Signals produced:
  signal_type="warn_filing"   value = normalized severity 0-1
    Severity is based on employees_affected normalized against WARN threshold (50).
    50 employees → 0.5, 200+ → 1.0

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

# Texas Open Data Portal — WARN notices (Socrata)
_WARN_API_URL = "https://data.texas.gov/resource/8w53-c4f6.json"

# NAICS codes for food service — used to pre-filter if NAICS field is present
_FOOD_SERVICE_NAICS_PREFIXES = ("722", "721", "44", "45")

# Employer name search strings per chain key
_EMPLOYER_SEARCH_TERMS: dict[str, list[str]] = {
    "starbucks": ["starbucks"],
    "dutch_bros": ["dutch bros", "dutch brothers"],
    "mcdonalds": ["mcdonald"],
}


class WARNAdapter(BaseScraper):
    """Scrapes Texas WARN Act filings for tracked chain employers.

    Queries the Socrata API for all WARN notices involving food-service
    or tracked chain employers in the target state. Emits warn_filing
    signals attributed to the specific establishment address.
    """

    name = "WARN"

    def __init__(self) -> None:
        super().__init__()
        self.http_cfg = get_http_config()
        self.rate_limit = get_rate_limit("warn")

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch Texas WARN notices for tracked chains.

        Args:
            region: Region key from config, e.g. 'austin_tx'.
            radius_mi: Unused — WARN data is statewide.

        Returns:
            List of ScraperSignal with signal_type='warn_filing'.
        """
        try:
            region_cfg = get_region(region)
            state = region_cfg.get("state", "TX")

            all_signals: list[ScraperSignal] = []

            # Fetch chain-specific notices by employer name
            chains = get_all_chains()
            for chain_key, chain_cfg in chains.items():
                search_terms = _EMPLOYER_SEARCH_TERMS.get(
                    chain_key, [chain_cfg.get("display_name", chain_key).lower()]
                )
                for term in search_terms:
                    chain_signals = self._fetch_warn_notices(
                        employer_query=term,
                        naics_prefix=None,
                        state=state,
                        region=region,
                        chain_key=chain_key,
                    )
                    all_signals.extend(chain_signals)
                    time.sleep(self.rate_limit.get("delay_seconds", 1.0))

            # Deduplicate by a composite key: employer + address + notice_date
            seen: set[str] = set()
            unique: list[ScraperSignal] = []
            for sig in all_signals:
                key = "|".join([
                    sig.metadata.get("employer_name", ""),
                    sig.metadata.get("address", ""),
                    sig.metadata.get("notice_date", ""),
                ])
                if key in seen:
                    continue
                seen.add(key)
                unique.append(sig)

            logger.info(
                "[%s] %d warn_filing signals for region=%s",
                self.name, len(unique), region,
            )
            return unique

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _fetch_warn_notices(
        self,
        employer_query: str | None,
        naics_prefix: str | None,
        state: str,
        region: str,
        chain_key: str,
    ) -> list[ScraperSignal]:
        """Query Socrata WARN API with optional employer name filter.

        Texas WARN dataset columns (8w53-c4f6):
          notice_date, job_site_name, county_name, wda_name,
          total_layoff_number, layoff_date, wfdd_received_date, city_name
        """
        signals: list[ScraperSignal] = []

        # Look back 3 years
        date_start = (datetime.utcnow() - timedelta(days=1095)).strftime("%Y-%m-%dT00:00:00.000")

        params: dict[str, Any] = {
            "$where": f"notice_date >= '{date_start}'",
            "$limit": 1000,
            "$order": "notice_date DESC",
        }

        if employer_query:
            # Socrata full-text search across all text columns
            params["$q"] = employer_query

        # naics_prefix filter is not available in the TX WARN dataset

        try:
            from backend.tracked_request import tracked_get
            resp = tracked_get(
                "warn_tx", "socrata_warn",
                _WARN_API_URL,
                params=params,
                headers={
                    "User-Agent": self.http_cfg["user_agent"],
                    "Accept": "application/json",
                },
                timeout=self.http_cfg["timeout_seconds"],
            )
            resp.raise_for_status()
            records = resp.json()
        except Exception as e:
            logger.warning("[%s] Socrata API call failed: %s", self.name, e)
            return signals

        if not isinstance(records, list):
            logger.warning("[%s] Unexpected Socrata response type: %s", self.name, type(records))
            return signals

        for record in records:
            sig = self._record_to_signal(record, chain_key, region)
            if sig is not None:
                signals.append(sig)

        return signals

    def _record_to_signal(
        self,
        record: dict,
        chain_key: str,
        region: str,
    ) -> ScraperSignal | None:
        """Convert a Socrata WARN record to a ScraperSignal.

        Texas WARN dataset (8w53-c4f6) actual field names:
          job_site_name, city_name, county_name, wda_name,
          total_layoff_number, notice_date, layoff_date, wfdd_received_date
        """
        employer_name = record.get("job_site_name") or ""
        city = record.get("city_name") or ""
        county = record.get("county_name") or ""
        state_field = "TX"
        zip_code = ""
        address = ""  # TX dataset does not include street address

        notice_date_raw = record.get("notice_date") or ""
        layoff_date_raw = record.get("layoff_date") or ""
        employees_raw = record.get("total_layoff_number") or "0"
        action_type = "layoff"  # TX dataset does not distinguish action type
        naics = ""  # TX dataset does not include NAICS

        # Parse employee count
        try:
            employees_affected = int(str(employees_raw).replace(",", "").strip())
        except (ValueError, TypeError):
            employees_affected = 0

        # Severity: normalized against the 50-employee WARN threshold
        # 50 → 0.5, 200 → 1.0, <50 → proportional
        severity = min(1.0, employees_affected / 200.0) if employees_affected > 0 else 0.1

        # Parse notice date
        try:
            if notice_date_raw:
                observed_at = datetime.fromisoformat(
                    str(notice_date_raw).replace("Z", "+00:00").split("T")[0]
                )
            else:
                observed_at = datetime.utcnow()
        except (ValueError, TypeError):
            observed_at = datetime.utcnow()

        # Build best available location string (TX dataset has city but no street address)
        full_address = " ".join(filter(None, [address, city, county, state_field, zip_code])).strip()

        # Attempt chain identification from employer name if chain_key unknown
        inferred_chain = chain_key
        if chain_key == "unknown":
            inferred_chain = _infer_chain_from_name(employer_name)

        # Build store_num from address
        if full_address:
            from collectors.geocoding import extract_store_num
            try:
                from config.loader import get_chain
                chain_cfg = get_chain(inferred_chain)
                prefix = chain_cfg.get("store_num_prefix", inferred_chain[:2].upper())
            except Exception:
                prefix = "WN"  # WARN prefix for unknown chains
            store_num = extract_store_num(prefix, None, full_address)
        else:
            store_num = f"REGIONAL-{region}"

        return ScraperSignal(
            store_num=store_num,
            chain=inferred_chain,
            source="warn_tx",
            signal_type="warn_filing",
            value=severity,
            metadata={
                "employer_name": employer_name,
                "address": full_address,
                "store_name": employer_name,
                "city": city,
                "county": county,
                "state": state_field,
                "zip_code": zip_code,
                "notice_date": str(notice_date_raw),
                "layoff_date": str(layoff_date_raw),
                "employees_affected": employees_affected,
                "action_type": action_type,
                "naics_code": naics,
                "severity": round(severity, 3),
            },
            observed_at=observed_at,
            source_url=_WARN_API_URL,
        )


def _infer_chain_from_name(employer_name: str) -> str:
    """Best-effort chain identification from an employer name string."""
    name_lower = employer_name.lower()
    for chain_key, terms in _EMPLOYER_SEARCH_TERMS.items():
        if any(term in name_lower for term in terms):
            return chain_key
    return "unknown"


def scrape_warn(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape WARN notices and optionally ingest."""
    adapter = WARNAdapter()
    signals = adapter.scrape(region)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain=None, source="warn_tx")
        logger.info("[WARN] Ingested %d signals", count)

    return signals


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch Texas WARN Act filings")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_warn(region=args.region, ingest=not args.no_ingest)
    for sig in signals:
        print(
            f"  {sig.metadata.get('notice_date','?')[:10]}  "
            f"{sig.metadata.get('employer_name','?'):<35}  "
            f"{sig.metadata.get('employees_affected',0):>4} workers  "
            f"@ {sig.metadata.get('city','?')}"
        )
    logger.info("Total: %d WARN filings", len(signals))


if __name__ == "__main__":
    main()
