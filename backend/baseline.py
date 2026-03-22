"""
Labor market baseline computation for ChainStaffingTracker.

Combines ground-truth data (QCEW, JOLTS, OEWS, LAUS) into the
LaborMarketBaseline table.  These baselines serve as the denominators
and benchmarks for the scoring engine.

Key formula:
  Hiring Intensity = Active Postings / QCEW Establishment Count
  Expected Separations = QCEW Employment × JOLTS Quits Rate
  Wage Gap = (Market Median - Chain Wage) / Market Median

Recomputed:
  - After each QCEW data fetch (quarterly)
  - Weekly on Sunday at 4am (catch-all)

Depends on: backend.database, config.loader
Called by: backend/scheduler.py, backend/scoring/engine.py
"""

import logging
from datetime import datetime

from sqlalchemy import func

from backend.database import (
    Base,
    JOLTSRecord,
    LAUSRecord,
    LaborMarketBaseline,
    OEWSRecord,
    QCEWRecord,
    get_session,
    init_db,
)
from config.loader import (
    get_qcew_config,
    get_qcew_county_fips,
    get_seasonal_config,
)

logger = logging.getLogger(__name__)


def compute_baselines(region: str) -> dict[str, dict]:
    """Compute labor market baselines from ground-truth data.

    Pulls the latest QCEW, JOLTS, OEWS, and LAUS data and writes
    LaborMarketBaseline rows for each NAICS code in the region.

    Returns:
        Mapping of naics_code -> baseline dict for logging/inspection.
    """
    engine = init_db()
    session = get_session(engine)

    try:
        qcew_cfg = get_qcew_config()
        naics_targets = qcew_cfg["naics_codes"]
        county_fips_list = list(get_qcew_county_fips().values())

        results: dict[str, dict] = {}

        for naics_key, naics_code in naics_targets.items():
            baseline = _compute_single_baseline(
                session, region, naics_code, county_fips_list
            )
            if baseline:
                results[naics_code] = baseline

                # Upsert into LaborMarketBaseline table
                _upsert_baseline(session, region, naics_code, baseline)

        session.commit()
        logger.info(
            "[Baseline] Computed %d baselines for region=%s: %s",
            len(results), region,
            {k: f"est={v.get('establishment_count', '?')}, emp={v.get('total_employment', '?')}"
             for k, v in results.items()},
        )
        return results

    except Exception as e:
        session.rollback()
        logger.error("[Baseline] Failed to compute baselines: %s", e)
        return {}
    finally:
        session.close()


def get_latest_baseline(
    region: str, naics_code: str
) -> dict | None:
    """Fetch the most recent LaborMarketBaseline for a region/NAICS.

    Used by the scoring engine at score-computation time.
    """
    engine = init_db()
    session = get_session(engine)
    try:
        row = (
            session.query(LaborMarketBaseline)
            .filter_by(region=region, naics_code=naics_code)
            .order_by(LaborMarketBaseline.computed_at.desc())
            .first()
        )
        return row.to_dict() if row else None
    finally:
        session.close()


def _compute_single_baseline(
    session, region: str, naics_code: str, county_fips_list: list[str]
) -> dict | None:
    """Compute baseline for one NAICS code across all counties in the region."""

    # ── QCEW: aggregate across counties ──────────────────────────────
    qcew_rows = (
        session.query(QCEWRecord)
        .filter(
            QCEWRecord.fips_code.in_(county_fips_list),
            QCEWRecord.naics_code == naics_code,
        )
        .order_by(QCEWRecord.year.desc(), QCEWRecord.quarter.desc())
        .all()
    )

    # Group by (year, quarter) and take the latest
    latest_qcew = {}
    latest_yq = None
    for row in qcew_rows:
        yq = (row.year, row.quarter)
        if latest_yq is None:
            latest_yq = yq
        if yq == latest_yq:
            latest_qcew[row.fips_code] = row

    total_establishments = 0
    total_employment = 0
    total_weekly_wage_sum = 0
    wage_count = 0

    for fips, row in latest_qcew.items():
        if row.establishments:
            total_establishments += row.establishments
        emp = row.avg_employment
        if emp:
            total_employment += int(emp)
        if row.avg_weekly_wage:
            total_weekly_wage_sum += row.avg_weekly_wage
            wage_count += 1

    avg_weekly_wage = (total_weekly_wage_sum / wage_count) if wage_count else None
    avg_emp_per_est = (
        total_employment / total_establishments
        if total_establishments > 0
        else None
    )

    period_label = f"{latest_yq[0]}-Q{latest_yq[1]}" if latest_yq else "unknown"

    # ── JOLTS: latest quits & openings rates ─────────────────────────
    # Map NAICS to JOLTS industry code (JOLTS uses broader codes)
    jolts_industry = _naics_to_jolts_industry(naics_code)
    quits_rate = None
    openings_rate = None

    if jolts_industry:
        for metric_name, target_var in [("quits_rate", "quits"), ("openings_rate", "openings")]:
            latest_jolts = (
                session.query(JOLTSRecord)
                .filter_by(metric=metric_name, industry_code=jolts_industry)
                .order_by(JOLTSRecord.year.desc(), JOLTSRecord.month.desc())
                .first()
            )
            if latest_jolts:
                if target_var == "quits":
                    quits_rate = latest_jolts.value
                else:
                    openings_rate = latest_jolts.value

    # Expected monthly separations
    expected_separations = None
    if total_employment and quits_rate:
        expected_separations = int(total_employment * (quits_rate / 100.0))

    # ── OEWS: occupation median wage ─────────────────────────────────
    oews_wage = None
    oews_employment = None
    oews_row = (
        session.query(OEWSRecord)
        .filter(
            OEWSRecord.region == region,
            OEWSRecord.naics_code == naics_code,
        )
        .order_by(OEWSRecord.year.desc())
        .first()
    )
    if oews_row:
        oews_wage = oews_row.wage_median_hourly
        oews_employment = oews_row.employment

    # ── LAUS: latest unemployment rate (average across counties) ─────
    unemployment_rate = None
    labor_force = None

    laus_rows = (
        session.query(LAUSRecord)
        .filter(LAUSRecord.region == region)
        .order_by(LAUSRecord.year.desc(), LAUSRecord.month.desc())
        .limit(len(county_fips_list))
        .all()
    )
    if laus_rows:
        rates = [r.unemployment_rate for r in laus_rows if r.unemployment_rate]
        forces = [r.labor_force for r in laus_rows if r.labor_force]
        if rates:
            unemployment_rate = sum(rates) / len(rates)
        if forces:
            labor_force = sum(forces)

    # ── Seasonal index ───────────────────────────────────────────────
    seasonal_index = _compute_seasonal_index(session, naics_code, county_fips_list)

    if total_establishments == 0 and not quits_rate and not unemployment_rate:
        logger.info("[Baseline] No ground-truth data for NAICS %s", naics_code)
        return None

    return {
        "period_label": period_label,
        "establishment_count": total_establishments or None,
        "total_employment": total_employment or None,
        "avg_weekly_wage": avg_weekly_wage,
        "avg_employees_per_establishment": avg_emp_per_est,
        "expected_quits_rate": quits_rate,
        "expected_openings_rate": openings_rate,
        "expected_monthly_separations": expected_separations,
        "occupation_median_wage": oews_wage,
        "occupation_employment": oews_employment,
        "unemployment_rate": unemployment_rate,
        "labor_force": labor_force,
        "seasonal_index": seasonal_index,
    }


def _upsert_baseline(
    session, region: str, naics_code: str, data: dict
) -> None:
    """Upsert a LaborMarketBaseline row."""
    period = data["period_label"]

    existing = (
        session.query(LaborMarketBaseline)
        .filter_by(region=region, naics_code=naics_code, period_label=period)
        .first()
    )

    if existing:
        for key, val in data.items():
            if key != "period_label" and hasattr(existing, key):
                setattr(existing, key, val)
        existing.computed_at = datetime.utcnow()
    else:
        row = LaborMarketBaseline(
            region=region,
            naics_code=naics_code,
            period_label=period,
            **{k: v for k, v in data.items() if k != "period_label"},
            computed_at=datetime.utcnow(),
        )
        session.add(row)


def _naics_to_jolts_industry(naics_code: str) -> str | None:
    """Map a specific NAICS code to the broader JOLTS industry code.

    JOLTS publishes at the supersector level (2-digit NAICS).
    """
    # All food/accommodation NAICS (72xxxx) map to JOLTS industry "72"
    if naics_code.startswith("72"):
        return "72"
    if naics_code.startswith("44") or naics_code.startswith("45"):
        return "44-45"  # Retail Trade
    return None


def _compute_seasonal_index(
    session, naics_code: str, county_fips_list: list[str]
) -> float | None:
    """Compute a seasonal index for the current month.

    Seasonal index = current quarter employment / trailing 4-quarter average.
    A value > 1.0 means the current quarter is above the annual average
    (hiring peak); < 1.0 means below (trough).
    """
    now = datetime.utcnow()
    current_quarter = (now.month - 1) // 3 + 1

    # Get last 4 quarters of QCEW data
    qcew_rows = (
        session.query(QCEWRecord)
        .filter(
            QCEWRecord.fips_code.in_(county_fips_list),
            QCEWRecord.naics_code == naics_code,
        )
        .order_by(QCEWRecord.year.desc(), QCEWRecord.quarter.desc())
        .limit(len(county_fips_list) * 4)
        .all()
    )

    if len(qcew_rows) < 4:
        return None

    # Group by quarter
    quarter_emp: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    for row in qcew_rows:
        emp = row.avg_employment
        if emp:
            quarter_emp[row.quarter].append(emp)

    # Compute annual average
    all_emps = [e for qlist in quarter_emp.values() for e in qlist]
    if not all_emps:
        return None

    annual_avg = sum(all_emps) / len(all_emps)
    current_q_emps = quarter_emp.get(current_quarter, [])
    if not current_q_emps or annual_avg == 0:
        return None

    current_avg = sum(current_q_emps) / len(current_q_emps)
    return round(current_avg / annual_avg, 3)
