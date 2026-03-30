"""
Composite scoring engine for ChainStaffingTracker.

Economically grounded scoring that uses government labor market data
as denominators and benchmarks, not arbitrary weighted averages.

Score formula:
  Composite = w₁·demand_pressure + w₂·wage_competitiveness + w₃·churn_signal + w₄·qualitative

Where:
  demand_pressure     = (postings per establishment) / regional baseline
  wage_competitiveness = (market median - chain wage) / market median
  churn_signal         = posting velocity / expected turnover (from JOLTS)
  qualitative          = sentiment score (Reddit + Google Reviews)

Each component has an economic interpretation.  If ground-truth data
(QCEW, JOLTS) is not yet available, falls back to the previous
percentile-based approach.

Weights are in config/chains.yaml under scoring.weights:
  demand_pressure:      35%
  wage_competitiveness: 25%
  churn_signal:         25%
  qualitative:          15%

Depends on: backend.database, backend.baseline, backend.scoring.{careers, sentiment, wage}
Called by: backend/scheduler.py, server.py (after ingestion)
"""

import logging
from datetime import datetime

from core.database import (
    Store,
    LocalEmployer,
    OEWSRecord,
    RevelioHiring,
    Score,
    Signal,
    Store,
    WageIndex,
    get_session,
    init_db,
)
from core.models.reference import BrandProfile
from core.scoring.careers import compute_careers_score, weighted_listing_count
from core.scoring.sentiment import compute_sentiment_score
from core.scoring.wage import compute_wage_score
from config.loader import get_score_tiers, get_scoring_weights, get_seasonal_config

logger = logging.getLogger(__name__)

# ── Revelio sector mapping ─────────────────────────────────────────────────
# Maps internal_industry → (revelio naics2d_name, primary SOC group)
# Used when QCEW/JOLTS data unavailable — provides sector-level benchmarks.
_INDUSTRY_REVELIO_MAP: dict[str, tuple[str, str]] = {
    "coffee_cafe":             ("Leisure and Hospitality", "Food Preparation and Serving Related"),
    "fast_food":               ("Leisure and Hospitality", "Food Preparation and Serving Related"),
    "full_service_restaurant": ("Leisure and Hospitality", "Food Preparation and Serving Related"),
    "food_service":            ("Leisure and Hospitality", "Food Preparation and Serving Related"),
    "accommodation_food":      ("Leisure and Hospitality", "Food Preparation and Serving Related"),
    "retail_general":          ("Retail Trade", "Sales and Related"),
    "food_retail":             ("Retail Trade", "Sales and Related"),
    "retail":                  ("Retail Trade", "Sales and Related"),
}

# Maps internal_industry → OEWS occupation code for wage benchmarking.
_INDUSTRY_OEWS_OCC: dict[str, str] = {
    "coffee_cafe":             "35-0000",  # Food Prep and Serving Overall
    "fast_food":               "35-3023",  # Fast Food and Counter Workers
    "full_service_restaurant": "35-0000",
    "food_service":            "35-0000",
    "accommodation_food":      "35-0000",
    "retail_general":          "41-0000",  # Sales and Related Occupations
    "food_retail":             "41-0000",
    "retail":                  "41-0000",
}

# Cross-sector TX monthly hiring/attrition reference rates (from Revelio data).
# 50 on the score scale = at this rate.
_REVELIO_HIRING_REF_RATE = 0.20   # ~20% monthly hiring = "normal" pressure
_REVELIO_ATTRITION_REF_RATE = 0.18  # ~18% monthly attrition = "normal" churn


def compute_all_scores(region: str, chain: str | None = None) -> dict[str, dict]:
    """Compute economically-grounded composite scores for all stores.

    Uses ground-truth baselines (QCEW establishment counts, JOLTS turnover,
    OEWS wages) when available, with percentile fallback when not.

    Args:
        region: Region key, e.g. 'austin_tx'.
        chain: Optional chain filter, e.g. 'starbucks'.

    Returns:
        Mapping of store_num -> {
            'composite': float,
            'tier': str,
            'demand_pressure': dict|None,
            'wage_competitiveness': dict|None,
            'churn_signal': dict|None,
            'qualitative': dict|None,
        }
    """
    engine = init_db()
    session = get_session(engine)
    weights = get_scoring_weights()
    tiers_cfg = get_score_tiers()

    try:
        # ── Fetch stores ─────────────────────────────────────────────
        query = session.query(Store).filter(Store.region == region, Store.is_active.is_(True))
        if chain:
            query = query.filter(Store.chain == chain)
        stores = query.all()

        if not stores:
            logger.info("[ScoringEngine] No stores found for region=%s chain=%s", region, chain)
            return {}

        store_nums = [s.store_num for s in stores]
        store_map = {s.store_num: s for s in stores}

        # ── Load ground-truth baseline ───────────────────────────────
        baseline = _load_baseline(region, chain)

        # ── Build per-store industry map and Revelio/OEWS context ────
        # industry is now populated on chain_locations from ref_brands
        store_industry: dict[str, str] = {
            s.store_num: (s.industry or "unknown") for s in stores
        }

        # Pre-load Revelio context and OEWS wages for each unique industry in this batch
        unique_industries = {ind for ind in store_industry.values() if ind != "unknown"}
        industry_revelio: dict[str, dict | None] = {
            ind: _load_revelio_context(session, ind) for ind in unique_industries
        }
        industry_oews: dict[str, float | None] = {
            ind: _get_oews_wage(session, region, ind) for ind in unique_industries
        }

        # For single-industry batches (filtered by chain), set dominant_industry
        dominant_industry = next(iter(unique_industries), None) if len(unique_industries) == 1 else None
        revelio_ctx = industry_revelio.get(dominant_industry) if dominant_industry else None

        # For mixed batches, use a fallback: pick the industry with most stores
        if not dominant_industry and unique_industries:
            from collections import Counter
            cnt = Counter(store_industry.values())
            dominant_industry = cnt.most_common(1)[0][0]
            revelio_ctx = industry_revelio.get(dominant_industry)

        # ── Load brand reference wages for stores lacking wage signals ──
        brand_wages: dict[str, dict] = {}
        for s in stores:
            if s.brand_key:
                bw = _get_brand_wage(session, s.brand_key)
                if bw:
                    brand_wages[s.store_num] = bw

        # ── Gather signals by store and type ─────────────────────────
        signals = (
            session.query(Signal)
            .filter(Signal.store_num.in_(store_nums))
            .order_by(Signal.observed_at.desc())
            .all()
        )

        store_listings: dict[str, list[dict]] = {sn: [] for sn in store_nums}
        store_sentiment: dict[str, list[dict]] = {sn: [] for sn in store_nums}
        store_wages: dict[str, dict] = {sn: {} for sn in store_nums}

        for sig in signals:
            sn = sig.store_num
            if sn not in store_listings:
                continue

            meta = sig.get_metadata()

            if sig.source in ("careers_api", "jobspy") and sig.signal_type == "listing":
                store_listings[sn].append({
                    "observed_at": sig.observed_at,
                    "posted_date": meta.get("posted_date") or meta.get("date_posted"),
                    "value": sig.value,
                })
            elif sig.signal_type in ("sentiment", "review_score"):
                store_sentiment[sn].append({
                    "signal_type": sig.signal_type,
                    "value": sig.value,
                    "source": sig.source,
                })
            elif sig.signal_type == "wage":
                if not store_wages[sn]:
                    store_wages[sn] = {
                        "wage_min": meta.get("wage_min"),
                        "wage_max": meta.get("wage_max"),
                        "wage_period": meta.get("wage_period", "hourly"),
                    }

        # Fill wage gaps from brand reference data
        for sn in store_nums:
            if not store_wages[sn] and sn in brand_wages:
                store_wages[sn] = brand_wages[sn]

        # ── Compute sub-scores ───────────────────────────────────────
        # 1. Demand pressure (postings-per-establishment → Revelio fallback)
        demand_scores = _compute_demand_pressure(store_listings, baseline, revelio_ctx)

        # 2. Wage competitiveness — per-industry OEWS median, or local avg fallback
        local_avg = _get_local_avg_wage(session, region, chain)
        # Use dominant industry's OEWS wage as the market_median for the batch
        market_median = (
            (baseline.get("occupation_median_wage") if baseline else None)
            or industry_oews.get(dominant_industry)
        )
        wage_scores = _compute_wage_competitiveness(
            store_wages, local_avg, market_median, store_industry, industry_oews
        )

        # 3. Churn signal (posting velocity → Revelio attrition fallback)
        churn_scores = _compute_churn_signal(store_listings, baseline, revelio_ctx)

        # 4. Qualitative (sentiment — unchanged methodology)
        qualitative_scores = compute_sentiment_score(store_sentiment)

        # ── Compute composite ────────────────────────────────────────
        results: dict[str, dict] = {}

        for sn in store_nums:
            sub_scores: dict[str, float | None] = {}
            available_weights: dict[str, float] = {}

            # Demand pressure
            dp = demand_scores.get(sn)
            if dp is not None:
                sub_scores["demand_pressure"] = dp["value"]
                available_weights["demand_pressure"] = weights.get("demand_pressure", 0.35)

            # Wage competitiveness
            wc = wage_scores.get(sn)
            if wc is not None:
                sub_scores["wage_competitiveness"] = wc["value"]
                available_weights["wage_competitiveness"] = weights.get("wage_competitiveness", 0.25)

            # Churn signal
            cs = churn_scores.get(sn)
            if cs is not None:
                sub_scores["churn_signal"] = cs["value"]
                available_weights["churn_signal"] = weights.get("churn_signal", 0.25)

            # Qualitative
            qs = qualitative_scores.get(sn)
            if qs and store_sentiment.get(sn):
                sub_scores["qualitative"] = qs["value"]
                available_weights["qualitative"] = weights.get("qualitative", 0.15)

            # Weighted average with redistribution
            total_weight = sum(available_weights.values()) or 1.0
            composite = 0.0
            for key, w in available_weights.items():
                val = sub_scores.get(key)
                if val is not None:
                    composite += (w / total_weight) * val

            # Apply seasonal adjustment if available
            seasonal_cfg = get_seasonal_config()
            if seasonal_cfg.get("enabled") and baseline:
                seasonal_idx = baseline.get("seasonal_index")
                if seasonal_idx and seasonal_idx != 0:
                    # Adjust composite: divide by seasonal index to normalize
                    # During peak hiring months, raw scores are inflated
                    composite = composite / seasonal_idx

            composite = max(0.0, min(100.0, composite))

            # Determine tier
            tier = "adequate"
            if composite >= tiers_cfg["critical"]["min_percentile"]:
                tier = "critical"
            elif composite >= tiers_cfg["elevated"]["min_percentile"]:
                tier = "elevated"

            results[sn] = {
                "composite": round(composite, 2),
                "tier": tier,
                "demand_pressure": demand_scores.get(sn),
                "wage_competitiveness": wage_scores.get(sn),
                "churn_signal": churn_scores.get(sn),
                "qualitative": qualitative_scores.get(sn),
                "baseline_available": baseline is not None,
                "revelio_available": revelio_ctx is not None,
            }

        # ── Write scores to DB ───────────────────────────────────────
        _write_scores(session, results)

        logger.info(
            "[ScoringEngine] Scored %d stores for region=%s "
            "(baseline=%s, revelio=%s, market_median=$%.2f): %s",
            len(results), region,
            "yes" if baseline else "no",
            "yes" if revelio_ctx else "no",
            market_median or 0,
            _tier_distribution(results),
        )
        return results

    except Exception as e:
        session.rollback()
        logger.error("[ScoringEngine] Failed to compute scores: %s", e)
        return {}
    finally:
        session.close()


# ── Sub-score computation ────────────────────────────────────────────────────

def _load_baseline(region: str, chain: str | None) -> dict | None:
    """Load the latest labor market baseline for the region.

    Maps chain → NAICS code and fetches the corresponding baseline.
    """
    try:
        from core.baseline import get_latest_baseline
        from config.loader import get_chain

        # Determine NAICS from chain config
        naics = "7225"  # default: food services
        if chain:
            try:
                chain_cfg = get_chain(chain)
                industry = chain_cfg.get("industry", "")
                # Map internal_industry → NAICS (all sectors)
                industry_naics = {
                    # Food service
                    "coffee_cafe": "722515",
                    "fast_food": "722513",
                    "full_service_restaurant": "722511",
                    "cafeteria": "722514",
                    "food_service": "7225",
                    "accommodation_food": "72",
                    "accommodation": "721",
                    # Retail
                    "retail_general": "452",
                    "food_retail": "445",
                    "retail": "44",
                    # Healthcare
                    "healthcare": "62",
                    "hospitals": "622",
                    "nursing_care": "623",
                    "ambulatory_health": "621",
                    # Professional / Technical
                    "professional_services": "54",
                    "it_services": "5415",
                    # Transportation / Warehousing
                    "transportation": "48",
                    "warehousing": "493",
                    # Construction
                    "construction": "23",
                    "hvac_skilled_trades": "23822",
                    # Manufacturing
                    "manufacturing": "31",
                    # Finance / Insurance
                    "finance": "52",
                    "banking": "522",
                    # Education
                    "education": "61",
                    # Admin / Support (staffing, janitorial, security)
                    "admin_support": "56",
                    "staffing_agencies": "5613",
                    # Auto services
                    "auto_repair": "8111",
                    "auto_services": "811",
                    # Personal care
                    "personal_care": "8121",
                    "salon_barbershop": "8121",
                }
                naics = industry_naics.get(industry, "7225")
            except (KeyError, TypeError):
                pass

        baseline = get_latest_baseline(region, naics)
        if baseline:
            logger.info(
                "[ScoringEngine] Loaded baseline: NAICS=%s, est=%s, emp=%s, quits=%.1f%%",
                naics,
                baseline.get("establishment_count", "?"),
                baseline.get("total_employment", "?"),
                baseline.get("expected_quits_rate", 0) or 0,
            )
        return baseline

    except ImportError:
        logger.debug("[ScoringEngine] baseline module not available — using fallback")
        return None
    except Exception as e:
        logger.warning("[ScoringEngine] Failed to load baseline: %s", e)
        return None


def _load_revelio_context(session, industry: str | None) -> dict | None:
    """Load Revelio sector hiring/attrition benchmarks for the given industry.

    Returns a dict with:
        hiring_rate: float  (monthly, e.g. 0.25 = 25%)
        attrition_rate: float
        sector: str
        soc_group: str
        months: int
    or None if no mapping or no data.
    """
    if not industry or industry == "unknown":
        return None

    mapping = _INDUSTRY_REVELIO_MAP.get(industry)
    if not mapping:
        return None

    sector_name, soc_name = mapping

    try:
        from sqlalchemy import func as sqlfunc
        rows = (
            session.query(
                sqlfunc.avg(RevelioHiring.hiring_rate_nsa).label("hiring_rate"),
                sqlfunc.avg(RevelioHiring.attrition_rate_nsa).label("attrition_rate"),
                sqlfunc.count(RevelioHiring.id).label("months"),
            )
            .filter(
                RevelioHiring.naics2d_name == sector_name,
                RevelioHiring.soc2d_name == soc_name,
            )
            .first()
        )

        if rows and rows.hiring_rate:
            return {
                "hiring_rate": float(rows.hiring_rate),
                "attrition_rate": float(rows.attrition_rate or 0),
                "sector": sector_name,
                "soc_group": soc_name,
                "months": rows.months,
            }
    except Exception as e:
        logger.warning("[ScoringEngine] Revelio context lookup failed: %s", e)

    return None


def _get_oews_wage(session, region: str, industry: str | None) -> float | None:
    """Return OEWS median hourly wage for the occupation matching this industry.

    Looks up the specific occupation code from _INDUSTRY_OEWS_OCC, then queries
    oews_data.  The OEWS region column stores display names like "Austin, TX"
    while our region keys use slugs like "austin_tx" — this function handles both.
    """
    if not industry or industry == "unknown":
        return None

    occ_code = _INDUSTRY_OEWS_OCC.get(industry)
    if not occ_code:
        return None

    # Build candidate region strings: slug first, then title-case variants
    region_candidates = [region]
    if "_" in region:
        # "austin_tx" → "Austin, TX"
        parts = region.split("_")
        city = parts[0].title()
        state = parts[-1].upper() if len(parts) > 1 else ""
        region_candidates.append(f"{city}, {state}")
        region_candidates.append(f"{city} {state}")

    try:
        for reg in region_candidates:
            row = (
                session.query(OEWSRecord)
                .filter(
                    OEWSRecord.region == reg,
                    OEWSRecord.occ_code == occ_code,
                )
                .order_by(OEWSRecord.year.desc())
                .first()
            )
            if row and row.wage_median_hourly:
                return row.wage_median_hourly
    except Exception as e:
        logger.warning("[ScoringEngine] OEWS wage lookup failed: %s", e)
    return None


def _get_brand_wage(session, brand_key: str) -> dict | None:
    """Return brand reference wage from ref_brands.avg_starting_wage."""
    try:
        brand = session.query(BrandProfile).filter_by(brand_key=brand_key).first()
        if brand and brand.avg_starting_wage:
            return {
                "wage_min": brand.avg_starting_wage,
                "wage_max": brand.avg_starting_wage,
                "wage_period": "hourly",
                "source": "ref_brands",
            }
    except Exception as e:
        logger.warning("[ScoringEngine] Brand wage lookup failed: %s", e)
    return None


def _compute_demand_pressure(
    store_listings: dict[str, list[dict]],
    baseline: dict | None,
    revelio_ctx: dict | None = None,
) -> dict[str, dict]:
    """Compute demand pressure: postings per establishment / regional norm.

    Priority order:
    1. QCEW ground-truth: (weighted_listings / establishment_count) / regional_norm × 50
    2. Revelio sector benchmark: (sector_hiring_rate / reference_rate) × 50
    3. Percentile fallback (relative to other stores in batch).

    Score interpretation: 50 = at norm, 100 = 2× norm, 0 = no activity.
    """
    # Compute weighted listing counts
    listing_counts: dict[str, float] = {}
    for sn, listings in store_listings.items():
        listing_counts[sn] = weighted_listing_count(listings)

    establishment_count = None
    if baseline:
        establishment_count = baseline.get("establishment_count")

    if establishment_count and establishment_count > 0:
        # Ground-truth scoring: normalize by establishment count
        total_listings = sum(listing_counts.values())
        regional_per_est = total_listings / establishment_count if establishment_count else 0

        scores: dict[str, dict] = {}
        for sn, count in listing_counts.items():
            if regional_per_est > 0:
                ratio = count / regional_per_est
                value = min(100.0, ratio * 50.0)
            else:
                value = 50.0 if count > 0 else 0.0

            scores[sn] = {
                "value": round(value, 2),
                "weighted_listings": round(count, 2),
                "regional_per_establishment": round(regional_per_est, 3),
                "establishment_count": establishment_count,
                "method": "ground_truth",
            }
        return scores

    elif revelio_ctx:
        # Revelio sector benchmark: sector hiring rate normalized to 0-100 scale
        hiring_rate = revelio_ctx["hiring_rate"]
        value = min(100.0, (hiring_rate / _REVELIO_HIRING_REF_RATE) * 50.0)
        value = round(value, 2)

        scores: dict[str, dict] = {}
        for sn, count in listing_counts.items():
            if count > 0:
                # Store has signal data — blend signal count into Revelio base
                local_value = min(100.0, value * (1 + count / 5.0))
            else:
                local_value = value  # sector baseline for all stores

            scores[sn] = {
                "value": round(local_value, 2),
                "sector_hiring_rate": round(hiring_rate, 4),
                "reference_rate": _REVELIO_HIRING_REF_RATE,
                "sector": revelio_ctx["sector"],
                "method": "revelio_sector",
            }
        return scores

    else:
        # Fallback: percentile rank within this batch
        careers_scores = compute_careers_score(store_listings)
        for sn in careers_scores:
            careers_scores[sn]["method"] = "percentile_fallback"
        return careers_scores


def _compute_wage_competitiveness(
    store_wages: dict[str, dict],
    local_avg: float | None,
    market_median: float | None,
    store_industry: dict[str, str] | None = None,
    industry_oews: dict[str, float | None] | None = None,
) -> dict[str, dict]:
    """Compute wage competitiveness score.

    Formula: gap_pct = (market_wage - chain_wage) / market_wage × 100
    Score: 50 + gap_pct (50 = at market, 100 = 50% below market, 0 = 50% above)

    Uses per-store OEWS wage when industry_oews is provided (multi-chain batches).
    Falls back to market_median → local_avg → neutral 50.
    """
    scores: dict[str, dict] = {}
    for sn, wages in store_wages.items():
        if not wages:
            continue

        chain_wage = None
        wmin = wages.get("wage_min")
        wmax = wages.get("wage_max")
        if wmin and wmax:
            chain_wage = (wmin + wmax) / 2.0
        elif wmin:
            chain_wage = wmin
        elif wmax:
            chain_wage = wmax

        if chain_wage is None:
            continue

        # Convert yearly to hourly if needed
        if wages.get("wage_period") == "yearly" and chain_wage > 100:
            chain_wage = chain_wage / 2080.0

        # Determine market reference: per-store OEWS preferred, then batch median, then local avg
        per_store_oews = None
        if store_industry and industry_oews:
            ind = store_industry.get(sn)
            per_store_oews = industry_oews.get(ind) if ind else None

        reference_wage = per_store_oews or market_median or local_avg
        method = (
            "oews_per_industry" if per_store_oews else
            "oews_median" if market_median else
            "local_avg" if local_avg else "none"
        )

        gap_pct = None
        if reference_wage and reference_wage > 0:
            gap_pct = ((reference_wage - chain_wage) / reference_wage) * 100.0
            value = max(0.0, min(100.0, 50.0 + gap_pct))
        else:
            value = 50.0  # no reference — neutral

        scores[sn] = {
            "value": round(value, 2),
            "chain_wage": round(chain_wage, 2),
            "market_reference": round(reference_wage, 2) if reference_wage else None,
            "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
            "method": method,
        }

    return scores


def _compute_churn_signal(
    store_listings: dict[str, list[dict]],
    baseline: dict | None,
    revelio_ctx: dict | None = None,
) -> dict[str, dict]:
    """Compute churn signal: posting velocity vs expected turnover.

    Priority order:
    1. JOLTS expected separations: ratio = active_postings / expected_monthly_seps
    2. Revelio attrition rate: (sector_attrition_rate / reference_rate) × 50
    3. Relative listing count fallback.

    Score: 50 = at expected churn rate, 100 = 2× expected.
    """
    expected_seps = None
    quits_rate = None
    if baseline:
        expected_seps = baseline.get("expected_monthly_separations")
        quits_rate = baseline.get("expected_quits_rate")

    listing_counts: dict[str, float] = {}
    for sn, listings in store_listings.items():
        listing_counts[sn] = weighted_listing_count(listings)

    scores: dict[str, dict] = {}

    if expected_seps and expected_seps > 0:
        n_stores = len([c for c in listing_counts.values() if c > 0])

        for sn, count in listing_counts.items():
            if count == 0:
                value = 0.0
            else:
                per_store_expected = expected_seps / max(n_stores, 1)
                ratio = count / per_store_expected if per_store_expected > 0 else 1.0
                value = min(100.0, ratio * 50.0)

            scores[sn] = {
                "value": round(value, 2),
                "weighted_listings": round(count, 2),
                "expected_monthly_separations": expected_seps,
                "quits_rate": quits_rate,
                "method": "jolts_benchmark",
            }

    elif revelio_ctx:
        # Revelio sector attrition rate as churn benchmark
        attrition_rate = revelio_ctx["attrition_rate"]
        base_value = min(100.0, (attrition_rate / _REVELIO_ATTRITION_REF_RATE) * 50.0)

        for sn, count in listing_counts.items():
            if count > 0:
                local_value = min(100.0, base_value * (1 + count / 5.0))
            else:
                local_value = base_value  # sector baseline

            scores[sn] = {
                "value": round(local_value, 2),
                "sector_attrition_rate": round(attrition_rate, 4),
                "reference_rate": _REVELIO_ATTRITION_REF_RATE,
                "sector": revelio_ctx["sector"],
                "method": "revelio_sector",
            }

    else:
        # Fallback: relative listing count
        all_counts = list(listing_counts.values())
        max_count = max(all_counts) if all_counts else 1.0

        for sn, count in listing_counts.items():
            value = (count / max_count) * 100.0 if max_count > 0 else 0.0
            scores[sn] = {
                "value": round(value, 2),
                "weighted_listings": round(count, 2),
                "method": "relative_fallback",
            }

    return scores


def _get_local_avg_wage(session, region: str, chain: str | None) -> float | None:
    """Compute average local (non-chain) wage for the region."""
    try:
        # Extract city/state from region key for location matching
        # e.g. "austin_tx" → search for "austin" or state "TX"
        # Include the wider MSA (Round Rock, Cedar Park, etc.)
        parts = region.split("_")
        city = parts[0] if parts else region
        state = parts[1].upper() if len(parts) > 1 else ""

        query = session.query(WageIndex).filter(
            WageIndex.is_chain.is_(False),
        )
        # Filter by state if available (broad MSA match)
        if state:
            query = query.filter(WageIndex.location.ilike(f"%{state}%"))
        else:
            query = query.filter(WageIndex.location.ilike(f"%{city}%"))

        rows = query.all()
        if not rows:
            return None

        hourly_wages: list[float] = []
        for r in rows:
            avg = None
            if r.wage_min is not None and r.wage_max is not None:
                avg = (r.wage_min + r.wage_max) / 2.0
            elif r.wage_min is not None:
                avg = r.wage_min
            elif r.wage_max is not None:
                avg = r.wage_max

            if avg is not None:
                if r.wage_period == "yearly" and avg > 100:
                    avg = avg / 2080
                hourly_wages.append(avg)

        if hourly_wages:
            return sum(hourly_wages) / len(hourly_wages)
        return None

    except Exception as e:
        logger.error("[ScoringEngine] Failed to get local avg wage: %s", e)
        return None


def _write_scores(session, results: dict[str, dict]) -> None:
    """Upsert Score rows for computed results."""
    now = datetime.utcnow()
    try:
        for store_num, data in results.items():
            # Composite score
            existing = (
                session.query(Score)
                .filter_by(store_num=store_num, score_type="composite")
                .first()
            )
            if existing:
                existing.value = data["composite"]
                existing.tier = data["tier"]
                existing.computed_at = now
            else:
                session.add(Score(
                    store_num=store_num,
                    score_type="composite",
                    value=data["composite"],
                    tier=data["tier"],
                    computed_at=now,
                ))

            # Sub-scores (new economically-grounded names)
            for sub_type in ("demand_pressure", "wage_competitiveness", "churn_signal", "qualitative"):
                sub = data.get(sub_type)
                if sub is None:
                    continue
                existing_sub = (
                    session.query(Score)
                    .filter_by(store_num=store_num, score_type=sub_type)
                    .first()
                )
                val = sub["value"] if isinstance(sub, dict) else sub
                if existing_sub:
                    existing_sub.value = val
                    existing_sub.tier = sub.get("tier", "unknown") if isinstance(sub, dict) else "unknown"
                    existing_sub.computed_at = now
                else:
                    session.add(Score(
                        store_num=store_num,
                        score_type=sub_type,
                        value=val,
                        tier=sub.get("tier", "unknown") if isinstance(sub, dict) else "unknown",
                        computed_at=now,
                    ))

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("[ScoringEngine] Failed to write scores: %s", e)


def _tier_distribution(results: dict[str, dict]) -> dict[str, int]:
    """Count stores per tier for logging."""
    dist: dict[str, int] = {"critical": 0, "elevated": 0, "adequate": 0}
    for r in results.values():
        tier = r.get("tier", "unknown")
        dist[tier] = dist.get(tier, 0) + 1
    return dist


def compute_local_employer_scores(region: str) -> dict[str, dict]:
    """Compute sector-level staffing stress scores for local_employers.

    Local employers have no per-location signal data yet, so scores reflect
    sector-level hiring pressure and churn derived from Revelio benchmarks.
    Uses overture_id as the score key (stored in scores.store_num).

    Returns:
        Mapping of overture_id -> score dict.
    """
    engine = init_db()
    session = get_session(engine)
    tiers_cfg = get_score_tiers()
    weights = get_scoring_weights()

    try:
        employers = (
            session.query(LocalEmployer)
            .filter(
                LocalEmployer.region == region,
                LocalEmployer.is_active.is_(True),
                LocalEmployer.industry.isnot(None),
            )
            .all()
        )

        if not employers:
            logger.info("[ScoringEngine] No local employers found for region=%s", region)
            return {}

        # Pre-load Revelio context and OEWS wage per unique industry
        unique_industries = {e.industry for e in employers if e.industry}
        industry_revelio: dict[str, dict | None] = {
            ind: _load_revelio_context(session, ind) for ind in unique_industries
        }
        industry_oews: dict[str, float | None] = {
            ind: _get_oews_wage(session, region, ind) for ind in unique_industries
        }

        results: dict[str, dict] = {}

        for emp in employers:
            ind = emp.industry or "unknown"
            revelio_ctx = industry_revelio.get(ind)
            oews_wage = industry_oews.get(ind)
            score_key = emp.overture_id

            sub_scores: dict[str, float] = {}
            available_weights: dict[str, float] = {}

            # Demand pressure from Revelio sector hiring rate
            if revelio_ctx:
                hiring_rate = revelio_ctx["hiring_rate"]
                dp_value = min(100.0, (hiring_rate / _REVELIO_HIRING_REF_RATE) * 50.0)
                sub_scores["demand_pressure"] = dp_value
                available_weights["demand_pressure"] = weights.get("demand_pressure", 0.35)

            # Churn signal from Revelio sector attrition rate
            if revelio_ctx:
                attrition_rate = revelio_ctx["attrition_rate"]
                cs_value = min(100.0, (attrition_rate / _REVELIO_ATTRITION_REF_RATE) * 50.0)
                sub_scores["churn_signal"] = cs_value
                available_weights["churn_signal"] = weights.get("churn_signal", 0.25)

            # Wage competitiveness: no per-employer wage data — skip
            # (will become active once signals / wage scrapes arrive)

            if not sub_scores:
                continue

            total_weight = sum(available_weights.values()) or 1.0
            composite = sum(
                (w / total_weight) * sub_scores[k]
                for k, w in available_weights.items()
            )
            composite = round(max(0.0, min(100.0, composite)), 2)

            tier = "adequate"
            if composite >= tiers_cfg["critical"]["min_percentile"]:
                tier = "critical"
            elif composite >= tiers_cfg["elevated"]["min_percentile"]:
                tier = "elevated"

            results[score_key] = {
                "composite": composite,
                "tier": tier,
                "demand_pressure": {
                    "value": round(sub_scores.get("demand_pressure", 0), 2),
                    "sector_hiring_rate": round(revelio_ctx["hiring_rate"], 4) if revelio_ctx else None,
                    "method": "revelio_sector",
                } if revelio_ctx else None,
                "wage_competitiveness": None,
                "churn_signal": {
                    "value": round(sub_scores.get("churn_signal", 0), 2),
                    "sector_attrition_rate": round(revelio_ctx["attrition_rate"], 4) if revelio_ctx else None,
                    "method": "revelio_sector",
                } if revelio_ctx else None,
                "qualitative": None,
                "revelio_available": revelio_ctx is not None,
                "oews_wage": oews_wage,
                "industry": ind,
                "category": emp.category,
                "name": emp.name,
            }

        _write_scores(session, results)

        logger.info(
            "[ScoringEngine] Scored %d local employers for region=%s: %s",
            len(results), region, _tier_distribution(results),
        )
        return results

    except Exception as e:
        session.rollback()
        logger.error("[ScoringEngine] Failed to score local employers: %s", e)
        return {}
    finally:
        session.close()
