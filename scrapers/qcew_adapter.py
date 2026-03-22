"""
scrapers/qcew_adapter.py

Fetches county-level employment and wage data from the BLS Quarterly Census
of Employment and Wages (QCEW) open data API.

No API key required. Single HTTP GET per county per quarter (~400 KB).
Data is updated quarterly with ~5-6 month lag (Q3 2025 available March 2026).

QCEW gives us ground-truth figures the BLS series API never could:
  - Establishment counts per industry per county
  - Average weekly wage per industry
  - Total employment per industry

Usage:
    python scrapers/qcew_adapter.py --region austin_tx
    python scrapers/qcew_adapter.py --region austin_tx --year 2024 --quarter a
"""

import csv
import io
import logging
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

# ── QCEW API ─────────────────────────────────────────────────────────────────

QCEW_API = "https://data.bls.gov/cew/data/api/{year}/{qtr}/area/{area}.csv"

# agglvl 78 = county, private sector, 6-digit NAICS
# agglvl 71 = county, by ownership total (for all-industry totals)
AGGLVL_COUNTY_6DIGIT = "78"
OWN_PRIVATE = "5"

# ── NAICS → industry key mapping (2022 NAICS revision) ───────────────────────
# Each code maps to one internal industry key.  Multiple codes can share a key
# (e.g. both 812111 and 812112 are hair_beauty).

NAICS_TO_INDUSTRY: dict[str, str] = {
    # Coffee & Café
    "722515": "coffee_cafe",

    # Fast Food / QSR
    "722513": "fast_food",

    # Full Service Restaurants
    "722511": "full_service_restaurant",

    # Retail General Merchandise
    "452210": "retail_general",   # Department stores
    "452319": "retail_general",   # Other general merchandise

    # Grocery & Supermarket
    "445110": "retail_grocery",

    # Healthcare Clinics & Urgent Care
    "621111": "healthcare_clinic",
    "621493": "healthcare_clinic",  # Freestanding ERs / urgent care

    # Pharmacy & Drugstore (NAICS 2022: 446110 → 456110)
    "456110": "pharmacy",
    "446110": "pharmacy",           # Keep old code for pre-2023 files

    # Hotels & Accommodation
    "721110": "accommodation",

    # Fitness & Wellness
    "713940": "fitness_wellness",

    # Childcare & Early Education
    "624410": "childcare",

    # Hair & Beauty Services
    "812111": "hair_beauty",        # Hair salons (cut/shampoo only)
    "812112": "hair_beauty",        # Beauty salons / barbershops
    "812113": "hair_beauty",        # Nail salons

    # Auto Repair & Maintenance
    "811111": "auto_repair",        # General automotive mechanical repair
    "811121": "auto_repair",        # Auto body repair (2022 NAICS)
    "811122": "auto_repair",        # Auto glass repair (2022 NAICS)
    "811112": "auto_repair",        # Exhaust/transmission (pre-2022 code)

    # HVAC & Skilled Trades
    "238221": "hvac_skilled_trades",  # Plumbing/HVAC residential (2022 NAICS)
    "238222": "hvac_skilled_trades",  # Plumbing/HVAC commercial (2022 NAICS)
    "238220": "hvac_skilled_trades",  # Pre-2022 combined code
    "238211": "hvac_skilled_trades",  # Electrical contractors residential (2022)
    "238212": "hvac_skilled_trades",  # Electrical contractors commercial (2022)
    "238210": "hvac_skilled_trades",  # Pre-2022 combined electrical code
}

# Human-readable label per industry for role_title field
INDUSTRY_ROLE_LABELS: dict[str, str] = {
    "coffee_cafe":            "Coffee Shop / Café Worker",
    "fast_food":              "Fast Food / QSR Worker",
    "full_service_restaurant":"Restaurant Worker",
    "retail_general":         "Retail Associate",
    "retail_grocery":         "Grocery / Supermarket Worker",
    "healthcare_clinic":      "Clinical / Medical Worker",
    "pharmacy":               "Pharmacy Worker",
    "accommodation":          "Hotel / Lodging Worker",
    "fitness_wellness":       "Fitness / Wellness Staff",
    "childcare":              "Childcare / Early Education Worker",
    "hair_beauty":            "Hair & Beauty Services Worker",
    "auto_repair":            "Auto Repair Technician",
    "hvac_skilled_trades":    "HVAC / Skilled Trades Worker",
}


# ── Adapter ───────────────────────────────────────────────────────────────────

class QCEWAdapter(BaseScraper):
    """Downloads QCEW county data and produces wage + establishment signals.

    Produces two signal types per industry:
      - signal_type="wage"              — avg weekly wage, establishment count,
                                          avg monthly employment
      - signal_type="establishment_count" — standalone establishment count signal
                                          (for scoring engine use)

    Data source: https://data.bls.gov/cew/data/api/{year}/{qtr}/area/{fips}.csv
    No API key. No rate limits. ~400 KB per county per quarter.
    """

    name = "qcew"

    def __init__(self) -> None:
        super().__init__()
        self._timeout = 30

    # ── Public interface ──────────────────────────────────────────────────────

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch the most recent QCEW data available for the region's county.

        Automatically picks the most recent published quarter.
        """
        from config.loader import get_region

        try:
            region_cfg = get_region(region)
        except (KeyError, Exception) as e:
            logger.error("[QCEW] Unknown region '%s': %s", region, e)
            return []

        county_fips = region_cfg.get("county_fips")
        if not county_fips:
            logger.error(
                "[QCEW] Region '%s' has no county_fips in config. "
                "Add county_fips to config/chains.yaml.", region
            )
            return []

        location = region_cfg.get("location_string", region)

        # Try quarters from most recent backward until we get data
        year, qtr = self._latest_available_quarter()
        for attempt in range(6):  # check up to 6 quarters back
            rows = self._fetch_county(county_fips, year, qtr)
            if rows:
                logger.info(
                    "[QCEW] Fetched %d rows for county=%s year=%s qtr=%s",
                    len(rows), county_fips, year, qtr
                )
                break
            year, qtr = self._prev_quarter(year, qtr)
        else:
            logger.error("[QCEW] No data found for county=%s after 6 attempts", county_fips)
            return []

        return self._build_signals(rows, region, location, year, qtr)

    def scrape_specific(
        self,
        region: str,
        year: int,
        quarter: str,  # '1','2','3','4' or 'a' for annual
    ) -> list[ScraperSignal]:
        """Fetch a specific year/quarter."""
        from config.loader import get_region
        region_cfg = get_region(region)
        county_fips = region_cfg["county_fips"]
        location = region_cfg.get("location_string", region)

        rows = self._fetch_county(county_fips, year, quarter)
        if not rows:
            logger.warning("[QCEW] No data for county=%s year=%s qtr=%s", county_fips, year, quarter)
            return []
        return self._build_signals(rows, region, location, year, quarter)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _latest_available_quarter(self) -> tuple[int, str]:
        """Return (year, quarter) for the most recently published QCEW quarter.

        QCEW release schedule (approximate):
          Q1 (Jan-Mar) → published August same year
          Q2 (Apr-Jun) → published November same year
          Q3 (Jul-Sep) → published February following year
          Q4 (Oct-Dec) → published June following year

        We work backward from now to find the most likely published quarter.
        """
        now = datetime.utcnow()
        year = now.year
        month = now.month

        # Map current month to which quarter is likely published
        if month >= 8:
            return year, "1"       # Q1 of current year published in August
        elif month >= 6:
            return year - 1, "4"   # Q4 of previous year published in June
        elif month >= 2:
            return year - 1, "3"   # Q3 of previous year published in February
        else:
            return year - 1, "2"   # Q2 of previous year published in November

    def _prev_quarter(self, year: int, qtr: str) -> tuple[int, str]:
        """Step one quarter backward."""
        if qtr == "a":
            return year - 1, "4"
        q = int(qtr)
        if q == 1:
            return year - 1, "4"
        return year, str(q - 1)

    def _fetch_county(self, fips: str, year: int, qtr: str) -> list[dict]:
        """Download and parse the QCEW county CSV. Returns list of row dicts."""
        url = QCEW_API.format(year=year, qtr=qtr, area=fips)
        logger.info("[QCEW] GET %s", url)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "First-Helios/1.0 (labor-market-research)"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status != 200:
                    logger.warning("[QCEW] HTTP %d for %s", resp.status, url)
                    return []
                content = resp.read().decode("utf-8")
        except Exception as e:
            logger.warning("[QCEW] Fetch failed for %s: %s", url, e)
            return []

        if not content.strip():
            return []

        try:
            reader = csv.DictReader(io.StringIO(content))
            return [
                {k.strip(): v.strip() for k, v in row.items()}
                for row in reader
            ]
        except Exception as e:
            logger.error("[QCEW] CSV parse failed: %s", e)
            return []

    def _build_signals(
        self,
        rows: list[dict],
        region: str,
        location: str,
        year: int,
        qtr: str,
    ) -> list[ScraperSignal]:
        """Filter rows to target NAICS codes and build ScraperSignal objects."""

        is_quarterly = qtr != "a"
        period_label = f"Q{qtr} {year}" if is_quarterly else f"Annual {year}"
        source_url = QCEW_API.format(year=year, qtr=qtr, area="[county]")

        # Filter: private sector, 6-digit NAICS, not suppressed, target industries
        relevant: list[dict] = []
        for row in rows:
            if row.get("agglvl_code") != AGGLVL_COUNTY_6DIGIT:
                continue
            if row.get("own_code") != OWN_PRIVATE:
                continue
            if row.get("disclosure_code", "").strip():
                continue  # suppressed — skip
            naics = row.get("industry_code", "").strip()
            if naics in NAICS_TO_INDUSTRY:
                relevant.append(row)

        if not relevant:
            logger.warning(
                "[QCEW] No target-industry rows found in %d total rows "
                "(agglvl=%s, own=%s, not-suppressed)",
                len(rows), AGGLVL_COUNTY_6DIGIT, OWN_PRIVATE,
            )
            return []

        # Aggregate by industry (multiple NAICS codes may map to one industry)
        # Keys: industry_key → accumulated stats
        industry_stats: dict[str, dict] = {}
        for row in relevant:
            naics = row["industry_code"].strip()
            ind_key = NAICS_TO_INDUSTRY[naics]

            if is_quarterly:
                estabs   = _int(row.get("qtrly_estabs", "0"))
                emp      = _int(row.get("month1_emplvl", "0"))
                wk_wage  = _float(row.get("avg_wkly_wage", "0"))
                ann_pay  = wk_wage * 52
                tot_wages = _int(row.get("total_qtrly_wages", "0"))
            else:
                estabs   = _int(row.get("annual_avg_estabs", "0"))
                emp      = _int(row.get("annual_avg_emplvl", "0"))
                wk_wage  = _float(row.get("annual_avg_wkly_wage", "0"))
                ann_pay  = _float(row.get("avg_annual_pay", "0"))
                tot_wages = _int(row.get("total_annual_wages", "0"))

            if ind_key not in industry_stats:
                industry_stats[ind_key] = {
                    "estabs": 0, "emp": 0,
                    "wage_sum": 0.0, "wage_count": 0,
                    "ann_pay_sum": 0.0, "ann_pay_count": 0,
                    "tot_wages": 0,
                    "naics_codes": [],
                }

            s = industry_stats[ind_key]
            s["estabs"]    += estabs
            s["emp"]       += emp
            s["tot_wages"] += tot_wages
            s["naics_codes"].append(naics)
            if wk_wage > 0:
                s["wage_sum"]   += wk_wage * max(estabs, 1)  # estabs-weighted
                s["wage_count"] += max(estabs, 1)
            if ann_pay > 0:
                s["ann_pay_sum"]   += ann_pay * max(estabs, 1)
                s["ann_pay_count"] += max(estabs, 1)

        signals: list[ScraperSignal] = []
        observed = datetime.utcnow()

        for ind_key, s in industry_stats.items():
            estabs   = s["estabs"]
            emp      = s["emp"]
            wk_wage  = round(s["wage_sum"] / s["wage_count"], 2) if s["wage_count"] else 0.0
            ann_pay  = round(s["ann_pay_sum"] / s["ann_pay_count"], 2) if s["ann_pay_count"] else wk_wage * 52
            hr_wage  = round(wk_wage / 40, 2) if wk_wage else 0.0
            role     = INDUSTRY_ROLE_LABELS.get(ind_key, ind_key)

            meta = {
                "period":           period_label,
                "year":             year,
                "quarter":          qtr,
                "naics_codes":      s["naics_codes"],
                "establishments":   estabs,
                "avg_monthly_employment": emp,
                "avg_weekly_wage":  wk_wage,
                "avg_annual_pay":   ann_pay,
                "avg_hourly_wage":  hr_wage,
                "total_wages":      s["tot_wages"],
                "industry":         ind_key,
                "location":         location,
                "source":           "qcew",
                "is_chain":         False,
            }

            # Primary wage signal — one per industry
            signals.append(ScraperSignal(
                store_num   = f"QCEW-{region}-{ind_key}",
                chain       = "qcew",
                source      = "qcew",
                signal_type = "wage",
                value       = hr_wage,
                metadata    = meta,
                observed_at = observed,
                wage_min    = hr_wage,
                wage_max    = hr_wage,
                wage_period = "hourly",
                role_title  = role,
                source_url  = source_url,
            ))

            # Establishment count signal — used by scoring and discovery
            signals.append(ScraperSignal(
                store_num   = f"QCEW-{region}-{ind_key}-estabs",
                chain       = "qcew",
                source      = "qcew",
                signal_type = "establishment_count",
                value       = float(estabs),
                metadata    = {**meta, "employment": emp},
                observed_at = observed,
                role_title  = role,
                source_url  = source_url,
            ))

            logger.info(
                "[QCEW] %-25s  estabs=%-5d  emp=%-6d  avg_wkly_wage=$%-7.2f  avg_annual=$%-9.0f",
                ind_key, estabs, emp, wk_wage, ann_pay,
            )

        logger.info("[QCEW] Built %d signals for %d industries", len(signals), len(industry_stats))
        return signals


# ── Helpers ───────────────────────────────────────────────────────────────────

def _int(v: str) -> int:
    try:
        return int(v.replace(",", "").strip() or "0")
    except (ValueError, AttributeError):
        return 0


def _float(v: str) -> float:
    try:
        return float(v.replace(",", "").strip() or "0")
    except (ValueError, AttributeError):
        return 0.0


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="QCEW county wage + establishment data")
    parser.add_argument("--region",  default="austin_tx", help="Region key from config")
    parser.add_argument("--year",    type=int, default=0,  help="Year (0=auto-detect latest)")
    parser.add_argument("--quarter", default="",           help="Quarter: 1-4 or 'a' for annual (blank=auto)")
    parser.add_argument("--ingest",  action="store_true",  help="Write signals to database")
    args = parser.parse_args()

    adapter = QCEWAdapter()

    if args.year and args.quarter:
        signals = adapter.scrape_specific(args.region, args.year, args.quarter)
    else:
        signals = adapter.scrape(args.region)

    print(f"\n{'='*60}")
    print(f"QCEW results for region={args.region}")
    print(f"{'='*60}")

    wage_sigs = [s for s in signals if s.signal_type == "wage"]
    estab_sigs = [s for s in signals if s.signal_type == "establishment_count"]

    print(f"\n{'Industry':<26} {'Estabs':>6}  {'Emp':>6}  {'Hrly Wage':>10}  {'Annual Pay':>12}")
    print("-" * 70)
    for s in wage_sigs:
        m = s.metadata
        print(
            f"{m['industry']:<26} {m['establishments']:>6}  "
            f"{m['avg_monthly_employment']:>6}  "
            f"${m['avg_hourly_wage']:>9.2f}  "
            f"${m['avg_annual_pay']:>11,.0f}"
        )

    print(f"\nTotal: {len(wage_sigs)} industries, {len(signals)} signals")

    if args.ingest and signals:
        from backend.ingest import ingest_signals
        n = ingest_signals(signals, region=args.region, chain="qcew", source="qcew")
        print(f"Ingested {n} signals.")
