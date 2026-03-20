"""
JobSpy adapter for ChainStaffingTracker.

Wraps python-jobspy (Indeed, Glassdoor, ZipRecruiter) output into
ScraperSignal objects. Operates in two modes:
  - chain mode: searches for chain-specific roles (detects repostings)
  - wage mode: searches for local employer listings (builds wage_index)

Depends on: python-jobspy, config.loader, scrapers.base, scrapers.geocoding
Called by: backend/scheduler.py, server.py, CLI
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import (
    get_chain,
    get_chains_for_industry,
    get_industry,
    get_region,
)
from scrapers.base import BaseScraper, ScraperSignal
from scrapers.geocoding import extract_store_num

logger = logging.getLogger(__name__)


class JobSpyAdapter(BaseScraper):
    """Wraps python-jobspy into the ScraperSignal pipeline.

    Does NOT write a custom scraper — delegates entirely to JobSpy
    and transforms the output.
    """

    name = "JobSpy"

    def __init__(
        self,
        chain_key: str | None = None,
        industry_key: str | None = None,
        mode: str = "chain",
    ) -> None:
        super().__init__()
        self.chain_key = chain_key
        self.industry_key = industry_key
        self.mode = mode  # "chain" or "wage"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Scrape job boards via JobSpy for the given region.

        Args:
            region: Region key from config.
            radius_mi: Search radius in miles.

        Returns:
            List of ScraperSignal objects. Empty on failure.
        """
        try:
            from jobspy import scrape_jobs

            region_cfg = get_region(region)
            location = region_cfg["location_string"]

            if self.mode == "chain" and self.chain_key:
                return self._scrape_chain(scrape_jobs, location, radius_mi, region)
            elif self.mode == "wage" and self.industry_key:
                return self._scrape_wages(scrape_jobs, location, radius_mi, region)
            else:
                logger.warning(
                    "[%s] Invalid mode=%s or missing chain/industry", self.name, self.mode
                )
                return []

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _scrape_chain(
        self, scrape_jobs, location: str, radius_mi: int, region: str
    ) -> list[ScraperSignal]:
        """Search for chain-specific job postings."""
        chain_cfg = get_chain(self.chain_key)
        target_roles = chain_cfg.get("target_roles", [])
        chain_name = chain_cfg["display_name"]
        prefix = chain_cfg.get("store_num_prefix", "XX")

        all_signals: list[ScraperSignal] = []

        for role in target_roles:
            search_term = f"{chain_name} {role}"
            logger.info("[%s] Searching: '%s' near %s", self.name, search_term, location)

            try:
                df = scrape_jobs(
                    site_name=["indeed", "glassdoor"],
                    search_term=search_term,
                    location=location,
                    distance=radius_mi,
                    hours_old=72,
                    results_wanted=100,
                    country_indeed="USA",
                )
            except Exception as e:
                logger.error("[%s] scrape_jobs failed for '%s': %s", self.name, search_term, e)
                continue

            if df is None or df.empty:
                logger.info("[%s] No results for '%s'", self.name, search_term)
                continue

            signals = self._df_to_signals(df, prefix, region, is_chain=True)
            all_signals.extend(signals)

        logger.info(
            "[%s] Chain mode: %d total signals for %s",
            self.name, len(all_signals), self.chain_key,
        )
        return all_signals

    def _scrape_wages(
        self, scrape_jobs, location: str, radius_mi: int, region: str
    ) -> list[ScraperSignal]:
        """Search for local employer listings to build wage index."""
        industry_cfg = get_industry(self.industry_key)
        search_terms = industry_cfg.get("local_search_terms", industry_cfg.get("search_terms", []))
        chain_keys = set(get_chains_for_industry(self.industry_key).keys())

        all_signals: list[ScraperSignal] = []

        for term in search_terms:
            logger.info("[%s] Wage search: '%s' near %s", self.name, term, location)

            try:
                df = scrape_jobs(
                    site_name=["indeed", "glassdoor"],
                    search_term=term,
                    location=location,
                    distance=radius_mi,
                    hours_old=168,  # 7 days for wage data
                    results_wanted=100,
                    country_indeed="USA",
                )
            except Exception as e:
                logger.error("[%s] scrape_jobs failed for '%s': %s", self.name, term, e)
                continue

            if df is None or df.empty:
                continue

            signals = self._df_to_signals(
                df, "LOCAL", region, is_chain=False, chain_keys=chain_keys
            )
            all_signals.extend(signals)

        logger.info(
            "[%s] Wage mode: %d total signals for industry=%s",
            self.name, len(all_signals), self.industry_key,
        )
        return all_signals

    def _df_to_signals(
        self,
        df: pd.DataFrame,
        prefix: str,
        region: str,
        is_chain: bool = True,
        chain_keys: set[str] | None = None,
    ) -> list[ScraperSignal]:
        """Convert a JobSpy DataFrame to ScraperSignal objects."""
        signals: list[ScraperSignal] = []

        for _, row in df.iterrows():
            company = str(row.get("company", "")).strip()

            # For wage mode, skip chain employers
            if not is_chain and chain_keys:
                company_lower = company.lower()
                if any(ck in company_lower for ck in chain_keys):
                    continue

            # Determine chain key
            chain = self.chain_key or "local"
            if not is_chain:
                chain = "local"

            # Build store_num
            job_url = str(row.get("job_url", ""))
            location_str = str(row.get("location", ""))
            store_num = extract_store_num(prefix, None, f"{company}-{location_str}")

            if not is_chain:
                store_num = f"REGIONAL-{region}"

            # Parse dates
            date_posted = row.get("date_posted")
            observed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if pd.notna(date_posted):
                try:
                    if isinstance(date_posted, str):
                        observed_at = datetime.fromisoformat(date_posted)
                    elif hasattr(date_posted, "to_pydatetime"):
                        observed_at = date_posted.to_pydatetime()
                except (ValueError, TypeError):
                    pass

            # Parse wages
            wage_min = row.get("min_amount") if pd.notna(row.get("min_amount")) else None
            wage_max = row.get("max_amount") if pd.notna(row.get("max_amount")) else None
            wage_period = str(row.get("interval", "hourly")).lower() if pd.notna(row.get("interval")) else "hourly"

            # Determine signal type
            signal_type = "listing"
            if wage_min is not None or wage_max is not None:
                signal_type = "wage" if not is_chain else "listing"

            title = str(row.get("title", ""))

            signal = ScraperSignal(
                store_num=store_num,
                chain=chain,
                source="jobspy",
                signal_type=signal_type,
                value=1.0,
                metadata={
                    "title": title,
                    "company": company,
                    "location": location_str,
                    "job_url": job_url,
                    "date_posted": observed_at.isoformat(),
                    "is_remote": bool(row.get("is_remote")) if pd.notna(row.get("is_remote")) else False,
                    "job_type": str(row.get("job_type", "")) if pd.notna(row.get("job_type")) else None,
                    "store_name": company,
                    "address": location_str,
                    "employer": company,
                    "is_chain": is_chain,
                    "industry": self.industry_key or "unknown",
                    "wage_min": float(wage_min) if wage_min is not None else None,
                    "wage_max": float(wage_max) if wage_max is not None else None,
                    "wage_period": wage_period,
                },
                observed_at=observed_at,
                wage_min=float(wage_min) if wage_min is not None else None,
                wage_max=float(wage_max) if wage_max is not None else None,
                wage_period=wage_period,
                role_title=title,
                source_url=job_url if job_url else None,
            )
            signals.append(signal)

        return signals


def scrape_jobspy(
    chain: str | None = None,
    industry: str | None = None,
    region: str = "austin_tx",
    mode: str = "chain",
    radius_mi: int = 25,
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape and optionally ingest."""
    adapter = JobSpyAdapter(chain_key=chain, industry_key=industry, mode=mode)
    signals = adapter.scrape(region, radius_mi)

    if ingest and signals:
        from backend.ingest import ingest_signals
        chain_key = chain or (industry or "local")
        count = ingest_signals(signals, region, chain_key, "jobspy")
        logger.info("[JobSpy] Ingested %d signals", count)

    return signals


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape job boards via JobSpy")
    parser.add_argument("--chain", help="Chain key (e.g. starbucks)")
    parser.add_argument("--industry", help="Industry key (e.g. coffee_cafe)")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--mode", default="chain", choices=["chain", "wage"])
    parser.add_argument("--radius", type=int, default=25, help="Radius in miles")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_jobspy(
        chain=args.chain,
        industry=args.industry,
        region=args.region,
        mode=args.mode,
        radius_mi=args.radius,
        ingest=not args.no_ingest,
    )
    logger.info("Scraped %d signals", len(signals))


if __name__ == "__main__":
    main()
